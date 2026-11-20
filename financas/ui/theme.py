"""Identidade visual do painel: paletas clara/escura, config do Streamlit e CSS dos componentes.

O Streamlit só deixa mudar cores/fonte pelo `.streamlit/config.toml`; o resto (cartões, sidebar, abas)
é CSS injetado. Sem fonte externa: usa a fonte do sistema, então nada é baixado da internet.
"""
from __future__ import annotations

import html as _html
import hashlib
import re

import pandas as pd
import streamlit as st

FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif"

# Tokens do sistema de design (docs/ui-evolucao/02-sistema-de-design.md).
# Neutros + um acento (azul: só o que é interativo) + cores com significado fixo:
#   in = entrada · out = saída · good/warn/crit = estado (sempre com ícone e texto, nunca só a cor).
# As chaves antigas (primary, soft, hover…) continuam valendo.
PALETTES = {
    "light": {"bg": "#F6F6F4", "card": "#FFFFFF", "line": "#E1E0D9", "text": "#0B0B0B", "sec": "#52514E",
              "muted": "#6F6D68", "primary": "#1F65BD", "soft": "#E8F0FB", "hover": "#EFEEEA",
              "in": "#1BAF7A", "out": "#EB6834", "good": "#0CA30C", "good_text": "#006300",
              "warn": "#FAB219", "warn_text": "#7A5200", "warn_soft": "#FFF4D6",
              "crit": "#D03B3B", "crit_text": "#A32020", "crit_soft": "#FBE9E9", "good_soft": "#E4F5E4",
              "grid": "#E1E0D9", "axis": "#C3C2B7", "other": "#9A9893"},
    "dark": {"bg": "#0D0D0D", "card": "#1A1A19", "line": "#2C2C2A", "text": "#F0EFEC", "sec": "#C3C2B7",
             "muted": "#989690", "primary": "#5B9DEB", "soft": "#17263A", "hover": "#242422",
             "in": "#199E70", "out": "#D95926", "good": "#0CA30C", "good_text": "#4CC24C",
             "warn": "#FAB219", "warn_text": "#FAB219", "warn_soft": "#33290F",
             "crit": "#D03B3B", "crit_text": "#F08080", "crit_soft": "#351717", "good_soft": "#12301A",
             "grid": "#2C2C2A", "axis": "#383835", "other": "#7C7A75"},
}

# Paleta categórica dos gráficos: ordem fixa, validada para daltonismo nas duas superfícies
# (azul, laranja, água, amarelo, magenta, verde, violeta, vermelho). Nunca ciclar: a 9ª série vira "Outros".
SERIES_BY_MODE = {
    "light": ["#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#008300", "#6250D6", "#E34948"],
    "dark": ["#3987E5", "#D95926", "#199E70", "#C98500", "#D55181", "#0CA30C", "#9085E9", "#E66767"],
}
SERIES = SERIES_BY_MODE["light"]  # compatibilidade; prefira series()


def _toml_block(p: dict) -> str:
    return (f'primaryColor = "{p["primary"]}"\nbackgroundColor = "{p["bg"]}"\n'
            f'secondaryBackgroundColor = "{p["card"]}"\ntextColor = "{p["text"]}"\n'
            'font = "sans-serif"\nborderColor = "' + p["line"] + '"\nbaseRadius = "medium"\n')


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


def series() -> list[str]:
    """Cores das séries para o tema em uso (mesmos matizes, passo próprio de cada superfície)."""
    return SERIES_BY_MODE[mode()]


