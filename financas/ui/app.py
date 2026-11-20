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
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from financas import __version__, analytics, backup, config, settings  # noqa: E402
from financas.categorize import (add_product_link, add_rule, all_categories, all_tags, delete_product_link,  # noqa: E402
                                 delete_rule, recategorize, set_manual, set_tag, store_pattern)
from financas.db import session as db_session  # noqa: E402

from financas.ui import theme as visual  # noqa: E402

SERIES = visual.series()  # paleta categórica em ordem fixa (por tema) — nunca ciclada
OTHER = visual.palette()["other"]
C_IN, C_OUT = visual.palette()["in"], visual.palette()["out"]  # entrada / saída: mesma cor em todas as telas
TOP_N = 7

ENV_NAME = os.getenv("FIN_ENV_NAME", "")
st.set_page_config(page_title="[DEV] Painel Financeiro" if ENV_NAME == "dev" else "Painel Financeiro",
                   page_icon=":material/account_balance_wallet:", layout="wide")
visual.inject_css()
if ENV_NAME in ("dev", "prod", "demo"):  # faixa fixa no topo: impossível confundir os ambientes
    bg, label = {"dev": ("#B54708", "Desenvolvimento · dados de teste (clone de prod). Nada aqui afeta produção."),
                 "demo": ("#1F65BD", "Demonstração · todos os dados são fictícios"),
                 "prod": ("#1E6B34", "Produção · dados reais")}[ENV_NAME]
    st.markdown(f"""<style>
      .env-banner {{position:fixed;top:0;left:0;right:0;z-index:999999;background:{bg};color:#fff;text-align:center;
                   font-weight:600;padding:{'1px' if ENV_NAME == 'prod' else '4px'} 12px;
                   font-size:{'11px' if ENV_NAME == 'prod' else '12.5px'};letter-spacing:.2px}}
      .stApp {{padding-top:{'16px' if ENV_NAME == 'prod' else '26px'}}}
    </style><div class="env-banner">{label}</div>""", unsafe_allow_html=True)


MES_ABR = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro",
         "Novembro", "Dezembro"]


def month_name(ym: str) -> str:
    """'2026-03' -> 'Março 2026'."""
    y, m = ym.split("-")
    return f"{MESES[int(m) - 1]} {y}"


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


PERIODS = ["Este mês", "Mês passado", "3 meses", "12 meses"]


def spend_window(sp: pd.DataFrame, per: str, today: date, custom: tuple | None = None):
    """Recorte dos gastos de um período -> (lançamentos, total, rótulo, nota em HTML, meses).

    Uma definição só para a Visão geral e para Gastos: o mesmo período dá o mesmo número nas duas telas.
    """
    cur, day = today.strftime("%Y-%m"), today.day
    months = sorted(sp["month"].unique())
    if per == "Este mês":
        # compara períodos equivalentes: dia 1 até hoje, no mês atual e nos 3 anteriores
        mtd = sp[sp["date"].dt.day <= day].groupby("month")["value"].sum()
        total = float(mtd.get(cur, 0))
        prev = mtd[mtd.index < cur].tail(3).mean()
        win = sp[(sp["month"] == cur) & (sp["date"].dt.day <= day)]
        label = f"Gasto em {month_name(cur).lower()}, do dia 1 ao dia {day}"
        if pd.notna(prev) and prev > 0:
            diff = 100 * (total - prev) / prev
            word, cls, ico = ("acima da", "up", "arrow_upward") if diff > 0 else ("abaixo da", "down", "arrow_downward")
            note = (f'<span class="pf-delta {cls}">{visual.icon(ico)} {abs(diff):.0f}% {word} média</span> '
                    f'· média do mesmo período nos 3 meses anteriores: {brl(prev)}')
        else:
            note = "Ainda sem meses anteriores para comparar."
        return win, total, label, note, [cur]
    if per == "Mês passado":
        sel = [m for m in months if m < cur][-1:]
        label = f"Gasto em {month_name(sel[0]).lower()} (mês fechado)" if sel else "Gasto no mês passado"
    else:
        sel = ([m for m in months if custom[0] <= m <= custom[1]] if custom
               else months[-(3 if per == "3 meses" else 12):])
        label = ("Gasto no período" if not sel else f"Gasto em {month_name(sel[0]).lower()}" if len(sel) == 1
                 else f"Gasto de {month_name(sel[0]).lower()} a {month_name(sel[-1]).lower()}")
    win = sp[sp["month"].isin(sel)]
    total = float(win["value"].sum())
    note = ""
    if len(sel) > 1:
        note = f"média de {brl(total / len(sel))} por mês" + (" · o mês atual entra só até hoje" if cur in sel else "")
    return win, total, label, note, sel


def style(fig, height=340, month_axis=True, money=True):
    fig.update_layout(height=height, margin=dict(l=8, r=28 if month_axis else 8, t=24, b=8), legend_title_text="",
                      bargap=0.45, hovermode="x unified" if fig.data and fig.data[0].type == "scatter" else "closest")
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)", zeroline=False, tickprefix="R$ " if money else "", separatethousands=True)
    fig.update_xaxes(showgrid=False, type="category" if month_axis else None,
                     **({"tickangle": 0, "dtick": 1} if month_axis else {}))
    if month_axis:
        months = sorted({str(x) for t in fig.data for x in (t.x if t.x is not None else [])})
        if months and all(re.fullmatch(r"\d{4}-\d{2}", m) for m in months):
            fig.update_xaxes(categoryorder="array", categoryarray=months, tickmode="array", tickvals=months,
                             ticktext=[f"{MES_ABR[int(m[5:]) - 1]}/{m[2:4]}" if len(months) <= 6 else
                                       MES_ABR[int(m[5:]) - 1] + (f"<br>’{m[2:4]}" if i == 0 or m[5:] == "01" else "")
                                       for i, m in enumerate(months)])
    else:
        fig.update_xaxes(tickformat="%m/%Y")
    visual.style_figure(fig)
    return fig


# ------------------------------------------------------------------ tema, backup automático, ver backup
THEME_FILE = Path.cwd() / ".streamlit" / "config.toml"  # o Streamlit lê o tema daqui (pasta onde o painel roda)
THEME_MARK = "# gerado pelo painel (aba Configurações) — pode apagar para voltar ao padrão"


def apply_theme(theme: str) -> bool | None:
    """Grava o tema na configuração do Streamlit. True = mudou (recarregar a página); None = arquivo próprio."""
    text = THEME_MARK + "\n" + visual.config_text(theme)
    current = THEME_FILE.read_text(encoding="utf-8") if THEME_FILE.exists() else None
    if current is not None and THEME_MARK not in current:
        return None  # configuração escrita à mão: não mexer
    if current == text:
        return False
    THEME_FILE.parent.mkdir(exist_ok=True)
    THEME_FILE.write_text(text, encoding="utf-8")
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
    st.warning(f"Você está vendo os dados do **{st.session_state['view'].lower()}** — somente leitura.")

OWNER_DEFAULT = "Conta principal"  # contas sem nome de dono, quando há mais de uma conta Pluggy
with session() as conn:
    df = analytics.transactions(conn)
    _owners = sorted({r[0] or OWNER_DEFAULT for r in conn.execute("SELECT owner FROM accounts WHERE source='pluggy'")})
OWNER = None  # filtro "Pessoa": só aparece quando há mais de uma conta Pluggy com dados
if len(_owners) > 1:
    _pick = st.sidebar.selectbox("Pessoa / conta", ["Todas"] + _owners, key="owner")
    OWNER = None if _pick == "Todas" else _pick
    if OWNER and not df.empty:
        df = df[df["owner"].fillna(OWNER_DEFAULT) == OWNER]

# ---------------- navegação: menu agrupado e um endereço por tela (?tela=gastos)
NAV_ICONS = {"Começar": "flag", "Visão geral": "space_dashboard", "Gastos": "receipt_long", "Entradas": "savings",
             "Cartão": "credit_card", "Previsão": "event_upcoming", "Contas de consumo": "bolt",
             "Empréstimos e vendas": "handshake", "Carro": "directions_car", "Investimentos": "trending_up",
             "Sincronizar": "sync", "Configurações": "settings"}
NAV_GROUPS = [("", ["Visão geral"]),
              ("Dia a dia", ["Gastos", "Entradas", "Cartão", "Contas de consumo"]),
              ("Compromissos", ["Empréstimos e vendas", "Previsão"]),
              ("Patrimônio", ["Investimentos", "Carro"]),
              ("Painel", ["Sincronizar", "Configurações", "Começar"])]
SLUGS = {"Começar": "comecar", "Visão geral": "visao-geral", "Gastos": "gastos", "Entradas": "entradas",
         "Cartão": "cartao", "Previsão": "previsao", "Contas de consumo": "contas", "Empréstimos e vendas": "emprestimos",
         "Carro": "carro", "Investimentos": "investimentos", "Sincronizar": "sincronizar", "Configurações": "configuracoes"}
BY_SLUG = {v: k for k, v in SLUGS.items()}

_q = st.query_params.get("tela")
if _q in BY_SLUG and _q != st.session_state.get("_tela_seen"):
    st.session_state["page"] = BY_SLUG[_q]  # veio do endereço: link, recarregar a página ou "voltar" do navegador
elif st.session_state.get("page") not in NAV_ICONS:  # instalação nova (sem conexões nem dados): abre no passo a passo
    from financas import connections
    fresh = df.empty and not any(connections.is_configured(s) for s in connections.SOURCES)
    st.session_state["page"] = "Começar" if fresh else "Visão geral"
page = st.session_state["page"]
st.session_state["_tela_seen"] = SLUGS[page]
if st.query_params.get("tela") != SLUGS[page]:
    st.query_params["tela"] = SLUGS[page]


def _nav(name: str) -> None:
    st.session_state["page"] = name


for _group, _names in NAV_GROUPS:
    if _group:
        st.sidebar.html(f'<p class="pf-navgroup">{_group}</p>')
    for _n in _names:
        st.sidebar.button(_n, key=f"nav_{SLUGS[_n]}", icon=f":material/{NAV_ICONS[_n]}:", on_click=_nav, args=(_n,),
                          type="secondary" if _n == page else "tertiary", use_container_width=True)


UNSORTED = ["Outros", "Pix enviado"]  # categorias de quem não caiu em nenhuma regra

_METHODS = {"PIX": "Pix", "TED": "TED", "DOC": "DOC", "BOLETO": "Boleto", "CARD": "Cartão", "DEBIT": "Débito"}


def paid_with(r) -> str:
    """Por onde o lançamento passou: cartão (pelo nome) ou conta, com o meio (Pix, TED...) quando o banco informa.

    Do cartão aparecem o nome e os 4 últimos dígitos (pedido do dono em 14/11/2026); nunca o número inteiro.
    Qualquer sequência de 4 ou mais dígitos no nome da conta/cartão é retirada."""
    def txt(v):
        return "" if v is None or pd.isna(v) else str(v).strip()
    name = re.sub(r"[\s*·.-]*\d{4,}[\d\s*.-]*", " ", txt(getattr(r, "account_name", None))).strip()
    inst = visual.institution_name(getattr(r, "institution", None)) if txt(getattr(r, "institution", None)) else ""
    method = _METHODS.get(txt(getattr(r, "payment_method", None)).upper(), "")
    if txt(getattr(r, "account_type", None)) == "CREDIT":
        name = name if name.lower().startswith("cart") else f"Cartão {name}".strip()
        tail = txt(getattr(r, "card_tail", None))
        return " ".join(x for x in (name, inst) if x) + (f" · final {tail}" if tail else "")
    conta = " ".join(x for x in (name or "Conta", inst) if x)
    return f"{method} · {conta}" if method else conta


def entry_item(r, value: float, value_class: str = "") -> dict:
    """Um lançamento como linha de extrato: quem/o quê em cima; categoria, produto, subdivisão, parcela e banco embaixo."""
    def has(v):
        return v is not None and not pd.isna(v) and str(v).strip() != ""
    cp, desc = str(r.counterparty or "").strip(), str(r.description or "").strip()
    cat = r.category + (f" › {r.product}" if has(getattr(r, "product", None)) else "")
    parts = [desc if cp and desc and desc != cp else "", cat,
             str(r.tag) if has(getattr(r, "tag", None)) else ""]
    n, tot = getattr(r, "installment_number", None), getattr(r, "total_installments", None)
    if has(n) and has(tot):
        parts.append(f"parcela {int(n)} de {int(tot)}")
    parts.append(paid_with(r))
    return {"date": r.date.date() if hasattr(r.date, "date") else r.date, "title": cp or desc or "Sem descrição",
            "sub": " · ".join(x for x in parts if x), "category": r.category, "value": float(value),
            "value_class": value_class}

def goto(name: str) -> None:
    """Leva a outra seção (usar em on_click): o valor clicado cai no detalhe que o explica."""
    st.session_state["page"] = name


def goto_unsorted() -> None:
    """Abre Gastos nos últimos 3 meses, filtrado nos lançamentos que não caíram em nenhuma regra."""
    st.session_state["gs_periodo"] = "3 meses"
    st.session_state["gs_cats"] = list(UNSORTED)
    st.session_state["page"] = "Gastos"


def _more_rows(key: str) -> None:
    st.session_state[f"{key}_n"] = st.session_state.get(f"{key}_n", 30) + 30


def ledger_rows(ordered: pd.DataFrame, value_col: str, key: str, refund_green: bool = False) -> None:
    """Extrato por dia em que cada linha abre o detalhe do lançamento. Mostra 30 por vez."""
    if ordered.empty:
        st.html('<div class="ft-empty">Nada para mostrar ainda.</div>')
        return
    n = st.session_state.get(f"{key}_n", 30)
    totals = ordered.groupby(ordered["date"].dt.date)[value_col].sum()
    last = None
    with st.container(key=f"lg_{key}"):
        for i, r in enumerate(ordered.head(n).itertuples()):
            v = float(getattr(r, value_col))
            it = entry_item(r, v, "in" if refund_green and v < 0 else "")
            st.html(visual.day_html(it["date"], brl(totals[it["date"]])) if it["date"] != last
                    else '<hr class="pf-sep">')
            last = it["date"]
            a_, b_ = st.columns([12, 1], vertical_alignment="center")
            a_.html(visual.row_html(visual.mark(it["category"], "category"), it["title"], it["sub"], brl(v),
                                    value_class=it["value_class"]))
            if b_.button("", icon=":material/chevron_right:", key=f"lgo_{key}_{i}", type="tertiary",
                         help="Ver o detalhe e corrigir"):
                tx_dialog(r.id)
    if len(ordered) > n:
        visual.scope(f"Aparecem os {n} lançamentos mais recentes de {len(ordered)}.")
        st.button("Mostrar mais 30", key=f"{key}_more", icon=":material/expand_more:", on_click=_more_rows, args=(key,))


@st.dialog("Lançamento", width="large")
def tx_dialog(tx_id: str) -> None:
    """Tudo sobre um lançamento e a correção no próprio lugar (categoria, regra e subdivisão)."""
    def txt(v) -> str:
        return "" if v is None or pd.isna(v) else str(v).strip()

    with session() as conn:
        t = analytics.transactions(conn)
        cats, tags = all_categories(conn), all_tags(conn)
    hit = t[t["id"] == tx_id]
    if hit.empty:
        st.info("Lançamento não encontrado.")
        return
    r = next(hit.itertuples())
    title = txt(r.counterparty) or txt(r.description) or "Sem descrição"
    visual.hero(title, brl(abs(r.amount)), f"{r.date:%d/%m/%Y} · " + ("entrada" if r.amount > 0 else "saída"))
    n, tot = txt(r.installment_number), txt(r.total_installments)
    fields = [("Categoria", r.category + (" · corrigida por você" if txt(r.manual_category) else " · pelas regras")),
              ("Categoria que veio do banco", txt(r.source_category)),
              ("Descrição", txt(r.description)), ("Quem recebeu ou enviou", txt(r.counterparty)),
              ("Por onde passou", paid_with(r)),
              ("Parcela", f"{int(float(n))} de {int(float(tot))}" if n and tot else ""),
              ("Produto", txt(r.product)), ("Subdivisão", txt(r.tag))]
    visual.rows([visual.row_html("", k, "", v) for k, v in fields if v])
    st.markdown("**Corrigir**")
    with st.form(f"tx_fix_{tx_id}", border=False):
        new_cat = st.selectbox("Categoria certa", cats, index=cats.index(r.category) if r.category in cats else 0)
        scope_ = st.radio("Aplicar em", ["Só este lançamento", "Sempre que aparecer este nome"], horizontal=True)
        name = st.text_input("Nome que identifica (para “sempre”)", txt(r.counterparty) or txt(r.description),
                             help="Pode encurtar: 'MARIA SILVA' pega todo Pix com esse nome. Acentos e maiúsculas "
                                  "não importam.")
        t1, t2 = st.columns(2)
        cur_tag = txt(r.tag)
        tag_pick = t1.selectbox("Subdivisão (opcional)", ["— nenhuma —"] + tags,
                                index=(tags.index(cur_tag) + 1) if cur_tag in tags else 0)
        tag_new = t2.text_input("…ou criar nova subdivisão", placeholder="ex.: Viagem Rio 2027")
        if st.form_submit_button("Salvar correção", type="primary", disabled=VIEW is not None):
            tag = tag_new.strip() or (None if tag_pick == "— nenhuma —" else tag_pick)
            with session() as conn:
                set_tag(conn, tx_id, tag)
                if scope_ == "Só este lançamento":
                    set_manual(conn, tx_id, new_cat)
                    st.session_state["fix_msg"] = f"Lançamento corrigido para **{new_cat}**."
                else:
                    k = add_rule(conn, name, new_cat)
                    st.session_state["fix_msg"] = (f"Regra criada: **{name}** → **{new_cat}** "
                                                   f"({k} lançamento(s) com esse nome).")
            st.rerun()
    visual.scope("Suas correções sempre vencem as regras padrão. Para vincular um produto, use “Corrigir e organizar” "
                 "em Gastos.")


