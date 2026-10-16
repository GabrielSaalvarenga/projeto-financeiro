"""Gravação das contas de consumo (Cemig / Cesama) com o detalhe de cada fatura.

Fontes: PDF da Cemig (`cemig_pdf`), JSON da API da Cesama (agência virtual) e o formulário manual do painel.
Tudo cai em `utility_bills`; o que não tem coluna própria fica no JSON `details`.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..db import log_sync
from . import cemig_pdf

COLS = ("provider", "ref_month", "due_date", "amount", "consumption", "unit", "file", "issue_date", "paid_date",
        "days", "tariff_untaxed", "energy_value", "icms", "pis", "cofins", "taxes_total", "public_lighting", "flag",
        "flag_value", "other_fees", "note")


def save(conn, bill: dict) -> None:
    row = {c: bill.get(c) for c in COLS}
    row["details"] = json.dumps({k: v for k, v in bill.items() if k not in COLS}, ensure_ascii=False, default=str)
    conn.execute(
        f"INSERT INTO utility_bills({', '.join(row)}) VALUES ({', '.join(':' + c for c in row)}) "
        f"ON CONFLICT(provider, ref_month) DO UPDATE SET "
        + ", ".join(f"{c}=excluded.{c}" for c in row if c not in ("provider", "ref_month")), row)


def cemig_bill(path: Path) -> dict:
    b = cemig_pdf.parse(path)
    b["other_fees"] = round(sum(i["valor"] for i in b.get("other_items", [])), 2)
    return b


def import_cemig_dir(conn, folder: Path) -> list[dict]:
    out = []
    for pdf in sorted(folder.glob("*.pdf")):
        b = cemig_bill(pdf)
        if b.get("ref_month") and b.get("amount"):
            save(conn, b)
            out.append(b)
        else:
            log_sync(conn, "cemig", False, f"{pdf.name}: não reconheci valor/mês — lançar manualmente")
    log_sync(conn, "cemig", True, f"{len(out)} fatura(s) de {folder.name}")
    return out


def import_cesama_json(conn, path: Path) -> list[dict]:
    """JSON salvo da agência virtual da Cesama: faturas pagas + leituras do hidrômetro."""
    data = json.loads(path.read_text())
    reads = {r["ref"]: r for r in data.get("leituras", [])}
    out = []
    for f in data.get("faturas", []):
        r = reads.get(f["ref"], {})
        b = {"provider": "cesama", "unit": "m3", "file": path.name, "ref_month": f["ref"], "due_date": f.get("venc"),
             "issue_date": f.get("emissao"), "paid_date": f.get("pago_em"), "amount": f.get("valor"),
             "consumption": r.get("consumo_m3"), "read_date": r.get("data_leitura"), "meter": r.get("leitura"),
             "avg_m3": r.get("media_m3"), "read_status": r.get("situacao")}
        if b["read_status"] and "REGISTRADA" not in b["read_status"]:
            b["note"] = b["read_status"].title()
        save(conn, b)
        out.append(b)
    log_sync(conn, "cesama", True, f"{len(out)} fatura(s) de {path.name}")
    return out