def inject_css() -> None:
    p = palette()
    st.markdown(f"""<style>
    .stApp, .stApp p, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp button, .stApp input,
    .stApp textarea {{font-family:{FONT};}}
    .block-container {{padding-top:2rem; max-width:1240px;}}
    /* escala tipográfica: título da tela discreto; quem domina é o número principal */
    h1 {{font-size:1.45rem !important; font-weight:650; letter-spacing:-0.01em; padding:0 0 .2rem 0;}}
    h2 {{font-size:1.1rem !important; font-weight:600; letter-spacing:-0.005em; margin-top:1.4rem; padding-bottom:.2rem;}}
    h3 {{font-size:1rem !important; font-weight:600; margin-top:1rem; padding-bottom:.1rem;}}
    /* barra lateral: navegação */
    [data-testid="stSidebar"] {{border-right:1px solid {p['line']};}}
    [data-testid="stSidebar"] [role="radiogroup"] {{gap:1px;}}
    [data-testid="stSidebar"] [role="radiogroup"] label {{padding:6px 10px; border-radius:8px; width:100%;}}
    [data-testid="stSidebar"] [role="radiogroup"] label:hover {{background:{p['hover']};}}
    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{background:{p['soft']}; font-weight:600;}}
    [data-testid="stSidebar"] [role="radiogroup"] label > div > div:first-child {{display:none;}}
    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{color:{p['primary']};}}
    [data-testid="stSidebar"] [role="radiogroup"] label p {{font-size:.92rem;}}
    /* indicadores secundários: rótulo pequeno, valor médio, sem caixa colorida */
    [data-testid="stMetric"] {{background:{p['card']}; border:1px solid {p['line']}; border-radius:10px;
                              padding:12px 14px;}}
    [data-testid="stMetricLabel"] p {{color:{p['muted']}; font-size:.78rem; font-weight:500;}}
    [data-testid="stMetricValue"] {{font-size:1.25rem; font-weight:650; letter-spacing:-0.01em;
                                   font-variant-numeric:tabular-nums;}}
    [data-testid="stMetricDelta"] {{background:none; padding:0; color:{p['muted']}; font-size:.78rem;
                                   white-space:normal; height:auto; line-height:1.4;}}
    [data-testid="stMetricDelta"] svg {{display:none;}}
    [data-testid="stMetric"] *, [data-testid="stMetricValue"] div {{white-space:normal !important; overflow:visible !important;
                                                                text-overflow:clip !important;}}
    /* gráficos, tabelas e formulários em painéis de borda fina */
    [data-testid="stPlotlyChart"], [data-testid="stDataFrame"], [data-testid="stForm"],
    [data-testid="stExpander"] {{background:{p['card']}; border:1px solid {p['line']}; border-radius:10px;
                                 padding:8px; overflow:hidden;}}
    [data-testid="stExpander"] details {{border:0;}}
    [data-testid="stVerticalBlockBorderWrapper"] {{border-radius:10px;}}
    /* abas e botões: botão é retângulo com peso; etiqueta de estado é pílula pequena e não reage ao mouse */
    [data-baseweb="tab-list"] {{gap:2px;}}
    [data-baseweb="tab"] {{font-weight:500;}}
    .stButton > button, .stDownloadButton > button {{border-radius:8px; font-weight:600;}}
    .stButton > button[kind="tertiary"] {{color:{p['primary']}; font-weight:600; padding:2px 4px; min-height:0;}}
    .stButton > button[kind="tertiary"]:hover {{text-decoration:underline;}}
    .stAppDeployButton {{display:none;}}
    [data-testid="stHeader"] {{background:transparent;}}
    /* botão só de ícone (abrir o detalhe de uma linha) */
    [class*="st-key-vg_go_"] button, [class*="st-key-gs_go_"] button {{padding:4px; min-height:0; min-width:0;}}
    /* linha com seta de abrir: não quebra em tela estreita */
    [class*="st-key-lg_"] [data-testid="stHorizontalBlock"], .st-key-vg_pend [data-testid="stHorizontalBlock"]
      {{flex-wrap:nowrap; gap:4px;}}
    [class*="st-key-lg_"] [data-testid="stColumn"], .st-key-vg_pend [data-testid="stColumn"] {{min-width:0 !important;}}
    [class*="st-key-lg_"] [data-testid="stColumn"]:last-child, .st-key-vg_pend [data-testid="stColumn"]:last-child
      {{flex:0 0 34px !important; width:34px !important;}}
    [class*="st-key-lg_"] [data-testid="stColumn"]:first-child, .st-key-vg_pend [data-testid="stColumn"]:first-child
      {{flex:1 1 auto !important;}}
    [class*="st-key-lg_"] [data-testid="stHtml"], [class*="st-key-lg_"] [data-testid="stColumn"]:first-child > div,
    .st-key-vg_pend [data-testid="stHtml"], .st-key-vg_pend [data-testid="stColumn"]:first-child > div {{width:100%;}}
    [class*="st-key-lg_"] {{gap:.1rem;}}
    [class*="st-key-lgo_"] button, [class*="st-key-vg_pd_"] button {{padding:4px; min-height:0; min-width:0;}}
    /* menu lateral agrupado */
    .pf-navgroup {{color:{p['muted']}; font-size:.72rem; font-weight:600; margin:.9rem 0 0 .35rem;}}
    [data-testid="stSidebar"] [class*="st-key-nav_"] button {{justify-content:flex-start; min-height:34px;
      padding:.25rem .6rem; font-weight:500;}}
    [data-testid="stSidebar"] [class*="st-key-nav_"] button[kind="secondary"] {{background:{p['soft']};
      border-color:transparent; color:{p['primary']}; font-weight:650;}}
    [data-testid="stSidebar"] [class*="st-key-nav_"] {{margin-top:-.7rem;}}
    .st-key-vg_hoje [data-testid="stHorizontalBlock"], .st-key-gs_rank [data-testid="stHorizontalBlock"]
      {{flex-wrap:nowrap; gap:4px;}}
    .st-key-vg_hoje [data-testid="stColumn"], .st-key-gs_rank [data-testid="stColumn"] {{min-width:0 !important;}}
    .st-key-vg_hoje [data-testid="stColumn"]:last-child, .st-key-gs_rank [data-testid="stColumn"]:last-child
      {{flex:0 0 32px !important; width:32px !important;}}
    /* textos */
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{max-width:76ch; line-height:1.55;
                                                                             color:{p['muted']};}}
    [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {{line-height:1.6;}}
    [data-testid="stMarkdownContainer"] ul, [data-testid="stMarkdownContainer"] ol {{padding-left:1.3rem;}}
    [data-testid="stMarkdownContainer"] li {{margin-bottom:.3rem;}}
    [data-testid="stAlert"] {{border-radius:10px;}}
    /* tabelas */
    .ft-wrap {{background:{p['card']}; border:1px solid {p['line']}; border-radius:10px; overflow:auto;
               max-height:560px;}}
    .ft {{border-collapse:separate; border-spacing:0; width:100%; font-size:.875rem; font-variant-numeric:tabular-nums;}}
    .ft th {{position:sticky; top:0; background:{p['card']}; color:{p['muted']}; font-size:.75rem; font-weight:600;
             text-align:left; padding:10px 14px; border-bottom:1px solid {p['line']}; white-space:nowrap; z-index:1;}}
    .ft td {{padding:9px 14px; border-bottom:1px solid {p['line']}; vertical-align:top; line-height:1.45;}}
    .ft td:not(.wrap):not(.c0) {{white-space:nowrap;}}
    .ft td.wrap {{min-width:150px; overflow-wrap:anywhere;}}
    .ft tbody tr:last-child td {{border-bottom:0;}}
    .ft tbody tr:hover td {{background:{p['hover']};}}
    .ft .num {{text-align:right; white-space:nowrap;}}
    .ft td.neg {{color:{p['crit_text']};}}
    .ft td.c0 {{font-weight:600;}}
    .ft .row_heading {{font-weight:600; text-align:left; padding:9px 14px; border-bottom:1px solid {p['line']};}}
    .ft-empty {{color:{p['muted']}; padding:18px 4px;}}

    /* ---------- componentes do painel (prefixo pf-) ---------- */
    .pf-ico {{font-family:'Material Symbols Rounded'; font-weight:400; font-style:normal; font-size:1.15em; line-height:1;
              display:inline-block; vertical-align:-0.18em; letter-spacing:normal; text-transform:none; white-space:nowrap;
              direction:ltr; -webkit-font-feature-settings:'liga'; font-feature-settings:'liga';
              -webkit-font-smoothing:antialiased;}}
    .pf-eyebrow {{color:{p['muted']}; font-size:.8rem; font-weight:600; margin:0;}}
    .pf-hero {{margin:.1rem 0 .2rem 0;}}
    .pf-hero .v {{font-size:clamp(2.2rem, 5vw, 3.1rem); font-weight:680; letter-spacing:-0.03em; line-height:1.05;
                  color:{p['text']};}}
    .pf-hero .v small {{font-size:.45em; font-weight:600; color:{p['muted']}; letter-spacing:0; margin-right:.25em;}}
    .pf-hero .n {{color:{p['sec']}; font-size:.9rem; margin-top:.45rem; line-height:1.5;}}
    .pf-scope {{color:{p['muted']}; font-size:.8rem; line-height:1.45; margin:.1rem 0 .3rem 0;}}
    .pf-delta {{font-weight:600; white-space:nowrap;}}
    .pf-delta.up {{color:{p['crit_text']};}} .pf-delta.down {{color:{p['good_text']};}}
    /* etiqueta de estado: ícone + texto; a forma do ícone muda com o estado (funciona em preto e branco) */
    .pf-badge {{display:inline-flex; align-items:center; gap:4px; font-size:.75rem; font-weight:600; line-height:1;
                padding:3px 8px 3px 6px; border-radius:99px; white-space:nowrap; cursor:default;}}
    .pf-badge.late {{background:{p['crit_soft']}; color:{p['crit_text']};}}
    .pf-badge.soon {{background:{p['warn_soft']}; color:{p['warn_text']};}}
    .pf-badge.ok {{background:{p['good_soft']}; color:{p['good_text']};}}
    .pf-badge.info {{background:{p['hover']}; color:{p['sec']};}}
    /* marca de instituição / ícone de categoria: reconhecer antes de ler */
    .pf-mark {{display:inline-flex; align-items:center; justify-content:center; width:30px; height:30px; flex:0 0 30px;
               border-radius:8px; font-size:.72rem; font-weight:700; letter-spacing:-0.02em;
               background:{p['hover']}; color:{p['sec']}; box-shadow:inset 0 0 0 1px rgba(128,128,128,.28);}}
    .pf-mark .pf-ico {{font-size:1.15rem; vertical-align:0;}}
    .pf-mark.sm {{width:22px; height:22px; flex-basis:22px; border-radius:6px; font-size:.6rem;}}
    /* linha de item: marca · título e detalhe · etiqueta · valor */
    .pf-row {{display:flex; align-items:center; gap:10px; padding:7px 0; min-height:44px;}}
    .pf-row .t {{flex:1 1 auto; min-width:0;}}
    .pf-row .t b {{display:block; font-weight:600; font-size:.9rem; color:{p['text']}; line-height:1.3;}}
    .pf-row .t .pf-badge {{display:inline-flex; margin-top:4px;}}
    .pf-row .t > span:not(.pf-badge) {{display:block; color:{p['muted']}; font-size:.78rem; line-height:1.35;}}
    .pf-row .val {{font-variant-numeric:tabular-nums; font-weight:650; font-size:.95rem; white-space:nowrap;
                   text-align:right; color:{p['text']};}}
    .pf-row .val span {{display:block; font-weight:500; font-size:.75rem; color:{p['muted']};}}
    .pf-row .val.in {{color:{p['good_text']};}}
    /* extrato: lançamentos agrupados por dia; todos os campos na própria linha, sem rolagem lateral */
    .pf-day {{display:flex; justify-content:space-between; align-items:baseline; gap:10px; padding:16px 0 6px 0;
              border-bottom:1px solid {p['line']}; font-size:.78rem; font-weight:600; color:{p['sec']};}}
    .pf-day:first-child {{padding-top:4px;}}
    .pf-day span {{font-variant-numeric:tabular-nums; color:{p['muted']}; font-weight:500; white-space:nowrap;}}
    .pf-ledger .pf-row .t b {{overflow-wrap:anywhere;}}
    /* passo numerado de um cadastro */
    .pf-step {{display:flex; align-items:center; gap:8px; font-weight:600; font-size:.92rem; color:{p['text']};
               margin:.7rem 0 0 0;}}
    .pf-step span {{display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px;
                    border-radius:99px; background:{p['hover']}; color:{p['sec']}; font-size:.75rem; font-weight:700;}}
    .pf-sep {{border:0; border-top:1px solid {p['line']}; margin:0;}}
    /* barras ordenadas (composição / comparação) */
    .pf-bars {{display:grid; grid-template-columns:auto fit-content(13em) minmax(40px, 1fr) auto; gap:7px 10px;
               align-items:center; font-size:.875rem;}}
    .pf-bars .lab {{overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:{p['text']};}}
    .pf-bars .trk {{height:8px; border-radius:4px; background:{p['hover']}; overflow:hidden;}}
    .pf-bars .trk i {{display:block; height:100%; border-radius:4px; background:{p['out']};}}
    .pf-bars .num {{font-variant-numeric:tabular-nums; text-align:right; white-space:nowrap; font-weight:600;}}
    .pf-bars .num span {{color:{p['muted']}; font-weight:500; margin-left:6px; font-size:.78rem;}}
    /* linha de ranking clicável: mesma leitura das barras, uma linha por vez (a seta fica ao lado) */
    .pf-brow {{display:flex; align-items:center; gap:10px; min-height:40px; font-size:.875rem; width:100%;}}
    .pf-brow .body {{flex:1 1 auto; min-width:0;}}
    .pf-brow .top {{display:flex; align-items:baseline; justify-content:space-between; gap:10px;}}
    .pf-brow .lab {{flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
                    color:{p['text']};}}
    .pf-brow .num {{flex:0 0 auto; font-variant-numeric:tabular-nums; white-space:nowrap; font-weight:600;}}
    .pf-brow .num span {{display:inline-block; min-width:2.4em; text-align:right; color:{p['muted']}; font-weight:500;
                         margin-left:6px; font-size:.78rem;}}
    .pf-brow .trk {{height:4px; border-radius:2px; background:{p['hover']}; overflow:hidden; margin-top:5px;}}
    .pf-brow .trk i {{display:block; height:100%; border-radius:2px; background:{p['out']};}}
    .st-key-gs_rank [data-testid="stHtml"], .st-key-gs_rank [data-testid="stColumn"]:first-child > div {{width:100%;}}
    .pf-brow.on .lab {{font-weight:700;}}
    .pf-brow.on .pf-mark {{background:{p['soft']}; color:{p['primary']}; box-shadow:inset 0 0 0 1.5px {p['primary']};}}
    .st-key-gs_rank {{gap:.2rem;}}
    /* barra de progresso com rótulo */
    .pf-prog {{height:8px; border-radius:4px; background:{p['hover']}; overflow:hidden; margin:4px 0;}}
    .pf-prog i {{display:block; height:100%; border-radius:4px; background:{p['primary']};}}
    @media (max-width:640px) {{
      /* tabela vira ficha: um registro por bloco, cada campo com seu rótulo (nada cortado no celular) */
      .ft thead {{display:none;}}
      .ft, .ft tbody, .ft tr {{display:block; width:100%;}}
      .ft tr {{padding:8px 0; border-bottom:1px solid {p['line']};}}
      .ft tbody tr:last-child {{border-bottom:0;}}
      .ft td {{display:flex; justify-content:space-between; gap:14px; padding:3px 14px; border-bottom:0;
               white-space:normal !important; text-align:right; min-width:0 !important;}}
      .ft td::before {{content:attr(data-l); color:{p['muted']}; font-size:.75rem; font-weight:500; text-align:left;
                       flex:0 0 auto; white-space:nowrap;}}
      .ft td.e {{display:none;}}
      .pf-bars {{grid-template-columns:auto 1fr auto;}} .pf-bars .trk {{display:none;}}
      .block-container {{padding-left:1rem; padding-right:1rem;}}
    }}
    </style>""", unsafe_allow_html=True)