def goto_gastos() -> None:
    """Abre Gastos no mesmo período que está na Visão geral: o total clicado reaparece igual no detalhe."""
    st.session_state["gs_periodo"] = st.session_state.get("vg_periodo") or "Este mês"
    st.session_state["page"] = "Gastos"


@st.dialog("Registrar recebimento")
def receive_dialog(item: dict) -> None:
    """Baixa interna de um recebimento (registro; nenhum dinheiro é movimentado pelo painel)."""
    directed = item.get("directed", True)
    st.markdown(item.get("head") or f"**{item['person']}** · {item['what']} · vencimento {item['due']:%d/%m/%Y}")
    rd = st.date_input("Data do recebimento", value=date.today(), format="DD/MM/YYYY", key="vg_rc_date")
    ra = st.number_input("Valor recebido (R$)", min_value=0.0, value=float(item["amount"]), step=50.0, key="vg_rc_amt")
    st.caption(("O valor abate este empréstimo ou venda, começando pelas parcelas mais antigas. " if directed else
                "O valor abate os empréstimos desta pessoa, começando pelos mais antigos; se sobrar, passa para o "
                "próximo. ") + "Só registra o que você já recebeu: o painel não movimenta dinheiro.")
    if st.button("Registrar recebimento", type="primary", disabled=ra <= 0, key="vg_rc_save"):
        with session() as conn:
            conn.execute("INSERT INTO loan_payments(loan_id, date, amount, note, directed, order_mode) "
                         "VALUES (?,?,?,?,?,'antigas')", (item["id"], rd.isoformat(), ra, "manual", int(directed)))
        st.rerun()


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def result_text(r) -> str:
    """Resultado de um empréstimo em uma frase: juros recebidos x previstos e pontualidade (linha de loan_results)."""
    parts = [f"juros recebidos {brl(r.interest_received)} de {brl(r.interest_expected)} previstos"
             if r.interest_expected > 0.005 else "sem juros"]
    if not r.scheduled:
        parts.append("sem data combinada: não há atraso a medir")
    elif r.due_count:
        parts.append(f"{r.on_time} de {_plural(r.due_count, 'parcela vencida paga', 'parcelas vencidas pagas')} em dia")
        if r.late_paid:
            parts.append(_plural(r.late_paid, "paga com atraso", "pagas com atraso"))
        if r.late_open:
            parts.append(_plural(r.late_open, "vencida em aberto", "vencidas em aberto"))
        if r.late_days:
            parts.append(f"{_plural(r.late_days, 'dia', 'dias')} de atraso somados")
    else:
        parts.append("nenhuma parcela venceu ainda")
    if r.done and r.realized_rate is not None and pd.notna(r.realized_rate):
        parts.append(f"taxa realizada {100 * r.realized_rate:.2f}% ao mês (combinada {100 * r.agreed_rate:.2f}%)"
                     .replace(".", ","))
    return " · ".join(parts)


@st.dialog("Ficha da pessoa", width="large")
def person_dialog(person: str, asof: date) -> None:
    """Tudo sobre uma pessoa num lugar só: saldo, empréstimos e vendas, próximas parcelas e linha do tempo. Só consulta."""
    with session() as conn:
        status = analytics.loan_status(conn, asof)
        sched = analytics.loan_schedule_open(conn, asof)
        res = analytics.loan_results(conn, asof)
        pays = pd.read_sql("SELECT p.date, p.amount, p.note, p.transaction_id, l.kind, l.item FROM loan_payments p "
                           "JOIN loans l ON l.id = p.loan_id WHERE l.person = ? ORDER BY p.date DESC, p.id DESC",
                           conn, params=(person,))
    mine = status[status["person"] == person] if not status.empty else status
    if mine.empty:
        st.info("Nada registrado para esta pessoa.")
        return
    open_ = mine[mine["closed"] == 0]
    late = float(open_["overdue"].sum())
    visual.hero(f"{person} · falta receber em {asof:%d/%m/%Y}", brl(open_["remaining"].sum()),
                f"emprestado ou vendido {brl(mine['principal'].sum())} · já recebido {brl(mine['paid'].sum())}"
                + ("<br>" + visual.badge(f"{brl(late)} em atraso", "late") if late > 0.005 else ""))
    by_id = {r.id: r for r in res.itertuples()} if not res.empty else {}
    st.markdown("**Empréstimos e vendas**")
    items = []
    for r in mine.sort_values("date", ascending=False).itertuples():
        when = f"{date.fromisoformat(str(r.date)[:10]):%d/%m/%Y}"
        sale = r.kind == "venda"
        title = f"Venda: {r.item or 'sem descrição'}" if sale else f"Empréstimo de {brl(r.principal)}"
        sub = (f"em {when} · {brl(r.principal)} · recebido {brl(r.paid)}" if sale else
               f"em {when} · " + (result_text(by_id[r.id]) if r.id in by_id else f"recebido {brl(r.paid)}"))
        badge = (visual.badge("Quitado", "ok") if r.closed else
                 visual.badge(f"{brl(r.overdue)} em atraso", "late") if r.overdue > 0.005 else "")
        items.append(visual.row_html(visual.mark("sell" if sale else "handshake", "icon"), title, sub,
                                     brl(r.remaining), "falta receber", badge_html=badge, badge_below=True))
    visual.rows(items)
    nxt = sched[sched["person"] == person].sort_values("due_date") if not sched.empty else sched
    if not nxt.empty:
        st.markdown("**Parcelas em aberto**")
        visual.rows([visual.row_html(visual.mark("event", "icon", small=True),
                                     f"Vencimento {date.fromisoformat(r.due_date):%d/%m/%Y}", f"parcela de {brl(r.amount)}",
                                     brl(r.remaining), "em aberto",
                                     badge_html=visual.due_badge(date.fromisoformat(r.due_date), asof))
                     for r in nxt.itertuples()])
    st.markdown("**Linha do tempo**")
    events = [(str(r.date)[:10], 0, visual.row_html(
        visual.mark("north_east", "icon", small=True),
        "Você vendeu" if r.kind == "venda" else "Você emprestou",
        f"{date.fromisoformat(str(r.date)[:10]):%d/%m/%Y}" + (f" · {r.item}" if r.kind == "venda" and r.item else "")
        + (f" · {r.note}" if isinstance(r.note, str) and r.note.strip() else ""), brl(r.principal)))
        for r in mine.itertuples()]
    events += [(str(r.date)[:10], 1, visual.row_html(
        visual.mark("south_west", "icon", small=True), "Você recebeu",
        f"{date.fromisoformat(str(r.date)[:10]):%d/%m/%Y} · "
        + ("Pix ligado ao lançamento do banco" if isinstance(r.transaction_id, str) and r.transaction_id
           else "lançado à mão") + (f" · venda: {r.item}" if r.kind == "venda" and r.item else ""),
        brl(r.amount), value_class="in")) for r in pays.itertuples()]
    visual.rows([h for _, _, h in sorted(events, key=lambda e: (e[0], e[1]), reverse=True)])
    visual.scope("Só consulta. Para registrar um recebimento, feche a ficha e use “Dar baixa”.")


@st.dialog("Confirmar Pix como pagamento")
def pix_confirm_dialog(q: dict) -> None:
    """Baixa interna de um Pix que já entrou na conta. O painel não movimenta dinheiro."""
    st.markdown(f"**{brl(q['amount'])}** recebido em {q['date']:%d/%m/%Y} de **{q['from'] or 'remetente não informado'}**".replace("$", "\\$"))
    labels = {f"{t['label']} · falta {brl(t['remaining'])}": t for t in q["targets"]}
    pick = labels[st.radio(f"Abater de qual registro de {q['person']}?", list(labels), key="fq_target")]
    st.caption(("O valor abate esta venda, começando pelas parcelas mais antigas. " if pick["kind"] == "venda" else
                "O valor abate os empréstimos desta pessoa, começando pelos mais antigos. ")
               + "Esse Pix deixa de contar como entrada comum e passa a contar como recebimento de "
               + ("venda" if pick["kind"] == "venda" else "empréstimo")
               + ", igual ao que o painel faz quando casa um Pix sozinho.")
    if st.button("Confirmar pagamento", type="primary", key="fq_save"):
        with session() as conn:
            analytics.confirm_loan_pix(conn, q["tx_id"], pick["id"])
        st.rerun()


@st.dialog("Registrar pagamento de parcela")
def pay_dialog(item: dict) -> None:
    """Registro de uma parcela de dívida com banco que você já pagou."""
    st.markdown(f"**{item['person']}** · parcela com vencimento {item['due']:%d/%m/%Y}")
    pd_ = st.date_input("Data do pagamento", value=date.today(), format="DD/MM/YYYY", key="vg_bp_date")
    pa = st.number_input("Valor pago (R$)", min_value=0.0, value=float(item["amount"]), step=10.0, key="vg_bp_amt")
    st.caption("Só registra um pagamento que você já fez no banco: o painel não paga nada.")
    if st.button("Registrar pagamento", type="primary", disabled=pa <= 0, key="vg_bp_save"):
        with session() as conn:
            conn.execute("INSERT INTO bank_loan_payments(bank_loan_id, date, amount) VALUES (?,?,?)",
                         (item["id"], pd_.isoformat(), pa))
        st.rerun()


if os.getenv("FIN_ENV_NAME") == "dev":
    st.sidebar.warning("**Desenvolvimento** — dados de teste (clone de prod)")
st.sidebar.caption(f"Base: `{DB}` · versão {__version__}")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _new_release():
    from financas import updates
    return updates.available(__version__)


if os.getenv("FIN_ENV_NAME") != "dev":
    with db_session() as _c:
        _check = settings.get(_c, "update_check") == "1"
    _rel = _new_release() if _check else None
    if _rel:
        st.sidebar.info(f"**Versão {_rel['version']} disponível** (você usa {__version__}). "
                        f"[Ver novidades e como atualizar]({_rel['url']})")

# ------------------------------------------------------------------ Começar
if page == "Começar":
    from financas.ui import guide
    guide.render(lambda name: st.session_state.update(page=name))

# ------------------------------------------------------------------ Visão geral
elif page == "Visão geral":
    st.title("Visão geral")
    today = date.today()
    with session() as conn:
        hold = analytics.latest_holdings(conn)
        loans = analytics.loan_status(conn)
        sched = analytics.loan_schedule_open(conn)
        bank_loans, bank_sched = analytics.bank_loan_status(conn)
        cards = analytics.card_summary(conn)
        hist = analytics.net_worth_history(conn)
        accts = pd.read_sql("SELECT institution, name, type, balance, balance_date, owner FROM accounts", conn)
        bills = pd.read_sql("SELECT provider, ref_month, due_date, paid_date, amount FROM utility_bills "
                            "WHERE due_date >= ? ORDER BY due_date", conn, params=(today.isoformat(),))
        if OWNER:
            accts = accts[accts["owner"].fillna(OWNER_DEFAULT) == OWNER]
            cards = [c for c in cards if (c["owner"] or OWNER_DEFAULT) == OWNER]
    sp, inc = analytics.spending(df), analytics.income(df)
    cur = today.strftime("%Y-%m")
    pal = visual.palette()

    left, right = st.columns([6, 5], gap="medium")

    # ---------- bloco do período: o filtro mora dentro do que ele controla
    with left, st.container(border=True, key="vg_gasto"):
        per = st.segmented_control("Período do gasto", PERIODS, default="Este mês", key="vg_periodo",
                                   label_visibility="collapsed") or "Este mês"
        if sp.empty:
            visual.hero("Gasto no período", "—")
            st.info("Sem transações ainda. Vá em **Sincronizar**.")
        else:
            win, total, label, note, _ = spend_window(sp, per, today)
            visual.hero(label, brl(total), note)
            cats = win.groupby("category")["value"].sum().sort_values(ascending=False)
            cats = cats[cats > 0]
            if not cats.empty:
                st.html('<p class="pf-eyebrow" style="margin-top:.6rem">Para onde foi</p>')
                top, rest = cats.head(6), cats.iloc[6:]
                items = [{"label": c, "value": v, "text": brl(v), "sub": f"{100 * v / total:.0f}%" if total else ""}
                         for c, v in top.items()]
                if not rest.empty:
                    items.append({"label": f"Outras {len(rest)} categorias", "value": float(rest.sum()),
                                  "text": brl(rest.sum()), "sub": f"{100 * rest.sum() / total:.0f}%" if total else "",
                                  "icon": "more_horiz", "kind": "icon"})
                visual.bars(items)
            st.button("Ver os lançamentos em Gastos", icon=":material/arrow_forward:", type="tertiary",
                      on_click=goto_gastos, key="vg_go_gastos")
        visual.scope("O período acima muda só este bloco. O bloco “Hoje” e a agenda mostram a posição atual.")

    # ---------- bloco "Hoje": estado atual, o período não mexe aqui
    with right, st.container(border=True, key="vg_hoje"):
        st.html(f'<p class="pf-eyebrow">Hoje · {today:%d/%m/%Y}</p>')

        def today_row(html: str, target: str, key: str) -> None:
            a_, b_ = st.columns([9, 1], vertical_alignment="center")
            a_.html(html)
            b_.button("", icon=":material/chevron_right:", key=key, type="tertiary", on_click=goto, args=(target,),
                      help=f"Abrir {target}")

        bank = accts[accts["type"] == "BANK"] if not accts.empty else accts
        bank_total = bank["balance"].sum() if not bank.empty else 0
        insts = " · ".join(sorted({visual.institution_name(i) for i in bank["institution"].dropna()})) if not bank.empty else ""
        st.html(visual.row_html(visual.mark("account_balance", "icon"), "Saldo em conta", insts or "sem contas ainda",
                                brl(bank_total)))
        st.html('<hr class="pf-sep">')
        inv_total = hold["value_brl"].sum() if not hold.empty else 0
        inv_src = " · ".join(visual.institution_name(x) for x in sorted(hold["source"].unique())) if not hold.empty else ""
        today_row(visual.row_html(visual.mark("trending_up", "icon"), "Investimentos", inv_src or "sem posições ainda",
                                  brl(inv_total)), "Investimentos", "vg_go_inv")
        st.html('<hr class="pf-sep">')
        open_l = loans[loans["closed"] == 0] if not loans.empty else loans
        rec_total = loans["remaining"].sum() if not loans.empty else 0
        late_total = float(open_l["overdue"].sum()) if not open_l.empty else 0.0
        by_kind = open_l.groupby("kind")["remaining"].sum() if not open_l.empty else {}
        parts = [f"{nome} {brl(by_kind.get(k, 0))}" for k, nome in (("emprestimo", "empréstimos"), ("venda", "vendas"))
                 if by_kind.get(k, 0) > 0]
        today_row(visual.row_html(visual.mark("handshake", "icon"), "A receber", " + ".join(parts) or "nada em aberto",
                                  brl(rec_total),
                                  badge_html=visual.badge(f"{brl(late_total)} em atraso", "late") if late_total > 0.005 else "",
                                  badge_below=True),
                  "Empréstimos e vendas", "vg_go_rec")
        for i, c in enumerate(cards):
            st.html('<hr class="pf-sep">')
            used_pct = (f"{100 * c['used'] / c['limit']:.0f}% do limite usado" if c["limit"] and c["used"] is not None
                        else "")
            today_row(visual.row_html(visual.mark("credit_card", "icon"), "Fatura do cartão",
                                      " · ".join(x for x in ("aberta, estimada", visual.institution_name(c["institution"]), used_pct) if x),
                                      brl(c["open_bill_estimate"])), "Cartão", f"vg_go_card{i}")
        debt = bank_loans["remaining"].sum() if not bank_loans.empty else 0
        if debt > 0.005:
            st.html('<hr class="pf-sep">')
            today_row(visual.row_html(visual.mark("account_balance_wallet", "icon"), "Dívida com banco",
                                      "falta pagar", brl(debt)), "Empréstimos e vendas", "vg_go_debt")

    # ---------- pendências: só o que pede uma ação do dono, com atalho para o lugar de resolver
    since60 = (today - timedelta(days=60)).isoformat()
    with session() as conn:
        pix_q = analytics.loan_pix_queue(conn, today)
        unpaid = conn.execute("SELECT COUNT(*) FROM utility_bills WHERE due_date < ? AND due_date >= ? "
                              "AND (paid_date IS NULL OR paid_date = '')", (today.isoformat(), since60)).fetchone()[0]
        last_sync = conn.execute("SELECT MAX(at) FROM sync_log WHERE ok = 1").fetchone()[0]
    unsorted = sp[(sp["date"] >= pd.Timestamp(since60)) & sp["category"].isin(UNSORTED)] if not sp.empty else sp
    revisar = len(list((config.BILLS_DIR / "revisar").glob("*.pdf"))) if (config.BILLS_DIR / "revisar").exists() else 0
    pend = []  # (ícone, título, detalhe, função de clique, argumentos)
    if pix_q:
        pend.append(("help", f"{_plural(len(pix_q), 'Pix pode', 'Pix podem')} ser pagamento de quem deve a você",
                     "Confirme ou ignore em Empréstimos e vendas.", goto, ("Empréstimos e vendas",)))
    if len(unsorted):
        pend.append(("label", f"{_plural(len(unsorted), 'gasto sem categoria definida', 'gastos sem categoria definida')}",
                     f"Dos últimos 60 dias, em “Outros” ou “Pix enviado”: {brl(unsorted['value'].sum())}.",
                     goto_unsorted, ()))
    if unpaid:
        pend.append(("receipt_long", f"{_plural(unpaid, 'conta de consumo vencida', 'contas de consumo vencidas')} "
                     "sem pagamento registrado", "Pode já estar paga: o painel só sabe quando a data de pagamento é lançada.",
                     goto, ("Contas de consumo",)))
    if revisar:
        pend.append(("upload_file", f"{_plural(revisar, 'PDF de conta aguardando', 'PDFs de conta aguardando')} revisão",
                     "O painel não conseguiu ler sozinho.", goto, ("Contas de consumo",)))
    if last_sync:
        age = (today - date.fromisoformat(str(last_sync)[:10])).days
        if age >= 3:
            pend.append(("sync_problem", f"Dados de {age} dias atrás",
                         f"Última sincronização que deu certo: {date.fromisoformat(str(last_sync)[:10]):%d/%m/%Y}.",
                         goto, ("Sincronizar",)))
    st.subheader(f"Pendências ({len(pend)})" if pend else "Pendências")
    if not pend:
        visual.scope("Nada pendente: sem Pix a conferir, gastos sem categoria, contas sem pagamento registrado ou dados "
                     "desatualizados.")
    else:
        with st.container(border=True, key="vg_pend"):
            for i, (ico, title_, sub_, fn, args_) in enumerate(pend):
                if i:
                    st.html('<hr class="pf-sep">')
                a_, b_ = st.columns([12, 1], vertical_alignment="center")
                a_.html(visual.row_html(visual.mark(ico, "icon"), title_, sub_))
                b_.button("", icon=":material/chevron_right:", key=f"vg_pd_{i}", type="tertiary", on_click=fn,
                          args=args_, help="Abrir o lugar de resolver")

    # ---------- agenda: o que vence e o que entra, com o aviso e a ação na própria linha
    st.subheader("Agenda: a receber e a pagar")
    horizon = today + timedelta(days=45)
    kind_of = dict(zip(loans["id"], loans["kind"])) if not loans.empty else {}
    item_of = dict(zip(loans["id"], loans["item"])) if not loans.empty else {}
    agenda = []
    for r in sched.itertuples():
        due = date.fromisoformat(r.due_date)
        if due <= horizon:
            venda = kind_of.get(r.loan_id) == "venda"
            agenda.append({"due": due, "dir": "in", "id": int(r.loan_id), "person": r.person, "amount": float(r.remaining),
                           "what": f"venda: {item_of.get(r.loan_id) or 'sem descrição'}" if venda else "parcela de empréstimo",
                           "mark": visual.mark("sell" if venda else "handshake", "icon")})
    for r in bank_sched.itertuples():
        due = date.fromisoformat(r.due_date)
        if due <= horizon:
            agenda.append({"due": due, "dir": "out", "id": int(r.bank_loan_id), "person": r.bank, "amount": float(r.remaining),
                           "what": "parcela de dívida com banco", "mark": visual.mark("account_balance", "icon")})
    for r in bills.itertuples():
        due = date.fromisoformat(r.due_date)
        if due <= horizon:
            paid = bool(r.paid_date) and str(r.paid_date) <= today.isoformat()
            agenda.append({"due": due, "dir": "bill", "id": None, "person": PROVIDER_NAMES.get(r.provider, r.provider.title()),
                           "amount": float(r.amount or 0), "what": f"conta de {month_name(r.ref_month).lower()}", "paid": paid,
                           "mark": visual.mark("water_drop" if r.provider == "cesama" else "bolt", "icon")})
    agenda.sort(key=lambda x: x["due"])

    def when_badge(it: dict) -> str:
        return visual.due_badge(it["due"], today, paid=bool(it.get("paid")))

    if not agenda:
        st.caption("Nada a receber ou a pagar nos próximos 45 dias.")
    else:
        late_n = sum(1 for it in agenda if it["due"] < today and not it.get("paid"))
        visual.scope(("" if not late_n else ("1 item em atraso. " if late_n == 1 else f"{late_n} itens em atraso. ")) +
                     f"Mostra o que está atrasado e o que vence até {horizon:%d/%m/%Y}. "
                     "Os botões só registram o que já aconteceu: o painel não paga nem transfere.")
        with st.container(border=True, key="vg_agenda"):
            for i, it in enumerate(agenda[:10]):
                if i:
                    st.html('<hr class="pf-sep">')
                a_, b_ = st.columns([6, 1.6], vertical_alignment="center")
                sign = "+ " if it["dir"] == "in" else ""
                a_.html(visual.row_html(it["mark"], it["person"], f"{it['due']:%d/%m/%Y} · {it['what']}",
                                        sign + brl(it["amount"]), "a receber" if it["dir"] == "in" else "a pagar",
                                        badge_html=when_badge(it), value_class="in" if it["dir"] == "in" else ""))
                if it["dir"] == "in":
                    if b_.button("Dar baixa", key=f"vg_ag_{i}", disabled=VIEW is not None, use_container_width=True):
                        receive_dialog(it)
                elif it["dir"] == "out":
                    if b_.button("Registrar", key=f"vg_ag_{i}", disabled=VIEW is not None, use_container_width=True,
                                 help="Registrar que esta parcela já foi paga"):
                        pay_dialog(it)
            if len(agenda) > 10:
                st.caption(f"Mais {len(agenda) - 10} item(ns) em Empréstimos e vendas.")

    # ---------- tendências
    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Entradas e saídas por mês")
        if not sp.empty:
            flow = pd.DataFrame({"Entradas": inc.groupby("month")["amount"].sum(),
                                 "Saídas": sp.groupby("month")["value"].sum()}).fillna(0).tail(12)
            flow = flow.reset_index(names="month").melt("month", var_name="Tipo", value_name="Valor")
            flow["txt"] = flow["Valor"].map(brl)
            fig = px.bar(flow, x="month", y="Valor", color="Tipo", barmode="group", custom_data=["txt"],
                         color_discrete_map={"Entradas": C_IN, "Saídas": C_OUT}, labels={"month": "", "Valor": ""})
            fig.update_traces(hovertemplate="%{customdata[0]}<extra>%{fullData.name}</extra>")
            st.plotly_chart(style(fig, 300), use_container_width=True)
            st.caption("Últimos 12 meses. O mês atual vai só até hoje.")
        else:
            st.info("Sem transações ainda. Vá em **Sincronizar**.")
    with right:
        st.subheader("Investimentos ao longo do tempo")
        if not hist.empty:
            piv = hist.pivot_table(index="snapshot", columns="source", values="value", aggfunc="sum").ffill().fillna(0)
            piv = piv.rename(columns=visual.institution_name)
            piv = piv.reset_index().melt("snapshot", var_name="Fonte", value_name="Valor")
            piv["txt"] = piv["Valor"].map(brl)
            srcs = sorted(piv["Fonte"].unique())
            fig = px.area(piv, x="snapshot", y="Valor", color="Fonte", custom_data=["txt"],
                          color_discrete_map={s_: SERIES[i] for i, s_ in enumerate(srcs)},
                          labels={"snapshot": "", "Valor": ""})
            fig.update_traces(hovertemplate="%{customdata[0]}<extra>%{fullData.name}</extra>", line_width=2)
            st.plotly_chart(style(fig, 300, month_axis=False), use_container_width=True)
            st.caption("Valor de cada retrato das posições, por instituição.")
        else:
            st.info("Sem histórico de investimentos ainda.")

