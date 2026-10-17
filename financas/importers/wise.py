"""Importação única do extrato CSV da Wise (contas EUR + BRL) — viagem de 2026.

Regras aprovadas pelo dono do painel (2026-10-14):
- Valores em EUR convertidos pelo CUSTO EFETIVO: BRL depositado ÷ EUR obtido nas conversões (tarifas incluídas).
- Compras no cartão → "Viagem", já descontados os estornos (débito + crédito iguais do mesmo comerciante se anulam).
- FNAC = MacBook M5 (€ 1.060, líquido do TaxFree) + fone Sony (resto) → "Compra de produtos".
- Envios a terceiros → "Viagem" (só nesta importação).
- Devolução ao Inter → não é gasto; a diferença de câmbio na volta → "Viagem".
- Depósitos BRL e conversões BRL→EUR não são importados (é o mesmo dinheiro mudando de moeda).
Todas as categorias são gravadas como correção manual (não mudam ao recategorizar).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import os

import pandas as pd

from ..db import log_sync

ACCOUNT_ID = "wise:viagem-2026"
MAC_EUR = 1060.00
# nome do titular como aparece nos envios da Wise (devolução para a própria conta não é gasto)
OWNER_NAME = os.getenv("FIN_OWNER_NAME", "")


def _id(*parts) -> str:
    return "wise:" + hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16]


def plan(folder: Path) -> tuple[list[dict], dict]:
    eur = pd.read_csv(next(folder.glob("*EUR*.csv")))
    brl = pd.read_csv(next(folder.glob("*BRL*.csv")))
    for d in (eur, brl):
        d["date"] = pd.to_datetime(d["Date"], format="%d-%m-%Y").dt.date.astype(str)

    deposited = brl.loc[brl["Transaction Details Type"] == "DEPOSIT", "Amount"].sum()
    bought = eur.loc[eur["Transaction Details Type"] == "CONVERSION", "Amount"].sum()
    rate = deposited / bought

    card = eur[eur["Transaction Details Type"] == "CARD"].copy()
    taxfree = card[card["Merchant"].str.contains("taxfree", case=False, na=False)]
    fnac = card[card["Merchant"].str.contains("fnac", case=False, na=False)]
    trip = card.drop(index=taxfree.index.union(fnac.index))

    # estornos: cada crédito anula um débito de mesmo comerciante e valor
    drop = set()
    for i, cr in trip[trip["Amount"] > 0].iterrows():
        match = trip[(trip["Amount"] == -cr["Amount"]) & (trip["Merchant"] == cr["Merchant"]) & ~trip.index.isin(drop)]
        if not match.empty:
            drop |= {i, match.index[0]}
    trip = trip.drop(index=list(drop))

    rows: list[dict] = []

    def add(date, desc, eur_amount, category, key):
        rows.append({"id": _id(key), "date": date, "description": desc,
                     "amount": round(eur_amount * rate, 2), "category": category})

    for _, r in trip.iterrows():
        add(r["date"], f"{r['Merchant']} (€ {abs(r['Amount']):.2f})", r["Amount"], "Viagem", r["TransferWise ID"])

    tf = taxfree["Amount"].sum()
    f = fnac.iloc[0]
    add(f["date"], f"MacBook M5 — FNAC (€ {MAC_EUR:.2f} − TaxFree € {tf:.2f})", -(MAC_EUR - tf),
        "Compra de produtos", f"{f['TransferWise ID']}-mac")
    add(f["date"], f"Fone Sony — FNAC (€ {abs(f['Amount']) - MAC_EUR:.2f})", -(abs(f["Amount"]) - MAC_EUR),
        "Compra de produtos", f"{f['TransferWise ID']}-sony")

    transfers = eur[eur["Transaction Details Type"] == "TRANSFER"]
    own = transfers[transfers["Description"].str.contains(OWNER_NAME, case=False, na=False, regex=False)] if OWNER_NAME \
        else transfers.iloc[0:0]
    others = transfers.drop(index=own.index)
    for _, r in others.iterrows():
        name = r["Description"].replace("Enviou dinheiro para ", "").title()
        add(r["date"], f"Envio para {name} (€ {abs(r['Amount']):.2f})", r["Amount"], "Viagem", r["TransferWise ID"])
    for _, r in own.iterrows():  # devolução ao Inter: só a perda de câmbio é custo
        loss_brl = abs(r["Amount"]) * rate - r["Exchange To Amount"]
        rows.append({"id": _id(r["TransferWise ID"], "fx"), "date": r["date"],
                     "description": f"Perda de câmbio na devolução ao Inter (€ {abs(r['Amount']):.2f} → "
                                    f"R$ {r['Exchange To Amount']:.2f})",
                     "amount": -round(loss_brl, 2), "category": "Viagem"})

    summary = {"deposited": deposited, "eur": bought, "rate": rate, "taxfree": tf, "n": len(rows),
               "by_category": pd.DataFrame(rows).groupby("category")["amount"].sum().round(2).to_dict()}
    return rows, summary


def import_folder(conn, folder: Path) -> dict:
    rows, summary = plan(folder)
    conn.execute("INSERT OR IGNORE INTO accounts(id, source, institution, name, type, balance, balance_date) "
                 "VALUES (?,?,?,?,?,?,?)", (ACCOUNT_ID, "wise", "Wise", "Wise – viagem 2026", "BANK", 0.0,
                                             max(r["date"] for r in rows)))
    for r in rows:
        conn.execute("INSERT OR REPLACE INTO transactions(id, account_id, source, date, description, amount, category, "
                     "manual_category) VALUES (?,?,?,?,?,?,?,?)",
                     (r["id"], ACCOUNT_ID, "wise", r["date"], r["description"], r["amount"], r["category"],
                      r["category"]))
    log_sync(conn, "wise", True, f"{summary['n']} lançamentos (câmbio efetivo R$ {summary['rate']:.4f}/€)")
    return summary
