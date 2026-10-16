"""Lê PDFs de contas de consumo (Cemig, Cesama) salvos em data/inbox/<fornecedor>/.

Extração heurística (vencimento, total, consumo, mês de referência). Os padrões
precisam ser calibrados com uma fatura real de cada fornecedor — o que não for
reconhecido fica para lançamento manual na tela "Contas".
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pdfplumber

from ..db import log_sync

MONEY = r"R?\$?\s*(\d{1,3}(?:\.\d{3})*,\d{2})"
DATE = r"(\d{2}/\d{2}/\d{4})"
MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"], start=1)}

PATTERNS = {
    "cemig": {
        "unit": "kWh",
        "due": [rf"Vencimento\s*{DATE}", rf"VENCIMENTO\s*{DATE}"],
        "total": [rf"Valor a pagar.*?{MONEY}", rf"TOTAL A PAGAR.*?{MONEY}", rf"Total\s*{MONEY}"],
        "consumption": [r"Consumo.*?(\d[\d\.]*)\s*kWh", r"(\d[\d\.]*)\s*kWh"],
    },
    "cesama": {
        "unit": "m3",
        "due": [rf"Vencimento\s*{DATE}", rf"VENCIMENTO\s*{DATE}"],
        "total": [rf"Total a pagar.*?{MONEY}", rf"TOTAL.*?{MONEY}", rf"Valor.*?{MONEY}"],
        "consumption": [r"Consumo.*?(\d+)\s*m[³3]", r"(\d+)\s*m[³3]"],
    },
}


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _first(patterns: list[str], text: str) -> str | None:
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1)
    return None


def _ref_month(text: str, due: str | None) -> str | None:
    m = re.search(r"\b(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)[/\s-]*(\d{4})\b", text.upper())
    if m:
        return f"{m.group(2)}-{MONTHS[m.group(1)]:02d}"
    m = re.search(r"Refer[eê]ncia\s*:?\s*(\d{2})/(\d{4})", text, re.IGNORECASE)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    if due:  # fallback: mês anterior ao vencimento
        d = datetime.strptime(due, "%d/%m/%Y")
        y, mth = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
        return f"{y}-{mth:02d}"
    return None


def parse(provider: str, path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    p = PATTERNS[provider]
    due = _first(p["due"], text)
    total = _first(p["total"], text)
    cons = _first(p["consumption"], text)
    return {
        "provider": provider,
        "ref_month": _ref_month(text, due),
        "due_date": datetime.strptime(due, "%d/%m/%Y").date().isoformat() if due else None,
        "amount": _num(total) if total else None,
        "consumption": _num(cons) if cons else None,
        "unit": p["unit"],
        "file": path.name,
    }


def import_inbox(conn, inbox: Path) -> list[dict]:
    results = []
    for provider in PATTERNS:
        for pdf in sorted((inbox / provider).glob("*.pdf")):
            if conn.execute("SELECT 1 FROM utility_bills WHERE file=?", (pdf.name,)).fetchone():
                continue
            if provider == "cemig":  # leitor detalhado (impostos, iluminação, bandeira)
                from .utilities import cemig_bill, save
                bill = cemig_bill(pdf)
                if bill.get("ref_month") and bill.get("amount"):
                    save(conn, bill)
                    log_sync(conn, provider, True, f"{pdf.name}: R$ {bill['amount']:.2f} ({bill['ref_month']})")
                    results.append(bill)
                    continue
            bill = parse(provider, pdf)
            results.append(bill)
            if bill["ref_month"] and bill["amount"]:
                conn.execute(
                    """INSERT OR REPLACE INTO utility_bills(provider, ref_month, due_date, amount, consumption, unit, file)
                       VALUES (:provider,:ref_month,:due_date,:amount,:consumption,:unit,:file)""", bill)
                log_sync(conn, provider, True, f"{pdf.name}: R$ {bill['amount']:.2f} ({bill['ref_month']})")
            else:
                log_sync(conn, provider, False, f"{pdf.name}: não reconheci valor/mês — lançar manualmente")
    return results