# ------------------------------------------------------------------ Gastos
elif page == "Gastos":
    st.title("Gastos")
    today = date.today()
    sp = analytics.spending(df)
    if sp.empty:
        st.info("Sem transações ainda. Vá em **Sincronizar**.")
        st.stop()
    months = sorted(sp["month"].unique())
    st.session_state.setdefault("gs_periodo", "Este mês")

    def pick_cats(cats: list[str]) -> None:
        """Clique numa linha do ranking: filtra os lançamentos por ela (clicar de novo desfaz)."""
        st.session_state["gs_cats"] = [] if st.session_state.get("gs_cats") == cats else cats

    left, right = st.columns(2, gap="medium")

    # ---------- bloco do período: total em destaque e o mês a mês
    with left, st.container(border=True, key="gs_resumo"):
        per = st.segmented_control("Período", PERIODS + ["Outro período"], key="gs_periodo",
                                   label_visibility="collapsed") or "Este mês"
        custom = None
        if per == "Outro período":
            custom = st.select_slider("De / até", options=months, value=(months[max(0, len(months) - 6)], months[-1]),
                                      format_func=month_name, key="gs_custom")
        win, total, label, note, sel_months = spend_window(sp, per, today, custom)
        visual.hero(label, brl(total), note)
        by_month = sp.groupby("month")["value"].sum()
        first = min([months[-12:][0]] + sel_months[:1])
        mm = by_month[by_month.index >= first].reset_index()
        mm["txt"] = mm["value"].map(brl)
        fig = px.bar(mm, x="month", y="value", custom_data=["txt"], labels={"month": "", "value": ""})
        fig.update_traces(marker_color=[C_OUT if m in sel_months else OTHER for m in mm["month"]],
                          hovertemplate="%{customdata[0]}<extra></extra>")
        style(fig, 230)
        # gráfico pequeno: um rótulo a cada dois meses (o último sempre aparece); o ano entra quando muda
        mlist, ticks, last_year = list(mm["month"]), [], None
        for i, m in enumerate(mlist):
            if len(mlist) > 6 and (len(mlist) - 1 - i) % 2:
                ticks.append("")
                continue
            ticks.append(MES_ABR[int(m[5:]) - 1] + (f"<br>’{m[2:4]}" if m[:4] != last_year else ""))
            last_year = m[:4]
        fig.update_xaxes(ticktext=ticks)
        st.plotly_chart(fig, use_container_width=True, key="gs_mes_a_mes")
        visual.scope("Cada barra é o gasto de um mês; em destaque, o período escolhido. O mês atual vai só até hoje. "
                     "O período muda o total, o ranking e os lançamentos desta tela.")

    # ---------- ranking: cada linha leva aos lançamentos que a explicam
    cats_total = win.groupby("category")["value"].sum().sort_values(ascending=False)
    cats_total = cats_total[cats_total.abs() > 0.005]
    cat_options = sorted(win["category"].unique())
    chosen_cats = [c for c in st.session_state.get("gs_cats", []) if c in cat_options]
    st.session_state["gs_cats"] = chosen_cats
    with right, st.container(border=True, key="gs_rank"):
        st.html('<p class="pf-eyebrow">Para onde foi</p>')
        if cats_total.empty:
            st.caption("Sem gastos neste período.")
        else:
            top = float(cats_total.abs().max())
            for i, (c, v) in enumerate(cats_total.items()):
                a_, b_ = st.columns([9, 1], vertical_alignment="center")
                a_.html(visual.bar_row_html(c, v, top, brl(v), f"{100 * v / total:.0f}%" if total else "",
                                            selected=c in chosen_cats))
                b_.button("", icon=":material/chevron_right:", key=f"gs_go_{i}", type="tertiary", on_click=pick_cats,
                          args=([c],), help=f"Ver os lançamentos de {c}")
            visual.scope("A seta de cada linha filtra os lançamentos abaixo por aquela categoria.")

    if len(sel_months) > 1:
        with st.expander("Composição mês a mês, por categoria", icon=":material/stacked_bar_chart:"):
            folded, cmap = fold_categories(win, "category", "value")
            agg = folded.groupby(["month", "category"], as_index=False)["value"].sum()
            agg["mes_txt"] = agg["month"].map(month_name)
            agg["valor_txt"] = agg["value"].map(brl)
            fig = px.bar(agg, x="month", y="value", color="category", color_discrete_map=cmap,
                         category_orders={"category": list(cmap)}, labels={"month": "", "value": "", "category": ""},
                         custom_data=["mes_txt", "valor_txt"])
            fig.update_traces(hovertemplate="%{customdata[0]}<br>%{customdata[1]}<extra>%{fullData.name}</extra>")
            st.plotly_chart(style(fig, 360), use_container_width=True, key="gasto_mensal_cat")
    with st.expander("Ranking com produtos e média por mês (para conferir)", icon=":material/table_rows:"):
        rlabel = win["category"] + win["product"].map(lambda p: "" if pd.isna(p) or not p else f" › {p}")
        rank = win.groupby(rlabel)["value"].agg(["sum", "count"]).sort_values("sum", ascending=False)
        rank["média/mês"] = rank["sum"] / max(1, win["month"].nunique())
        visual.table(rank.rename(columns={"sum": "total", "count": "lançamentos"}).reset_index()
                     .rename(columns={"index": "categoria", "category": "categoria"})
                     .style.format({"total": brl, "média/mês": brl}), use_container_width=True)

    # ---------- lançamentos: os filtros moram dentro do bloco que eles controlam
    st.subheader("Lançamentos")
    with st.container(border=True, key="gs_lanc"):
        f1, f2 = st.columns([3, 2])
        cats = f1.multiselect("Categorias", cat_options, key="gs_cats", placeholder="Todas as categorias")
        q = f2.text_input("Buscar descrição ou contraparte", key="gs_busca")
        show = win if not cats else win[win["category"].isin(cats)]
        if q:
            show = show[(show["description"].fillna("") + " " + show["counterparty"].fillna(""))
                        .str.contains(q, case=False, regex=False)]
        visual.scope(f"{len(show)} lançamento{'s' if len(show) != 1 else ''} · total {brl(show['value'].sum())} · "
                     + label.replace("Gasto ", "", 1)
                     + ("" if not cats else " · " + ", ".join(cats)))
        ordered = show.fillna({"counterparty": "", "description": ""}).sort_values("date", ascending=False)
        if msg := st.session_state.pop("fix_msg", None):
            st.success(msg)
        visual.scope("A seta de cada linha abre o detalhe do lançamento, onde dá para corrigir a categoria.")
        ledger_rows(ordered, "value", "gs", refund_green=True)
        with st.expander("Ver como tabela (uma coluna por campo)", icon=":material/table_rows:"):
            visual.table(ordered.assign(institution=[paid_with(r) for r in ordered.itertuples()])[
                ["date", "description", "counterparty", "category", "product", "tag", "value", "institution",
                 "installment_number", "total_installments"]].rename(columns={"tag": "subdivisão", "product": "produto",
                                                                              "category": "categoria",
                                                                              "institution": "pago com"})
                .style.format({"value": brl, "date": lambda d: d.strftime("%d/%m/%Y"),
                               "installment_number": lambda v: "" if pd.isna(v) else str(int(v)),
                               "total_installments": lambda v: "" if pd.isna(v) else str(int(v))}, na_rep=""),
                use_container_width=True, hide_index=True)
        st.caption("Valores negativos são reembolsos (ex.: amigos devolvendo a parte deles) e abatem o gasto.")

    # ---------- recorrentes e subdivisões: não dependem do período
    st.subheader("Recorrentes detectados")
    visual.scope("Pix e cobranças que se repetem quase todo mês com valor parecido. Considera todo o histórico: "
                 "o período escolhido não muda esta lista.")
    rec = analytics.recurring(df)
    visual.listing(rec.rename(columns={"key": "descrição", "category": "categoria", "monthly": "valor/mês",
                                     "hits": "meses", "last": "último"})
                 .style.format({"valor/mês": brl, "último": lambda m: f"{MES_ABR[int(str(m)[5:7]) - 1]}/{str(m)[:4]}"
                                if re.fullmatch(r"\d{4}-\d{2}", str(m)) else m}),
                 title="{descrição}", value="{valor/mês}", value_sub="por mês", sub=["{categoria}", "{meses} meses", "último em {último}"], icon=("category", "{categoria}"), table="os recorrentes", use_container_width=True, hide_index=True)

    with session() as conn:
        tagged = pd.read_sql("SELECT tag, category, date, amount FROM transactions WHERE tag IS NOT NULL", conn,
                             parse_dates=["date"])
    if not tagged.empty:
        st.subheader("Por subdivisão")
        visual.scope("Custo líquido (gastos − reembolsos) de cada subdivisão, em todo o histórico.")
        agg = tagged.groupby("tag").agg(custo=("amount", lambda x: -x.sum()), lançamentos=("amount", "size"),
                                        início=("date", "min"), fim=("date", "max"),
                                        categorias=("category", lambda x: ", ".join(sorted(set(x))))).reset_index()
        visual.listing(agg.rename(columns={"tag": "subdivisão"}).sort_values("início", ascending=False)
                     .style.format({"custo": brl, "início": lambda d: d.strftime("%d/%m/%Y"),
                                    "fim": lambda d: d.strftime("%d/%m/%Y")}), title="{subdivisão}", value="{custo}", sub=["{lançamentos} lançamentos", "de {início} a {fim}", "{categorias}"], icon=("icon", "sell"), table="as subdivisões", use_container_width=True, hide_index=True)

    # ---------- correções: cadastro separado da consulta
    st.subheader("Corrigir e organizar")
    visual.scope("Use os filtros de Lançamentos, acima, para achar o lançamento. Suas correções sempre vencem as "
                 "regras padrão.")
    if msg := st.session_state.pop("fix_msg", None):
        st.success(msg)
    pick = show.sort_values("date", ascending=False).head(300)

    def txt(v) -> str:
        return "" if v is None or pd.isna(v) else str(v)

    labels = {" · ".join(x for x in (f"{r.date:%d/%m/%Y}", txt(r.description), txt(r.counterparty), brl(r.value),
                                     f"[{r.category}]") if x): r for r in pick.itertuples()}
    with st.expander("Corrigir a categoria de um lançamento", icon=":material/edit:"):
        if pick.empty:
            st.info("Nenhum lançamento no filtro atual.")
        else:
            with session() as conn:
                all_cat_options = all_categories(conn)
                tag_options = all_tags(conn)
            # fora do form para que o nome sugerido acompanhe o lançamento escolhido
            chosen = labels[st.selectbox("Lançamento", list(labels))]
            with st.form("fix_category"):
                new_cat = st.selectbox("Categoria certa", all_cat_options,
                                       index=all_cat_options.index(chosen.category)
                                       if chosen.category in all_cat_options else 0)
                scope = st.radio("Aplicar em", ["Só este lançamento", "Sempre que aparecer este nome"], horizontal=True)
                name = st.text_input("Nome que identifica (para 'sempre')",
                                     txt(chosen.counterparty) or txt(chosen.description), key=f"rule_name_{chosen.id}",
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

    with st.expander("Vincular um produto a uma compra", icon=":material/sell:"):
        st.caption("Diga qual produto foi uma compra. Com 'loja + valor', toda parcela igual (as de meses passados e "
                   "as futuras) já aparece como esse produto, e o ranking mostra 'Compras online › Produto'.")
        if pick.empty:
            st.info("Nenhum lançamento no filtro atual.")
        else:
            pchosen = labels[st.selectbox("Lançamento da compra", list(labels), key="prod_pick")]
            with st.form("link_product"):
                pname = st.text_input("Produto", txt(pchosen.product), key=f"prod_name_{pchosen.id}",
                                      placeholder="ex.: Projetor XGIMI Horizon Ultra")
                pscope = st.radio("Vale para", ["Só este lançamento", "Toda compra desta loja com este valor"],
                                  index=1 if pd.notna(pchosen.total_installments) else 0, horizontal=True)
                pstore = st.text_input("Loja (nome que identifica)", store_pattern(txt(pchosen.description)),
                                       key=f"prod_store_{pchosen.id}",
                                       help="Duas primeiras palavras da descrição. Acentos e maiúsculas não importam.")
                if st.form_submit_button("Vincular produto") and pname.strip():
                    with session() as conn:
                        if pscope == "Só este lançamento":
                            n = add_product_link(conn, pname, tx_id=pchosen.id)
                        else:
                            n = add_product_link(conn, pname, pattern=pstore, amount=pchosen.value)
                    st.session_state["fix_msg"] = (f"**{pname.strip()}** vinculado a {n} lançamento(s), agora em "
                                                   "Compras online.")
                    st.rerun()
    with session() as conn:
        plinks = pd.read_sql("SELECT l.id, l.product, COALESCE(l.pattern, 'lançamento único') AS loja, l.amount, "
                             "(SELECT COUNT(*) FROM transactions t WHERE t.product = l.product) AS lançamentos "
                             "FROM product_links l ORDER BY l.id", conn)
    if not plinks.empty:
        with st.expander(f"Produtos vinculados ({len(plinks)})", icon=":material/inventory_2:"):
            visual.listing(plinks.drop(columns="id").rename(columns={"product": "produto", "amount": "valor"})
                         .style.format({"valor": lambda v: "" if pd.isna(v) else brl(v)}),
                         title="{produto}", value="{valor}", sub=["{loja}", "{lançamentos} lançamentos"], icon=("icon", "inventory_2"), use_container_width=True, hide_index=True)
            with st.form("delete_product_link"):
                opts = {f"{r.product} · {r.loja}": r.id for r in plinks.itertuples()}
                rmp = st.selectbox("Apagar vínculo", ["—"] + list(opts))
                if st.form_submit_button("Apagar") and rmp != "—":
                    with session() as conn:
                        delete_product_link(conn, opts[rmp])
                    st.session_state["fix_msg"] = f"Vínculo **{rmp}** apagado; lançamentos voltaram à categoria das regras."
                    st.rerun()

    with session() as conn:
        mine = pd.read_sql("SELECT pattern, category, created_at FROM user_rules ORDER BY created_at DESC", conn)
    if not mine.empty:
        with st.expander(f"Minhas regras ({len(mine)})", icon=":material/rule:"):
            visual.listing(mine.rename(columns={"pattern": "nome", "category": "categoria", "created_at": "criada em"}),
                         title="{nome}", sub=["{categoria}", "criada em {criada em}"], icon=("category", "{categoria}"), use_container_width=True, hide_index=True)
            # em form: escolher a regra não recarrega a página (senão o expander fecha e esconde o botão)
            with st.form("delete_rule"):
                rm = st.selectbox("Apagar regra", ["—"] + mine["pattern"].tolist())
                if st.form_submit_button("Apagar") and rm != "—":
                    with session() as conn:
                        delete_rule(conn, rm)
                    st.session_state["fix_msg"] = f"Regra **{rm}** apagada; lançamentos voltaram às regras padrão."
                    st.rerun()

# ------------------------------------------------------------------ Entradas
elif page == "Entradas":
    st.title("Entradas")
    inc = analytics.income(df)
    if inc.empty:
        st.info("Nenhuma entrada registrada ainda.")
        st.stop()
    months = sorted(inc["month"].unique())
    left, right = st.columns(2, gap="medium")
    with left, st.container(border=True, key="en_resumo"):
        sel = st.select_slider("Período", options=months, value=(months[max(0, len(months) - 6)], months[-1]),
                               format_func=month_name, key="inc_period")
        win = inc[(inc["month"] >= sel[0]) & (inc["month"] <= sel[1])]
        n_months = max(1, win["month"].nunique())
        total_in = float(win["amount"].sum())
        visual.hero(f"Entradas em {month_name(sel[0]).lower()}" if sel[0] == sel[1] else
                    f"Entradas de {month_name(sel[0]).lower()} a {month_name(sel[1]).lower()}", brl(total_in),
                    f"média de {brl(total_in / n_months)} por mês · {len(win)} lançamento{'s' if len(win) != 1 else ''}")
        visual.scope("Só o que entrou na conta: salário, mesada, vendas e outras entradas. Não conta transferência "
                     "entre suas contas, resgates nem estornos. O período muda tudo nesta tela, menos “Vendas a "
                     "receber”.")
    by_cat = win.groupby("category")["amount"].agg(["sum", "count"]).sort_values("sum", ascending=False)
    with right, st.container(border=True, key="en_rank"):
        st.html('<p class="pf-eyebrow" style="margin-bottom:.5rem">De onde veio</p>')
        if by_cat.empty:
            st.caption("Sem entradas neste período.")
        else:
            visual.bars([{"label": c, "value": float(v), "text": brl(v), "sub": f"{100 * v / total_in:.0f}%" if total_in else "",
                          "icon": "payments", "kind": "icon"} for c, v in by_cat["sum"].items()], color=C_IN)

    st.subheader("Entradas por mês")
    folded, cmap = fold_categories(win, "category", "amount")
    agg = folded.groupby(["month", "category"], as_index=False)["amount"].sum()
    agg["mes_txt"] = agg["month"].map(month_name)
    agg["valor_txt"] = agg["amount"].map(brl)
    fig = px.bar(agg, x="month", y="amount", color="category", color_discrete_map=cmap,
                 category_orders={"category": list(cmap)}, labels={"month": "", "amount": "", "category": ""},
                 custom_data=["mes_txt", "valor_txt"])
    fig.update_traces(hovertemplate="%{customdata[0]}<br>%{customdata[1]}<extra>%{fullData.name}</extra>")
    st.plotly_chart(style(fig, 340), use_container_width=True)
    with st.expander("Por tipo de entrada, com média por mês (para conferir)", icon=":material/table_rows:"):
        by_cat["média/mês"] = by_cat["sum"] / n_months
        visual.table(by_cat.rename(columns={"sum": "total", "count": "lançamentos"}).reset_index()
                     .rename(columns={"category": "tipo"}).style.format({"total": brl, "média/mês": brl}),
                     use_container_width=True, hide_index=True)

    st.subheader("Lançamentos")
    f1, f2 = st.columns([3, 2])
    cats = f1.multiselect("Tipos", sorted(win["category"].unique()), key="inc_cats", placeholder="Todos os tipos")
    q = f2.text_input("Buscar descrição ou quem enviou", key="inc_q")
    show = win if not cats else win[win["category"].isin(cats)]
    if q:
        show = show[(show["description"].fillna("") + " " + show["counterparty"].fillna(""))
                    .str.contains(q, case=False, regex=False)]
    visual.scope(f"{len(show)} lançamento{'s' if len(show) != 1 else ''} · total {brl(show['amount'].sum())}")
    ordered = show.fillna({"counterparty": "", "description": ""}).sort_values("date", ascending=False)
    with st.container(border=True, key="en_lanc"):
        if msg := st.session_state.pop("fix_msg", None):
            st.success(msg)
        ledger_rows(ordered, "amount", "en")
    with st.expander("Ver como tabela (uma coluna por campo)", icon=":material/table_rows:"):
        visual.table(ordered.assign(institution=[paid_with(r) for r in ordered.itertuples()])[
                         ["date", "description", "counterparty", "category", "amount", "institution"]]
                     .rename(columns={"date": "data", "description": "descrição", "counterparty": "quem enviou",
                                      "category": "tipo", "amount": "valor", "institution": "entrou por"})
                     .style.format({"valor": brl, "data": lambda d: d.strftime("%d/%m/%Y")}, na_rep=""),
                     use_container_width=True, hide_index=True)

    # ---- vendas parceladas (ligadas ao módulo Empréstimos e vendas)
    with session() as conn:
        sales_sum, sales_up = analytics.sales_overview(conn)
    st.subheader("Vendas a receber")
    visual.scope("Posição de hoje: não muda com o período escolhido acima.")
    if sales_sum.empty:
        st.caption("Nenhuma venda parcelada ainda. Transforme uma entrada recorrente em venda logo abaixo.")
    else:
        m1, m2 = st.columns(2)
        m1.metric("Falta receber de vendas", brl(sales_sum["falta_receber"].sum()))
        m2.metric("Parcelas por vir", len(sales_up))
        visual.listing(sales_sum.assign(recebidas=lambda d: d["recebidas"].astype(str) + "/" + d["parcelas"].astype(str))
                     [["produto", "comprador", "recebidas", "faltam", "parcela", "falta_receber", "proxima", "ultima"]]
                     .rename(columns={"recebidas": "parcelas recebidas", "parcela": "valor da parcela",
                                      "falta_receber": "falta receber", "proxima": "próxima", "ultima": "termina em"})
                     .style.format({"valor da parcela": brl, "falta receber": brl,
                                    "próxima": lambda d: "" if pd.isna(d) else d.strftime("%d/%m/%Y"),
                                    "termina em": lambda d: d.strftime("%m/%Y")}),
                     title="{produto}", value="{falta receber}", value_sub="faltam {faltam}", sub=["{comprador}", "{parcelas recebidas} recebidas", "parcela de {valor da parcela}", "próxima em {próxima}", "termina em {termina em}"], icon=("icon", "sell"), table="as vendas", use_container_width=True, hide_index=True)
        st.button("Dar baixa ou ver o detalhe em Empréstimos e vendas", icon=":material/arrow_forward:", type="tertiary",
                  on_click=goto, args=("Empréstimos e vendas",), key="en_go_vendas")
        with st.expander(f"Datas das próximas parcelas ({len(sales_up)})", icon=":material/event:"):
            visual.listing(sales_up.drop(columns="id").rename(columns={"valor": "valor a receber"})
                         .style.format({"valor a receber": brl, "vencimento": lambda d: d.strftime("%d/%m/%Y"),
                                        "atrasada": lambda v: "sim" if v else ""}),
                         title="{produto}", value="{valor a receber}", icon=("icon", "event"), badge=lambda row: visual.badge("Atrasada", "late") if row.get("atrasada") else "", use_container_width=True, hide_index=True)

    st.subheader("Cadastrar e ajustar")
    if msg := st.session_state.pop("inc_msg", None):
        st.success(msg)
    with st.expander("Transformar uma entrada recorrente em venda parcelada", icon=":material/sell:"):
        st.caption("Para uma entrada que se repete (ex.: alguém pagando um produto seu em parcelas). Cria a venda em "
                   "**Empréstimos e vendas**, dá baixa nos Pix já recebidos desse nome com o mesmo valor e deixa as "
                   "parcelas restantes como a receber, com data.")
        pickable = show[show["category"] != "Venda recebida"].sort_values("date", ascending=False).head(300)
        if pickable.empty:
            st.info("Nenhuma entrada disponível no filtro atual.")
        else:
            sel_lab = {f"{r.date:%d/%m/%Y} · {r.description} · {brl(r.amount)}": r for r in pickable.itertuples()}
            tx = sel_lab[st.selectbox("Entrada", list(sel_lab), key="isv_pick")]
            who = analytics.income_person({"counterparty": tx.counterparty, "description": tx.description})
            same = inc[(inc["amount"].round(2) == round(tx.amount, 2)) & (inc["category"] != "Venda recebida")
                       & (inc["description"].fillna("") + " " + inc["counterparty"].fillna(""))
                       .map(analytics._norm).str.contains(analytics._norm(who), regex=False)].sort_values("date")
            k = tx.id
            a, b = st.columns(2)
            isv_item = a.text_input("O que foi vendido", key=f"isv_item_{k}", placeholder="ex.: Projetor LG HU70LA")
            isv_person = b.text_input("Comprador", who, key=f"isv_person_{k}")
            a, b, c = st.columns(3)
            isv_n = a.number_input("Nº total de parcelas", min_value=1, step=1, value=10, key=f"isv_n_{k}")
            isv_amt = b.number_input("Valor da parcela (R$)", min_value=0.0, step=10.0, value=float(tx.amount), key=f"isv_amt_{k}")
            isv_first = c.date_input("1º vencimento", value=(same["date"].iloc[0] if len(same) else tx.date).date(), key=f"isv_first_{k}",
                                     help="Padrão: a data do Pix mais antigo com esse nome e valor.", format="DD/MM/YYYY")
            isv_pix = st.text_input("Nome no Pix (para baixar as próximas parcelas sozinho)", who, key=f"isv_pix_{k}")
            end = (pd.Timestamp(isv_first) + pd.DateOffset(months=int(isv_n) - 1)).date()
            got = same[same["date"].dt.date >= isv_first]
            st.info(f"{len(got)} Pix igual(is) já recebido(s) serão baixados · faltam **{max(0, int(isv_n) - len(got))}** "
                    f"parcela(s) de **{brl(isv_amt)}** · última em **{end:%m/%Y}** · total da venda {brl(isv_amt * isv_n)}.".replace("$", "\\$"))
            if st.button("Criar venda", type="primary", key=f"isv_save_{k}",
                         disabled=not isv_item.strip() or not isv_person.strip() or isv_amt <= 0):
                with session() as conn:
                    _, n_paid = analytics.register_sale_from_income(conn, tx.id, isv_item, int(isv_n), isv_amt, isv_first,
                                                                    isv_person.strip(), isv_pix.strip())
                st.session_state["inc_msg"] = (f"Venda **{isv_item.strip()}** criada: {n_paid} parcela(s) já baixada(s), "
                                               f"termina em {end:%m/%Y}. Veja em Empréstimos e vendas.")
                st.rerun()

# ------------------------------------------------------------------ Cartão
elif page == "Cartão":
    st.title("Cartão")
    with session() as conn:
        cards = analytics.card_summary(conn)
    if OWNER:
        cards = [c for c in cards if (c["owner"] or OWNER_DEFAULT) == OWNER]
    if not cards:
        st.info("Nenhum cartão conectado.")
        st.stop()
    for ci, card in enumerate(cards):
        st.subheader(f"{visual.institution_name(card['institution'])} · {card['name']}"
                     + (f" · {card['owner']}" if card["owner"] else ""))
        with st.container(border=True, key=f"ct_resumo_{ci}"):
            h_, d_ = st.columns([3, 2], gap="medium")
            with h_:
                visual.hero("Fatura aberta (estimativa)", brl(card["open_bill_estimate"]),
                            "Usado menos as parcelas dos próximos meses. A fatura real só fecha no vencimento.")
                if card.get("last_due"):
                    visual.scope(f"Última fatura registrada: vencimento em {date.fromisoformat(card['last_due'][:10]):%d/%m/%Y}. "
                                 "A data da próxima não vem do banco.")
            with d_:
                if card["limit"]:
                    frac = min(1.0, (card["used"] or 0) / card["limit"])
                    visual.progress(frac, f"{(card['used'] or 0) / card['limit']:.0%} do limite comprometido")
                visual.rows([visual.row_html("", "Limite", "", brl(card["limit"])),
                             visual.row_html("", "Usado", "inclui as parcelas futuras", brl(card["used"])),
                             visual.row_html("", "Parcelas futuras", "já contratadas", brl(card["future_installments"])),
                             visual.row_html("", "Disponível", "", brl(card["available"]))])
        left, right = st.columns(2)
        with left:
            st.markdown("**Parcelas já contratadas por mês**")
            if not card["ahead"].empty:
                fig = px.bar(card["ahead"].assign(txt=card["ahead"]["value"].map(brl)), x="month", y="value",
                             custom_data=["txt"], labels={"month": "", "value": ""})
                fig.update_traces(marker_color=C_OUT, hovertemplate="%{customdata[0]}<extra></extra>")
                st.plotly_chart(style(fig, 280), use_container_width=True)
            else:
                st.caption("Nenhuma parcela futura.")
        with right:
            st.markdown("**Faturas fechadas (últimos 12 meses, por vencimento)**")
            if not card["bills"].empty:
                fig = px.bar(card["bills"].assign(txt=card["bills"]["total"].map(brl)), x="due_date", y="total",
                             custom_data=["txt"], labels={"due_date": "", "total": ""})
                fig.update_traces(marker_color=OTHER, hovertemplate="vencimento %{x|%d/%m/%Y}<br>%{customdata[0]}<extra></extra>")
                st.plotly_chart(style(fig, 280, month_axis=False), use_container_width=True)
        oi = card["open_installments"]
        if not oi.empty:
            st.markdown("**Compras parceladas em aberto**")
            visual.listing(oi.sort_values("to_pay", ascending=False)[
                ["date", "description", "installment_number", "total_installments", "value", "remaining", "to_pay"]]
                .rename(columns={"date": "última parcela", "description": "compra", "installment_number": "parcela",
                                 "total_installments": "de", "value": "valor parcela", "remaining": "faltam",
                                 "to_pay": "a pagar"})
                .style.format({"valor parcela": brl, "a pagar": brl, "última parcela": lambda d: d.strftime("%d/%m/%Y"),
                               "parcela": "{:.0f}", "de": "{:.0f}"}), title="{compra}", value="{a pagar}", value_sub="faltam {faltam}", sub=["parcela {parcela} de {de}", "{valor parcela} por mês", "última cobrada em {última parcela}"], icon=("icon", "credit_card"), table="as compras parceladas", use_container_width=True, hide_index=True)

# ------------------------------------------------------------------ Previsão
elif page == "Previsão":
    st.title("Previsão")
    with st.container(border=True, key="pv_resumo"):
        h_, f_ = st.columns([3, 2], gap="medium")
        with f_:
            n = st.slider("Meses à frente", 3, 12, 6)
            visual.scope("Muda o gráfico e a tabela. O número ao lado é sempre o do próximo mês.")
        with session() as conn:
            fc = analytics.forecast(conn, n)
        with h_:
            if fc.empty:
                visual.hero("Sobra prevista", "—")
            else:
                f0 = fc.iloc[0]
                visual.hero(f"Sobra prevista em {month_name(f0['month']).lower()} (estimativa)", brl(f0["Saldo previsto"]),
                            f"entradas previstas {brl(f0['Salário'] + f0['Benefícios (Flash)'] + f0['A receber (empréstimos)'])}"
                            f" − saídas previstas {brl(f0['Saídas previstas'])}")
                visual.scope("É uma estimativa pelo histórico: pode não se confirmar. Veja abaixo como cada parte é "
                             "calculada.")
    visual.notes("Como a previsão é calculada", [
        "**Salário**: mediana dos últimos 3 meses fechados.",
        "**Recorrentes**: Pix e assinaturas detectados.",
        "**Cemig/Cesama**: mesmo mês do ano anterior (ou média de 3 meses).",
        "**Parcelas**: compras parceladas já feitas.",
        "**Variáveis**: mediana do resto dos gastos.",
        "**A receber**: parcelas combinadas dos empréstimos.",
        "**Benefícios (Flash)**: rendas fora do banco, cadastradas abaixo.",
        "A mesada não entra (visão conservadora).",
    ], expanded=False)
    out_cols = ["Recorrentes", "Cemig + Cesama", "Parcelas cartão", "Empréstimo (banco)", "Variáveis (média)"]
    long = fc.melt("month", value_vars=out_cols, var_name="Componente", value_name="Valor")
    fig = px.bar(long, x="month", y="Valor", color="Componente",
                 color_discrete_map={c: SERIES[j] for c, j in zip(out_cols, (0, 1, 3, 4, 6))}, labels={"month": "", "Valor": ""})
    fig.add_scatter(x=fc["month"], y=fc["Salário"] + fc["Benefícios (Flash)"] + fc["A receber (empréstimos)"], mode="lines+markers",
                    name="Entradas previstas", line=dict(color=C_IN, width=2), marker=dict(size=8))
    st.plotly_chart(style(fig, 380), use_container_width=True)
    money = [c for c in fc.columns if c != "month"]
    visual.listing(fc.assign(month=fc["month"].map(month_name)).rename(columns={"month": "mês"})
                 .style.format({c: brl for c in money}), title="{mês}", value="{Saldo previsto}", value_sub="sobra prevista", icon=("icon", "calendar_month"), table="a previsão", use_container_width=True, hide_index=True)

    st.subheader("Rendas fora do banco")
    st.caption("Valores fixos que o Open Finance não enxerga (ex.: benefícios no Flash). Entram só na previsão; "
               "o histórico mostra apenas o que de fato caiu na conta.")
    with session() as conn:
        oi = pd.read_sql("SELECT id, name, amount, day, category, active, note FROM other_income ORDER BY day", conn)
    if not oi.empty:
        visual.listing(oi.drop(columns="id").rename(columns={"name": "nome", "amount": "valor/mês", "day": "dia",
                                                           "category": "categoria", "active": "ativa", "note": "obs"})
                     .style.format({"valor/mês": brl}), title="{nome}", value="{valor/mês}", value_sub="por mês", sub=["dia {dia}", "{categoria}", "{obs}"], icon=("icon", "payments"), badge=lambda row: visual.badge("Entra na previsão", "ok") if row.get("ativa") in ("1", "True") else visual.badge("Desativada", "info"), table="as rendas", use_container_width=True, hide_index=True)
    with st.expander("Cadastrar ou atualizar uma renda", icon=":material/add_circle:"), st.form("other_income"):
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
    fmt = lambda f, suf="": (lambda v: "—" if pd.isna(v) else format(v, f).replace(".", ",") + suf)  # noqa: E731  (conta sem detalhe não quebra a tabela)

    def last_bill_hero(bills: pd.DataFrame, nome: str, key: str) -> None:
        """Conta mais recente como número dominante da aba, com vencimento e estado."""
        r = bills.iloc[-1]
        due = date.fromisoformat(r["due_date"][:10]) if isinstance(r["due_date"], str) and r["due_date"] else None
        paid = isinstance(r["paid_date"], str) and bool(r["paid_date"]) and r["paid_date"][:10] <= date.today().isoformat()
        note = []
        if due:
            state = (visual.badge("Paga", "ok") if paid else visual.due_badge(due, date.today()) if due >= date.today()
                     else visual.badge("Pagamento não registrado", "info"))
            note.append(f"vencimento {due:%d/%m/%Y} {state}")
        if pd.notna(r.get("amount_var")):
            note.append(f"{r['amount_var']:+.0f}% em relação à conta anterior")
        with st.container(border=True, key=key):
            visual.hero(f"Conta de {month_name(r['ref_month']).lower()} · {nome}", brl(r["amount"]), " · ".join(note))

    tab_e, tab_a = st.tabs([f":material/bolt: Energia ({', '.join(PROVIDER_NAMES[p] for p in energia)})", ":material/water_drop: Água (Cesama)"])

    with tab_e:
        if len(energia) > 1:  # mais de uma distribuidora com contas (ex.: mudança de cidade)
            prov_e = st.radio("Distribuidora", list(energia), format_func=PROVIDER_NAMES.get, horizontal=True)
            cem = energia[prov_e]
        if not cem.empty:
            dist = PROVIDER_NAMES[cem["provider"].iloc[0]]
            last12 = cem.tail(12)
            last_bill_hero(cem, dist, "cc_energia")
            st.html('<p class="pf-eyebrow">Últimos 12 meses</p>')
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Gasto em 12 meses", brl(last12["amount"].sum()), f"média {brl(last12['amount'].mean())}/mês",
                      delta_color="off")
            c2.metric("Consumo em 12 meses", f"{last12['consumption'].sum():,.0f} kWh".replace(",", "."),
                      f"média {last12['consumption'].mean():.0f} kWh/mês", delta_color="off")
            c3.metric("kWh puro (sem impostos)", brl(last12["energy_untaxed"].sum() / last12["consumption"].sum()),
                      f"tarifa da {dist}", delta_color="off")
            c4.metric("kWh cheio (tudo incluído)", brl(last12["amount"].sum() / last12["consumption"].sum()),
                      "impostos + iluminação + taxas", delta_color="off")
            c5.metric("Impostos", f"{100 * last12['taxes_total'].sum() / last12['amount'].sum():.1f}% da conta".replace(".", ","),
                      f"iluminação pública: {100 * last12['public_lighting'].sum() / last12['amount'].sum():.1f}%".replace(".", ","),
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
                                         labels={"ref_month": "", "R$": ""})), use_container_width=True)

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
            visual.listing(pd.DataFrame({
                "Mês": t["ref_month"].map(month_name), "Total": t["amount"].map(brl), "vs mês ant.": t["amount_var"].map(pct),
                "kWh": t["consumption"].round().astype("Int64"), "kWh vs ant.": t["cons_var"].map(pct),
                "kWh/dia": t["daily"].map(fmt(".1f")), "Puro R$/kWh": t["tariff_untaxed"].map(fmt(".4f")),
                "Cheio R$/kWh": t["price_full"].map(fmt(".2f")), "ICMS": t["icms"].map(brl),
                "PIS+COFINS": (t["pis"].fillna(0) + t["cofins"].fillna(0)).map(brl),
                "Impostos %": t["taxes_pct"].map(fmt(".1f", "%")), "Iluminação": t["public_lighting"].map(brl),
                "Iluminação %": t["lighting_pct"].map(fmt(".1f", "%")), "Bandeira": t["flag"],
                "Multas/créditos": t["other_fees"].map(lambda v: brl(v) if v else ""),
                "Vencimento": t["due_date"]}), title="{Mês}", value="{Total}", value_sub="{vs mês ant.} vs mês anterior", sub=["{kWh} kWh", "consumo {kWh vs ant.} vs mês anterior", "{kWh/dia} kWh por dia", "R$ {Cheio R$/kWh} por kWh, com tudo", "impostos {Impostos %}", "iluminação {Iluminação}", "bandeira {Bandeira}", "multas/créditos {Multas/créditos}", "vence em {Vencimento}"], icon=("icon", "bolt"), table="a energia mês a mês", use_container_width=True, hide_index=True)

            with st.expander("Detalhe de uma fatura", icon=":material/receipt_long:"):
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
            last_bill_hero(ces, "Cesama", "cc_agua")
            st.html('<p class="pf-eyebrow">Últimos 12 meses</p>')
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Gasto em 12 meses", brl(last12["amount"].sum()), f"média {brl(last12['amount'].mean())}/mês",
                      delta_color="off")
            c2.metric("Consumo em 12 meses", f"{last12['consumption'].sum():.0f} m³",
                      f"média {last12['consumption'].mean():.1f} m³/mês".replace(".", ","), delta_color="off")
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
            st.caption(esc(f"No histórico, o consumo ficou entre {ces['consumption'].min():.0f} e {ces['consumption'].max():.0f} m³ "
                           f"por mês e a conta entre {brl(ces['amount'].min())} e {brl(ces['amount'].max())}."))
            st.subheader("Mês a mês")
            t = ces.iloc[::-1]
            visual.listing(pd.DataFrame({
                "Mês": t["ref_month"].map(month_name), "Total": t["amount"].map(brl), "vs mês ant.": t["amount_var"].map(pct),
                "m³": t["consumption"].round().astype("Int64"), "R$/m³": t["price_full"].map(brl),
                "Emissão": t["issue_date"], "Vencimento": t["due_date"], "Pago em": t["paid_date"],
                "Obs.": t["note"].fillna("")}), title="{Mês}", value="{Total}", value_sub="{vs mês ant.} vs mês anterior", sub=["{m³} m³", "{R$/m³} por m³", "emitida em {Emissão}", "vence em {Vencimento}", "paga em {Pago em}", "{Obs.}"], icon=("icon", "water_drop"), table="a água mês a mês", use_container_width=True, hide_index=True)

    st.subheader("Adicionar conta")
    with st.expander("Enviar PDF da fatura", icon=":material/upload_file:"):
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
                st.caption(esc(why.read_text(encoding="utf-8").splitlines()[0] if why.exists() else p.name))

    from financas.importers import utilities
    with st.expander("Lançar ou completar uma conta à mão", icon=":material/edit:", expanded="bill_msg" in st.session_state):
        for kind, msg in st.session_state.pop("bill_msg", []):
            getattr(st, kind)(esc(msg))
        p = st.radio("Fornecedor", ["cemig", "cesama"], horizontal=True,
                     format_func={"cemig": "Cemig", "cesama": "Cesama"}.get)
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
elif page == "Empréstimos e vendas":
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
        st.session_state.setdefault(f"{key}_pct", 1.0)
        st.session_state.setdefault(f"{key}_comp", default_comp)
        pct = c1.number_input("Taxa (%)", min_value=0.0, step=0.1, format="%.3f", key=f"{key}_pct")
        per = c2.radio("Período da taxa", ["ao mês", "ao ano"], horizontal=True, key=f"{key}_per")
        comp = c3.radio("Cálculo dos juros", ["simples", "composto"],
                        horizontal=True, key=f"{key}_comp",
                        help="Simples: rende só sobre o valor emprestado. Composto: juros sobre juros.")
        return pct / 100, ("mes" if per == "ao mês" else "ano"), comp

    def hp12c_help() -> None:
        with st.popover("Como conferir na HP 12C", icon=":material/calculate:", use_container_width=True):
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