def style_figure(fig) -> None:
    """Estilo comum dos gráficos Plotly: fundo transparente, grade discreta, números no formato brasileiro."""
    p = palette()
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", separators=",.",
                      font=dict(family=FONT, color=p["muted"], size=12),
                      hoverlabel=dict(bgcolor=p["card"], bordercolor=p["line"], font=dict(family=FONT, color=p["text"])),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                                  font=dict(color=p["sec"])))
    fig.update_yaxes(gridcolor=p["grid"], linecolor=p["axis"], title_font=dict(color=p["muted"], size=11))
    fig.update_xaxes(linecolor=p["axis"], title_font=dict(color=p["muted"], size=11))
    fig.update_traces(selector=dict(type="bar"), marker_cornerradius=4, marker_line_width=0)


# ------------------------------------------------------------------ componentes
_E = _html.escape

# Ícone por categoria (Material Symbols, já embutido no Streamlit: nada é baixado de fora).
CATEGORY_ICONS = {
    "moradia": "home", "mercado": "shopping_cart", "compras online": "local_mall", "saúde": "medical_services",
    "viagem": "flight", "compra de produtos": "devices", "carro - combustível": "local_gas_station",
    "carro": "directions_car", "alimentação fora": "restaurant", "lazer": "theater_comedy", "energia": "bolt",
    "água": "water_drop", "telefone/internet": "wifi", "transporte": "commute", "assinaturas": "autorenew",
    "presentes e doações": "redeem", "educação": "school", "investimento": "trending_up", "salário": "work",
    "outros": "more_horiz",
}
# Marca de instituição: monograma em bloco (não é o logotipo oficial). Cor só ajuda; as letras identificam.
INSTITUTIONS = {"inter": ("In", "#F26A1B", "#FFFFFF"), "xp": ("XP", "#1B1B1B", "#FFFFFF"),
                "binance": ("Bn", "#F0B90B", "#1B1B1B")}
