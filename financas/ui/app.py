"""Painel financeiro — streamlit run financas/ui/app.py

Somente consulta e registro manual de fatos (empréstimos, carro, contas).
Não existe nenhuma ação de pagamento ou movimentação de dinheiro.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from financas import analytics, backup, config, settings  # noqa: E402
from financas.categorize import (add_rule, all_categories, all_tags, delete_rule, recategorize,  # noqa: E402
                                 set_manual, set_tag)
from financas.db import session as db_session  # noqa: E402

# paleta categórica de referência (skill dataviz), em ordem fixa — nunca ciclada
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER = "#9a9893"
TOP_N = 7

ENV_NAME = os.getenv("FIN_ENV_NAME", "")
st.set_page_config(page_title="[DEV] Painel Financeiro" if ENV_NAME == "dev" else "Painel Financeiro",
                   page_icon="🧪" if ENV_NAME == "dev" else "📊", layout="wide")
if ENV_NAME in ("dev", "prod"):  # faixa fixa no topo: impossível confundir os ambientes
    bg, label = (("#d9480f", "🧪 AMBIENTE DE DESENVOLVIMENTO — dados de teste (clone de prod). Nada aqui afeta produção.")
                 if ENV_NAME == "dev" else ("#2b8a3e", "PRODUÇÃO — dados reais"))
    st.markdown(f"""<style>
      .env-banner {{position:fixed;top:0;left:0;right:0;z-index:999999;background:{bg};color:#fff;text-align:center;
                   font-weight:700;padding:{'8px' if ENV_NAME == 'dev' else '2px'} 12px;
                   font-size:{'15px' if ENV_NAME == 'dev' else '11px'};letter-spacing:.3px}}
      .stApp {{padding-top:{'38px' if ENV_NAME == 'dev' else '18px'}}}
    </style><div class="env-banner">{label}</div>""", unsafe_allow_html=True)


def brl(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _read_date(bill: dict, key: str = "read_curr") -> date | None:
    """Data de leitura da Cemig ("dd/mm" no PDF) com o ano do mês de referência."""
    if not bill.get(key):
        return None
    d, m = map(int, bill[key].split("/"))
    y, ref_m = map(int, bill["ref_month"].split("-"))
    return date(y + (1 if m < ref_m - 6 else 0), m, d)


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


# ------------------------------------------------------------------ tema, backup automático, ver backup
THEME_FILE = Path.cwd() / ".streamlit" / "config.toml"  # o Streamlit lê o tema daqui (pasta onde o painel roda)
THEME_MARK = "# gerado pelo painel (aba Configurações) — pode apagar para voltar ao padrão"


def apply_theme(theme: str) -> bool | None:
    """Grava o tema na configuração do Streamlit. True = mudou (recarregar a página); None = arquivo próprio."""
    text = THEME_MARK + "\n" + (f'[theme]\nbase = "{theme}"\n' if theme in ("light", "dark") else "")
    current = THEME_FILE.read_text() if THEME_FILE.exists() else None
    if current is not None and THEME_MARK not in current:
        return None  # configuração escrita à mão: não mexer
    if current == text:
        return False
    THEME_FILE.parent.mkdir(exist_ok=True)
    THEME_FILE.write_text(text)
    return True


def reload_page() -> None:
    """O tema só vale para a página carregada depois da mudança: recarrega (após o Streamlit reler o arquivo)."""
    import streamlit.components.v1 as components
    components.html("<script>setTimeout(() => window.parent.location.reload(), 1500)</script>", height=0)


ENERGY_PROVIDERS = ("cemig", "edp")  # distribuidoras de energia com leitor de PDF
PROVIDER_NAMES = {"cemig": "Cemig", "edp": "EDP", "cesama": "Cesama"}


def backup_label(b: dict) -> str:
    return f"{b['created']:%d/%m/%Y %H:%M}" + (" · manual" if b["kind"] == "manual" else "")


if "booted" not in st.session_state:  # uma vez por visita: tema salvo e backup automático
    st.session_state.booted = True
    with db_session() as conn:
        saved_theme = settings.get(conn, "theme")
    if apply_theme(saved_theme):
        st.info("Aplicando o tema salvo…")
        reload_page()
        st.stop()
    try:
        made = backup.auto()
        if made:
            st.toast(f"Backup automático feito ({made.name})")
    except Exception as e:  # noqa: BLE001 — backup nunca derruba o painel
        st.toast(f"Backup automático falhou: {e}")

views = {"Dados atuais": None} | {f"Backup de {backup_label(b)}": b["path"] for b in backup.list_backups()}
if st.session_state.get("view") not in views:
    st.session_state["view"] = "Dados atuais"
VIEW = views[st.sidebar.selectbox("Ver dados de", list(views), key="view")]
DB = backup.open_for_view(VIEW) if VIEW else config.DB_PATH


@contextmanager
def session():
    """Banco do painel: o atual, ou o backup escolhido em "Ver dados de" (somente leitura)."""
    try:
        with db_session(DB, readonly=VIEW is not None) as conn:
            yield conn
    except sqlite3.OperationalError as e:
        if VIEW is not None and "readonly" in str(e):
            st.error("Você está vendo um backup: nada é gravado. Volte para **Dados atuais** em \"Ver dados de\" "
                     "para fazer alterações.")
            st.stop()
        raise


if VIEW:
    st.warning(f"📦 Você está vendo os dados do **{st.session_state['view'].lower()}** — somente leitura.")

with session() as conn:
    df = analytics.transactions(conn)

page = st.sidebar.radio("Seção", ["Visão geral", "Gastos", "Cartão", "Previsão", "Contas de consumo",
                                  "Empréstimos", "Carro", "Investimentos", "Sincronizar", "Configurações"])
if os.getenv("FIN_ENV_NAME") == "dev":
    st.sidebar.warning("🧪 **DESENVOLVIMENTO** — dados de teste (clone de prod)")
st.sidebar.caption(f"Base: `{DB}`")

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
    out_cols = ["Recorrentes", "Cemig + Cesama", "Parcelas cartão", "Empréstimo (banco)", "Variáveis (média)"]
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
    st.title("Contas de consumo")
    with session() as conn:
        energia = {p: analytics.utility_bills(conn, p) for p in ENERGY_PROVIDERS}
        ces = analytics.utility_bills(conn, "cesama")
    energia = {p: d for p, d in energia.items() if not d.empty} or {"cemig": energia["cemig"]}
    cem = next(iter(energia.values()))
    if cem.empty and ces.empty:
        st.info("Nenhuma conta ainda. Envie o PDF abaixo ou lance manualmente.")
    esc = lambda txt: txt.replace("$", "\\$")  # noqa: E731  (evita o Streamlit ler R$ como fórmula)
    pct = lambda v: "—" if pd.isna(v) else f"{v:+.0f}%"  # noqa: E731
    fmt = lambda f, suf="": (lambda v: "—" if pd.isna(v) else format(v, f) + suf)  # noqa: E731  (conta sem detalhe não quebra a tabela)
    tab_e, tab_a = st.tabs([f"⚡ Energia ({', '.join(PROVIDER_NAMES[p] for p in energia)})", "💧 Água (Cesama)"])

    with tab_e:
        if len(energia) > 1:  # mais de uma distribuidora com contas (ex.: mudança de cidade)
            prov_e = st.radio("Distribuidora", list(energia), format_func=PROVIDER_NAMES.get, horizontal=True)
            cem = energia[prov_e]
        if not cem.empty:
            dist = PROVIDER_NAMES[cem["provider"].iloc[0]]
            last12 = cem.tail(12)
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Gasto em 12 meses", brl(last12["amount"].sum()), f"média {brl(last12['amount'].mean())}/mês",
                      delta_color="off")
            c2.metric("Consumo em 12 meses", f"{last12['consumption'].sum():,.0f} kWh".replace(",", "."),
                      f"média {last12['consumption'].mean():.0f} kWh/mês", delta_color="off")
            c3.metric("kWh puro (sem impostos)", brl(last12["energy_untaxed"].sum() / last12["consumption"].sum()),
                      f"tarifa da {dist}", delta_color="off")
            c4.metric("kWh cheio (tudo incluído)", brl(last12["amount"].sum() / last12["consumption"].sum()),
                      "impostos + iluminação + taxas", delta_color="off")
            c5.metric("Impostos", f"{100 * last12['taxes_total'].sum() / last12['amount'].sum():.1f}% da conta",
                      f"iluminação pública: {100 * last12['public_lighting'].sum() / last12['amount'].sum():.1f}%",
                      delta_color="off")

            st.subheader("Para onde vai o dinheiro da conta")
            comp = cem.assign(**{"Energia (tarifa)": cem["energy_untaxed"], "ICMS": cem["icms"],
                                 "PIS + COFINS": cem["pis"].fillna(0) + cem["cofins"].fillna(0),
                                 "Iluminação pública": cem["public_lighting"], "Multas, juros e créditos": cem["other_fees"]})
            # arredondamento da tarifa: a diferença vai para a energia, para a pilha fechar com o total
            comp["Energia (tarifa)"] += comp["amount"] - comp[["Energia (tarifa)", "ICMS", "PIS + COFINS",
                                                                "Iluminação pública", "Multas, juros e créditos"]].sum(axis=1)
            long = comp.melt(id_vars="ref_month", value_vars=["Energia (tarifa)", "ICMS", "PIS + COFINS",
                                                              "Iluminação pública", "Multas, juros e créditos"],
                             var_name="Parte", value_name="R$")
            st.plotly_chart(style(px.bar(long, x="ref_month", y="R$", color="Parte", color_discrete_sequence=SERIES,
                                         labels={"ref_month": ""})), use_container_width=True)

            a, b = st.columns(2)
            a.subheader("Preço do kWh")
            pr = cem.melt(id_vars="ref_month", value_vars=["tariff_untaxed", "price_taxed", "price_full"],
                          var_name="Preço", value_name="R$/kWh")
            pr["Preço"] = pr["Preço"].map({"tariff_untaxed": "Puro (sem impostos)", "price_taxed": "Com impostos",
                                           "price_full": "Cheio (tudo incluído)"})
            fig = px.line(pr, x="ref_month", y="R$/kWh", color="Preço", markers=True, color_discrete_sequence=SERIES,
                          labels={"ref_month": ""})
            a.plotly_chart(style(fig, 300), use_container_width=True)
            a.caption("A iluminação pública é cobrada por faixa de consumo: abaixo de ~100 kWh ela cai para R\\$ 6–7, por isso o "
                      "preço cheio fica menor nesses meses.")
            b.subheader("Consumo (kWh)")
            fig = px.bar(cem.assign(flag=cem["flag"].fillna("Não informada")), x="ref_month", y="consumption", color="flag", labels={"ref_month": "", "consumption": "kWh",
                         "flag": "Bandeira"}, category_orders={"ref_month": cem["ref_month"].tolist()},
                         color_discrete_map={"Verde": SERIES[2], "Amarela": SERIES[3], "Vermelha": SERIES[7],
                                                                  "Vermelha Patamar 1": SERIES[7],
                                                                  "Vermelha Patamar 2": "#a01c1c"},
                         hover_data={"daily": ":.1f", "days": True})
            b.plotly_chart(style(fig, 300).update_yaxes(tickprefix=""), use_container_width=True)

            st.subheader("Mês a mês")
            t = cem.iloc[::-1]
            st.dataframe(pd.DataFrame({
                "Mês": t["ref_month"], "Total": t["amount"].map(brl), "vs mês ant.": t["amount_var"].map(pct),
                "kWh": t["consumption"].round().astype("Int64"), "kWh vs ant.": t["cons_var"].map(pct),
                "kWh/dia": t["daily"].map(fmt(".1f")), "Puro R$/kWh": t["tariff_untaxed"].map(fmt(".4f")),
                "Cheio R$/kWh": t["price_full"].map(fmt(".2f")), "ICMS": t["icms"].map(brl),
                "PIS+COFINS": (t["pis"].fillna(0) + t["cofins"].fillna(0)).map(brl),
                "Impostos %": t["taxes_pct"].map(fmt(".1f", "%")), "Iluminação": t["public_lighting"].map(brl),
                "Iluminação %": t["lighting_pct"].map(fmt(".1f", "%")), "Bandeira": t["flag"],
                "Multas/créditos": t["other_fees"].map(lambda v: brl(v) if v else ""),
                "Vencimento": t["due_date"]}), use_container_width=True, hide_index=True)

            with st.expander("Detalhe de uma fatura"):
                mes = st.selectbox("Mês", t["ref_month"].tolist(), key="cemig_mes")
                row = cem[cem["ref_month"] == mes].iloc[0]
                det = json.loads(row["details"]) if isinstance(row["details"], str) else {}
                st.markdown(esc(f"**{det.get('tariff_class') or ''} · {det.get('supply') or ''}** · leitura {det.get('read_prev')} → "
                         f"{det.get('read_curr')} ({row['days']} dias) · próxima leitura {det.get('read_next')} · "
                         f"emitida em {row['issue_date']}"))
                st.markdown(esc(f"ICMS {det.get('icms_rate')}% sobre {brl(det.get('icms_base'))} = {brl(row['icms'])} · "
                         f"PIS {det.get('pis_rate')}% = {brl(row['pis'])} · COFINS {det.get('cofins_rate')}% = "
                         f"{brl(row['cofins'])}"))
                if row["flag_value"]:
                    st.markdown(esc(f"Bandeira {row['flag']}: {brl(row['flag_value'])} (já incluída no valor da energia)"))
                for it in det.get("other_items", []):
                    st.markdown(esc(f"{it['item']}: {brl(it['valor'])}"))
                if row["file"]:
                    st.caption(f"Arquivo: {row['file']}")

    with tab_a:
        if not ces.empty:
            last12 = ces.tail(12)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Gasto em 12 meses", brl(last12["amount"].sum()), f"média {brl(last12['amount'].mean())}/mês",
                      delta_color="off")
            c2.metric("Consumo em 12 meses", f"{last12['consumption'].sum():.0f} m³",
                      f"média {last12['consumption'].mean():.1f} m³/mês", delta_color="off")
            c3.metric("Preço cheio do m³", brl(last12["amount"].sum() / last12["consumption"].sum()),
                      "tudo incluído", delta_color="off")
            fundo = last12.dropna(subset=["other_fees"])
            c4.metric("Impostos", "não destacados", f"fundo municipal: {100 * fundo['other_fees'].sum() / fundo['amount'].sum():.1f}% "
                      "da conta" if not fundo.empty else "envie o PDF para ver água, esgoto e fundo", delta_color="off")
            a, b = st.columns(2)
            a.subheader("Valor (R$)")
            a.plotly_chart(style(px.bar(ces, x="ref_month", y="amount", color_discrete_sequence=[SERIES[0]],
                                        labels={"ref_month": "", "amount": "Valor"}), 300), use_container_width=True)
            b.subheader("Consumo (m³)")
            b.plotly_chart(style(px.bar(ces, x="ref_month", y="consumption", color_discrete_sequence=[SERIES[2]],
                                        labels={"ref_month": "", "consumption": "m³"}), 300).update_yaxes(tickprefix=""),
                           use_container_width=True)
            st.caption("Com 3 a 6 m³ por mês, a conta ficou entre R\\$ 33 e R\\$ 51 no período.")
            st.subheader("Mês a mês")
            t = ces.iloc[::-1]
            st.dataframe(pd.DataFrame({
                "Mês": t["ref_month"], "Total": t["amount"].map(brl), "vs mês ant.": t["amount_var"].map(pct),
                "m³": t["consumption"].round().astype("Int64"), "R$/m³": t["price_full"].map(brl),
                "Emissão": t["issue_date"], "Vencimento": t["due_date"], "Pago em": t["paid_date"],
                "Obs.": t["note"].fillna("")}), use_container_width=True, hide_index=True)

    st.subheader("Adicionar conta")
    with st.expander("Enviar PDF da fatura"):
        from financas.importers import bills_folder
        st.caption("O fornecedor é reconhecido pela própria fatura. Também dá para só salvar o PDF na pasta "
                   f"`{config.BILLS_DIR / 'entrada'}`: ele é lançado na próxima sincronização.")
        files = st.file_uploader("PDF da fatura", type="pdf", accept_multiple_files=True)
        if files and st.button("Importar PDFs"):
            entrada = bills_folder.ensure(config.BILLS_DIR) / "entrada"
            for f in files:
                (entrada / Path(f.name).name).write_bytes(f.getbuffer())
            with session() as conn:
                res = bills_folder.import_folder(conn, config.BILLS_DIR, min_age=0)
            for r in res:
                (st.success if r["ok"] else st.warning)(esc(f"{r['file']}: {r['message']}"))
        revisar = sorted((config.BILLS_DIR / "revisar").glob("*.pdf")) if (config.BILLS_DIR / "revisar").exists() else []
        if revisar:
            st.warning(f"{len(revisar)} PDF(s) aguardando revisão em `{config.BILLS_DIR / 'revisar'}`")
            for p in revisar:
                why = p.with_suffix(".txt")
                st.caption(esc(why.read_text().splitlines()[0] if why.exists() else p.name))

    from financas.importers import utilities
    with st.expander("Lançar ou completar uma conta à mão", expanded="bill_msg" in st.session_state):
        for kind, msg in st.session_state.pop("bill_msg", []):
            getattr(st, kind)(esc(msg))
        p = st.radio("Fornecedor", ["cemig", "cesama"], horizontal=True,
                     format_func={"cemig": "⚡ Cemig", "cesama": "💧 Cesama"}.get)
        with session() as conn:
            last = utilities.load(conn, p, before="9999-99")
            next_ref = (pd.Period(last["ref_month"], "M") + 1).strftime("%Y-%m") if last else date.today().strftime("%Y-%m")
            ref = st.text_input("Mês de referência (AAAA-MM)", next_ref).strip()
            ok_ref = bool(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", ref))
            cur = (utilities.load(conn, p, ref) if ok_ref else None) or {}
            prev = (utilities.load(conn, p, before=ref) if ok_ref else None) or {}
        if not ok_ref:
            st.error("Mês de referência no formato AAAA-MM (ex.: 2026-10).")
            st.stop()
        st.caption(("Este mês já está lançado: os campos mostram o que está gravado. " if cur else "Mês novo. ")
                   + "Campo vazio não apaga nada. Consumo, dias, tarifa e impostos totais são calculados.")
        iso = lambda v: date.fromisoformat(v) if isinstance(v, str) and v else None  # noqa: E731
        num = lambda k, d=cur: None if d.get(k) is None or pd.isna(d.get(k)) else d[k]  # noqa: E731
        integer = lambda v: None if v is None else int(v)  # noqa: E731
        money = dict(step=0.01, format="%.2f", min_value=0.0)
        with st.form(f"bill_{p}_{ref}"):
            c = st.columns(3)
            bill = {"provider": p, "ref_month": ref,
                    "issue_date": c[0].date_input("Emissão", value=iso(cur.get("issue_date")), format="DD/MM/YYYY"),
                    "due_date": c[1].date_input("Vencimento", value=iso(cur.get("due_date")), format="DD/MM/YYYY"),
                    "paid_date": c[2].date_input("Pago em", value=iso(cur.get("paid_date")), format="DD/MM/YYYY")}
            if p == "cemig":
                c = st.columns(5)
                bill["amount"] = c[0].number_input("Valor total (R$)", value=num("amount"), **money)
                bill["meter_prev"] = c[1].number_input("Leitura anterior", min_value=0, step=1,
                                                       value=integer(num("meter_prev") if cur else num("meter_curr", prev)))
                bill["read_prev_date"] = c[2].date_input("Data da leitura anterior", format="DD/MM/YYYY",
                                                         value=_read_date(cur, "read_prev") if cur else _read_date(prev))
                bill["meter_curr"] = c[3].number_input("Leitura atual", min_value=0, step=1, value=integer(num("meter_curr")))
                bill["read_curr_date"] = c[4].date_input("Data da leitura atual", value=_read_date(cur), format="DD/MM/YYYY")
                c = st.columns(5)
                bill["energy_untaxed"] = c[0].number_input("Energia sem impostos (R$)", value=num("energy_untaxed"), **money)
                bill["icms"] = c[1].number_input("ICMS (R$)", value=num("icms"), **money)
                bill["pis"] = c[2].number_input("PIS (R$)", value=num("pis"), **money)
                bill["cofins"] = c[3].number_input("COFINS (R$)", value=num("cofins"), **money)
                bill["public_lighting"] = c[4].number_input("Iluminação pública (R$)", value=num("public_lighting"), **money)
                c = st.columns([1, 1, 3])
                flags = ["", "Verde", "Amarela", "Vermelha Patamar 1", "Vermelha Patamar 2"]
                bill["flag"] = c[0].selectbox("Bandeira", flags, index=flags.index(cur["flag"]) if cur.get("flag") in flags else 0,
                                              format_func=lambda f: f or "—")
                bill["flag_value"] = c[1].number_input("Valor da bandeira (R$)", value=num("flag_value"), **money)
                items = c[2].data_editor(pd.DataFrame(cur.get("other_items") or [], columns=["item", "valor"]).astype(
                                             {"item": "str", "valor": "float"}),
                                         num_rows="dynamic", use_container_width=True, key=f"bill_items_{ref}",
                                         column_config={"item": "Outros itens (multa, juros, Bônus Itaipu…)",
                                                        "valor": st.column_config.NumberColumn("R$ (crédito negativo)",
                                                                                               format="%.2f")})
                items = items.dropna(subset=["valor"])
                bill["other_items"] = [{"item": i if isinstance(i, str) else "", "valor": float(v)}
                                       for i, v in zip(items["item"], items["valor"])]
            else:
                c = st.columns(3)
                bill["amount"] = c[0].number_input("Valor total (R$)", value=num("amount"), **money)
                bill["meter"] = c[1].number_input("Leitura do hidrômetro (m³)", min_value=0, step=1,
                                                  value=integer(num("meter")))
                bill["read_date"] = c[2].date_input("Data da leitura", value=iso(cur.get("read_date")), format="DD/MM/YYYY")
                c = st.columns(3)
                bill["taxes_total"] = c[0].number_input("Impostos (R$, se tiver o PDF)", value=num("taxes_total"), **money)
            bill["note"] = st.text_input("Observação", cur.get("note") or "")
            if st.form_submit_button("Salvar conta"):
                if not cur and not bill["amount"]:
                    st.error("Conta nova: informe pelo menos o valor total.")
                    st.stop()
                with session() as conn:
                    b = utilities.manual(conn, bill)
                unit = "kWh" if p == "cemig" else "m³"
                msgs = [("success", f"{p.title()} {ref} {'atualizada' if cur else 'lançada'}: {brl(b.get('amount'))}"
                         + (f" · {b['consumption']:.0f} {unit}" if b.get("consumption") is not None else ""))]
                gap = utilities.total_gap(b)
                if gap:
                    msgs.append(("warning", f"As partes somam {brl(b['amount'] - gap)}, mas o total é "
                                            f"{brl(b['amount'])} (diferença {brl(gap)}). Confira os valores."))
                st.session_state["bill_msg"] = msgs
                st.rerun()

# ------------------------------------------------------------------ Empréstimos
elif page == "Empréstimos":
    from dataclasses import replace as dc_replace

    from financas import loans as lo

    def rate_txt(rate, period, comp) -> str:
        if not rate:
            return "sem juros"
        return f"{rate * 100:.2f}% a.{'m.' if period == 'mes' else 'a.'} · {comp}".replace(".", ",", 1)

    def rate_equiv(rate, period, comp) -> str:
        m, a = lo.monthly_rate(rate, period, comp), lo.annual_rate(rate, period, comp)
        return f"{m * 100:.3f}% ao mês  ≈  {a * 100:.2f}% ao ano ({comp})".replace(".", ",")

    def rate_inputs(key: str, default_comp: str, allow_none: bool = True):
        """Campos de taxa. Devolve (taxa em fração, 'mes'|'ano', 'simples'|'composto')."""
        if allow_none:
            with_int = st.radio("Esse empréstimo cobra juros?", ["Não, sem juros", "Sim, com juros"], horizontal=True,
                                key=f"{key}_wi") == "Sim, com juros"
        else:
            with_int = True
        if not with_int:
            return 0.0, "mes", default_comp
        c1, c2, c3 = st.columns(3)
        pct = c1.number_input("Taxa (%)", min_value=0.0, step=0.1, value=1.0, format="%.3f", key=f"{key}_pct")
        per = c2.radio("Período da taxa", ["ao mês", "ao ano"], horizontal=True, key=f"{key}_per")
        comp = c3.radio("Cálculo dos juros", ["simples", "composto"], index=["simples", "composto"].index(default_comp),
                        horizontal=True, key=f"{key}_comp",
                        help="Simples: rende só sobre o valor emprestado. Composto: juros sobre juros.")
        return pct / 100, ("mes" if per == "ao mês" else "ano"), comp

    def hp12c_help() -> None:
        with st.popover("ℹ️ Como conferir na HP 12C", use_container_width=True):
            st.markdown("""
