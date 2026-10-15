"""Análises: gastos, recorrências, previsão, empréstimos e carro."""
from __future__ import annotations

import re
import unicodedata
from datetime import date

import pandas as pd

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

    result = result.fillna(0.0)
    out_cols = ["Recorrentes", "Cemig + Cesama", "Parcelas cartão", "Variáveis (média)"]
    result["Saídas previstas"] = result[out_cols].sum(axis=1)
    result["Saldo previsto"] = (result["Salário"] + result["Benefícios (Flash)"] + result["A receber (empréstimos)"]
                                - result["Saídas previstas"])
    result.attrs["loans_open"] = float(loans["remaining"].sum()) if not loans.empty else 0.0
    return result


# ---------- Empréstimos ----------

def match_loan_payments(conn) -> int:
    """Casa Pix recebidos com empréstimos abertos pelo nome do pagador."""
    loans = conn.execute("SELECT * FROM loans WHERE closed=0 AND match_name IS NOT NULL AND match_name<>'' "
                         "ORDER BY date").fetchall()
    n = 0
    for loan in loans:
        needle = _norm(loan["match_name"])
        cands = conn.execute(
            """SELECT id, date, amount, description, counterparty FROM transactions
               WHERE amount > 0 AND date >= ? AND id NOT IN (SELECT transaction_id FROM loan_payments
               WHERE transaction_id IS NOT NULL) ORDER BY date""", (loan["date"],)).fetchall()
        for t in cands:
            if needle and needle in _norm(f"{t['counterparty']} {t['description']}"):
                conn.execute("INSERT INTO loan_payments(loan_id, date, amount, transaction_id, note) VALUES (?,?,?,?,?)",
                             (loan["id"], t["date"], t["amount"], t["id"], "Pix casado automaticamente"))
                conn.execute("UPDATE transactions SET category='Empréstimo recebido', manual_category='Empréstimo recebido' WHERE id=?", (t["id"],))
                n += 1
    return n


def loan_status(conn) -> pd.DataFrame:
    df = pd.read_sql(
        """SELECT l.id, l.person, l.date, l.principal, l.note, l.closed,
                  COALESCE((SELECT SUM(amount) FROM loan_payments p WHERE p.loan_id=l.id),0) AS paid
           FROM loans l ORDER BY l.closed, l.date""", conn)
    if df.empty:
        return df
    df["remaining"] = (df["principal"] - df["paid"]).clip(lower=0)
    sched = loan_schedule_open(conn)
    today = date.today().isoformat()
    nxt = sched[sched["due_date"] >= today].groupby("loan_id")["due_date"].min() if not sched.empty else {}
    late = sched[sched["due_date"] < today].groupby("loan_id")["remaining"].sum() if not sched.empty else {}
    df["next_due"] = df["id"].map(nxt)
    df["overdue"] = df["id"].map(late).fillna(0.0)
    return df


def loan_schedule_open(conn) -> pd.DataFrame:
    """Parcelas combinadas, abatendo os pagamentos recebidos na ordem do vencimento."""
    sched = pd.read_sql("SELECT s.loan_id, s.due_date, s.amount, l.person FROM loan_schedule s "
                        "JOIN loans l ON l.id=s.loan_id WHERE l.closed=0 ORDER BY s.loan_id, s.due_date", conn)
    if sched.empty:
        return sched.assign(remaining=[], month=[])
    paid = pd.read_sql("SELECT loan_id, SUM(amount) AS paid FROM loan_payments GROUP BY loan_id", conn) \
        .set_index("loan_id")["paid"].to_dict()
    rem = []
    for loan_id, grp in sched.groupby("loan_id", sort=False):
        credit = paid.get(loan_id, 0.0)
        for amt in grp["amount"]:
            used = min(credit, amt)
            credit -= used
            rem.append(amt - used)
    sched["remaining"] = rem
    sched["month"] = sched["due_date"].str[:7]
    return sched[sched["remaining"] > 0.005]


# ---------- Carro ----------

def car_summary(conn) -> dict:
    ev = pd.read_sql("SELECT * FROM car_events ORDER BY date, odometer", conn)
    fixed = pd.read_sql("SELECT * FROM car_fixed", conn)
    fipe = pd.read_sql("SELECT * FROM fipe_history ORDER BY ref_month", conn)
    out: dict = {"events": ev, "fixed": fixed, "fipe": fipe}

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