INSTITUTION_NAMES = {"inter": "Inter", "xp": "XP", "binance": "Binance", "pluggy": "Pluggy"}


def icon(name: str) -> str:
    return f'<span class="pf-ico" aria-hidden="true">{_E(name)}</span>'


def category_icon(category: str) -> str:
    c = str(category or "").lower()
    for key, ico in CATEGORY_ICONS.items():
        if c.startswith(key):
            return ico
    return "label"


def mark(name: str, kind: str = "institution", small: bool = False) -> str:
    """Bloco de reconhecimento: monograma da instituição ou ícone da categoria."""
    cls = "pf-mark sm" if small else "pf-mark"
    if kind == "icon":
        return f'<span class="{cls}">{icon(name)}</span>'
    if kind == "category":
        return f'<span class="{cls}" title="{_E(str(name))}">{icon(category_icon(name))}</span>'
    key = str(name or "").strip().lower()
    txt, bg, fg = INSTITUTIONS.get(key, ((str(name or "?")[:2]).title(), None, None))
    style = f' style="background:{bg};color:{fg}"' if bg else ""
    return f'<span class="{cls}"{style} title="{_E(institution_name(name))}">{_E(txt)}</span>'


def institution_name(name) -> str:
    return INSTITUTION_NAMES.get(str(name or "").strip().lower(), str(name or "").strip().title())


