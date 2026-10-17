"""Análises: gastos, recorrências, previsão, empréstimos e carro."""
from __future__ import annotations

import re
import unicodedata
from datetime import date

import pandas as pd

from . import loans as loans_mod
from .categorize import non_spending


def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[\d\W_]+", " ", s).strip()


def _month(d) -> str:
    return pd.Timestamp(d).strftime("%Y-%m")


def _add_months(ym: str, n: int) -> str:
    return (pd.Period(ym, "M") + n).strftime("%Y-%m")


def transactions(conn) -> pd.DataFrame:
    df = pd.read_sql("SELECT t.*, a.institution, a.type AS account_type FROM transactions t "
                     "LEFT JOIN accounts a ON a.id = t.account_id", conn, parse_dates=["date"])
    if df.empty:
        return df
    df["month"] = df["date"].dt.strftime("%Y-%m")
    df["is_flow"] = ~df["category"].isin(non_spending())
    return df


# Só estas categorias contam como renda. Dinheiro que entra em qualquer outra categoria de fluxo
# (ex.: amigo devolvendo a parte da viagem, cashback, estorno) é REEMBOLSO e abate o gasto daquela categoria.
INCOME_CATEGORIES = {"Salário", "Mesada / ajuda de custos", "Outras entradas", "Pix recebido"}


def _is_refund(df: pd.DataFrame) -> pd.Series:
    return (df["amount"] > 0) & df["is_flow"] & ~df["category"].isin(INCOME_CATEGORIES)


def spending(df: pd.DataFrame) -> pd.DataFrame:
    """Gastos reais (exclui faturas, transferências internas, investimentos). value > 0 = gasto, < 0 = reembolso."""
    if df.empty:
        return df
    out = df[((df["amount"] < 0) & df["is_flow"]) | _is_refund(df)].copy()
    out["value"] = -out["amount"]
    return out


