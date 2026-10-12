"""Exporta um resumo para UMA nota do cofre (OBSIDIAN_NOTE). Só escreve com --write."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from . import analytics, config
from .db import session


def brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def render() -> str:
    with session() as conn:
        df = analytics.transactions(conn)
        hold = analytics.latest_holdings(conn)
        fc = analytics.forecast(conn, 3)
        loans = analytics.loan_status(conn)
    today = date.today().isoformat()
    lines = [
        "---", "tipo: visao-geral", 'projeto: "Projeto Financeiro"', f"criado: {today}", f"atualizado: {today}",
        "tags: [visao-geral, automacao, projeto-financeiro]", "---", "",
        "# 📊 Painel Financeiro (automático)", "",
        f"> [!info] Gerado pelo [[Painel Financeiro - App]] em {today}. Não editar à mão — é sobrescrito.", "",
        "## Patrimônio por fonte", "", "| Fonte | Valor | Data |", "|---|---|---|",
    ]
    for src, grp in hold.groupby("source"):
        lines.append(f"| {src} | {brl(grp['value_brl'].sum())} | {grp['snapshot'].iloc[0]} |")
    lines.append(f"| **Total** | **{brl(hold['value_brl'].sum())}** | |")

    sp = analytics.spending(df)
    if not sp.empty:
        last = sorted(sp["month"].unique())[-2:]
        lines += ["", "## Gastos por categoria", "", "| Categoria | " + " | ".join(last) + " |",
                  "|---|" + "---|" * len(last)]
        pv = sp[sp["month"].isin(last)].pivot_table(index="category", columns="month", values="value", aggfunc="sum")
        for cat, row in pv.fillna(0).sort_values(last[-1], ascending=False).iterrows():
            lines.append(f"| {cat} | " + " | ".join(brl(row.get(m, 0)) for m in last) + " |")

    lines += ["", "## Previsão (3 meses)", "", "| Mês | Entradas | Saídas | Saldo |", "|---|---|---|---|"]
    for _, r in fc.iterrows():
        lines.append(f"| {r['month']} | {brl(r['Salário'] + r['A receber (empréstimos)'])} | "
                     f"{brl(r['Saídas previstas'])} | {brl(r['Saldo previsto'])} |")

    if not loans.empty:
        lines += ["", "## Empréstimos a receber", "", "| Pessoa | Emprestado | Recebido | Falta | Próx. venc. |",
                  "|---|---|---|---|---|"]
        for _, r in loans[loans["closed"] == 0].iterrows():
            lines.append(f"| {r['person']} | {brl(r['principal'])} | {brl(r['paid'])} | {brl(r['remaining'])} | "
                         f"{r['next_due'] or '—'} |")
    lines += ["", "---", "Ligações: [[01 - Visão Geral]] · [[Painel Financeiro - App]] · [[Nota de Ouro Projeto Financeiro]]", ""]
    return "\n".join(lines)


def export(dry_run: bool = True) -> str:
    md = render()
    if dry_run or not config.OBSIDIAN_NOTE:
        return md if dry_run else "OBSIDIAN_NOTE não definido no .env"
    Path(config.OBSIDIAN_NOTE).write_text(md, encoding="utf-8")
    return f"Escrito em {config.OBSIDIAN_NOTE}"