_BADGE_ICONS = {"late": "error", "soon": "schedule", "ok": "check_circle", "info": "info"}


def badge(text: str, kind: str = "info") -> str:
    """Etiqueta de estado (não é botão). kind: late (atrasado) · soon (atenção) · ok · info."""
    return f'<span class="pf-badge {kind}">{icon(_BADGE_ICONS.get(kind, "info"))}{_E(text)}</span>'


def due_badge(due, ref, paid: bool = False) -> str:
    """Estado de um vencimento em relação à data de referência: mesma regra e mesmo texto em todas as telas."""
    days = (due - ref).days
    if paid:
        return badge("Paga", "ok")
    if days < 0:
        return badge(f"Atrasada há {-days} dia{'s' if days < -1 else ''}", "late")
    if days == 0:
        return badge("Vence hoje", "soon")
    if days <= 7:
        return badge(f"Vence em {days} dia{'s' if days > 1 else ''}", "soon")
    return badge(f"Em {days} dias", "info")


def money_html(text: str) -> str:
    """'R$ 1.234,56' com o 'R$' menor, para o número principal."""
    t = _E(text)
    return t.replace("R$ ", "<small>R$</small>", 1) if t.startswith("R$ ") else t


def hero(label: str, value: str, note_html: str = "") -> None:
    """Número dominante da tela: um por tela."""
    st.html(f'<p class="pf-eyebrow">{_E(label)}</p><div class="pf-hero"><div class="v">{money_html(value)}</div>'
            + (f'<div class="n">{note_html}</div>' if note_html else "") + "</div>")