**Antes de tudo:** `f` `CLX` (limpa registros) · `f` `FIN` (limpa financeiros) · aperte `STO` `EEX` até aparecer **C** no visor
(sem o **C**, a HP 12C usa juros simples na parte fracionária de `n` e o resultado não bate com o painel).

**Períodos (n)** — é o que o painel usa: *meses de calendário completos* + *dias que sobram ÷ 30,4375*.
Ex.: 17/10/2026 → 17/10/2027 = **12 meses exatos** → `n` = 12. De 17/10/2026 a 02/01/2027 = 2 meses + 16 dias → `16` `ENTER` `30.4375` `÷` `2` `+` → `n` = 2,5257.
Taxa **ao ano**: `n` = meses ÷ 12 (ex.: 12 meses → `n` = 1).
(Dias que sobram: `g` `D.MY`, data1 `ENTER` data2 `g` `ΔDYS`.)

---
**Juros compostos (saldo numa data)**
1. `n` = períodos (acima) · `i` = taxa em % (ex.: `2` `i`)
2. `PV` = valor emprestado com `CHS` (ex.: `1000` `CHS` `PV`)
3. `FV` → **saldo** (principal + juros) na data.

**Juros simples (saldo numa data)**
`1000` `ENTER` `2` `%` (juros de 1 período; o 1000 fica guardado) → digite `n` `×` `+` → **saldo**.
*(Não use `f` `INT`: ela usa ano de 360/365 dias, outra convenção.)*

