"""Identidade visual do painel: paletas clara/escura, config do Streamlit e CSS dos componentes.

O Streamlit só deixa mudar cores/fonte pelo `.streamlit/config.toml`; o resto (cartões, sidebar, abas)
é CSS injetado. Sem fonte externa: usa a fonte do sistema, então nada é baixado da internet.
"""
from __future__ import annotations

import html as _html
import re

import pandas as pd
import streamlit as st

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif"

PALETTES = {
    "light": {"bg": "#F5F6F8", "card": "#FFFFFF", "line": "#E7E9EE", "text": "#16181D", "muted": "#6B7280",
              "primary": "#0B7A5F", "soft": "#E3F4EE", "hover": "#F0F2F5"},
    "dark": {"bg": "#0D1014", "card": "#151A21", "line": "#232A33", "text": "#EEF1F5", "muted": "#8A94A3",
             "primary": "#3DDC97", "soft": "#16301F", "hover": "#1C242D"},
}

# paleta categórica dos gráficos, ordem fixa; verde (entradas) e laranja (saídas) vêm primeiro
SERIES = ["#0B7A5F", "#F08A5D", "#3B82F6", "#EDA100", "#E87BA4", "#7C5CD6", "#14B8A6", "#E34948"]


def _toml_block(p: dict) -> str:
    return (f'primaryColor = "{p["primary"]}"\nbackgroundColor = "{p["bg"]}"\n'
            f'secondaryBackgroundColor = "{p["card"]}"\ntextColor = "{p["text"]}"\n'
            'font = "sans-serif"\nborderColor = "' + p["line"] + '"\nbaseRadius = "large"\n')


def config_text(theme: str) -> str:
    """Conteúdo do bloco [theme] do config.toml para 'light', 'dark' ou 'system' (segue o computador)."""
    if theme in ("light", "dark"):
        return f'[theme]\nbase = "{theme}"\n' + _toml_block(PALETTES[theme])
    return ("[theme.light]\nbase = \"light\"\n" + _toml_block(PALETTES["light"])
            + "\n[theme.dark]\nbase = \"dark\"\n" + _toml_block(PALETTES["dark"]))


def mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # noqa: BLE001 — versão antiga do Streamlit ou sem contexto: claro
        return "light"


def palette() -> dict:
    return PALETTES[mode()]


def inject_css() -> None:
    p = palette()
    st.markdown(f"""<style>
    .stApp, .stApp p, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp button, .stApp input,
    .stApp textarea {{font-family:{FONT};}}
    .block-container {{padding-top:2.2rem; max-width:1400px;}}
    h1 {{font-weight:700; letter-spacing:-0.02em; padding-bottom:.4rem;}}
    h2, h3 {{font-weight:600; letter-spacing:-0.01em;}}
    /* barra lateral */
    [data-testid="stSidebar"] {{border-right:1px solid {p['line']};}}
    [data-testid="stSidebar"] [role="radiogroup"] {{gap:2px;}}
    [data-testid="stSidebar"] [role="radiogroup"] label {{padding:8px 12px; border-radius:10px; width:100%;}}
    [data-testid="stSidebar"] [role="radiogroup"] label:hover {{background:{p['hover']};}}
    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{background:{p['soft']}; font-weight:600;}}
    [data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {{display:none;}}
    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{color:{p['primary']};}}
    /* indicadores viram cartões */
    [data-testid="stMetric"] {{background:{p['card']}; border:1px solid {p['line']}; border-radius:16px;
                              padding:18px 20px;}}
    [data-testid="stMetricLabel"] p {{color:{p['muted']}; font-size:.85rem; font-weight:500;}}
    [data-testid="stMetricValue"] {{font-size:1.75rem; font-weight:700; letter-spacing:-0.02em;}}
    [data-testid="stMetricDelta"] {{background:{p['soft']}; border-radius:99px; padding:2px 10px; width:fit-content;
                                   color:{p['primary']};
                                   white-space:normal; height:auto; line-height:1.4;}}
    [data-testid="stMetric"] *, [data-testid="stMetricValue"] div {{white-space:normal !important; overflow:visible !important;
                                                                text-overflow:clip !important;}}
    [data-testid="stMetricValue"] {{font-size:clamp(1.25rem, 1.9vw, 1.75rem);}}
    /* gráficos, tabelas e formulários em cartões */
    [data-testid="stPlotlyChart"], [data-testid="stDataFrame"], [data-testid="stForm"],
    [data-testid="stExpander"] {{background:{p['card']}; border:1px solid {p['line']}; border-radius:16px;
                                 padding:10px; overflow:hidden;}}
    [data-testid="stExpander"] details {{border:0;}}
    /* abas e botões */
    [data-baseweb="tab-list"] {{gap:4px;}}
    [data-baseweb="tab"] {{border-radius:10px 10px 0 0; font-weight:500;}}
    .stButton > button, .stDownloadButton > button {{border-radius:10px; font-weight:600;}}
    /* textos: linhas curtas e espaçadas, em vez de um parágrafo comprido de ponta a ponta */
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{max-width:76ch; line-height:1.65;
                                                                             color:{p['muted']};}}
    [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {{line-height:1.65;}}
    [data-testid="stMarkdownContainer"] ul, [data-testid="stMarkdownContainer"] ol {{padding-left:1.3rem;}}
    [data-testid="stMarkdownContainer"] li {{margin-bottom:.35rem;}}
    [data-testid="stVerticalBlock"] {{gap:1rem;}}
    h2, h3 {{margin-top:1.2rem;}}
    [data-testid="stAlert"] {{border-radius:14px;}}
    /* tabelas */
    .ft-wrap {{background:{p['card']}; border:1px solid {p['line']}; border-radius:16px; overflow:auto;
               max-height:560px;}}
    .ft {{border-collapse:separate; border-spacing:0; width:100%; font-size:.9rem; font-variant-numeric:tabular-nums;}}
    .ft th {{position:sticky; top:0; background:{p['card']}; color:{p['muted']}; font-size:.75rem; font-weight:600;
             text-transform:uppercase; letter-spacing:.04em; text-align:left; padding:14px 16px;
             border-bottom:1px solid {p['line']}; white-space:nowrap; z-index:1;}}
    .ft td {{padding:12px 16px; border-bottom:1px solid {p['line']}; vertical-align:top; line-height:1.45;}}
    .ft td:not(.wrap) {{white-space:nowrap;}}
    .ft td.wrap {{min-width:220px;}}
    .ft tbody tr:last-child td {{border-bottom:0;}}
    .ft tbody tr:hover td {{background:{p['hover']};}}
    .ft .num {{text-align:right; white-space:nowrap;}}
    .ft td.neg {{color:#C2410C;}}
    .ft td.c0 {{font-weight:600; white-space:nowrap;}}
    .ft .row_heading {{font-weight:600; text-align:left; padding:12px 16px; border-bottom:1px solid {p['line']};}}
    .ft-empty {{color:{p['muted']}; padding:18px 4px;}}
    </style>""", unsafe_allow_html=True)