def step(n: int | str, title: str) -> None:
    """Título de um passo numerado dentro de um cadastro."""
    st.html(f'<p class="pf-step"><span>{_E(str(n))}</span>{_E(title)}</p>')


def scope(text: str) -> None:
    """Frase curta que diz até onde vai o efeito de um filtro (ou a data de referência de um bloco)."""
    st.html(f'<p class="pf-scope">{_E(text)}</p>')


def row_html(mark_html: str, title: str, sub: str = "", value: str = "", value_sub: str = "",
             badge_html: str = "", value_class: str = "", badge_below: bool = False) -> str:
    v = (f'<div class="val {value_class}">{_E(value)}' + (f"<span>{_E(value_sub)}</span>" if value_sub else "")
         + "</div>") if value else ""
    return (f'<div class="pf-row">{mark_html}<div class="t"><b>{_E(title)}</b>'
            + (f"<span>{_E(sub)}</span>" if sub else "") + (badge_html if badge_below else "")
            + f"</div>{'' if badge_below else badge_html}{v}</div>")


def rows(items: list[str]) -> None:
    """Lista de linhas de item separadas por fio."""
    st.html('<hr class="pf-sep">'.join(items))


def bars(items: list[dict], color: str | None = None) -> None:
    """Barras horizontais ordenadas. items: {label, value, text, sub?, icon?}; largura proporcional ao maior."""
    top = max((abs(i["value"]) for i in items), default=0) or 1
    bg = f";background:{color}" if color else ""
    cells = []
    for i in items:
        w = max(2.0, 100 * abs(i["value"]) / top)
        cells.append(f'{mark(i.get("icon", i["label"]), i.get("kind", "category"), small=True)}'
                     f'<span class="lab" title="{_E(i["label"])}">{_E(i["label"])}</span>'
                     f'<span class="trk"><i style="width:{w:.1f}%{bg}"></i></span>'
                     f'<span class="num">{_E(i["text"])}' + (f'<span>{_E(i["sub"])}</span>' if i.get("sub") else "")
                     + "</span>")
    st.html(f'<div class="pf-bars">{"".join(cells)}</div>')