**Parcelas iguais (regra do painel: juros sobre o valor total)**
Compostos: `n` = meses até o **último** vencimento · `i` = taxa ao mês · `PV` = −valor emprestado · `FV` → **total** a receber;
parcela = total ÷ nº de parcelas. Ex.: 20.000 a 14% a.a., 12 parcelas → total 22.800, parcela 1.900.
Simples: total = valor × (1 + taxa × meses até o último vencimento); parcela = total ÷ nº de parcelas.
*(Não é a Tabela Price: aqui os juros não diminuem conforme as parcelas são pagas.)*

**Com recebimentos no meio:** o painel calcula o saldo até a data do recebimento, abate o valor
(**primeiro juros, depois principal**) e recomeça dali. Na HP: calcule o saldo, subtraia o recebimento
e use o resultado como novo `PV` até a próxima data. A tabela *Memória de cálculo* mostra cada passo.
""")

    def schedule_summary(label: str, sched: list, principal: float, extra: str = "", cost: str = "Juros") -> None:
        """Cartão de resumo ao lado de um cadastro: total, parcela, juros e datas, calculados enquanto se preenche."""
        total = sum(x for _, x in sched)
        visual.hero(label, brl(total), extra)
        lines = [("Parcelas", f"{len(sched)}x de {brl(sched[0][1])}"), (cost, brl(total - principal)),
                 ("Primeira parcela", f"{sched[0][0]:%d/%m/%Y}"), ("Última parcela", f"{sched[-1][0]:%d/%m/%Y}")]
        if abs(sched[-1][1] - sched[0][1]) > 0.005:
            lines.insert(1, ("Última parcela (ajuste de centavos)", brl(sched[-1][1])))
        visual.rows([visual.row_html("", k, "", v) for k, v in lines])

    def missing_hint(missing: list[str]) -> None:
        if missing:
            visual.scope("Para registrar, falta: " + ", ".join(missing) + ".")

    st.title("Empréstimos e vendas")
    today = date.today()

    # ---------- topo: o mesmo "A receber" da Visão geral, com a data de referência dentro do bloco
    with st.container(border=True, key="emp_topo"):
        h_, f_ = st.columns([3, 2], gap="medium")
        with f_:
            asof = st.date_input("Posição em", value=today, key="asof", format="DD/MM/YYYY",
                                 help="Só muda o cálculo na tela (juros acumulados até essa data). Nada é gravado.")
            visual.scope("Escolha uma data futura para simular quanto estará devendo. Vale para as abas de empréstimos "
                         "e de vendas.")
            hp12c_help()
        with session() as conn:
            loans = analytics.loan_status(conn, asof)
            sched = analytics.loan_schedule_open(conn, asof)
            pays = pd.read_sql("SELECT p.*, l.person FROM loan_payments p JOIN loans l ON l.id=p.loan_id "
                               "ORDER BY p.date DESC", conn)
            people = [r["name"] for r in conn.execute("SELECT name FROM people ORDER BY name COLLATE NOCASE")]
        all_open = loans[loans["closed"] == 0] if not loans.empty else loans
        rec_total = loans["remaining"].sum() if not loans.empty else 0
        late_total = float(all_open["overdue"].sum()) if not all_open.empty else 0.0
        by_kind = all_open.groupby("kind")["remaining"].sum() if not all_open.empty else {}
        parts = [f"{nome} {brl(by_kind.get(k, 0))}" for k, nome in (("emprestimo", "empréstimos"), ("venda", "vendas"))
                 if by_kind.get(k, 0) > 0]
        with h_:
            visual.hero(f"A receber em {asof:%d/%m/%Y}" + ("" if asof == today else " (simulação)"), brl(rec_total),
                        (" + ".join(parts) or "nada em aberto")
                        + ("<br>" + visual.badge(f"{brl(late_total)} em atraso", "late") if late_total > 0.005 else ""))
            visual.scope("Soma das abas de empréstimos e de vendas, com juros até a data. Não inclui o que você deve ao "
                         "banco.")
    if asof != today:
        st.warning(f"Simulação: valores calculados para **{asof:%d/%m/%Y}**, não para hoje.")
    # ---------- fila de Pix a conferir: o painel sugere, quem decide é o usuário
    with session() as conn:
        queue = analytics.loan_pix_queue(conn, today)
        n_ignored = len(analytics.ignored_loan_pix(conn))
    if queue:
        st.subheader(f"Pix a conferir ({len(queue)})")
        visual.scope("Pix que já entraram na conta e podem ser pagamento de quem deve a você. O painel só sugere: "
                     "confirme ou ignore. Nenhum dinheiro é movimentado.")
        with st.container(border=True, key="emp_fila"):
            for i, q in enumerate(queue[:20]):
                if i:
                    st.html('<hr class="pf-sep">')
                a_, b_, c_ = st.columns([6, 1.6, 1.4], vertical_alignment="center")
                a_.html(visual.row_html(visual.mark("help", "icon"), f"Pode ser pagamento de {q['person']}",
                                        f"{q['date']:%d/%m/%Y} · de {q['from'] or 'remetente não informado'} · {q['why']}",
                                        brl(q["amount"])))
                if b_.button("Confirmar", key=f"emp_fq_ok_{i}", disabled=VIEW is not None, use_container_width=True):
                    pix_confirm_dialog(q)
                if c_.button("Ignorar", key=f"emp_fq_no_{i}", type="tertiary", disabled=VIEW is not None,
                             use_container_width=True, help="Tira este Pix da fila. Ele continua nos lançamentos."):
                    with session() as conn:
                        analytics.ignore_loan_pix(conn, q["tx_id"])
                    st.rerun()
            if len(queue) > 20:
                visual.scope(f"Aparecem os 20 mais recentes de {len(queue)}.")
    if n_ignored:
        if st.button(f"Rever {_plural(n_ignored, 'Pix ignorado', 'Pix ignorados')}", key="emp_fq_rever", type="tertiary",
                     icon=":material/undo:", disabled=VIEW is not None,
                     help="Devolve à fila “Pix a conferir” os Pix que você ignorou."):
            with session() as conn:
                analytics.restore_ignored_loan_pix(conn)
            st.rerun()
    if msg := st.session_state.pop("emp_msg", None):
        st.success(msg)
    if not loans.empty:
        with st.container(border=True, key="emp_ficha"):
            a_, b_ = st.columns([4, 1.5], vertical_alignment="bottom")
            who_f = a_.selectbox("Ficha por pessoa", sorted(loans["person"].unique(), key=str.lower), key="emp_ficha_quem",
                                 help="Saldo, empréstimos e vendas, parcelas em aberto e linha do tempo de uma pessoa, "
                                      "inclusive de quem já quitou.")
            if b_.button("Abrir ficha", icon=":material/person_search:", key="emp_ficha_abrir", use_container_width=True):
                person_dialog(who_f, asof)
    tab_rec, tab_sales, tab_debt = st.tabs(["Empréstimos (a receber)", "Vendas (a receber)", "Que eu devo (banco)"])

    # ================================================== A RECEBER
    with tab_rec:
        sales = loans[loans["kind"] == "venda"]
        sales_sched = sched[sched["loan_id"].isin(sales["id"])]
        sales_pays = pays[pays["loan_id"].isin(sales["id"])]
        loans = loans[loans["kind"] == "emprestimo"]
        sched = sched[sched["loan_id"].isin(loans["id"])]
        pays = pays[pays["loan_id"].isin(loans["id"])]
        if not loans.empty:
            open_ = loans[loans["closed"] == 0]
            c1, c2, c3 = st.columns(3)
            c1.metric("A receber de empréstimos (com juros até a data)", brl(open_["remaining"].sum()))
            c2.metric("Em atraso", brl(open_["overdue"].sum()))
            c3.metric("Pessoas com saldo", open_["person"].nunique())
            if not open_.empty:
                st.subheader("Quem me deve")
                visual.scope("“Dar baixa” só registra um valor que você já recebeu: o painel não movimenta dinheiro.")
                with st.container(border=True, key="emp_pessoas"):
                    by_person = open_.groupby("person")["remaining"].sum().sort_values(ascending=False)
                    for i, (person, rem) in enumerate(by_person.items()):
                        if i:
                            st.html('<hr class="pf-sep">')
                        mine = open_[open_["person"] == person]
                        late = float(mine["overdue"].sum())
                        nxt = sched[sched["person"] == person].sort_values("due_date")
                        sub = (f"{len(mine)} empréstimo{'s' if len(mine) != 1 else ''} em aberto · " +
                               (f"próximo vencimento {date.fromisoformat(nxt.iloc[0].due_date):%d/%m/%Y}" if not nxt.empty
                                else "sem data combinada"))
                        a_, f_, b_ = st.columns([5, 1.7, 1.6], vertical_alignment="center")
                        a_.html(visual.row_html(visual.mark("person", "icon"), person, sub, brl(rem), "falta receber",
                                                badge_html=visual.badge(f"{brl(late)} em atraso", "late")
                                                if late > 0.005 else "", badge_below=True))
                        if f_.button("Ver ficha", key=f"emp_fi_{i}", icon=":material/person_search:", use_container_width=True,
                                     help=f"Histórico completo de {person}"):
                            person_dialog(person, asof)
                        if b_.button("Dar baixa", key=f"emp_rc_{i}", disabled=VIEW is not None, use_container_width=True):
                            receive_dialog({"id": int(mine["id"].iloc[0]), "directed": False,
                                            "amount": float(nxt.iloc[0].remaining) if not nxt.empty else 0.0,
                                            "head": f"**{person}** · falta receber {brl(rem)}"})
            if not sched.empty:
                st.subheader("Quando vou receber")
                with st.container(border=True, key="emp_agenda"):
                    visual.rows([visual.row_html(
                        visual.mark("handshake", "icon", small=True), r.person,
                        f"vencimento {date.fromisoformat(r.due_date):%d/%m/%Y} · parcela de {brl(r.amount)}",
                        brl(r.remaining), "em aberto", badge_html=visual.due_badge(date.fromisoformat(r.due_date), asof))
                        for r in sched.sort_values("due_date").itertuples()])
            with session() as conn:
                res = analytics.loan_results(conn, asof)
            if not res.empty:
                st.subheader("Resultado por empréstimo")
                visual.scope("Juros já recebidos contra os previstos e pontualidade das parcelas vencidas, até a data "
                             "escolhida. No empréstimo parcelado o juro vem na mesma proporção em todas as parcelas "
                             "(parcela = total ÷ n).")
                with st.container(border=True, key="emp_result"):
                    visual.rows([visual.row_html(
                        visual.mark("percent", "icon"),
                        f"{r.person} · {brl(r.principal)} em {r.date:%d/%m/%Y}", result_text(r),
                        brl(r.interest_received), f"de {brl(r.interest_expected)} em juros",
                        badge_html=(visual.badge("Quitado", "ok") if r.done else
                                    visual.badge(_plural(r.late_open, "parcela vencida em aberto",
                                                         "parcelas vencidas em aberto"), "late") if r.late_open else ""),
                        badge_below=True) for r in res.sort_values("date", ascending=False).itertuples()])
            with session() as conn:
                tl_person, tl_total = analytics.loan_timeline(conn, asof)
            if not tl_person.empty:
                st.subheader("Evolução do que tenho a receber (empréstimos parcelados)")
                folded, cmap = fold_categories(tl_person, "person", "saldo")
                fig = px.bar(folded.groupby(["month", "person"], as_index=False)["saldo"].sum(), x="month", y="saldo",
                             color="person", color_discrete_map=cmap, labels={"month": "", "saldo": "", "person": ""})
                fig.add_scatter(x=tl_total["month"], y=tl_total["emprestado"], mode="lines+markers", name="Total emprestado (acum.)",
                                line=dict(color=SERIES[6], width=2), marker=dict(size=7))
                fig.update_layout(barmode="stack")
                st.plotly_chart(style(fig, 340), use_container_width=True)
                visual.notes("Como ler o gráfico", [
                    "**Barras**: quanto cada pessoa ainda deve naquele mês, com juros.",
                    "**Linha**: total já emprestado. Barra acima da linha = juros a receber; abaixo = parte já paga.",
                    "Empréstimos sem data de retorno não entram. O último mês usa a data escolhida em *Posição em*.",
                ], expanded=False)
            with st.expander(f"Todos os empréstimos ({len(loans)}) — tabela para conferir", icon=":material/table_rows:"):
                show = loans.assign(taxa=[rate_txt(r.rate, r.rate_period, r.compounding) for r in loans.itertuples()],
                                    tipo=["parcelado" if s else "sem data combinada" for s in loans["scheduled"]],
                                    installments=[f"{int(v)}x" if pd.notna(v) else "—" for v in loans["installments"]])
                visual.table(show[["person", "date", "principal", "installments", "taxa", "tipo", "paid", "interest",
                                   "remaining", "overdue", "next_due", "note", "closed"]]
                             .rename(columns={"person": "pessoa", "date": "data", "principal": "valor",
                                              "installments": "parcelas", "paid": "recebido", "interest": "juros",
                                              "remaining": "falta", "overdue": "atrasado", "next_due": "próx. venc.",
                                              "note": "obs", "closed": "quitado"})
                             .style.format({"valor": brl, "recebido": brl, "juros": brl, "falta": brl,
                                            "atrasado": brl}), use_container_width=True, hide_index=True)
            if not pays.empty:
                with st.expander(f"Recebimentos registrados ({len(pays)})", icon=":material/receipt_long:"):
                    pays["como"] = pays.apply(lambda r: "direto no empréstimo" if r["directed"] else
                                              f"baixa {'dos mais recentes' if r['order_mode'] == 'recentes' else 'dos mais antigos'} primeiro", axis=1)
                    visual.listing(pays[["person", "date", "amount", "como", "note"]]
                                 .rename(columns={"person": "pessoa", "date": "data", "amount": "valor", "note": "obs"})
                                 .style.format({"valor": brl}), title="{pessoa}", value="{valor}", sub=["{data}", "{como}", "{obs}"], icon=("icon", "person"), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum empréstimo registrado.")

        st.subheader("Cadastrar e ajustar")
        # ---------------- memória de cálculo
        free_all = loans[(~loans["scheduled"]) & (loans["kind"] == "emprestimo")] if not loans.empty else loans
        if not free_all.empty:
            with st.expander("Memória de cálculo (para conferir na HP 12C)", icon=":material/calculate:"):
                lab = {f"{r.person} · {r.date} · {brl(r.principal)} · {rate_txt(r.rate, r.rate_period, r.compounding)}": r.id
                       for r in free_all.itertuples()}
                pick_l = lab[st.selectbox("Empréstimo", list(lab), key="memo_loan")]
                with session() as conn:
                    memo = analytics.loan_statement(conn, pick_l, asof)
                visual.notes("Como os juros são calculados", [
                    "**Juros simples**: principal em aberto × taxa × períodos.",
                    "**Juros compostos**: saldo × ((1 + taxa)^períodos − 1).",
                    "**Períodos**: meses de calendário completos + dias que sobram ÷ 30,4375 (taxa ao ano: meses ÷ 12).",
                    "Cada recebimento paga primeiro os juros, depois o principal.",
                ], expanded=False)
                visual.table(memo.style.format({"períodos": "{:.6f}", "juros": brl, "pago": brl, "saldo": brl}),
                             use_container_width=True, hide_index=True)

        # ---------------- simulador: nada é gravado
        with st.expander("Simular antes de emprestar (nada é gravado)", icon=":material/science:"):
            a, b = st.columns(2)
            sim_val = a.number_input("Valor a emprestar (R$)", min_value=0.0, step=100.0, value=1000.0, key="sim_val")
            sim_date = b.date_input("Data do empréstimo", value=today, format="DD/MM/YYYY", key="sim_date")
            s_rate, s_per, s_comp = rate_inputs("sim", "composto")
            a, b = st.columns(2)
            sim_n = a.number_input("Nº de parcelas", min_value=1, step=1, value=6, key="sim_n")
            sim_first = b.date_input("1º vencimento", value=(pd.Timestamp(sim_date) + pd.DateOffset(months=1)).date(),
                                     format="DD/MM/YYYY", key=f"sim_first_{sim_date.isoformat()}")
            sim_sched = (lo.make_schedule(sim_val, s_rate, s_per, s_comp, int(sim_n), sim_first, start=sim_date)
                         if sim_val > 0 else [])
            if sim_sched:
                sim_total = sum(x for _, x in sim_sched)
                m1, m2, m3 = st.columns(3)
                m1.metric("Você recebe no total", brl(sim_total))
                m2.metric(f"Parcela ({int(sim_n)}x)", brl(sim_sched[0][1]))
                m3.metric("Juros", brl(sim_total - sim_val))
                visual.scope(("Taxa: " + rate_equiv(s_rate, s_per, s_comp) + ". " if s_rate else "Sem juros. ")
                             + "Regra do painel: juros sobre o valor total pelo prazo todo; parcela = total ÷ nº de parcelas.")
                st.markdown("**Cronograma**")
                visual.rows([visual.row_html(visual.mark("event", "icon", small=True), f"Parcela {k + 1} de {int(sim_n)}",
                                             f"vencimento {due:%d/%m/%Y}", brl(amt))
                             for k, (due, amt) in enumerate(sim_sched)])
                cur_ym = today.strftime("%Y-%m")
                last_ym = sim_sched[-1][0].strftime("%Y-%m")
                span = (int(last_ym[:4]) - today.year) * 12 + int(last_ym[5:]) - today.month
                if span >= 1:
                    with session() as conn:
                        fc_sim = analytics.forecast(conn, months=min(span, 12))
                    delta: dict[str, float] = {}
                    for due, amt in sim_sched:
                        delta[due.strftime("%Y-%m")] = delta.get(due.strftime("%Y-%m"), 0.0) + amt
                    out_ym = sim_date.strftime("%Y-%m")
                    st.markdown("**Efeito na Previsão**")
                    lines = []
                    for ym, base in zip(fc_sim["month"], fc_sim["Saldo previsto"].astype(float)):
                        gain, out = delta.get(ym, 0.0), (sim_val if ym == out_ym else 0.0)
                        how = " · ".join(x for x in (f"sai o empréstimo de {brl(out)}" if out else "",
                                                     f"entra parcela de {brl(gain)}" if gain else "",
                                                     "" if out or gain else "sem efeito neste mês") if x)
                        lines.append(visual.row_html(visual.mark("calendar_month", "icon", small=True), month_name(ym),
                                                     f"sobra prevista hoje {brl(base)} · {how}", brl(base - out + gain),
                                                     "sobra com o empréstimo"))
                    visual.rows(lines)
                    visual.scope("Estimativa: usa a mesma conta da tela Previsão, que começa no mês que vem."
                                 + (f" O valor de {brl(sim_val)} sai neste mês, que não aparece na lista."
                                    if out_ym <= cur_ym else "")
                                 + (" A lista mostra só os próximos 12 meses." if span > 12 else ""))
                def sim_to_form():
                    ss = st.session_state
                    d0 = ss["sim_date"]
                    ss["ln_principal"], ss["ln_date"], ss["ln_n"] = ss["sim_val"], d0, ss["sim_n"]
                    ss["ln_how"] = "Em parcelas com data"
                    ss[f"ln_first_{d0.isoformat()}"] = ss.get(f"sim_first_{d0.isoformat()}")
                    for k in ("wi", "pct", "per", "comp"):
                        if f"sim_{k}" in ss:
                            ss[f"ln_{k}"] = ss[f"sim_{k}"]
                    ss["emp_msg"] = ("Valores da simulação copiados para “Novo empréstimo a uma pessoa”. Nada foi gravado: "
                                     "falta escolher a pessoa e registrar.")

                st.button("Usar estes valores no cadastro", icon=":material/arrow_downward:", key="sim_copy",
                          on_click=sim_to_form, help="Preenche “Novo empréstimo a uma pessoa” com esta simulação. "
                                                     "Nada é gravado até você registrar.")

        # ---------------- novo empréstimo
        with st.expander("Novo empréstimo a uma pessoa", icon=":material/add_circle:"):
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
                    st.session_state["sv_pending_person"] = name
                    st.rerun()

            if "ln_pending_person" in st.session_state:
                st.session_state["ln_person"] = st.session_state.pop("ln_pending_person")
            st.session_state.setdefault("ln_how", "Em parcelas com data")
            st.session_state.setdefault("ln_n", 1)
            form_, resumo_ = st.columns([3, 2], gap="large")
            with form_:
                visual.step(1, "Quem e quanto")
                a, b = st.columns([3, 1.4], vertical_alignment="bottom")
                person = a.selectbox("Pessoa", people, index=None, placeholder="Escolha uma pessoa já cadastrada",
                                     key="ln_person") or ""
                if b.button("Nova pessoa", key="ln_newbtn", icon=":material/person_add:", use_container_width=True):
                    new_person_dialog()
                a, b = st.columns(2)
                d = a.date_input("Data do empréstimo", key="ln_date", format="DD/MM/YYYY")
                principal = b.number_input("Valor emprestado (R$)", min_value=0.0, step=50.0, key="ln_principal")
                visual.step(2, "Juros")
                rate, period, comp = rate_inputs("ln", "simples")
                visual.step(3, "Devolução")
                how = st.segmented_control("Como a pessoa vai devolver", ["Em parcelas com data", "Sem data combinada"],
                                           key="ln_how", label_visibility="collapsed")
                no_sched = how == "Sem data combinada"
                sched_new: list = []
                if not no_sched:
                    a, b = st.columns(2)
                    n = a.number_input("Nº de parcelas", min_value=1, step=1, key="ln_n")
                    fkey = f"ln_first_{d.isoformat()}"
                    if st.session_state.get(fkey) is None:
                        st.session_state[fkey] = (pd.Timestamp(d) + pd.DateOffset(months=1)).date()
                    first = b.date_input("1º vencimento", key=fkey, format="DD/MM/YYYY",
                                         help="Padrão: 1 mês depois do empréstimo. Se for no mesmo dia, a 1ª parcela é uma "
                                              "entrada (sem juros).")
                    sched_new = lo.make_schedule(principal, rate, period, comp, int(n), first, start=d) if principal > 0 else []
                visual.step(4, "Detalhes (opcional)")
                note = st.text_input("Observação", key="ln_note", placeholder="ex.: conserto do carro")
                tx_opts = {"—": None} | {f"{r.date:%d/%m} · {r.description} · {r.counterparty or ''} · {brl(-r.amount)}": r.id
                                         for r in out_pix.itertuples()} if not out_pix.empty else {"—": None}
                tx_sel = st.selectbox("Pix de saída correspondente", list(tx_opts), key="ln_tx",
                                      help="Opcional. Liga o empréstimo ao Pix que você fez e tira esse Pix do cálculo de gastos.")
            with resumo_, st.container(border=True, key="ln_resumo"):
                if sched_new:
                    schedule_summary("Você vai receber no total", sched_new, principal,
                                     ("Taxa: " + rate_equiv(rate, period, comp) if rate else "Sem juros"))
                    visual.scope("Juros sobre o valor total pelo prazo todo; parcela = total ÷ nº de parcelas.")
                elif principal > 0 and no_sched:
                    visual.hero("Valor emprestado", brl(principal),
                                ("Taxa: " + rate_equiv(rate, period, comp)) if rate else "Sem juros combinados")
                    visual.scope("Sem data combinada: " + ("o saldo cresce com os juros até o dia em que a pessoa pagar. "
                                 if rate else "") + "Quando ela pagar, use “Quitar”, mais abaixo"
                                 + ("." if rate else ", para o painel descobrir a taxa."))
                else:
                    st.html('<p class="pf-eyebrow">Resumo</p>')
                    visual.scope("Informe o valor para ver aqui o total a receber, a parcela, os juros e as datas.")
            missing = ([] if person else ["escolher a pessoa"]) + ([] if principal > 0 else ["informar o valor emprestado"])
            missing_hint(missing)
            if st.button("Registrar empréstimo", type="primary", key="ln_save", disabled=bool(missing) or VIEW is not None):
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
                st.session_state["emp_msg"] = f"Empréstimo de {brl(principal)} a {person} registrado."
                st.rerun()

        open_loans = loans[loans["closed"] == 0] if not loans.empty else loans

        # ---------------- recebimento
        if not open_loans.empty:
            with st.expander("Lançar recebimento com prévia (ordem de abatimento ou empréstimo específico)", icon=":material/payments:"):
                st.caption("O valor abate os empréstimos da pessoa na ordem escolhida; se sobrar, passa para o próximo. "
                           "Recebimentos de vendas ficam na aba **Vendas**.")
                who_names = sorted(open_loans["person"].unique(), key=str.lower)
                a, b, c = st.columns(3)
                who = a.selectbox("Quem pagou", who_names, key="rc_who")
                rdate = b.date_input("Data do recebimento", key="rc_date", format="DD/MM/YYYY")
                ramt = c.number_input("Valor recebido (R$)", min_value=0.0, step=50.0, key="rc_amt")
                mine = open_loans[open_loans["person"] == who]
                mode = st.radio("Abater", ["Mais antigos primeiro", "Mais recentes primeiro", "Um empréstimo específico"],
                                horizontal=True, key="rc_mode")
                target = None
                if mode == "Um empréstimo específico":
                    lab = {f"{'Venda ' + (r.item or '') if r.kind == 'venda' else 'Empréstimo'} · {r.date} · {brl(r.principal)} · "
                           f"falta {brl(r.remaining)}": r.id for r in mine.itertuples()}
                    target = lab[st.selectbox("Qual empréstimo", list(lab), key="rc_target")]
                if ramt > 0:
                    with session() as conn:
                        ls, rs = analytics.load_loans(conn)
                    ref = int(mine["id"].iloc[0])
                    mine_item = dict(zip(mine["id"], mine["item"]))
                    hyp = lo.Receipt(10**9, target or ref, rdate, ramt, directed=target is not None,
                                     order="recentes" if mode.startswith("Mais recentes") else "antigas")
                    after = lo.replay(ls, rs + [hyp], max(asof, rdate))
                    before = lo.replay(ls, rs, max(asof, rdate))
                    ref_kind = next(l.kind for l in ls if l.id == (target or ref))
                    prev = pd.DataFrame([{"operação": f"{'Venda ' + (mine_item.get(l.id) or '') if l.kind == 'venda' else 'Empréstimo'}"
                                                       f" · {l.date} · {brl(l.principal)}", "falta hoje": before[l.id].balance(),
                                          "depois do recebimento": after[l.id].balance()}
                                         for l in ls if l.person == who and l.kind == ref_kind
                                         and before[l.id].balance() > lo.EPS])
                    st.markdown("**Como vai ficar**")
                    with st.container(border=True, key="rc_previa"):
                        visual.rows([visual.row_html(visual.mark("handshake", "icon", small=True), r["operação"],
                                                     f"falta hoje {brl(r['falta hoje'])}", brl(r["depois do recebimento"]),
                                                     "depois do recebimento") for r in prev.to_dict("records")])
                    sobra = ramt - sum(after[l.id].paid - before[l.id].paid for l in ls if l.person == who and l.kind == ref_kind)
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
                with st.expander("Quitar empréstimo sem data combinada (descobrir a taxa)", icon=":material/task_alt:"):
                    st.caption("Informe quanto ela pagou no total para encerrar. O programa calcula a taxa de juros "
                               "embutida e guarda no empréstimo.")
                    lab = {f"{r.person} · {r.date} · {brl(r.principal)} · falta {brl(r.remaining)}": r.id
                           for r in free.itertuples()}
                    qid = lab[st.selectbox("Empréstimo", list(lab), key="q_loan")]
                    a, b = st.columns(2)
                    qdate = a.date_input("Data da quitação", key="q_date", format="DD/MM/YYYY")
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

    # ================================================== VENDAS
    with tab_sales:
        sales_open = sales[sales["closed"] == 0] if not sales.empty else sales
        if not sales.empty:
            c1, c2, c3 = st.columns(3)
            c1.metric("A receber de vendas", brl(sales_open["remaining"].sum()))
            c2.metric("Em atraso", brl(sales_open["overdue"].sum()))
            c3.metric("Vendas em aberto", len(sales_open))
            if not sales_open.empty:
                st.subheader("Vendas em aberto")
                with st.container(border=True, key="emp_vendas"):
                    for i, r in enumerate(sales_open.sort_values("remaining", ascending=False).itertuples()):
                        if i:
                            st.html('<hr class="pf-sep">')
                        nxt = sales_sched[sales_sched["loan_id"] == r.id].sort_values("due_date")
                        sub = (r.item or "sem descrição") + (
                            f" · próximo vencimento {date.fromisoformat(nxt.iloc[0].due_date):%d/%m/%Y}" if not nxt.empty else "")
                        a_, f_, b_ = st.columns([5, 1.7, 1.6], vertical_alignment="center")
                        a_.html(visual.row_html(visual.mark("sell", "icon"), r.person, sub, brl(r.remaining), "falta receber",
                                                badge_html=visual.badge(f"{brl(r.overdue)} em atraso", "late")
                                                if r.overdue > 0.005 else "", badge_below=True))
                        if f_.button("Ver ficha", key=f"emp_fv_{i}", icon=":material/person_search:", use_container_width=True,
                                     help=f"Histórico completo de {r.person}"):
                            person_dialog(r.person, asof)
                        if b_.button("Dar baixa", key=f"emp_sv_{i}", disabled=VIEW is not None, use_container_width=True):
                            receive_dialog({"id": int(r.id), "amount": float(nxt.iloc[0].remaining) if not nxt.empty else 0.0,
                                            "head": f"**{r.person}** · venda: {r.item or 'sem descrição'} · falta {brl(r.remaining)}"})
            if not sales_sched.empty:
                st.subheader("Parcelas a receber")
                item_of = dict(zip(sales["id"], sales["item"]))
                with st.container(border=True, key="emp_vendas_agenda"):
                    visual.rows([visual.row_html(
                        visual.mark("sell", "icon", small=True), r.person,
                        f"vencimento {date.fromisoformat(r.due_date):%d/%m/%Y} · {item_of.get(r.loan_id) or 'venda'} · "
                        f"parcela de {brl(r.amount)}", brl(r.remaining), "em aberto",
                        badge_html=visual.due_badge(date.fromisoformat(r.due_date), asof))
                        for r in sales_sched.sort_values("due_date").itertuples()])
            with st.expander(f"Todas as vendas ({len(sales)}) — tabela para conferir", icon=":material/table_rows:"):
                visual.table(sales.assign(parcelas=[f"{int(v)}x" if pd.notna(v) else "—" for v in sales["installments"]])
                             [["person", "item", "date", "principal", "parcelas", "paid", "remaining", "overdue", "next_due",
                               "note", "closed"]]
                             .rename(columns={"person": "comprador", "item": "o que foi vendido", "date": "data",
                                              "principal": "valor", "paid": "recebido", "remaining": "falta",
                                              "overdue": "atrasado", "next_due": "próx. venc.", "note": "obs",
                                              "closed": "quitada"})
                             .style.format({"valor": brl, "recebido": brl, "falta": brl, "atrasado": brl}),
                             use_container_width=True, hide_index=True)
            if not sales_pays.empty:
                with st.expander(f"Recebimentos de vendas ({len(sales_pays)})", icon=":material/receipt_long:"):
                    visual.listing(sales_pays[["person", "date", "amount", "note"]]
                                 .rename(columns={"person": "comprador", "date": "data", "amount": "valor", "note": "obs"})
                                 .style.format({"valor": brl}), title="{comprador}", value="{valor}", sub=["{data}", "{obs}"], icon=("icon", "person"), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhuma venda registrada.")

        # ---------------- nova venda
        st.subheader("Cadastrar e ajustar")
        with st.expander("Nova venda de produto ou serviço", icon=":material/add_circle:"):
            st.caption("Venda parcelada (ex.: 5x no Pix). As parcelas entram como **previsão de entrada** em 'Quando vou receber' "
                       "e na Previsão. Quando a pessoa fizer o Pix com o **valor de uma parcela**, ela é baixada sozinha.")
            if "sv_pending_person" in st.session_state:
                st.session_state["sv_person"] = st.session_state.pop("sv_pending_person")
            with session() as conn:
                pix_names = {r["name"]: r["match_name"] or "" for r in conn.execute("SELECT name, match_name FROM people")}
            st.session_state.setdefault("sv_n", 1)
            form_, resumo_ = st.columns([3, 2], gap="large")
            with form_:
                visual.step(1, "Quem comprou e o quê")
                a, b = st.columns([3, 1.4], vertical_alignment="bottom")
                sv_person = a.selectbox("Comprador", people, index=None, placeholder="Escolha uma pessoa já cadastrada",
                                        key="sv_person") or ""
                if b.button("Nova pessoa", key="sv_newbtn", icon=":material/person_add:", use_container_width=True):
                    new_person_dialog()
                a, b = st.columns(2)
                sv_item = a.text_input("O que foi vendido", key="sv_item", placeholder="ex.: Notebook usado, aula particular")
                sv_total = b.number_input("Valor total da venda (R$)", min_value=0.0, step=50.0, key="sv_total")
                visual.step(2, "Parcelas")
                a, b, c = st.columns(3)
                sv_date = a.date_input("Data da venda", key="sv_date", format="DD/MM/YYYY")
                sv_n = b.number_input("Nº de parcelas", min_value=1, step=1, key="sv_n")
                skey = f"sv_first_{sv_date.isoformat()}"
                if st.session_state.get(skey) is None:
                    st.session_state[skey] = sv_date
                sv_first = c.date_input("1º vencimento", key=skey, format="DD/MM/YYYY",
                                        help="Padrão: o dia da venda (a 1ª parcela é a entrada). Mude se a 1ª parcela for depois.")
                sv_sched = (lo.make_schedule(sv_total, 0.0, "mes", "simples", int(sv_n), sv_first, start=sv_date)
                            if sv_total > 0 else [])
                visual.step(3, "Baixa automática e detalhes (opcional)")
                sv_pix = st.text_input("Nome como aparece no Pix do comprador",
                                       value=pix_names.get(sv_person, ""), key=f"sv_pix_{sv_person}",
                                       help="Em branco = nenhum Pix é casado sozinho; você lança os recebimentos à mão. "
                                            "Só baixa quando o valor do Pix é igual ao de uma parcela em aberto.")
                sv_note = st.text_input("Observação", key="sv_note")
            with resumo_, st.container(border=True, key="sv_resumo"):
                if sv_sched:
                    schedule_summary("Você vai receber no total", sv_sched, sv_total, "Venda sem juros")
                    visual.scope("As parcelas entram em “Parcelas a receber” e na Previsão."
                                 + (" O Pix com o valor exato de uma parcela é baixado sozinho." if sv_pix.strip() else
                                    " Sem nome de Pix, os recebimentos são lançados à mão."))
                else:
                    st.html('<p class="pf-eyebrow">Resumo</p>')
                    visual.scope("Informe o valor da venda para ver aqui a parcela e as datas.")
            missing = (([] if sv_person else ["escolher o comprador"]) + ([] if sv_item.strip() else ["dizer o que foi vendido"])
                       + ([] if sv_total > 0 else ["informar o valor total"]))
            missing_hint(missing)
            if st.button("Registrar venda", type="primary", key="sv_save", disabled=bool(missing) or VIEW is not None):
                with session() as conn:
                    conn.execute("INSERT OR IGNORE INTO people(name) VALUES (?)", (sv_person,))
                    if sv_pix.strip():
                        conn.execute("UPDATE people SET match_name=? WHERE name=?", (sv_pix.strip(), sv_person))
                    cur = conn.execute(
                        "INSERT INTO loans(person, match_name, date, principal, note, rate, rate_period, compounding, kind, item) "
                        "VALUES (?,?,?,?,?,0,'mes','simples','venda',?)",
                        (sv_person, sv_pix.strip() or None, sv_date.isoformat(), sv_total, sv_note, sv_item.strip()))
                    for due, amt in sv_sched:
                        conn.execute("INSERT INTO loan_schedule(loan_id, due_date, amount) VALUES (?,?,?)",
                                     (cur.lastrowid, due.isoformat(), amt))
                    analytics.match_loan_payments(conn)
                for k in [k for k in st.session_state if k.startswith("sv_")]:
                    del st.session_state[k]
                st.session_state["emp_msg"] = f"Venda de {brl(sv_total)} a {sv_person} registrada."
                st.rerun()

        if not sales_open.empty:
            with st.expander("Lançar recebimento de venda com outro valor", icon=":material/payments:"):
                st.caption("Use quando o valor não é o de uma parcela, ou a pessoa pagou por outro meio. O Pix com o valor "
                           "exato de uma parcela já é baixado sozinho.")
                a, b, c = st.columns(3)
                lab = {f"{r.person} · {r.item} · falta {brl(r.remaining)}": r.id for r in sales_open.itertuples()}
                sale_pick = lab[a.selectbox("Venda", list(lab), key="sr_sale")]
                sr_date = b.date_input("Data do recebimento", key="sr_date", format="DD/MM/YYYY")
                sr_amt = c.number_input("Valor recebido (R$)", min_value=0.0, step=50.0, key="sr_amt")
                if st.button("Registrar recebimento", type="primary", key="sr_save", disabled=sr_amt <= 0):
                    with session() as conn:
                        conn.execute("INSERT INTO loan_payments(loan_id, date, amount, note, directed, order_mode) "
                                     "VALUES (?,?,?,?,1,'antigas')", (sale_pick, sr_date.isoformat(), sr_amt, "manual"))
                    for k in [k for k in st.session_state if k.startswith("sr_")]:
                        del st.session_state[k]
                    st.rerun()

    # ================================================== QUE EU DEVO
    with tab_debt:
        with session() as conn:
            bl, bopen = analytics.bank_loan_status(conn)
        if not bl.empty:
            c1, c2 = st.columns(2)
            c1.metric("Falta pagar ao banco (todos os contratos)", brl(bl["remaining"].sum()))
            c2.metric("Parcelas em aberto", int(bl["installments_left"].sum()))
            if not bopen.empty:
                st.subheader("Próximas parcelas")
                visual.scope("O botão só registra uma parcela que você já pagou no banco: o painel não paga nada.")
                bo = bopen.sort_values("due_date")
                with st.container(border=True, key="emp_banco"):
                    for i, r in enumerate(bo.head(6).itertuples()):
                        if i:
                            st.html('<hr class="pf-sep">')
                        due = date.fromisoformat(r.due_date)
                        a_, b_ = st.columns([6, 1.6], vertical_alignment="center")
                        a_.html(visual.row_html(visual.mark("account_balance", "icon"), r.bank,
                                                f"vencimento {due:%d/%m/%Y} · parcela de {brl(r.amount)}", brl(r.remaining),
                                                "a pagar", badge_html=visual.due_badge(due, today)))
                        if b_.button("Registrar", key=f"emp_bp_{i}", disabled=VIEW is not None, use_container_width=True,
                                     help="Registrar que esta parcela já foi paga"):
                            pay_dialog({"id": int(r.bank_loan_id), "person": r.bank, "due": due, "amount": float(r.remaining)})
                if len(bo) > 6:
                    with st.expander(f"Todas as parcelas em aberto ({len(bo)})", icon=":material/table_rows:"):
                        visual.table(bo[["bank", "due_date", "amount", "remaining"]]
                                     .rename(columns={"bank": "banco", "due_date": "vencimento", "amount": "parcela",
                                                      "remaining": "em aberto"})
                                     .style.format({"parcela": brl, "em aberto": brl}), use_container_width=True,
                                     hide_index=True)
            st.subheader("Contratos")
            show = bl.assign(taxa=[rate_txt(r.rate, r.rate_period, r.compounding) for r in bl.itertuples()])
            visual.listing(show[["bank", "date", "principal", "taxa", "installments", "installments_left", "total", "paid",
                               "remaining", "note"]]
                         .rename(columns={"bank": "banco", "date": "data", "principal": "valor tomado",
                                          "installments": "parcelas", "installments_left": "faltam", "total": "total do contrato",
                                          "paid": "pago", "remaining": "falta pagar", "note": "obs"})
                         .style.format({"valor tomado": brl, "total do contrato": brl, "pago": brl, "falta pagar": brl}),
                         title="{banco}", value="{falta pagar}", value_sub="falta pagar", sub=["contratado em {data}", "tomado {valor tomado}", "{taxa}", "faltam {faltam} de {parcelas} parcelas", "total do contrato {total do contrato}", "pago {pago}", "{obs}"], icon=("icon", "account_balance"), table="os contratos", use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum empréstimo de banco registrado.")

        st.subheader("Cadastrar e ajustar")
        with st.expander("Novo empréstimo no banco", icon=":material/add_circle:"):
            st.session_state.setdefault("bk_n", 12)
            form_, resumo_ = st.columns([3, 2], gap="large")
            with form_:
                visual.step(1, "Contrato")
                a, b = st.columns(2)
                bank = a.text_input("Banco ou financeira", key="bk_bank")
                bdate = b.date_input("Data da contratação", key="bk_date", format="DD/MM/YYYY")
                a, b = st.columns(2)
                bprin = a.number_input("Valor recebido do banco (R$)", min_value=0.0, step=100.0, key="bk_prin")
                bn = b.number_input("Nº de parcelas", min_value=1, step=1, key="bk_n")
                visual.step(2, "Juros")
                brate, bper, bcomp = rate_inputs("bk", "composto")
                visual.step(3, "Parcelas")
                a, b = st.columns(2)
                bkey = f"bk_first_{bdate.isoformat()}"
                if st.session_state.get(bkey) is None:
                    st.session_state[bkey] = (pd.Timestamp(bdate) + pd.DateOffset(months=1)).date()
                bfirst = a.date_input("1º vencimento", key=bkey, format="DD/MM/YYYY")
                binst = b.number_input("Valor da parcela do contrato (opcional)", min_value=0.0, step=10.0, key="bk_inst",
                                       help="Se o contrato diz o valor da parcela, informe: ele vale mais que a taxa. "
                                            "Em branco = calculado pela taxa.")
                bnote = st.text_input("Observação", key="bk_note")
            prev = lo.make_schedule(bprin, brate, bper, bcomp, int(bn), bfirst, binst or None, start=bdate) if bprin > 0 else []
            with resumo_, st.container(border=True, key="bk_resumo"):
                if prev:
                    schedule_summary("Você vai pagar no total", prev, bprin,
                                     "Parcela informada do contrato" if binst else
                                     ("Taxa: " + rate_equiv(brate, bper, bcomp) if brate else "Sem juros informados"),
                                     cost="Juros e custos")
                    visual.scope("O painel só registra o contrato para acompanhar: ele não paga nada ao banco.")
                else:
                    st.html('<p class="pf-eyebrow">Resumo</p>')
                    visual.scope("Informe o valor recebido para ver aqui o total a pagar, a parcela e as datas.")
            missing = ([] if bank.strip() else ["informar o banco"]) + ([] if bprin > 0 else ["informar o valor recebido"])
            missing_hint(missing)
            if st.button("Registrar empréstimo do banco", type="primary", key="bk_save",
                         disabled=bool(missing) or VIEW is not None):
                with session() as conn:
                    conn.execute("INSERT INTO bank_loans(bank, date, principal, rate, rate_period, compounding, installments, "
                                 "first_due, installment_amount, note) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                 (bank.strip(), bdate.isoformat(), bprin, brate, bper, bcomp, int(bn), bfirst.isoformat(),
                                  binst or None, bnote))
                for k in [k for k in st.session_state if k.startswith("bk_")]:
                    del st.session_state[k]
                st.session_state["emp_msg"] = f"Empréstimo de {brl(bprin)} no {bank.strip()} registrado."
                st.rerun()

        if not bl.empty and (bl["remaining"] > 0.005).any():
            with st.expander("Registrar pagamento com outro valor ou data", icon=":material/payments:"):
                act = bl[bl["remaining"] > 0.005]
                lab = {f"{r.bank} · {r.date} · falta {brl(r.remaining)}": r.id for r in act.itertuples()}
                a, b, c = st.columns(3)
                pid = lab[a.selectbox("Empréstimo", list(lab), key="bp_loan")]
                pdt = b.date_input("Data do pagamento", key="bp_date", format="DD/MM/YYYY")
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
    st.title("Carro")
    with session() as conn:
        car = analytics.car_summary(conn)
    prof = car["profile"]

    # ---- cadastro do carro
    if prof is None:
        st.info("Cadastre o carro para ver o painel dele.")
    with st.expander("Dados do carro" if prof else "Cadastrar o carro", expanded=prof is None):
        with st.form("car_profile"):
            a, b, c = st.columns([2, 2, 1])
            brand = a.text_input("Marca", value=(prof or {}).get("brand", ""))
            model = b.text_input("Modelo", value=(prof or {}).get("model", ""))
            year = c.number_input("Ano", min_value=1980, max_value=date.today().year + 1,
                                  value=(prof or {}).get("year") or date.today().year, step=1)
            if st.form_submit_button("Salvar carro"):
                if not brand.strip() or not model.strip():
                    st.error("Informe marca e modelo.")
                else:
                    with session() as conn:
                        conn.execute(
                            "INSERT INTO car_profile(id, brand, model, year) VALUES (1,?,?,?) "
                            "ON CONFLICT(id) DO UPDATE SET brand=excluded.brand, model=excluded.model, year=excluded.year",
                            (brand.strip(), model.strip(), int(year)))
                    st.rerun()
    if prof is None:
        st.stop()
    st.subheader(f"{prof['brand']} {prof['model']}" + (f" · {prof['year']}" if prof.get("year") else ""))

    # ---- custo por mês: número dominante (soma de partes que o painel já calcula)
    fuel_sp = analytics.spending(df)
    fuel_sp = fuel_sp[fuel_sp["category"] == "Carro - Combustível"] if not fuel_sp.empty else fuel_sp
    fuel_3m = float(fuel_sp[fuel_sp["date"] >= pd.Timestamp.today() - pd.DateOffset(months=3)]["value"].sum()) \
        if not fuel_sp.empty else 0.0
    cost_parts = [("fixos", car.get("fixed_month")), ("depreciação", car.get("depr_month")),
                  ("combustível", fuel_3m / 3 if fuel_3m else None)]
    have = [(n_, float(v_)) for n_, v_ in cost_parts if v_ is not None and not pd.isna(v_) and float(v_) > 0]
    missing = [n_ for n_, _ in cost_parts if n_ not in dict(have)]
    with st.container(border=True, key="car_resumo"):
        visual.hero("Custo por mês (estimativa)", brl(sum(v_ for _, v_ in have)) if have else "—",
                    " + ".join(f"{n_} {brl(v_)}" for n_, v_ in have))
        visual.scope("Fixos: seguro, IPVA e licenciamento do ano ÷ 12. Depreciação: pela tabela FIPE. Combustível: "
                     "média dos últimos 3 meses de gasto em posto. Manutenção e revisão não entram."
                     + (f" Sem dados de: {', '.join(missing)}." if missing else ""))

    # ---- painel: situação atual
    year_now = date.today().year
    ins = car["fixed"][(car["fixed"]["year"] == year_now) & (car["fixed"]["item"] == "seguro")]["amount"] \
        if not car["fixed"].empty else []
    insurance = float(ins.iloc[0]) if len(ins) else None
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Km atual", f"{prof['km_now']:,.0f} km".replace(",", ".") if prof.get("km_now") is not None else "—",
              help=f"Atualizado em {prof['km_now_date']}" if prof.get("km_now_date") else None)
    left = car.get("km_to_service")
    m2.metric("Próxima revisão", f"{prof['next_service_km']:,.0f} km".replace(",", ".") if prof.get("next_service_km") else "—",
              delta=(f"faltam {left:,.0f} km".replace(",", ".") if left is not None and left >= 0
                     else f"passou {-left:,.0f} km".replace(",", ".")) if left is not None else None,
              delta_color="off" if left is None or left >= 0 else "inverse")
    m3.metric("Preço da revisão", brl(prof.get("next_service_price")),
              help=(f"≈ {brl(car['service_per_km'])} por km rodado no intervalo de "
                    f"{car['service_interval']:,.0f} km".replace(",", ".")) if car.get("service_per_km") else
              "O preço por km aparece quando há uma manutenção registrada com odômetro (intervalo entre revisões).")
    m4.metric("Seguro (ano)", brl(insurance), delta=f"{brl(insurance / 12)} / mês" if insurance else None, delta_color="off")
    if car.get("service_per_km"):
        interval_txt = f"{car['service_interval']:,.0f}".replace(",", ".")
        st.caption((f"Revisão custa ≈ **{brl(car['service_per_km'])} / km** "
                    f"({brl(prof['next_service_price'])} ÷ {interval_txt} km desde a última manutenção).").replace("$", "\\$"))

    with st.expander("Atualizar km, revisão e seguro", icon=":material/edit:"):
        with st.form("car_status"):
            a, b = st.columns(2)
            km_now = a.number_input("Km atual (odômetro)", min_value=0.0, step=100.0, value=float(prof.get("km_now") or 0))
            ns_km = b.number_input("Km da próxima revisão", min_value=0.0, step=1000.0,
                                   value=float(prof.get("next_service_km") or 0))
            c, d = st.columns(2)
            ns_price = c.number_input("Preço da próxima revisão (R$)", min_value=0.0, step=50.0,
                                      value=float(prof.get("next_service_price") or 0))
            ins_v = d.number_input(f"Seguro de {year_now} (R$ no ano)", min_value=0.0, step=100.0,
                                   value=float(insurance or 0))
            if st.form_submit_button("Salvar"):
                with session() as conn:
                    conn.execute("UPDATE car_profile SET km_now=?, km_now_date=?, next_service_km=?, next_service_price=? "
                                 "WHERE id=1", (km_now or None, date.today().isoformat() if km_now else None,
                                                ns_km or None, ns_price or None))
                    if ins_v:
                        conn.execute("INSERT OR REPLACE INTO car_fixed(year, item, amount) VALUES (?,?,?)",
                                     (year_now, "seguro", ins_v))
                st.rerun()
    st.divider()
    fuel_card = analytics.spending(df)
    fuel_card = fuel_card[fuel_card["category"] == "Carro - Combustível"] if not fuel_card.empty else fuel_card

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Consumo médio", f"{car['km_l']:.1f} km/L".replace(".", ",") if car.get("km_l") else "—")
    c2.metric("Combustível por km", brl(car.get("fuel_per_km")))
    c3.metric("Fixos por mês", brl(car.get("fixed_month")), help="Seguro + IPVA + licenciamento do ano ÷ 12")
    c4.metric("Depreciação por mês", brl(car.get("depr_month")), help=f"FIPE atual {brl(car.get('fipe_now'))}")
    per_km = sum(v for v in (car.get("fuel_per_km"), car.get("maint_per_km")) if v)
    st.caption((f"Custo variável ≈ **{brl(per_km)} / km** (combustível + manutenção). "
                f"Gasto em posto no cartão (últimos 3 meses): "
                f"{brl(fuel_card[fuel_card['date'] >= pd.Timestamp.today() - pd.DateOffset(months=3)]['value'].sum() if not fuel_card.empty else 0)}.").replace("$", "\\$"))

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
            st.plotly_chart(style(fig, 260, month_axis=False, money=False), use_container_width=True)
        st.subheader("Abastecimentos e manutenções")
        evt = ev.sort_values("date", ascending=False)
        evt = evt.assign(kind=evt["kind"].map({"combustivel": "Combustível", "manutencao": "Manutenção",
                                               "outro": "Outro"}).fillna(evt["kind"]),
                         full_tank=[("sim" if f_ == 1 else "não") if pd.notna(l_) else ""
                                    for f_, l_ in zip(evt["full_tank"], evt["liters"])])
        visual.listing(evt.style.format({"amount": brl,
                                       "odometer": lambda v: "" if pd.isna(v) else f"{v:,.0f} km".replace(",", "."),
                                       "liters": lambda v: "" if pd.isna(v) else f"{v:.1f}".replace(".", ",")}, na_rep=""),
                     title="{kind}", value="{amount}", sub=["{date}", "{odometer}", "{liters} L", "tanque cheio: {full_tank}", "{trip}", "{note}"], icon=("icon", "directions_car"), table="os eventos do carro", use_container_width=True, hide_index=True)

    st.subheader("Cadastrar e ajustar")
    with st.expander("Lançar abastecimento, manutenção, custo fixo ou valor da FIPE", icon=":material/add_circle:"):
        a, b, c = st.columns(3)
        with a.form("fuel"):
            st.markdown("**Abastecimento / manutenção**")
            kind = st.selectbox("Tipo", ["combustivel", "manutencao", "outro"],
                                format_func={"combustivel": "Combustível", "manutencao": "Manutenção", "outro": "Outro"}.get)
            d = st.date_input("Data", format="DD/MM/YYYY")
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
    ASSET_TYPES = {"CRYPTO": "Cripto", "FIXED_INCOME": "Renda fixa", "MUTUAL_FUND": "Fundos", "EQUITY": "Ações",
                   "STOCK": "Ações", "FUND": "Fundos", "ETF": "ETF", "COE": "COE"}
    TYPE_ICONS = {"Cripto": "currency_bitcoin", "Renda fixa": "lock_clock", "Fundos": "pie_chart", "Ações": "show_chart"}
    hold = hold.assign(classe=hold["asset_type"].map(lambda t: ASSET_TYPES.get(str(t).upper(), "Outros")))
    total = float(hold["value_brl"].sum())
    snaps = sorted(hold["snapshot"].astype(str).unique())
    ref = pd.Timestamp(snaps[-1]).strftime("%d/%m/%Y")

    left, right = st.columns([7, 5], gap="large")
    with left, st.container(border=True, key="inv_total"):
        visual.hero("Total investido", brl(total),
                    f"posição de {ref} · {len(hold)} ativos em {hold['source'].nunique()} instituições")
        st.html('<p class="pf-eyebrow" style="margin-top:.6rem">Alocação por classe</p>')
        by_class = hold.groupby("classe")["value_brl"].sum().sort_values(ascending=False)
        visual.bars([{"label": c, "value": v, "text": brl(v), "sub": f"{100 * v / total:.0f}%",
                      "icon": TYPE_ICONS.get(c, "category"), "kind": "icon"} for c, v in by_class.items()],
                    color=visual.palette()["primary"])
        visual.scope("O painel mostra a posição e a alocação. Custo médio e rentabilidade ainda não são registrados, "
                     "por isso não aparecem aqui.")
    with right, st.container(border=True, key="inv_inst"):
        st.html('<p class="pf-eyebrow">Por instituição</p>')
        by_src = hold.groupby("source")["value_brl"].agg(["sum", "count"]).sort_values("sum", ascending=False)
        visual.rows([visual.row_html(visual.mark(src), visual.institution_name(src),
                                     f"{int(r['count'])} ativo{'s' if r['count'] > 1 else ''}", brl(r["sum"]),
                                     f"{100 * r['sum'] / total:.0f}% do total") for src, r in by_src.iterrows()])

    st.subheader("Posições")
    for src in by_src.index:
        grp = hold[hold["source"] == src].sort_values("value_brl", ascending=False)
        with st.container(border=True, key=f"inv_pos_{src}"):
            st.html(visual.row_html(visual.mark(src), visual.institution_name(src),
                                    f"posição de {pd.Timestamp(str(grp['snapshot'].iloc[0])).strftime('%d/%m/%Y')}",
                                    brl(grp["value_brl"].sum())))
            lines = []
            for r in grp.itertuples():
                qty = "" if pd.isna(r.quantity) else f" · {r.quantity:,.8g}".replace(",", "X").replace(".", ",").replace("X", ".") + " un."
                lines.append(visual.row_html(visual.mark(TYPE_ICONS.get(r.classe, "category"), "icon", small=True),
                                             r.asset, f"{r.classe}{qty}", brl(r.value_brl),
                                             f"{100 * r.value_brl / total:.1f}% da carteira".replace(".", ",")))
            st.html('<hr class="pf-sep">' + '<hr class="pf-sep">'.join(lines))
    with st.expander("Tabela completa (para conferir)"):
        visual.table(hold[["source", "asset", "classe", "quantity", "price_usd", "value_brl", "snapshot"]]
                     .assign(source=hold["source"].map(visual.institution_name))
                     .rename(columns={"source": "instituição", "asset": "ativo", "quantity": "quantidade",
                                      "price_usd": "preço US$", "value_brl": "valor", "snapshot": "posição de"})
                     .style.format({"valor": brl, "preço US$": "{:,.2f}", "quantidade": "{:,.8g}"}, na_rep="—"),
                     use_container_width=True, hide_index=True)

# ------------------------------------------------------------------ Sincronizar
elif page == "Sincronizar":
    st.title("Sincronizar")
    st.write("Fontes: **Pluggy** (Inter + XP via Open Finance) · **Binance** (API só leitura) · "
             f"**Contas** (PDF) em `{config.BILLS_DIR / 'entrada'}` · **OFX** em `data/inbox/ofx` (plano B). "
             "A sincronização sempre usa os **dados atuais** e faz o backup automático quando vence.")
    status = {
        "Pluggy": bool(config.PLUGGY_ACCOUNTS),
        "Binance": bool(config.BINANCE_API_KEY),
    }
    st.write(" · ".join(f"{k}: {':material/check_circle: configurado' if v else ':material/radio_button_unchecked: falta no .env'}" for k, v in status.items()))
    a, b = st.columns(2)
    if a.button("Sincronizar tudo", type="primary", icon=":material/sync:"):
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
    visual.listing(logs.assign(at=[f"{pd.Timestamp(v):%d/%m/%Y %H:%M}" if pd.notna(pd.to_datetime(v, errors="coerce"))
                                    else str(v) for v in logs["at"]]), title="{source}", sub=["{at}", "{message}"], icon=("icon", "sync"), badge=lambda row: visual.badge("Deu certo", "ok") if row.get("ok") in ("1", "True") else visual.badge("Falhou", "late"), table="o histórico", use_container_width=True, hide_index=True)

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

    st.subheader("Atualizações")
    with db_session() as conn:
        chk = settings.get(conn, "update_check") == "1"
    new_chk = st.toggle("Avisar quando houver versão nova", value=chk)
    st.caption("Consulta o GitHub no máximo a cada 6 horas e não envia nenhum dado seu. "
               "Atualizar continua sendo manual: veja \"Como atualizar\" no README.")
    if new_chk != chk:
        with db_session() as conn:
            settings.set_(conn, "update_check", "1" if new_chk else "0")
        st.rerun()

    st.subheader("Conexões")
    from financas import connections
    visual.notes(None, [
        f"As chaves ficam no arquivo `{config.ENV_FILE.name}` desta instalação, nunca no banco nem no backup.",
        "Depois de salvas, elas não são mostradas de novo.",
        "Só é salvo o que passar no teste, que faz apenas consultas de leitura.",
        "**Atenção:** quem abre este painel pode trocar as chaves. Num servidor compartilhado, o painel vai precisar de senha.",
    ])
    for src in connections.SOURCES:
        cur = connections.current(src)
        with st.expander(f"{src.name} · {'conectado' if connections.is_configured(src) else 'não conectado'}", icon=':material/check_circle:' if connections.is_configured(src) else ':material/radio_button_unchecked:'):
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
                do_test = c1.form_submit_button("Testar conexão")
                do_save = c2.form_submit_button("Testar e salvar", type="primary")
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
        visual.notes(None, [
            f"O próximo backup automático é feito {when}.",
            "Ele acontece quando o painel abre ou a sincronização roda (no servidor, a cada 6 h).",
            f"Ficam os {backup.KEEP_AUTO} automáticos mais recentes; os manuais nunca são apagados sozinhos.",
        ])
    if st.button("Fazer backup agora", type="primary", icon=":material/save:"):
        made = backup.make("manual")
        st.success(f"Backup criado: {made.name}")

    items = backup.list_backups()
    if not items:
        st.info("Nenhum backup ainda.")
    else:
        visual.table(pd.DataFrame({"Data": [f"{b['created']:%d/%m/%Y %H:%M}" for b in items],
                                   "Tipo": ["Manual" if b["kind"] == "manual" else "Automático" for b in items],
                                   "Tamanho": [f"{b['size'] / 1e6:.1f} MB" if b["size"] >= 1e6 else f"{b['size'] / 1e3:.0f} KB"
                                               for b in items]}),
                     use_container_width=True, hide_index=True, height=min(35 * (len(items) + 1) + 3, 300))
        sel = st.selectbox("Escolha um backup", items, format_func=backup_label)
        c1, c2 = st.columns(2)
        c1.download_button("Baixar (.zip)", icon=":material/download:", data=sel["path"].read_bytes(), file_name=sel["path"].name,
                           mime="application/zip", help="Guarde onde quiser: pendrive, nuvem, e-mail.")
        c2.button("Ver estes dados no painel", icon=":material/visibility:", on_click=lambda: st.session_state.update(view=f"Backup de {backup_label(sel)}"),
                  help="O painel inteiro passa a mostrar os números daquele dia, somente leitura.")
        st.caption(f"Pasta dos backups: `{backup.backup_dir()}`")