**Descobrir a taxa na quitação**
- Compostos: `PV` = −emprestado, `FV` = valor pago, `n` = períodos → `i` = taxa por período.
- Simples: `valor pago` `ENTER` `emprestado` `÷` `1` `−` `n` `÷` `100` `×` → taxa por período em %.

**Parcelas iguais (Price, juros compostos)**
`n` = nº de parcelas · `i` = taxa ao mês · `PV` = −valor emprestado · `PMT` → parcela.

**Com recebimentos no meio:** o painel calcula o saldo até a data do recebimento, abate o valor
(**primeiro juros, depois principal**) e recomeça dali. Na HP: calcule o saldo, subtraia o recebimento
e use o resultado como novo `PV` até a próxima data. A tabela *Memória de cálculo* mostra cada passo.
""")

    st.title("Empréstimos")
    tab_rec, tab_debt = st.tabs(["💸 Que eu emprestei (a receber)", "🏦 Que eu devo (banco)"])

    # ================================================== A RECEBER
    with tab_rec:
        a_, b_ = st.columns([3, 2], vertical_alignment="bottom")
        asof = a_.date_input("📅 Posição em (simulação: escolha uma data futura para ver quanto estará devendo)",
                             value=date.today(), key="asof",
                             help="Só muda o cálculo na tela (juros acumulados até essa data). Nada é gravado.")
        with b_:
            hp12c_help()
        if asof != date.today():
            st.warning(f"Simulação: valores calculados para **{asof:%d/%m/%Y}**, não para hoje.")
        with session() as conn:
            loans = analytics.loan_status(conn, asof)
            sched = analytics.loan_schedule_open(conn, asof)
            pays = pd.read_sql("SELECT p.*, l.person FROM loan_payments p JOIN loans l ON l.id=p.loan_id "
                               "ORDER BY p.date DESC", conn)
            people = [r["name"] for r in conn.execute("SELECT name FROM people ORDER BY name COLLATE NOCASE")]
        if not loans.empty:
            open_ = loans[loans["closed"] == 0]
            c1, c2, c3 = st.columns(3)
            c1.metric("Total a receber (com juros até hoje)", brl(open_["remaining"].sum()))
            c2.metric("Em atraso", brl(open_["overdue"].sum()))
            c3.metric("Pessoas com saldo", open_["person"].nunique())
            show = loans.assign(taxa=[rate_txt(r.rate, r.rate_period, r.compounding) for r in loans.itertuples()],
                                tipo=["parcelado" if s else "sem data combinada" for s in loans["scheduled"]],
                                installments=[f"{int(v)}x" if pd.notna(v) else "—" for v in loans["installments"]])
            st.dataframe(show[["person", "date", "principal", "installments", "taxa", "tipo", "paid", "interest", "remaining", "overdue",
                               "next_due", "note", "closed"]]
                         .rename(columns={"person": "pessoa", "date": "data", "principal": "emprestado",
                                          "installments": "parcelas", "paid": "recebido", "interest": "juros", "remaining": "falta",
                                          "overdue": "atrasado", "next_due": "próx. venc.", "note": "obs",
                                          "closed": "quitado"})
                         .style.format({"emprestado": brl, "recebido": brl, "juros": brl, "falta": brl,
                                        "atrasado": brl}), use_container_width=True, hide_index=True)
            with session() as conn:
                tl_person, tl_total = analytics.loan_timeline(conn, asof)
            if not tl_person.empty:
                st.subheader("Evolução do que tenho a receber (empréstimos parcelados)")
                folded, cmap = fold_categories(tl_person, "person", "saldo")
                fig = px.bar(folded.groupby(["month", "person"], as_index=False)["saldo"].sum(), x="month", y="saldo",
                             color="person", color_discrete_map=cmap, labels={"month": "", "saldo": "A receber", "person": ""})
                fig.add_scatter(x=tl_total["month"], y=tl_total["emprestado"], mode="lines+markers", name="Total emprestado (acum.)",
                                line=dict(color=SERIES[6], width=2), marker=dict(size=7))
                fig.update_layout(barmode="stack")
                st.plotly_chart(style(fig, 360), use_container_width=True)
                st.caption("Barras = quanto cada pessoa ainda deve naquele mês (com juros). Linha = total já emprestado. "
                           "Barra acima da linha = juros a receber; barra abaixo = parte já paga. "
                           "Empréstimos sem data de retorno não entram neste gráfico. O último mês usa a data escolhida em *Posição em*.")
            if not sched.empty:
                st.subheader("Quando vou receber")
                st.dataframe(sched[["person", "due_date", "amount", "remaining"]]
                             .rename(columns={"person": "pessoa", "due_date": "vencimento", "amount": "parcela",
                                              "remaining": "em aberto"})
                             .style.format({"parcela": brl, "em aberto": brl}), use_container_width=True, hide_index=True)
            if not pays.empty:
                st.subheader("Recebimentos")
                pays["como"] = pays.apply(lambda r: "direto no empréstimo" if r["directed"] else
                                          f"baixa {'dos mais recentes' if r['order_mode'] == 'recentes' else 'dos mais antigos'} primeiro", axis=1)
                st.dataframe(pays[["person", "date", "amount", "como", "note"]]
                             .rename(columns={"person": "pessoa", "date": "data", "amount": "valor", "note": "obs"})
                             .style.format({"valor": brl}), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum empréstimo registrado.")

        # ---------------- memória de cálculo
        free_all = loans[~loans["scheduled"]] if not loans.empty else loans
        if not free_all.empty:
            with st.expander("🧮 Memória de cálculo (para conferir na HP 12c)"):
                lab = {f"{r.person} · {r.date} · {brl(r.principal)} · {rate_txt(r.rate, r.rate_period, r.compounding)}": r.id
                       for r in free_all.itertuples()}
                pick_l = lab[st.selectbox("Empréstimo", list(lab), key="memo_loan")]
                with session() as conn:
                    memo = analytics.loan_statement(conn, pick_l, asof)
                st.caption("Juros simples: juros = principal em aberto × taxa × períodos. Composto: juros = saldo × ((1+taxa)^períodos − 1). "
                           "Períodos = meses de calendário completos + dias que sobram ÷ 30,4375 (taxa ao ano: meses ÷ 12). Recebimento paga juros primeiro, depois principal.")
                st.dataframe(memo.style.format({"períodos": "{:.6f}", "juros": brl, "pago": brl, "saldo": brl}),
                             use_container_width=True, hide_index=True)

        # ---------------- novo empréstimo
        st.subheader("Novo empréstimo a uma pessoa")
        out_pix = df[(df.get("amount", pd.Series(dtype=float)) < 0)].sort_values("date", ascending=False).head(40) \
            if not df.empty else pd.DataFrame()

        @st.dialog("Cadastrar nova pessoa")
        def new_person_dialog():
            name = st.text_input("Nome da pessoa")
            pix = st.text_input("Nome como aparece no Pix dela (opcional)",
                                help="Só preencha se ela costuma pagar só por Pix e nunca manda Pix por outros motivos. "
                                     "Em branco = nenhum Pix é casado sozinho; você lança os recebimentos à mão.")
            if st.button("Salvar pessoa", type="primary"):
                name = name.strip()
                if not name:
                    st.error("Informe o nome.")
                    return
                with session() as conn:
                    conn.execute("INSERT OR IGNORE INTO people(name) VALUES (?)", (name,))
                    if pix.strip():
                        conn.execute("UPDATE people SET match_name=? WHERE name=?", (pix.strip(), name))
                st.session_state["ln_pending_person"] = name  # aplicado antes de o seletor ser criado
                st.rerun()

        if "ln_pending_person" in st.session_state:
            st.session_state["ln_person"] = st.session_state.pop("ln_pending_person")
        a, b = st.columns([3, 1], vertical_alignment="bottom")
        person = a.selectbox("Pessoa", people, index=None, placeholder="Escolha uma pessoa já cadastrada", key="ln_person") or ""
        if b.button("➕ Nova pessoa", key="ln_newbtn"):
            new_person_dialog()
        a, b = st.columns(2)
        d = a.date_input("Data do empréstimo", key="ln_date")
        principal = b.number_input("Valor emprestado (R$)", min_value=0.0, step=50.0, key="ln_principal")
        rate, period, comp = rate_inputs("ln", "simples")
        no_sched = st.checkbox("Não combinei data de retorno nem dia da 1ª parcela", key="ln_nosched")
        sched_new: list = []
        if not no_sched:
            a, b = st.columns(2)
            n = a.number_input("Nº de parcelas", min_value=1, step=1, value=1, key="ln_n")
            first = b.date_input("1º vencimento", value=(pd.Timestamp(d) + pd.DateOffset(months=1)).date(),
                                 key=f"ln_first_{d.isoformat()}", help="Padrão: 1 mês depois do empréstimo. "
                                 "Se for no mesmo dia, a 1ª parcela é uma entrada (sem juros).")
            sched_new = lo.make_schedule(principal, rate, period, comp, int(n), first, start=d) if principal > 0 else []
            if sched_new:
                total = sum(x for _, x in sched_new)
                st.info(f"Você vai receber **{brl(total)}** no total em {int(n)}x de **{brl(sched_new[0][1])}**, "
                        f"de {sched_new[0][0]:%d/%m/%Y} a {sched_new[-1][0]:%d/%m/%Y}"
                        + (f" (juros de {brl(total - principal)}). Taxa: {rate_equiv(rate, period, comp)}." if rate else
                           " (sem juros)."))
        elif rate:
            st.info("Sem data combinada: o saldo cresce com os juros ({}) até o dia em que ela pagar. "
                    "Quando pagar, use **Quitar** abaixo.".format(rate_equiv(rate, period, comp)))
        else:
            st.caption("Sem data e sem juros combinados. Quando ela pagar, use **Quitar** para o programa descobrir a taxa.")
        note = st.text_input("Observação (ex.: 'conserto do carro')", key="ln_note")
        tx_opts = {"—": None} | {f"{r.date:%d/%m} · {r.description} · {r.counterparty or ''} · {brl(-r.amount)}": r.id
                                 for r in out_pix.itertuples()} if not out_pix.empty else {"—": None}
        tx_sel = st.selectbox("Pix de saída correspondente (opcional — tira do cálculo de gastos)", list(tx_opts),
                              key="ln_tx")
        if st.button("Registrar empréstimo", type="primary", key="ln_save"):
            if not person or principal <= 0:
                st.error("Escolha a pessoa (ou cadastre uma nova) e informe o valor emprestado.")
            else:
                with session() as conn:
                    conn.execute("INSERT OR IGNORE INTO people(name) VALUES (?)", (person,))
                    cur = conn.execute(
                        "INSERT INTO loans(person, match_name, date, principal, note, transaction_id, rate, rate_period, "
                        "compounding) VALUES (?,?,?,?,?,?,?,?,?)",
                        (person, None, d.isoformat(), principal, note, tx_opts[tx_sel], rate, period, comp))
                    for due, amt in sched_new:
                        conn.execute("INSERT INTO loan_schedule(loan_id, due_date, amount) VALUES (?,?,?)",
                                     (cur.lastrowid, due.isoformat(), amt))
                    if tx_opts[tx_sel]:
                        conn.execute("UPDATE transactions SET category='Empréstimo concedido', "
                                     "manual_category='Empréstimo concedido' WHERE id=?", (tx_opts[tx_sel],))
                    analytics.match_loan_payments(conn)
                for k in [k for k in st.session_state if k.startswith("ln_")]:
                    del st.session_state[k]
                st.rerun()

        open_loans = loans[loans["closed"] == 0] if not loans.empty else loans

        # ---------------- recebimento
        if not open_loans.empty:
            st.subheader("Lançar recebimento")
            st.caption("O valor abate os empréstimos da pessoa na ordem escolhida; se sobrar, passa para o próximo.")
            who_names = sorted(open_loans["person"].unique(), key=str.lower)
            a, b, c = st.columns(3)
            who = a.selectbox("Quem pagou", who_names, key="rc_who")
            rdate = b.date_input("Data do recebimento", key="rc_date")
            ramt = c.number_input("Valor recebido (R$)", min_value=0.0, step=50.0, key="rc_amt")
            mine = open_loans[open_loans["person"] == who]
            mode = st.radio("Abater", ["Mais antigos primeiro", "Mais recentes primeiro", "Um empréstimo específico"],
                            horizontal=True, key="rc_mode")
            target = None
            if mode == "Um empréstimo específico":
                lab = {f"{r.date} · {brl(r.principal)} · falta {brl(r.remaining)}": r.id for r in mine.itertuples()}
                target = lab[st.selectbox("Qual empréstimo", list(lab), key="rc_target")]
            if ramt > 0:
                with session() as conn:
                    ls, rs = analytics.load_loans(conn)
                ref = int(mine["id"].iloc[0])
                hyp = lo.Receipt(10**9, target or ref, rdate, ramt, directed=target is not None,
                                 order="recentes" if mode.startswith("Mais recentes") else "antigas")
                after = lo.replay(ls, rs + [hyp], max(asof, rdate))
                before = lo.replay(ls, rs, max(asof, rdate))
                prev = pd.DataFrame([{"empréstimo": f"{l.date} · {brl(l.principal)}", "falta hoje": before[l.id].balance(),
                                      "depois do recebimento": after[l.id].balance()}
                                     for l in ls if l.person == who and before[l.id].balance() > lo.EPS])
                st.markdown("**Como vai ficar:**")
                st.dataframe(prev.style.format({"falta hoje": brl, "depois do recebimento": brl}),
                             use_container_width=True, hide_index=True)
                sobra = ramt - sum(after[l.id].paid - before[l.id].paid for l in ls if l.person == who)
                if sobra > 0.01:
                    st.warning(f"Sobram {brl(sobra)} acima do que ela devia — confira o valor.")
            if st.button("Registrar recebimento", type="primary", key="rc_save", disabled=ramt <= 0):
                with session() as conn:
                    conn.execute(
                        "INSERT INTO loan_payments(loan_id, date, amount, note, directed, order_mode) VALUES (?,?,?,?,?,?)",
                        (target or int(mine["id"].iloc[0]), rdate.isoformat(), ramt, "manual", int(target is not None),
                         "recentes" if mode.startswith("Mais recentes") else "antigas"))
                for k in [k for k in st.session_state if k.startswith("rc_")]:
                    del st.session_state[k]
                st.rerun()

            # ---------------- quitar / descobrir a taxa
            free = open_loans[~open_loans["scheduled"]]
            if not free.empty:
                st.subheader("Quitar empréstimo sem data combinada (descobrir a taxa)")
                st.caption("Informe quanto ela pagou no total para encerrar. O programa calcula a taxa de juros "
                           "embutida e guarda no empréstimo.")
                lab = {f"{r.person} · {r.date} · {brl(r.principal)} · falta {brl(r.remaining)}": r.id
                       for r in free.itertuples()}
                qid = lab[st.selectbox("Empréstimo", list(lab), key="q_loan")]
                a, b = st.columns(2)
                qdate = a.date_input("Data da quitação", key="q_date")
                qamt = b.number_input("Valor pago para quitar (R$)", min_value=0.0, step=50.0, key="q_amt")
                c1, c2 = st.columns(2)
                qper = "mes" if c1.radio("Mostrar taxa", ["ao mês", "ao ano"], horizontal=True, key="q_per") == "ao mês" else "ano"
                qcomp = c2.radio("Cálculo dos juros", ["simples", "composto"], horizontal=True, key="q_comp")
                if qamt > 0:
                    with session() as conn:
                        ls, rs = analytics.load_loans(conn)
                    ls = [dc_replace(l, period=qper, compounding=qcomp) if l.id == qid else l for l in ls]
                    try:
                        found = lo.solve_rate(ls, rs, qid, qdate, qamt)
                    except ValueError as e:
                        found = None
                        st.error(str(e))
                    if found is None:
                        st.warning("O valor pago é menor ou igual ao que ela devia sem juros — não há taxa a calcular.")
                    else:
                        st.success(f"Taxa efetiva: **{rate_equiv(found, qper, qcomp)}**")
                        if st.button("Confirmar quitação", type="primary", key="q_save"):
                            with session() as conn:
                                conn.execute("UPDATE loans SET rate=?, rate_period=?, compounding=? WHERE id=?",
                                             (found, qper, qcomp, qid))
                                conn.execute("INSERT INTO loan_payments(loan_id, date, amount, note, directed) "
                                             "VALUES (?,?,?,?,1)", (qid, qdate.isoformat(), qamt, "quitação"))
                            for k in [k for k in st.session_state if k.startswith("q_")]:
                                del st.session_state[k]
                            st.rerun()

    # ================================================== QUE EU DEVO
    with tab_debt:
        with session() as conn:
            bl, bopen = analytics.bank_loan_status(conn)
        if not bl.empty:
            c1, c2 = st.columns(2)
            c1.metric("Falta pagar (todos)", brl(bl["remaining"].sum()))
            c2.metric("Parcelas em aberto", int(bl["installments_left"].sum()))
            show = bl.assign(taxa=[rate_txt(r.rate, r.rate_period, r.compounding) for r in bl.itertuples()])
            st.dataframe(show[["bank", "date", "principal", "taxa", "installments", "installments_left", "total", "paid",
                               "remaining", "note"]]
                         .rename(columns={"bank": "banco", "date": "data", "principal": "valor tomado",
                                          "installments": "parcelas", "installments_left": "faltam", "total": "total do contrato",
                                          "paid": "pago", "remaining": "falta pagar", "note": "obs"})
                         .style.format({"valor tomado": brl, "total do contrato": brl, "pago": brl, "falta pagar": brl}),
                         use_container_width=True, hide_index=True)
            if not bopen.empty:
                st.subheader("Parcelas em aberto")
                st.dataframe(bopen[["bank", "due_date", "amount", "remaining"]]
                             .rename(columns={"bank": "banco", "due_date": "vencimento", "amount": "parcela",
                                              "remaining": "em aberto"})
                             .style.format({"parcela": brl, "em aberto": brl}), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum empréstimo de banco registrado.")

        st.subheader("Novo empréstimo no banco")
        a, b = st.columns(2)
        bank = a.text_input("Banco / financeira", key="bk_bank")
        bdate = b.date_input("Data da contratação", key="bk_date")
        a, b = st.columns(2)
        bprin = a.number_input("Valor recebido do banco (R$)", min_value=0.0, step=100.0, key="bk_prin")
        bn = b.number_input("Nº de parcelas", min_value=1, step=1, value=12, key="bk_n")
        brate, bper, bcomp = rate_inputs("bk", "composto")
        a, b = st.columns(2)
        bfirst = a.date_input("1º vencimento", value=(pd.Timestamp(bdate) + pd.DateOffset(months=1)).date(),
                              key=f"bk_first_{bdate.isoformat()}")
        binst = b.number_input("Valor da parcela do contrato (opcional)", min_value=0.0, step=10.0, key="bk_inst",
                               help="Se o contrato diz o valor da parcela, informe. Em branco = calculado pela taxa.")
        bnote = st.text_input("Observação", key="bk_note")
        prev = lo.make_schedule(bprin, brate, bper, bcomp, int(bn), bfirst, binst or None, start=bdate) if bprin > 0 else []
        if prev:
            tot = sum(x for _, x in prev)
            st.info(f"{int(bn)}x de **{brl(prev[0][1])}** — total a pagar **{brl(tot)}** (juros/custos {brl(tot - bprin)}).")
        if st.button("Registrar empréstimo do banco", type="primary", key="bk_save"):
            if not bank.strip() or bprin <= 0:
                st.error("Informe o banco e o valor.")
            else:
                with session() as conn:
                    conn.execute("INSERT INTO bank_loans(bank, date, principal, rate, rate_period, compounding, installments, "
                                 "first_due, installment_amount, note) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                 (bank.strip(), bdate.isoformat(), bprin, brate, bper, bcomp, int(bn), bfirst.isoformat(),
                                  binst or None, bnote))
                for k in [k for k in st.session_state if k.startswith("bk_")]:
                    del st.session_state[k]
                st.rerun()

        if not bl.empty and (bl["remaining"] > 0.005).any():
            st.subheader("Registrar pagamento de parcela")
            act = bl[bl["remaining"] > 0.005]
            lab = {f"{r.bank} · {r.date} · falta {brl(r.remaining)}": r.id for r in act.itertuples()}
            a, b, c = st.columns(3)
            pid = lab[a.selectbox("Empréstimo", list(lab), key="bp_loan")]
            pdt = b.date_input("Data do pagamento", key="bp_date")
            pam = c.number_input("Valor pago (R$)", min_value=0.0, step=10.0, key="bp_amt")
            if st.button("Registrar pagamento", type="primary", key="bp_save", disabled=pam <= 0):
                with session() as conn:
                    conn.execute("INSERT INTO bank_loan_payments(bank_loan_id, date, amount) VALUES (?,?,?)",
                                 (pid, pdt.isoformat(), pam))
                for k in [k for k in st.session_state if k.startswith("bp_")]:
                    del st.session_state[k]
                st.rerun()

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
             f"**Contas** (PDF) em `{config.BILLS_DIR / 'entrada'}` · **OFX** em `data/inbox/ofx` (plano B). "
             "A sincronização sempre usa os **dados atuais** e faz o backup automático quando vence.")
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

# ------------------------------------------------------------------ Configurações
elif page == "Configurações":
    st.title("Configurações")
    with db_session() as conn:  # preferências sempre dos dados atuais, mesmo vendo um backup
        theme = settings.get(conn, "theme")
        hours = backup.interval_h(conn)
        due = backup.next_due(conn)

    st.subheader("Aparência")
    new_theme = st.radio("Tema", list(settings.THEMES), index=list(settings.THEMES).index(theme),
                         format_func=settings.THEMES.get, horizontal=True)
    st.caption("Vale para todos que usam este painel. \"Seguir o sistema\" usa o tema do computador ou celular.")
    if new_theme != theme:
        with db_session() as conn:
            settings.set_(conn, "theme", new_theme)
        res = apply_theme(new_theme)
        if res is None:
            st.warning(f"O arquivo `{THEME_FILE}` tem configuração própria; o tema não foi alterado.")
        else:
            st.info("Aplicando o tema…")
            reload_page()
            st.stop()

    st.subheader("Conexões")
    from financas import connections
    st.caption(f"As chaves ficam no arquivo `{config.ENV_FILE.name}` desta instalação (nunca no banco nem no backup) e "
               "não são mostradas de novo depois de salvas. Só é salvo o que passar no teste, que faz apenas consultas "
               "de leitura. Atenção: quem abre este painel pode trocar as chaves — num servidor compartilhado, o "
               "painel vai precisar de senha.")
    for src in connections.SOURCES:
        cur = connections.current(src)
        with st.expander(f"{'✅' if connections.is_configured(src) else '⚪'} {src.name}"):
            st.markdown(src.how_to)
            with st.form(f"conn_{src.id}"):
                typed = {}
                for f in src.fields:
                    if f.secret:
                        typed[f.key] = st.text_input(f.label, type="password", help=f.help, placeholder=(
                            "•••••• salvo — deixe vazio para manter" if cur[f.key] else "cole aqui"))
                    else:
                        typed[f.key] = st.text_input(f.label, value=cur[f.key], help=f.help)
                c1, c2 = st.columns(2)
                do_test = c1.form_submit_button("🔌 Testar conexão")
                do_save = c2.form_submit_button("💾 Testar e salvar", type="primary")
            if do_test or do_save:
                vals = connections.merged(src, typed)
                missing = [f.label for f in src.fields if f.key in src.required and not vals[f.key]]
                if missing:
                    st.error("Falta preencher: " + ", ".join(missing))
                else:
                    try:
                        with st.spinner("Consultando…"):
                            msg = src.test(vals)
                    except Exception as e:  # noqa: BLE001 — mostrar o motivo em vez de quebrar a página
                        st.error(f"Não funcionou: {e}")
                        if do_save:
                            st.warning("Nada foi salvo.")
                    else:
                        st.success(msg.replace("$", "\\$"))
                        if do_save:
                            changed = connections.save(src, typed)
                            labels = {f.key: f.label for f in src.fields}
                            st.success("Salvo: " + ", ".join(labels[k] for k in changed) if changed
                                       else "Nada mudou — as chaves salvas continuam valendo.")

    st.subheader("Backup")
    choices = settings.BACKUP_CHOICES
    new_hours = st.selectbox("Backup automático", list(choices), format_func=choices.get,
                             index=list(choices).index(hours) if hours in choices else list(choices).index(24))
    if new_hours != hours:
        with db_session() as conn:
            settings.set_(conn, "backup_interval_h", new_hours)
        st.rerun()
    if due is None:
        st.caption("Backup automático desligado — use o botão abaixo quando quiser.")
    else:
        when = "na próxima vez que o painel abrir ou a sincronização rodar" if due <= datetime.now() else f"a partir de {due:%d/%m/%Y %H:%M}"
        st.caption(f"O próximo backup automático é feito {when}. Ele acontece quando o painel abre ou a sincronização "
                   f"roda (no servidor, a cada 6 h). Ficam os {backup.KEEP_AUTO} automáticos mais recentes; os manuais "
                   "nunca são apagados sozinhos.")
    if st.button("💾 Fazer backup agora", type="primary"):
        made = backup.make("manual")
        st.success(f"Backup criado: {made.name}")

    items = backup.list_backups()
    if not items:
        st.info("Nenhum backup ainda.")
    else:
        st.dataframe(pd.DataFrame({"Data": [f"{b['created']:%d/%m/%Y %H:%M}" for b in items],
                                   "Tipo": ["Manual" if b["kind"] == "manual" else "Automático" for b in items],
                                   "Tamanho": [f"{b['size'] / 1e6:.1f} MB" if b["size"] >= 1e6 else f"{b['size'] / 1e3:.0f} KB"
                                               for b in items]}),
                     use_container_width=True, hide_index=True, height=min(35 * (len(items) + 1) + 3, 300))
        sel = st.selectbox("Escolha um backup", items, format_func=backup_label)
        c1, c2 = st.columns(2)
        c1.download_button("⬇️ Baixar (.zip)", data=sel["path"].read_bytes(), file_name=sel["path"].name,
                           mime="application/zip", help="Guarde onde quiser: pendrive, nuvem, e-mail.")
        c2.button("👁️ Ver estes dados no painel", on_click=lambda: st.session_state.update(view=f"Backup de {backup_label(sel)}"),
                  help="O painel inteiro passa a mostrar os números daquele dia, somente leitura.")
        st.caption(f"Pasta dos backups: `{backup.backup_dir()}`")