def bar_row_html(label: str, value: float, top: float, text: str, sub: str = "", selected: bool = False) -> str:
    """Uma linha de ranking (ícone, nome, barra, valor) para ficar ao lado de um botão de abrir o detalhe."""
    w = max(2.0, 100 * abs(value) / (top or 1))
    return (f'<div class="pf-brow{" on" if selected else ""}">{mark(label, "category", small=True)}'
            f'<div class="body"><div class="top"><span class="lab" title="{_E(label)}">{_E(label)}</span>'
            f'<span class="num">{_E(text)}' + (f"<span>{_E(sub)}</span>" if sub else "") + "</span></div>"
            f'<div class="trk"><i style="width:{w:.1f}%"></i></div></div></div>')


def progress(frac: float, label: str = "") -> None:
    frac = min(1.0, max(0.0, float(frac or 0)))
    st.html((f'<p class="pf-scope" style="margin-bottom:2px">{_E(label)}</p>' if label else "")
            + f'<div class="pf-prog"><i style="width:{100 * frac:.1f}%"></i></div>')


_WEEK = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
_MON = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def day_html(d, total_text: str) -> str:
    """Cabeçalho de um dia no extrato: data e dia da semana à esquerda, total do dia à direita."""
    return (f'<div class="pf-day">{d.day} {_MON[d.month - 1]} {d.year} · {_WEEK[d.weekday()]}'
            f"<span>{_E(total_text)}</span></div>")


def ledger(items: list[dict], fmt, limit: int = 300) -> int:
    """Extrato: lançamentos agrupados por dia, do mais recente para o mais antigo, com o total do dia.

    items (já ordenados): {date, title, sub, category, value, value_class?}. `fmt` formata dinheiro.
    Mostra no máximo `limit` linhas e devolve quantas mostrou."""
    if not items:
        st.html('<div class="ft-empty">Nada para mostrar ainda.</div>')
        return 0
    totals: dict = {}
    for i in items:
        totals[i["date"]] = totals.get(i["date"], 0.0) + i["value"]
    out, last = [], None
    for i in items[:limit]:
        d = i["date"]
        if d != last:
            out.append(f'<div class="pf-day">{d.day} {_MON[d.month - 1]} {d.year} · {_WEEK[d.weekday()]}'
                       f"<span>{_E(fmt(totals[d]))}</span></div>")
        elif out:
            out.append('<hr class="pf-sep">')
        last = d
        out.append(row_html(mark(i["category"], "category"), i["title"], i.get("sub", ""), fmt(i["value"]),
                            value_class=i.get("value_class", "")))
    st.html(f'<div class="pf-ledger">{"".join(out)}</div>')
    return min(len(items), limit)


_FIELD = re.compile(r"\{([^{}]+)\}")