def income(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df[(df["amount"] > 0) & df["is_flow"] & df["category"].isin(INCOME_CATEGORIES)].copy()


def recurring(df: pd.DataFrame, lookback: int = 4, min_hits: int = 3) -> pd.DataFrame:
    """Despesas que se repetem quase todo mês com valor parecido (Pix recorrente, assinaturas, contas)."""
    out = spending(df)
    if out.empty:
        return pd.DataFrame(columns=["key", "category", "monthly", "hits", "last"])
    out = out[out["total_installments"].isna()]
    months = sorted(out["month"].unique())[-lookback:]
    out = out[out["month"].isin(months)]
    out["key"] = (out["counterparty"].fillna("") + " " + out["description"].fillna("")).map(_norm).str[:40]
    g = out.groupby(["key", "month"]).agg(value=("value", "sum"), category=("category", "first")).reset_index()
    rows = []
    for key, grp in g.groupby("key"):
        if len(grp) < min(min_hits, len(months)):
            continue
        med = grp["value"].median()
        if med and grp["value"].std(ddof=0) / med <= 0.35:
            rows.append({"key": key, "category": grp["category"].iloc[-1], "monthly": med,
                         "hits": len(grp), "last": grp["month"].max()})
    return pd.DataFrame(rows).sort_values("monthly", ascending=False) if rows else \
        pd.DataFrame(columns=["key", "category", "monthly", "hits", "last"])


def installments_ahead(df: pd.DataFrame) -> pd.DataFrame:
    """Parcelas futuras de compras parceladas no cartão, por mês."""
    out = spending(df)
    if out.empty:
        return pd.DataFrame(columns=["month", "value"])
    out = out[out["total_installments"].notna()].copy()
    rows = []
    # a parcela mais recente de cada compra define o que ainda falta — filtrar as quitadas só DEPOIS
    # (senão a última parcela some e a penúltima "projeta" uma parcela fantasma)
    out["purchase"] = out["description"].map(_norm) + "|" + out["total_installments"].astype(int).astype(str)
    last = out.sort_values("installment_number").groupby("purchase").tail(1)
    for _, r in last[last["installment_number"] < last["total_installments"]].iterrows():
        for k in range(1, int(r["total_installments"] - r["installment_number"]) + 1):
            rows.append({"month": _add_months(r["month"], k), "value": r["value"]})
    return pd.DataFrame(rows).groupby("month", as_index=False)["value"].sum() if rows else \
        pd.DataFrame(columns=["month", "value"])


def forecast(conn, months: int = 6) -> pd.DataFrame:
    df = transactions(conn)
    cur = date.today().strftime("%Y-%m")
    future = [_add_months(cur, i) for i in range(1, months + 1)]
    result = pd.DataFrame({"month": future})

    spend, inc = spending(df), income(df)
    closed = [m for m in sorted(df["month"].unique()) if m < cur][-3:] if not df.empty else []

    salary = inc[inc["category"] == "Salário"] if not inc.empty else inc
    result["Salário"] = salary[salary["month"].isin(closed)].groupby("month")["amount"].sum().median() \
        if not salary.empty else 0.0

    rec = recurring(df)
    rec_fixed = rec[~rec["category"].isin(["Energia (Cemig)", "Água (Cesama)"])]["monthly"].sum() if not rec.empty else 0
    result["Recorrentes"] = rec_fixed

    bills = pd.read_sql("SELECT provider, ref_month, amount FROM utility_bills", conn)
    util = []
    for m in future:
        total = 0.0
        for prov, grp in bills.groupby("provider"):
            same = grp[grp["ref_month"] == _add_months(m, -12)]  # sazonalidade: mesmo mês ano passado
            total += same["amount"].iloc[0] if not same.empty else grp.sort_values("ref_month").tail(3)["amount"].mean()
        util.append(total)
    result["Cemig + Cesama"] = util

    inst = installments_ahead(df).set_index("month")["value"] if not df.empty else pd.Series(dtype=float)
    result["Parcelas cartão"] = result["month"].map(inst).fillna(0.0)

    if not spend.empty:
        rec_keys = set(rec["key"]) if not rec.empty else set()
        sp = spend.copy()
        sp["key"] = (sp["counterparty"].fillna("") + " " + sp["description"].fillna("")).map(_norm).str[:40]
        variable = sp[~sp["key"].isin(rec_keys) & sp["total_installments"].isna()
                      & ~sp["category"].isin(["Energia (Cemig)", "Água (Cesama)"])]
        result["Variáveis (média)"] = variable[variable["month"].isin(closed)].groupby("month")["value"].sum().median()
    else:
        result["Variáveis (média)"] = 0.0

    loans = loan_status(conn)
    sched = loan_schedule_open(conn)
    other = pd.read_sql("SELECT amount FROM other_income WHERE active=1", conn)
    result["Benefícios (Flash)"] = float(other["amount"].sum()) if not other.empty else 0.0

    result["A receber (empréstimos)"] = result["month"].map(
        sched.groupby("month")["remaining"].sum() if not sched.empty else {}).fillna(0.0)

    _, bank_open = bank_loan_status(conn)
    result["Empréstimo (banco)"] = result["month"].map(
        bank_open.groupby("month")["remaining"].sum() if not bank_open.empty else {}).fillna(0.0)

    result = result.fillna(0.0)
    out_cols = ["Recorrentes", "Cemig + Cesama", "Parcelas cartão", "Empréstimo (banco)", "Variáveis (média)"]
    result["Saídas previstas"] = result[out_cols].sum(axis=1)
    result["Saldo previsto"] = (result["Salário"] + result["Benefícios (Flash)"] + result["A receber (empréstimos)"]
                                - result["Saídas previstas"])
    result.attrs["loans_open"] = float(loans["remaining"].sum()) if not loans.empty else 0.0
    return result


# ---------- Empréstimos ----------

def match_loan_payments(conn) -> int:
    """Casa Pix recebidos com a pessoa pelo trecho de nome (opcional) e baixa os empréstimos dela.
    Pessoa sem nome de Pix cadastrado nunca é casada automaticamente."""
    needles: dict[str, set[str]] = {}
    for r in conn.execute("SELECT name, match_name FROM people WHERE match_name IS NOT NULL AND match_name<>''"):
        needles.setdefault(r["name"], set()).add(_norm(r["match_name"]))
    for r in conn.execute("SELECT person, match_name FROM loans WHERE closed=0 AND match_name IS NOT NULL AND match_name<>''"):
        needles.setdefault(r["person"], set()).add(_norm(r["match_name"]))
    n = 0
    for person, keys in needles.items():
        keys.discard("")
        ref = conn.execute("SELECT id, date FROM loans WHERE person=? ORDER BY date, id", (person,)).fetchone()
        if not keys or ref is None:
            continue
        cands = conn.execute(
            """SELECT id, date, amount, description, counterparty FROM transactions
               WHERE amount > 0 AND date >= ? AND id NOT IN (SELECT transaction_id FROM loan_payments
               WHERE transaction_id IS NOT NULL) ORDER BY date""", (ref["date"],)).fetchall()
        for t in cands:
            if any(k in _norm(f"{t['counterparty']} {t['description']}") for k in keys):
                conn.execute("INSERT INTO loan_payments(loan_id, date, amount, transaction_id, note, directed, order_mode) "
                             "VALUES (?,?,?,?,?,0,'antigas')",
                             (ref["id"], t["date"], t["amount"], t["id"], "Pix casado automaticamente"))
                conn.execute("UPDATE transactions SET category='Empréstimo recebido', manual_category='Empréstimo recebido' WHERE id=?", (t["id"],))
                n += 1
    return n


def _d(s) -> date:
    return date.fromisoformat(str(s)[:10])


def load_loans(conn) -> tuple[list[loans_mod.Loan], list[loans_mod.Receipt]]:
    sched: dict[int, list] = {}
    for r in conn.execute("SELECT loan_id, due_date, amount FROM loan_schedule ORDER BY due_date"):
        sched.setdefault(r["loan_id"], []).append((_d(r["due_date"]), r["amount"]))
    ls = [loans_mod.Loan(r["id"], r["person"], _d(r["date"]), r["principal"], r["rate"] or 0.0,
                         r["rate_period"] or "mes", r["compounding"] or "simples", sched.get(r["id"], []), bool(r["closed"]))
          for r in conn.execute("SELECT * FROM loans ORDER BY date, id")]
    rs = [loans_mod.Receipt(r["id"], r["loan_id"], _d(r["date"]), r["amount"], bool(r["directed"]), r["order_mode"] or "antigas")
          for r in conn.execute("SELECT * FROM loan_payments ORDER BY date, id")]
    return ls, rs


def loan_status(conn, today: date | None = None) -> pd.DataFrame:
    today = today or date.today()
    df = pd.read_sql("SELECT id, person, date, principal, note, closed, rate, rate_period, compounding "
                     "FROM loans ORDER BY date, id", conn)
    if df.empty:
        return df.assign(paid=[], remaining=[], overdue=[], next_due=[], scheduled=[], interest=[], installments=[])
    ls, rs = load_loans(conn)
    states = loans_mod.replay(ls, rs, today)
    df["paid"] = df["id"].map(lambda i: round(states[i].paid, 2))
    df["remaining"] = df["id"].map(lambda i: round(states[i].balance(), 2))
    df["scheduled"] = df["id"].map(lambda i: states[i].scheduled)
    df["installments"] = df["id"].map(lambda i: len(states[i].loan.schedule) or None)
    df["quitado"] = (df["remaining"] <= loans_mod.EPS) | (df["closed"] == 1)
    df.loc[df["closed"] == 1, "remaining"] = 0.0  # marcado quitado à mão (legado)
    df["interest"] = (df["paid"] + df["remaining"] - df["principal"]).round(2)
    nxt, late = {}, {}
    for l in ls:
        if not l.schedule or df.loc[df["id"] == l.id, "closed"].iloc[0]:
            continue
        for due, _, rem in loans_mod.open_installments(l.schedule, states[l.id].paid):
            if rem > loans_mod.EPS:
                (late if due < today else nxt).setdefault(l.id, []).append((due, rem))
    df["next_due"] = df["id"].map(lambda i: min(d for d, _ in nxt[i]).isoformat() if i in nxt else None)
    df["overdue"] = df["id"].map(lambda i: round(sum(r for _, r in late.get(i, [])), 2))
    df["closed"] = df["quitado"].astype(int)
    return df.drop(columns="quitado")


def loan_schedule_open(conn, today: date | None = None) -> pd.DataFrame:
    """Parcelas combinadas ainda em aberto (recebimentos já descontados na ordem escolhida)."""
    ls, rs = load_loans(conn)
    states = loans_mod.replay(ls, rs, today or date.today())
    rows = []
    for l in ls:
        if l.closed or not l.schedule:
            continue
        for due, amt, rem in loans_mod.open_installments(l.schedule, states[l.id].paid):
            if rem > loans_mod.EPS:
                rows.append({"loan_id": l.id, "due_date": due.isoformat(), "amount": amt, "person": l.person,
                             "remaining": rem, "month": due.isoformat()[:7]})
    cols = ["loan_id", "due_date", "amount", "person", "remaining", "month"]
    return pd.DataFrame(rows, columns=cols).sort_values(["loan_id", "due_date"]).reset_index(drop=True)


def loan_statement(conn, loan_id: int, today: date | None = None) -> pd.DataFrame:
    """Memória de cálculo do empréstimo (sem parcelas fixas): linha a linha, para conferir em calculadora."""
    ls, rs = load_loans(conn)
    st = loans_mod.replay(ls, rs, today or date.today())[loan_id]
    loan = st.loan
    rows = [{"data": loan.date, "evento": "empréstimo", "dias": 0, "períodos": 0.0, "juros": 0.0, "pago": 0.0,
             "saldo": loan.principal}] + st.trace
    return pd.DataFrame(rows)


def loan_timeline(conn, asof: date | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Foto mensal (fim de cada mês; a última é `asof`/hoje): saldo a receber por pessoa e total emprestado acumulado.
    Só empréstimos com parcelas combinadas — os sem data de retorno ficam fora do gráfico."""
    ls, rs = load_loans(conn)
    ls = [l for l in ls if l.schedule]
    if not ls:
        return pd.DataFrame(columns=["month", "person", "saldo"]), pd.DataFrame(columns=["month", "emprestado", "recebido"])
    end = max(asof or date.today(), date.today())
    first = min(l.date for l in ls)
    snaps = []
    for per in pd.period_range(pd.Period(first, "M"), pd.Period(end, "M")):
        d = min(per.end_time.date(), end)
        if d >= first:
            snaps.append((per.strftime("%Y-%m"), d))
    by_person, totals = [], []
    for month, d in snaps:
        states = loans_mod.replay(ls, rs, d)
        acc: dict[str, float] = {}
        for l in ls:
            if l.date <= d and not l.closed:
                acc[l.person] = acc.get(l.person, 0.0) + states[l.id].balance()
        by_person += [{"month": month, "person": p, "saldo": round(v, 2)} for p, v in acc.items()]
        totals.append({"month": month, "emprestado": sum(l.principal for l in ls if l.date <= d),
                       "recebido": round(sum(states[l.id].paid for l in ls if l.date <= d), 2)})
    return pd.DataFrame(by_person), pd.DataFrame(totals)


# ---------- Empréstimos que eu devo (banco) ----------

def bank_loan_status(conn) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(resumo por empréstimo, parcelas em aberto). Pagamentos abatem as parcelas mais antigas primeiro."""
    df = pd.read_sql("SELECT * FROM bank_loans ORDER BY date, id", conn)
    cols = ["bank_loan_id", "bank", "due_date", "amount", "remaining", "month"]
    if df.empty:
        return df.assign(paid=[], remaining=[], total=[]), pd.DataFrame(columns=cols)
    paid = {r["bank_loan_id"]: r["s"] for r in conn.execute(
        "SELECT bank_loan_id, SUM(amount) AS s FROM bank_loan_payments GROUP BY bank_loan_id")}
    rows, summary = [], []
    for r in df.itertuples():
        sch = loans_mod.make_schedule(r.principal, r.rate or 0.0, r.rate_period, r.compounding, int(r.installments),
                                      _d(r.first_due), r.installment_amount if r.installment_amount == r.installment_amount else None,
                                      start=_d(r.date))
        opened = loans_mod.open_installments(sch, paid.get(r.id, 0.0) or 0.0)
        total = sum(a for _, a in sch)
        rem = sum(x for _, _, x in opened)
        summary.append({"id": r.id, "total": round(total, 2), "paid": round(paid.get(r.id, 0.0) or 0.0, 2),
                        "remaining": round(rem, 2), "installments_left": sum(1 for *_, x in opened if x > loans_mod.EPS)})
        for due, amt, x in opened:
            if x > loans_mod.EPS:
                rows.append({"bank_loan_id": r.id, "bank": r.bank, "due_date": due.isoformat(), "amount": amt,
                             "remaining": x, "month": due.isoformat()[:7]})
    df = df.merge(pd.DataFrame(summary), on="id")
    return df, pd.DataFrame(rows, columns=cols)


# ---------- Carro ----------

def car_profile(conn) -> dict | None:
    row = conn.execute("SELECT * FROM car_profile WHERE id=1").fetchone()
    return dict(row) if row else None


def service_outlook(profile: dict | None, events: pd.DataFrame) -> dict:
    """Quanto falta para a revisão e quanto ela custa por km rodado.
    Intervalo = km da próxima revisão − km da última manutenção registrada (se houver)."""
    out: dict = {"km_to_service": None, "service_interval": None, "service_per_km": None}
    if not profile:
        return out
    now, nxt, price = profile.get("km_now"), profile.get("next_service_km"), profile.get("next_service_price")
    if now is not None and nxt:
        out["km_to_service"] = nxt - now
    last = events[(events["kind"] == "manutencao") & events["odometer"].notna()] if not events.empty else events
    if nxt and len(last):
        interval = nxt - last["odometer"].max()
        if interval > 0:
            out["service_interval"] = interval
            if price:
                out["service_per_km"] = price / interval
    return out


def car_summary(conn) -> dict:
    ev = pd.read_sql("SELECT * FROM car_events ORDER BY date, odometer", conn)
    fixed = pd.read_sql("SELECT * FROM car_fixed", conn)
    fipe = pd.read_sql("SELECT * FROM fipe_history ORDER BY ref_month", conn)
    out: dict = {"events": ev, "fixed": fixed, "fipe": fipe, "profile": car_profile(conn)}
    out.update(service_outlook(out["profile"], ev))

    fuel = ev[ev["kind"] == "combustivel"].dropna(subset=["odometer"])
    full = fuel[fuel["full_tank"] == 1]
    if len(full) >= 2:  # método do tanque cheio: litros entre dois tanques cheios / km rodados
        first, last = full.iloc[0], full.iloc[-1]
        between = fuel[(fuel["odometer"] > first["odometer"]) & (fuel["odometer"] <= last["odometer"])]
        km = last["odometer"] - first["odometer"]
        out["km_l"] = km / between["liters"].sum() if between["liters"].sum() else None
        out["fuel_per_km"] = between["amount"].sum() / km if km else None
    km_all = ev["odometer"].dropna()
    km_span = (km_all.max() - km_all.min()) if len(km_all) >= 2 else 0
    maint = ev[ev["kind"] != "combustivel"]["amount"].sum()
    out["maint_per_km"] = maint / km_span if km_span else None

    year = date.today().year
    out["fixed_month"] = fixed[fixed["year"] == year]["amount"].sum() / 12 if not fixed.empty else 0.0
    if len(fipe) >= 2:
        n = (pd.Period(fipe["ref_month"].iloc[-1], "M") - pd.Period(fipe["ref_month"].iloc[0], "M")).n or 1
        out["depr_month"] = (fipe["value"].iloc[0] - fipe["value"].iloc[-1]) / n
    out["fipe_now"] = fipe["value"].iloc[-1] if not fipe.empty else None
    return out


# ---------- Patrimônio ----------

def latest_holdings(conn) -> pd.DataFrame:
    return pd.read_sql(
        """SELECT h.* FROM holdings h JOIN (SELECT source, MAX(snapshot) s FROM holdings GROUP BY source) m
           ON m.source = h.source AND m.s = h.snapshot ORDER BY value_brl DESC""", conn)


def net_worth_history(conn) -> pd.DataFrame:
    return pd.read_sql("SELECT snapshot, source, SUM(value_brl) AS value FROM holdings GROUP BY snapshot, source "
                       "ORDER BY snapshot", conn)


# ---------- Cartão ----------

def card_summary(conn) -> list[dict]:
    """Uma entrada por cartão: limite, usado, disponível, parcelas futuras, fatura aberta estimada, faturas."""
    df = transactions(conn)
    cards = conn.execute("SELECT * FROM accounts WHERE type='CREDIT'").fetchall()
    cur = date.today().strftime("%Y-%m")
    out = []
    for c in cards:
        sub = df[df["account_id"] == c["id"]] if not df.empty else df
        ahead = installments_ahead(sub) if not sub.empty else pd.DataFrame(columns=["month", "value"])
        future = ahead[ahead["month"] > cur] if not ahead.empty else ahead
        used = (c["credit_limit"] - c["available_limit"]) if c["credit_limit"] is not None and \
            c["available_limit"] is not None else c["balance"]
        future_total = float(future["value"].sum()) if not future.empty else 0.0
        # compras parceladas ainda em aberto (última parcela vista de cada compra)
        inst = spending(sub)
        open_inst = pd.DataFrame()
        if not inst.empty:
            inst = inst[inst["total_installments"].notna()].copy()
            if not inst.empty:
                inst["purchase"] = inst["description"].map(_norm) + "|" + inst["total_installments"].astype(int).astype(str)
                last = inst.sort_values("installment_number").groupby("purchase").tail(1)
                open_inst = last[last["installment_number"] < last["total_installments"]].assign(
                    remaining=lambda x: (x["total_installments"] - x["installment_number"]).astype(int))
                open_inst = open_inst.assign(to_pay=open_inst["value"] * open_inst["remaining"])
        bills = pd.read_sql("SELECT due_date, total, minimum FROM card_bills WHERE account_id=? ORDER BY due_date",
                            conn, params=(c["id"],))
        out.append({
            "name": c["name"], "institution": c["institution"], "limit": c["credit_limit"],
            "available": c["available_limit"], "used": used, "future_installments": future_total,
            "open_bill_estimate": (used - future_total) if used is not None else None,
            "last_due": c["bill_due_date"], "ahead": future, "open_installments": open_inst, "bills": bills,
        })
    return out


def utility_bills(conn, provider: str) -> pd.DataFrame:
    """Contas de consumo de um fornecedor com os indicadores derivados (preço por unidade, impostos em %, variação)."""
    b = pd.read_sql("SELECT * FROM utility_bills WHERE provider=? ORDER BY ref_month", conn, params=(provider,))
    if b.empty:
        return b
    b["price_full"] = b["amount"] / b["consumption"].where(b["consumption"] > 0)
    b["energy_untaxed"] = b["tariff_untaxed"] * b["consumption"]
    b["price_taxed"] = b["energy_value"] / b["consumption"].where(b["consumption"] > 0)
    b["taxes_pct"] = 100 * b["taxes_total"] / b["amount"]
    b["lighting_pct"] = 100 * b["public_lighting"] / b["amount"]
    b["daily"] = b["consumption"] / b["days"]
    b["amount_var"] = 100 * b["amount"].pct_change()
    b["cons_var"] = 100 * b["consumption"].pct_change()
    return b