def style_figure(fig) -> None:
    """Estilo comum dos gráficos Plotly: fundo transparente (vale no claro e no escuro), fonte e grade discretas."""
    p = palette()
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family=FONT, color=p["muted"], size=12),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
    fig.update_yaxes(gridcolor=p["line"], linecolor=p["line"])
    fig.update_xaxes(linecolor=p["line"])
    fig.update_traces(selector=dict(type="bar"), marker_cornerradius=6)


# ------------------------------------------------------------------ tabelas
_NUM = re.compile(r"^[-−+]?\s*(R\$\s*)?[\d.,]+\s*(%|kWh|m³|km)?$")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})( 00:00:00)?$")
_LONG_FLOAT = re.compile(r"^-?\d+\.\d{3,}$")
_TD = re.compile(r'<td id="[^"]*" class="data row(\d+) col(\d+)" >(.*?)</td>', re.S)
_TH = re.compile(r'<th id="[^"]*" class="col_heading level0 col(\d+)" >(.*?)</th>', re.S)
_EMPTY = {"nan", "NaT", "None", "<NA>", "R$ nan", "—"}


def _cell(text: str) -> str:
    text = _html.unescape(text).strip()
    if text in _EMPTY or text == "R$ —":
        return ""
    if m := _ISO.match(text):
        return f"{m[3]}/{m[2]}/{m[1]}"
    if _LONG_FLOAT.match(text):
        return f"{float(text):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text


def _pretty(name) -> str:
    s = str(name).replace("_", " ")
    return s[:1].upper() + s[1:]


def table(data, hide_index: bool = True, max_rows: int = 250, **_ignored) -> None:
    """Tabela do painel (HTML): cabeçalho discreto, números à direita, linhas arejadas. Vale no claro e no escuro.

    Aceita DataFrame ou Styler (mantém os formatos). Acima de `max_rows` linhas usa o st.dataframe, que rola e filtra.
    """
    styler = data if hasattr(data, "to_html") and hasattr(data, "data") else data.style
    df = styler.data
    if df.empty and len(df.columns) == 0 or len(df) == 0:
        st.html('<div class="ft-empty">Nada para mostrar ainda.</div>')
        return
    if len(df) > max_rows:
        st.dataframe(data, use_container_width=True, hide_index=hide_index, height=520)
        return
    if hide_index:
        styler = styler.hide(axis="index")
    raw = styler.to_html()
    body = raw[raw.index("<table"):]
    cells = [(int(r), int(c), _cell(t)) for r, c, t in _TD.findall(body)]
    ncols = len(df.columns)
    numeric = {c for c in range(ncols)
               if (vals := [t for _, cc, t in cells if cc == c and t]) and all(_NUM.match(v) for v in vals)}

    def td(m):
        r, c, t = int(m[1]), int(m[2]), _cell(m[3])
        cls = ["num"] if c in numeric else []
        if c in numeric and t[:1] in "-−":
            cls.append("neg")
        if c == 0:
            cls.append("c0")
        if len(t) > 32:
            cls.append("wrap")
        return f'<td class="{" ".join(cls)}">{_html.escape(t)}</td>'

    def th(m):
        c = int(m[1])
        return f'<th class="{"num" if c in numeric else ""}">{_html.escape(_pretty(_html.unescape(m[2])))}</th>'

    body = _TD.sub(td, body)
    body = _TH.sub(th, body)
    body = re.sub(r"<table[^>]*>", '<table class="ft">', body, count=1)
    body = re.sub(r">\s+<", "><", body)
    st.html(f'<div class="ft-wrap">{body}</div>')


def notes(title: str | None, items: list[str], expanded: bool | None = None) -> None:
    """Lista curta de observações: no lugar de um parágrafo comprido separado por pontos.

    `expanded` None = sempre visível, num cartão; True/False = recolhível (aberto/fechado)."""
    text = "\n".join(f"- {i}" for i in items)
    if expanded is None:
        with st.container(border=True):
            if title:
                st.markdown(f"**{title}**")
            st.markdown(text)
    else:
        with st.expander(title or "Detalhes", expanded=expanded):
            st.markdown(text)
