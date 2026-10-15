"""Painel financeiro — streamlit run financas/ui/app.py

Somente consulta e registro manual de fatos (empréstimos, carro, contas).
Não existe nenhuma ação de pagamento ou movimentação de dinheiro.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from financas import analytics, config  # noqa: E402
from financas.categorize import (add_rule, all_categories, all_tags, delete_rule, recategorize,  # noqa: E402
                                 set_manual, set_tag)
from financas.db import session  # noqa: E402

# paleta categórica de referência (skill dataviz), em ordem fixa — nunca ciclada
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER = "#9a9893"
TOP_N = 7

st.set_page_config(page_title="Painel Financeiro", page_icon="📊", layout="wide")


def brl(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fold_categories(df: pd.DataFrame, col: str, value: str) -> tuple[pd.DataFrame, dict]:
    """Top N categorias por valor + 'Outros'; cor presa à categoria, não ao ranking do mês."""
    order = df.groupby(col)[value].sum().sort_values(ascending=False).index.tolist()
    keep = order[:TOP_N]
    df = df.assign(**{col: df[col].where(df[col].isin(keep), "Outros")})
    cmap = {c: SERIES[i] for i, c in enumerate(keep)}
    cmap["Outros"] = OTHER
    return df, cmap


def style(fig, height=340, month_axis=True):
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=24, b=8), legend_title_text="",
                      bargap=0.35, hovermode="x unified" if fig.data and fig.data[0].type == "scatter" else "closest")
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)", zeroline=False, tickprefix="R$ ", separatethousands=True)
    fig.update_xaxes(showgrid=False, type="category" if month_axis else None)
    return fig


with session() as conn:
    df = analytics.transactions(conn)

page = st.sidebar.radio("Seção", ["Visão geral", "Gastos", "Cartão", "Previsão", "Contas de consumo",
                                  "Empréstimos", "Carro", "Investimentos", "Sincronizar"])
st.sidebar.caption(f"Base: `{config.DB_PATH}`")

# ------------------------------------------------------------------ Visão geral
if page == "Visão geral":
    st.title("Visão geral")
    with session() as conn:
        hold = analytics.latest_holdings(conn)
        loans = analytics.loan_status(conn)
        hist = analytics.net_worth_history(conn)
        accts = pd.read_sql("SELECT institution, name, type, balance, balance_date FROM accounts", conn)
    sp, inc = analytics.spending(df), analytics.income(df)
    cur = date.today().strftime("%Y-%m")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Investimentos", brl(hold["value_brl"].sum() if not hold.empty else 0))
    bank = accts[accts["type"] == "BANK"]["balance"].sum() if not accts.empty else 0
    c2.metric("Saldo em conta", brl(bank))
    if not sp.empty:
        # compara períodos equivalentes: dia 1 até hoje, no mês atual e nos 3 anteriores
        day = date.today().day
        mtd = sp[sp["date"].dt.day <= day].groupby("month")["value"].sum()
        prev = mtd[mtd.index < cur].tail(3).mean()
        c3.metric("Gasto no mês", brl(mtd.get(cur, 0)), delta=f"dia 1–{day}, média 3m: {brl(prev)}",
                  delta_color="off", help=f"Gasto do dia 1 ao dia {day} deste mês x a média do mesmo período "
                                          "nos 3 meses anteriores. Não conta fatura, investimentos, "
                                          "transferências entre suas contas nem empréstimos.")
    else:
        c3.metric("Gasto no mês", "—")
    c4.metric("A receber (empréstimos)", brl(loans["remaining"].sum() if not loans.empty else 0))

    left, right = st.columns(2)
    with left:
        st.subheader("Entradas x saídas por mês")
        if not sp.empty:
            flow = pd.DataFrame({"Entradas": inc.groupby("month")["amount"].sum(),
                                 "Saídas": sp.groupby("month")["value"].sum()}).fillna(0).tail(12)
            flow = flow.reset_index(names="month").melt("month", var_name="Tipo", value_name="Valor")
            st.plotly_chart(style(px.bar(flow, x="month", y="Valor", color="Tipo", barmode="group",
                                         color_discrete_map={"Entradas": SERIES[0], "Saídas": SERIES[1]},
                                         labels={"month": ""})), use_container_width=True)
        else:
            st.info("Sem transações ainda — vá em **Sincronizar**.")
    with right:
        st.subheader("Patrimônio investido")
        if not hist.empty:
            piv = hist.pivot_table(index="snapshot", columns="source", values="value", aggfunc="sum").ffill().fillna(0)
            piv = piv.reset_index().melt("snapshot", var_name="Fonte", value_name="Valor")
            srcs = sorted(piv["Fonte"].unique())
            st.plotly_chart(style(px.area(piv, x="snapshot", y="Valor", color="Fonte",
                                          color_discrete_map={s: SERIES[i] for i, s in enumerate(srcs)},
                                          labels={"snapshot": ""}), month_axis=False), use_container_width=True)
        else:
            st.info("Sem posições ainda.")

# ------------------------------------------------------------------ Gastos
elif page == "Gastos":
    st.title("Para onde vai o dinheiro")
    sp = analytics.spending(df)
    if sp.empty:
        st.info("Sem transações ainda.")
        st.stop()
    months = sorted(sp["month"].unique())
    sel = st.select_slider("Período", options=months, value=(months[max(0, len(months) - 6)], months[-1]))
    win = sp[(sp["month"] >= sel[0]) & (sp["month"] <= sel[1])]
    folded, cmap = fold_categories(win, "category", "value")

    st.subheader("Gasto mensal por categoria")
    agg = folded.groupby(["month", "category"], as_index=False)["value"].sum()
    fig = px.bar(agg, x="month", y="value", color="category", color_discrete_map=cmap,
                 category_orders={"category": list(cmap)}, labels={"month": "", "value": "Valor", "category": ""})
    fig.update_traces(marker_line_width=2, marker_line_color="rgba(0,0,0,0)")
    st.plotly_chart(style(fig, 380), use_container_width=True)

    left, right = st.columns([1, 1])
    with left:
        st.subheader("Ranking no período")
        rank = win.groupby("category")["value"].agg(["sum", "count"]).sort_values("sum", ascending=False)
        rank["média/mês"] = rank["sum"] / win["month"].nunique()
        st.dataframe(rank.rename(columns={"sum": "total", "count": "lançamentos"})
                     .style.format({"total": brl, "média/mês": brl}), use_container_width=True)
    with right:
        st.subheader("Recorrentes detectados")
        st.caption("Pix e cobranças que se repetem quase todo mês com valor parecido.")
        rec = analytics.recurring(df)
        st.dataframe(rec.rename(columns={"key": "descrição", "category": "categoria", "monthly": "valor/mês",
                                         "hits": "meses", "last": "último"})
                     .style.format({"valor/mês": brl}), use_container_width=True, hide_index=True)

    st.subheader("Lançamentos")
    cats = st.multiselect("Categorias", sorted(win["category"].unique()))
    q = st.text_input("Buscar descrição / contraparte")
    show = win if not cats else win[win["category"].isin(cats)]
    if q:
        show = show[(show["description"].fillna("") + " " + show["counterparty"].fillna(""))
                    .str.contains(q, case=False)]
    st.dataframe(show.fillna({"counterparty": "", "description": ""}).sort_values("date", ascending=False)[
        ["date", "description", "counterparty", "category", "tag", "value", "institution", "installment_number",
         "total_installments"]].rename(columns={"tag": "subdivisão"})
        .style.format({"value": brl, "date": lambda d: d.strftime("%d/%m/%Y")}, na_rep=""),
        use_container_width=True, hide_index=True)
    st.caption("Valores negativos em 'value' são reembolsos (ex.: amigos devolvendo a parte deles) e abatem o gasto.")

    st.subheader("Corrigir categoria")
    st.caption("Use a busca/filtro acima para achar o lançamento. Suas correções sempre vencem as regras padrão.")
    pick = show.sort_values("date", ascending=False).head(300)
    if pick.empty:
        st.info("Nenhum lançamento no filtro atual.")
    else:
        def txt(v) -> str:
            return "" if v is None or pd.isna(v) else str(v)

        labels = {f"{r.date:%d/%m/%Y} · {txt(r.description)} · {txt(r.counterparty)} · {brl(r.value)} · [{r.category}]": r
                  for r in pick.itertuples()}
        with session() as conn:
            cat_options = all_categories(conn)
            tag_options = all_tags(conn)
        # fora do form para que o nome sugerido acompanhe o lançamento escolhido
        chosen = labels[st.selectbox("Lançamento", list(labels))]
        with st.form("fix_category"):
            new_cat = st.selectbox("Categoria certa", cat_options,
                                   index=cat_options.index(chosen.category) if chosen.category in cat_options else 0)
            scope = st.radio("Aplicar em", ["Só este lançamento", "Sempre que aparecer este nome"], horizontal=True)
            name = st.text_input("Nome que identifica (para 'sempre')", txt(chosen.counterparty) or txt(chosen.description),
                                 key=f"rule_name_{chosen.id}",
                                 help="Pode encurtar: 'MARIA SILVA' pega todo Pix com esse nome. Acentos e "
                                      "maiúsculas não importam.")
            t1, t2 = st.columns(2)
            cur_tag = txt(chosen.tag)
            tag_pick = t1.selectbox("Subdivisão (opcional)", ["— nenhuma —"] + tag_options,
                                    index=(tag_options.index(cur_tag) + 1) if cur_tag in tag_options else 0,
                                    key=f"tag_pick_{chosen.id}")
            tag_new = t2.text_input("…ou criar nova subdivisão", key=f"tag_new_{chosen.id}",
                                    placeholder="ex.: Viagem Rio 2027")
            if st.form_submit_button("Salvar correção"):
                tag = tag_new.strip() or (None if tag_pick == "— nenhuma —" else tag_pick)
                with session() as conn:
                    set_tag(conn, chosen.id, tag)
                    if scope == "Só este lançamento":
                        set_manual(conn, chosen.id, new_cat)
                        st.session_state["fix_msg"] = f"Lançamento corrigido para **{new_cat}**."
                    else:
                        n = add_rule(conn, name, new_cat)
                        st.session_state["fix_msg"] = (f"Regra criada: **{name}** → **{new_cat}** "
                                                       f"({n} lançamento(s) com esse nome).")
                st.rerun()
    if msg := st.session_state.pop("fix_msg", None):
        st.success(msg)

    with session() as conn:
        tagged = pd.read_sql("SELECT tag, category, date, amount FROM transactions WHERE tag IS NOT NULL", conn,
                             parse_dates=["date"])
    if not tagged.empty:
        st.subheader("Por subdivisão")
        st.caption("Custo líquido (gastos − reembolsos) de cada subdivisão, em todo o período.")
        agg = tagged.groupby("tag").agg(custo=("amount", lambda x: -x.sum()), lançamentos=("amount", "size"),
                                        início=("date", "min"), fim=("date", "max"),
                                        categorias=("category", lambda x: ", ".join(sorted(set(x))))).reset_index()
        st.dataframe(agg.rename(columns={"tag": "subdivisão"}).sort_values("início", ascending=False)
                     .style.format({"custo": brl, "início": lambda d: d.strftime("%d/%m/%Y"),
                                    "fim": lambda d: d.strftime("%d/%m/%Y")}), use_container_width=True, hide_index=True)

    with session() as conn:
        mine = pd.read_sql("SELECT pattern, category, created_at FROM user_rules ORDER BY created_at DESC", conn)
    if not mine.empty:
        with st.expander(f"Minhas regras ({len(mine)})"):
            st.dataframe(mine.rename(columns={"pattern": "nome", "category": "categoria", "created_at": "criada em"}),
                         use_container_width=True, hide_index=True)
            # em form: escolher a regra não recarrega a página (senão o expander fecha e esconde o botão)
            with st.form("delete_rule"):
                rm = st.selectbox("Apagar regra", ["—"] + mine["pattern"].tolist())
                if st.form_submit_button("Apagar") and rm != "—":
                    with session() as conn:
                        delete_rule(conn, rm)
                    st.session_state["fix_msg"] = f"Regra **{rm}** apagada; lançamentos voltaram às regras padrão."
                    st.rerun()

# ------------------------------------------------------------------ Cartão
elif page == "Cartão":
    st.title("Cartão de crédito")
    with session() as conn:
        cards = analytics.card_summary(conn)
    if not cards:
        st.info("Nenhum cartão conectado.")
        st.stop()
    for card in cards:
        st.subheader(f"{card['institution']} · {card['name']}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Limite", brl(card["limit"]))
        c2.metric("Usado", brl(card["used"]), help="Limite − disponível. Inclui as parcelas futuras.")
        c3.metric("Disponível", brl(card["available"]))
        c4.metric("Fatura aberta (estimada)", brl(card["open_bill_estimate"]),
                  help="Usado − parcelas dos próximos meses. A fatura real só fecha no vencimento.")
        if card["limit"]:
            st.progress(min(1.0, (card["used"] or 0) / card["limit"]),
                        text=f"{(card['used'] or 0) / card['limit']:.0%} do limite comprometido · "
                             f"parcelas futuras {brl(card['future_installments'])}")
        left, right = st.columns(2)
        with left:
            st.markdown("**Parcelas já contratadas por mês**")
            if not card["ahead"].empty:
                fig = px.bar(card["ahead"], x="month", y="value", labels={"month": "", "value": "Valor"})
                fig.update_traces(marker_color=SERIES[1])
                st.plotly_chart(style(fig, 280), use_container_width=True)
            else:
                st.caption("Nenhuma parcela futura.")
        with right:
            st.markdown("**Faturas (últimos 12 meses)**")
            if not card["bills"].empty:
                fig = px.bar(card["bills"], x="due_date", y="total", labels={"due_date": "vencimento", "total": "Valor"})
                fig.update_traces(marker_color=SERIES[0])
                st.plotly_chart(style(fig, 280, month_axis=False), use_container_width=True)
        oi = card["open_installments"]
        if not oi.empty:
            st.markdown("**Compras parceladas em aberto**")
            st.dataframe(oi.sort_values("to_pay", ascending=False)[
                ["date", "description", "installment_number", "total_installments", "value", "remaining", "to_pay"]]
                .rename(columns={"date": "última parcela", "description": "compra", "installment_number": "parcela",
                                 "total_installments": "de", "value": "valor parcela", "remaining": "faltam",
                                 "to_pay": "a pagar"})
                .style.format({"valor parcela": brl, "a pagar": brl, "última parcela": lambda d: d.strftime("%d/%m/%Y"),
                               "parcela": "{:.0f}", "de": "{:.0f}"}), use_container_width=True, hide_index=True)

# ------------------------------------------------------------------ Previsão
elif page == "Previsão":
    st.title("Estimativa dos próximos meses")
    n = st.slider("Meses", 3, 12, 6)
    with session() as conn:
        fc = analytics.forecast(conn, n)
    st.caption("Salário = mediana dos últimos 3 meses fechados · Recorrentes = Pix/assinaturas detectados · "
               "Cemig/Cesama = mesmo mês do ano anterior (ou média 3m) · Parcelas = compras parceladas já feitas · "
               "Variáveis = mediana do resto · A receber = parcelas combinadas dos empréstimos · "
               "Benefícios (Flash) = rendas fora do banco cadastradas abaixo. Mesada não entra (conservador).")
    out_cols = ["Recorrentes", "Cemig + Cesama", "Parcelas cartão", "Variáveis (média)"]
    long = fc.melt("month", value_vars=out_cols, var_name="Componente", value_name="Valor")
    fig = px.bar(long, x="month", y="Valor", color="Componente",
                 color_discrete_map={c: SERIES[i] for i, c in enumerate(out_cols)}, labels={"month": ""})
    fig.add_scatter(x=fc["month"], y=fc["Salário"] + fc["Benefícios (Flash)"] + fc["A receber (empréstimos)"], mode="lines+markers",
                    name="Entradas previstas", line=dict(color=SERIES[6], width=2), marker=dict(size=8))
    st.plotly_chart(style(fig, 380), use_container_width=True)
    money = [c for c in fc.columns if c != "month"]
    st.dataframe(fc.style.format({c: brl for c in money}), use_container_width=True, hide_index=True)

    st.subheader("Rendas fora do banco")
    st.caption("Valores fixos que o Open Finance não enxerga (ex.: benefícios no Flash). Entram só na previsão; "
               "o histórico mostra apenas o que de fato caiu na conta.")
    with session() as conn:
        oi = pd.read_sql("SELECT id, name, amount, day, category, active, note FROM other_income ORDER BY day", conn)
    if not oi.empty:
        st.dataframe(oi.drop(columns="id").rename(columns={"name": "nome", "amount": "valor/mês", "day": "dia",
                                                           "category": "categoria", "active": "ativa", "note": "obs"})
                     .style.format({"valor/mês": brl}), use_container_width=True, hide_index=True)
    with st.form("other_income"):
        a, b, c = st.columns([3, 2, 1])
        name = a.text_input("Nome (igual a um existente = atualiza)")
        amt = b.number_input("Valor mensal (R$)", min_value=0.0, step=10.0)
        day = c.number_input("Dia", min_value=1, max_value=31, value=1)
        active = st.checkbox("Ativa (entra na previsão)", value=True)
        note = st.text_input("Observação")
        if st.form_submit_button("Salvar renda") and name:
            with session() as conn:
                conn.execute("INSERT INTO other_income(name, amount, day, active, note) VALUES (?,?,?,?,?) "
                             "ON CONFLICT(name) DO UPDATE SET amount=excluded.amount, day=excluded.day, "
                             "active=excluded.active, note=excluded.note", (name, amt, int(day), int(active), note))
            st.rerun()

# ------------------------------------------------------------------ Contas de consumo
elif page == "Contas de consumo":
    st.title("Cemig e Cesama")
    with session() as conn:
        bills = pd.read_sql("SELECT * FROM utility_bills ORDER BY ref_month", conn)
    if bills.empty:
        st.info("Nenhuma conta ainda. Envie o PDF abaixo ou lance manualmente.")
    else:
        bills["Fornecedor"] = bills["provider"].str.capitalize()
        cmap = {"Cemig": SERIES[3], "Cesama": SERIES[0]}
        a, b = st.columns(2)
        a.subheader("Valor (R$)")
        a.plotly_chart(style(px.bar(bills, x="ref_month", y="amount", color="Fornecedor", barmode="group",
                                    color_discrete_map=cmap, labels={"ref_month": "", "amount": "Valor"})),
                       use_container_width=True)
        for prov, unit, col in (("cemig", "kWh", b), ("cesama", "m3", b)):
            sub = bills[bills["provider"] == prov]
            if not sub.empty:
                fig = px.line(sub, x="ref_month", y="consumption", markers=True, labels={"ref_month": "", "consumption": unit})
                fig.update_traces(line=dict(color=cmap[prov.capitalize()], width=2), marker=dict(size=8))
                fig.update_yaxes(tickprefix="")
                col.subheader(f"Consumo {prov.capitalize()} ({unit})")
                col.plotly_chart(style(fig, 160), use_container_width=True)
        st.dataframe(bills[["Fornecedor", "ref_month", "due_date", "amount", "consumption", "unit", "file"]]
                     .style.format({"amount": brl}), use_container_width=True, hide_index=True)

    st.subheader("Adicionar conta")
    up_col, man_col = st.columns(2)
    with up_col:
        prov = st.selectbox("Fornecedor do PDF", ["cemig", "cesama"])
        files = st.file_uploader("PDF da fatura", type="pdf", accept_multiple_files=True)
        if files and st.button("Importar PDFs"):
            from financas.importers import utility_pdf
            (config.INBOX / prov).mkdir(parents=True, exist_ok=True)
            for f in files:
                (config.INBOX / prov / f.name).write_bytes(f.getbuffer())
            with session() as conn:
                res = utility_pdf.import_inbox(conn, config.INBOX)
            for r in res:
                (st.success if r["amount"] and r["ref_month"] else st.warning)(
                    f"{r['file']}: {brl(r['amount'])} · ref {r['ref_month']} · venc {r['due_date']} · "
                    f"{r['consumption']} {r['unit']}")
    with man_col:
        with st.form("bill"):
            p = st.selectbox("Fornecedor", ["cemig", "cesama"])
            ref = st.text_input("Mês de referência (AAAA-MM)", date.today().strftime("%Y-%m"))
            due = st.date_input("Vencimento")
            amt = st.number_input("Valor (R$)", min_value=0.0, step=1.0)
            cons = st.number_input("Consumo (kWh ou m³)", min_value=0.0, step=1.0)
            if st.form_submit_button("Salvar"):
                with session() as conn:
                    conn.execute("INSERT OR REPLACE INTO utility_bills(provider, ref_month, due_date, amount, consumption,"
                                 " unit) VALUES (?,?,?,?,?,?)", (p, ref, due.isoformat(), amt, cons,
                                                                 "kWh" if p == "cemig" else "m3"))
                st.rerun()

# ------------------------------------------------------------------ Empréstimos
elif page == "Empréstimos":
    st.title("Empréstimos a receber")
    with session() as conn:
        loans = analytics.loan_status(conn)
        sched = analytics.loan_schedule_open(conn)
        pays = pd.read_sql("SELECT p.*, l.person FROM loan_payments p JOIN loans l ON l.id=p.loan_id ORDER BY p.date DESC",
                           conn)
    if not loans.empty:
        open_ = loans[loans["closed"] == 0]
        c1, c2, c3 = st.columns(3)
        c1.metric("Total a receber", brl(open_["remaining"].sum()))
        c2.metric("Em atraso", brl(open_["overdue"].sum()))
        c3.metric("Pessoas", open_["person"].nunique())
        st.dataframe(loans[["person", "date", "principal", "paid", "remaining", "overdue", "next_due", "note", "closed"]]
                     .rename(columns={"person": "pessoa", "date": "data", "principal": "emprestado", "paid": "recebido",
                                      "remaining": "falta", "overdue": "atrasado", "next_due": "próx. venc.",
                                      "note": "obs", "closed": "quitado"})
                     .style.format({"emprestado": brl, "recebido": brl, "falta": brl, "atrasado": brl}),
                     use_container_width=True, hide_index=True)
        if not sched.empty:
            st.subheader("Quando vou receber")
            st.dataframe(sched[["person", "due_date", "amount", "remaining"]]
                         .rename(columns={"person": "pessoa", "due_date": "vencimento", "amount": "parcela",
                                          "remaining": "em aberto"})
                         .style.format({"parcela": brl, "em aberto": brl}), use_container_width=True, hide_index=True)
        if not pays.empty:
            st.subheader("Recebimentos")
            st.dataframe(pays[["person", "date", "amount", "note"]].style.format({"amount": brl}),
                         use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum empréstimo registrado.")

    st.subheader("Novo empréstimo")
    out_pix = df[(df.get("amount", pd.Series(dtype=float)) < 0)].sort_values("date", ascending=False).head(40) \
        if not df.empty else pd.DataFrame()
    with st.form("loan"):
        a, b = st.columns(2)
        person = a.text_input("Pessoa")
        match = b.text_input("Nome como aparece no Pix dela (para casar automaticamente)",
                             help="Ex.: 'JOAO DA SILVA'. Pix recebidos com esse trecho no nome abatem a dívida.")
        d = a.date_input("Data do empréstimo")
        principal = b.number_input("Valor emprestado (R$)", min_value=0.0, step=50.0)
        n = a.number_input("Nº de parcelas combinadas (0 = sem data)", min_value=0, step=1, value=1)
        first = b.date_input("1º vencimento")
        note = st.text_input("Observação (ex.: 'conserto do carro, paga dia 10')")
        tx_opts = {"—": None} | {f"{r.date:%d/%m} · {r.description} · {r.counterparty or ''} · {brl(-r.amount)}": r.id
                                 for r in out_pix.itertuples()} if not out_pix.empty else {"—": None}
        tx_sel = st.selectbox("Pix de saída correspondente (opcional — tira do cálculo de gastos)", list(tx_opts))
        if st.form_submit_button("Registrar") and person and principal > 0:
            with session() as conn:
                cur = conn.execute("INSERT INTO loans(person, match_name, date, principal, note, transaction_id) "
                                   "VALUES (?,?,?,?,?,?)", (person, match or None, d.isoformat(), principal, note,
                                                            tx_opts[tx_sel]))
                if n:
                    per = round(principal / n, 2)
                    for k in range(int(n)):
                        due = (pd.Timestamp(first) + pd.DateOffset(months=k)).date().isoformat()
                        amt = per if k < n - 1 else round(principal - per * (n - 1), 2)
                        conn.execute("INSERT INTO loan_schedule(loan_id, due_date, amount) VALUES (?,?,?)",
                                     (cur.lastrowid, due, amt))
                if tx_opts[tx_sel]:
                    conn.execute("UPDATE transactions SET category='Empréstimo concedido', manual_category='Empréstimo concedido' WHERE id=?", (tx_opts[tx_sel],))
                analytics.match_loan_payments(conn)
            st.rerun()

    if not loans.empty:
        st.subheader("Lançar recebimento manual / quitar")
        with st.form("pay"):
            opts = {f"{r.person} ({brl(r.remaining)})": r.id for r in loans[loans["closed"] == 0].itertuples()}
            if opts:
                who = st.selectbox("Empréstimo", list(opts))
                pd_ = st.date_input("Data")
                amt = st.number_input("Valor recebido (R$)", min_value=0.0, step=50.0)
                close = st.checkbox("Marcar como quitado")
                if st.form_submit_button("Salvar"):
                    with session() as conn:
                        if amt > 0:
                            conn.execute("INSERT INTO loan_payments(loan_id, date, amount, note) VALUES (?,?,?,?)",
                                         (opts[who], pd_.isoformat(), amt, "manual"))
                        if close:
                            conn.execute("UPDATE loans SET closed=1 WHERE id=?", (opts[who],))
                    st.rerun()
            else:
                st.form_submit_button("Salvar", disabled=True)

# ------------------------------------------------------------------ Carro
elif page == "Carro":
    st.title("Quanto me custa o carro")
    with session() as conn:
        car = analytics.car_summary(conn)
    fuel_card = analytics.spending(df)
    fuel_card = fuel_card[fuel_card["category"] == "Carro - Combustível"] if not fuel_card.empty else fuel_card

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Consumo médio", f"{car['km_l']:.1f} km/L" if car.get("km_l") else "—")
    c2.metric("Combustível por km", brl(car.get("fuel_per_km")))
    c3.metric("Fixos por mês", brl(car.get("fixed_month")), help="Seguro + IPVA + licenciamento do ano ÷ 12")
    c4.metric("Depreciação por mês", brl(car.get("depr_month")), help=f"FIPE atual {brl(car.get('fipe_now'))}")
    per_km = sum(v for v in (car.get("fuel_per_km"), car.get("maint_per_km")) if v)
    st.caption(f"Custo variável ≈ **{brl(per_km)} / km** (combustível + manutenção). "
               f"Gasto em posto no cartão (últimos 3 meses): "
               f"{brl(fuel_card[fuel_card['date'] >= pd.Timestamp.today() - pd.DateOffset(months=3)]['value'].sum() if not fuel_card.empty else 0)}.")

    ev = car["events"]
    if not ev.empty:
        f = ev[ev["kind"] == "combustivel"].copy()
        if len(f) > 1:
            f["km_l"] = f["odometer"].diff() / f["liters"]
            fig = px.line(f.dropna(subset=["km_l"]), x="date", y="km_l", markers=True,
                          labels={"date": "", "km_l": "km/L"})
            fig.update_traces(line=dict(color=SERIES[0], width=2), marker=dict(size=8))
            fig.update_yaxes(tickprefix="")
            st.subheader("km/L por abastecimento")
            st.plotly_chart(style(fig, 260, month_axis=False), use_container_width=True)
        st.dataframe(ev.sort_values("date", ascending=False).style.format({"amount": brl}),
                     use_container_width=True, hide_index=True)

    a, b, c = st.columns(3)
    with a.form("fuel"):
        st.markdown("**Abastecimento / manutenção**")
        kind = st.selectbox("Tipo", ["combustivel", "manutencao", "outro"])
        d = st.date_input("Data")
        odo = st.number_input("Odômetro (km)", min_value=0.0, step=1.0)
        liters = st.number_input("Litros", min_value=0.0, step=0.1)
        full = st.checkbox("Tanque cheio", value=True)
        trip = st.selectbox("Uso predominante", ["cidade", "estrada", "misto"])
        amt = st.number_input("Valor (R$)", min_value=0.0, step=1.0)
        note = st.text_input("Obs.")
        if st.form_submit_button("Salvar"):
            with session() as conn:
                conn.execute("INSERT INTO car_events(date, kind, odometer, liters, full_tank, trip, amount, note) "
                             "VALUES (?,?,?,?,?,?,?,?)", (d.isoformat(), kind, odo or None, liters or None, int(full),
                                                          trip, amt, note))
            st.rerun()
    with b.form("fixed"):
        st.markdown("**Custos fixos do ano**")
        y = st.number_input("Ano", value=date.today().year, step=1)
        item = st.selectbox("Item", ["seguro", "ipva", "licenciamento", "garagem", "financiamento"])
        v = st.number_input("Valor anual (R$)", min_value=0.0, step=10.0)
        if st.form_submit_button("Salvar"):
            with session() as conn:
                conn.execute("INSERT OR REPLACE INTO car_fixed(year, item, amount) VALUES (?,?,?)", (int(y), item, v))
            st.rerun()
    with c.form("fipe"):
        st.markdown("**Tabela FIPE**")
        ref = st.text_input("Mês (AAAA-MM)", date.today().strftime("%Y-%m"))
        v = st.number_input("Valor FIPE (R$)", min_value=0.0, step=100.0)
        if st.form_submit_button("Salvar"):
            with session() as conn:
                conn.execute("INSERT OR REPLACE INTO fipe_history VALUES (?,?)", (ref, v))
            st.rerun()

# ------------------------------------------------------------------ Investimentos
elif page == "Investimentos":
    st.title("Investimentos")
    with session() as conn:
        hold = analytics.latest_holdings(conn)
    if hold.empty:
        st.info("Sem posições. Configure Binance e Pluggy (XP) e sincronize.")
        st.stop()
    for src, grp in hold.groupby("source"):
        st.subheader(f"{src.upper()} — {brl(grp['value_brl'].sum())}  ·  posição de {grp['snapshot'].iloc[0]}")
        cols = ["asset", "asset_type", "quantity", "price_usd", "value_brl"]
        st.dataframe(grp[cols].rename(columns={"asset": "ativo", "asset_type": "tipo", "quantity": "qtd",
                                               "price_usd": "preço US$", "value_brl": "valor"})
                     .style.format({"valor": brl, "preço US$": "{:,.2f}", "qtd": "{:,.8g}"}, na_rep="—"),
                     use_container_width=True, hide_index=True)

# ------------------------------------------------------------------ Sincronizar
elif page == "Sincronizar":
    st.title("Coleta de dados")
    st.write("Fontes: **Pluggy** (Inter + XP via Open Finance) · **Binance** (API só leitura) · "
             "**PDFs** em `data/inbox/cemig|cesama` · **OFX** em `data/inbox/ofx` (plano B).")
    status = {
        "Pluggy": bool(config.PLUGGY_CLIENT_ID and config.PLUGGY_ITEM_IDS),
        "Binance": bool(config.BINANCE_API_KEY),
    }
    st.write(" · ".join(f"{k}: {'✅ configurado' if v else '⚪ falta no .env'}" for k, v in status.items()))
    a, b = st.columns(2)
    if a.button("🔄 Sincronizar tudo", type="primary"):
        from financas.sync import run_all
        with st.spinner("Coletando…"):
            for name, ok, msg in run_all():
                (st.success if ok else st.error)(f"{name}: {msg}")
    if b.button("Recategorizar tudo (após editar rules.yaml)"):
        with session() as conn:
            st.success(f"{recategorize(conn)} transações recategorizadas")
    ofx_files = st.file_uploader("Extrato/fatura OFX do Inter", type="ofx", accept_multiple_files=True)
    if ofx_files and st.button("Importar OFX"):
        from financas.importers import ofx
        with session() as conn:
            for f in ofx_files:
                p = config.INBOX / "ofx" / f.name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(f.getbuffer())
                st.success(f"{f.name}: {ofx.import_file(conn, p)} transações")
            recategorize(conn, only_missing=True)
            analytics.match_loan_payments(conn)
    with session() as conn:
        logs = pd.read_sql("SELECT at, source, ok, message FROM sync_log ORDER BY id DESC LIMIT 50", conn)
    st.subheader("Histórico")
    st.dataframe(logs, use_container_width=True, hide_index=True)