def listing(data, title: str, value: str = "", value_sub: str = "", sub: list[str] | None = None,
            icon: tuple[str, str] = ("icon", "label"), badge=None, table: str | None = None,
            key: str | None = None, **_ignored) -> None:
    """Lista de registros no lugar da tabela: um registro por linha, com todos os campos, sem rolagem lateral.

    Os textos são modelos com o nome da coluna entre chaves ("faltam {faltam} de {parcelas}"); um trecho some
    quando algum campo dele está vazio. `sub=None` lista os campos restantes como "Rótulo: valor".
    `badge(linha)` devolve o HTML de uma etiqueta. `table="nome"` oferece a mesma informação em tabela, num expansor."""
    styler = data if hasattr(data, "to_html") and hasattr(data, "data") else data.style
    df = styler.data
    if len(df) == 0:
        st.html('<div class="ft-empty">Nada para mostrar ainda.</div>')
        return
    raw = styler.hide(axis="index").to_html()
    names = [str(c) for c in df.columns]
    grid: dict = {}
    for r, c, t in _TD.findall(raw[raw.index("<table"):]):
        grid.setdefault(int(r), {})[names[int(c)]] = _cell(t)

    def fill(tpl: str, row: dict) -> str:
        missing = []

        def rep(m):
            v = row.get(m[1], "")
            if not v:
                missing.append(m[1])
            return v
        out = _FIELD.sub(rep, tpl)
        return "" if missing else out

    used = set(_FIELD.findall(" ".join([title, value, value_sub, icon[1]] + (sub or []))))
    items = []
    for r in sorted(grid)[:300]:
        row = grid[r]
        parts = ([fill(t, row) for t in sub] if sub is not None
                 else [f"{_pretty(n)}: {row[n]}" for n in names if n not in used and row.get(n)])
        mk = mark(fill(icon[1], row) or "label", icon[0]) if icon[0] != "icon" else mark(icon[1], "icon")
        items.append(row_html(mk, fill(title, row) or "—", " · ".join(x for x in parts if x), fill(value, row),
                              fill(value_sub, row), badge_html=badge(row) if badge else "", badge_below=True))
    rows(items)
    if len(grid) > 300:
        scope(f"Aparecem as 300 primeiras linhas de {len(grid)}.")
    if table:
        with st.expander(f"Ver {table} em tabela", icon=":material/table_rows:"):
            globals()["table"](data, key=key)


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


_HEADERS = {"date": "data", "description": "descrição", "counterparty": "contraparte", "category": "categoria",
            "month": "mês", "kind": "tipo", "odometer": "odômetro (km)", "liters": "litros", "full_tank": "tanque cheio",
            "trip": "uso", "amount": "valor", "note": "obs", "at": "quando", "source": "fonte", "message": "mensagem",
            "value": "valor", "institution": "instituição", "installment_number": "parcela",
            "total_installments": "de", "id": "nº", "ok": "deu certo"}


def _pretty(name) -> str:
    s = _HEADERS.get(str(name).lower(), str(name)).replace("_", " ")
    return s[:1].upper() + s[1:]


def table(data, hide_index: bool = True, max_rows: int = 250, key: str | None = None, **_ignored) -> None:
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

    heads = {int(c): _pretty(_html.unescape(h)) for c, h in _TH.findall(body)}
    order = list(range(ncols))
    # Botão "Colunas": quem usa escolhe quais campos aparecem e em que ordem (vale até fechar o painel).
    if hide_index and ncols >= 3 and len(set(heads.values())) == ncols == len(heads):
        names = [heads[c] for c in range(ncols)]
        wkey = key or "cols_" + hashlib.md5("|".join(names).encode()).hexdigest()[:10]
        with st.popover("Colunas", icon=":material/view_column:"):
            picked = st.multiselect("Campos que aparecem", names, default=names, key=wkey,
                                    help="A ordem da lista é a ordem das colunas. Para mudar um campo de lugar, "
                                         "tire-o e escolha de novo: ele vai para o fim.")
            st.caption("Vale só para esta tabela e até você fechar o painel. Nenhum dado é apagado.")
        order = [names.index(n) for n in picked] or order

    def td(r, c, t):
        cls = ["num"] if c in numeric else []
        if c in numeric and t[:1] in "-−":
            cls.append("neg")
        if c == order[0]:
            cls.append("c0")
        if len(t) > 22 and c not in numeric:
            cls.append("wrap")
        if not t:
            cls.append("e")
        return f'<td class="{" ".join(cls)}" data-l="{_html.escape(heads.get(c, ""))}">{_html.escape(t)}</td>'

    if hide_index and len(heads) == ncols:
        grid: dict = {}
        for r, c, t in cells:
            grid.setdefault(r, {})[c] = t
        head = "".join(f'<th class="{"num" if c in numeric else ""}">{_html.escape(heads[c])}</th>' for c in order)
        rows_ = "".join("<tr>" + "".join(td(r, c, grid[r].get(c, "")) for c in order) + "</tr>" for r in sorted(grid))
        st.html(f'<div class="ft-wrap"><table class="ft"><thead><tr>{head}</tr></thead><tbody>{rows_}</tbody></table></div>')
        return

    body = _TD.sub(lambda m: td(int(m[1]), int(m[2]), _cell(m[3])), body)
    body = _TH.sub(lambda m: f'<th class="{"num" if int(m[1]) in numeric else ""}">'
                             f'{_html.escape(_pretty(_html.unescape(m[2])))}</th>', body)
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
