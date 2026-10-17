"""Gravação das contas de consumo (Cemig / Cesama) com o detalhe de cada fatura.

Fontes: PDF da Cemig (`cemig_pdf`), JSON da API da Cesama (agência virtual) e o formulário manual do painel.
Tudo cai em `utility_bills`; o que não tem coluna própria fica no JSON `details`.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..db import log_sync
from . import cemig_pdf, cesama_pdf

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


def cesama_bill(path: Path) -> dict:
    return cesama_pdf.parse(path)


def cemig_bill(path: Path) -> dict:
    b = cemig_pdf.parse(path)
    b["other_fees"] = round(sum(i["valor"] for i in b.get("other_items", [])), 2)
    return b


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


def load(conn, provider: str, ref_month: str | None = None, before: str | None = None) -> dict | None:
    """Uma conta já gravada (colunas + `details` abertos): a do mês, ou a última antes de `before`."""
    if ref_month:
        r = conn.execute("SELECT * FROM utility_bills WHERE provider=? AND ref_month=?", (provider, ref_month)).fetchone()
    else:
        r = conn.execute("SELECT * FROM utility_bills WHERE provider=? AND ref_month<? ORDER BY ref_month DESC LIMIT 1",
                         (provider, before)).fetchone()
    if not r:
        return None
    b = {k: r[k] for k in r.keys() if k not in ("id", "details")}
    b.update(json.loads(r["details"] or "{}"))
    return b


def merge(conn, bill: dict) -> dict:
    """A conta do mês já gravada com os campos preenchidos de `bill` por cima (vazio não apaga)."""
    b = load(conn, bill["provider"], bill["ref_month"]) or {}
    b.update({k: v for k, v in bill.items() if v not in (None, "")})
    return b


def manual(conn, bill: dict) -> dict:
    """Conta lançada no formulário do painel.

    Campo vazio (None/"") não apaga o que já existe: a conta do mês é mesclada com o que veio do PDF/API.
    Os derivados (consumo, dias, tarifa, impostos, outros itens) são recalculados a partir do que foi informado.
    """
    p, ref = bill["provider"], bill["ref_month"]
    b = merge(conn, {"file": "manual", **bill}) if not load(conn, p, ref) else merge(conn, bill)
    b["unit"] = "kWh" if p == "cemig" else "m3"
    for k in ("due_date", "issue_date", "paid_date", "read_date"):
        if hasattr(b.get(k), "isoformat"):
            b[k] = b[k].isoformat()
    if p == "cemig":
        _derive_cemig(b)
    else:
        prev = load(conn, p, before=ref)
        if b.get("meter") is not None and prev and prev.get("meter") is not None:
            b["consumption"] = b["meter"] - prev["meter"]
    save(conn, b)
    return b


def _derive_cemig(b: dict) -> None:
    if b.get("meter_prev") is not None and b.get("meter_curr") is not None:
        b["consumption"] = b["meter_curr"] - b["meter_prev"]
    d0, d1 = b.pop("read_prev_date", None), b.pop("read_curr_date", None)
    if d0 and d1:
        b["days"] = (d1 - d0).days
        b["read_prev"], b["read_curr"] = d0.strftime("%d/%m"), d1.strftime("%d/%m")
    kwh = b.get("consumption")
    if b.get("energy_untaxed") is not None and kwh:
        b["tariff_untaxed"] = round(b["energy_untaxed"] / kwh, 5)
    if any(b.get(t) is not None for t in ("icms", "pis", "cofins")):
        b["taxes_total"] = round(sum(b.get(t) or 0 for t in ("icms", "pis", "cofins")), 2)
        if b.get("energy_untaxed") is not None:
            b["energy_value"] = round(b["energy_untaxed"] + b["taxes_total"], 2)
    if "other_items" in b:
        b["other_fees"] = round(sum(i["valor"] for i in b["other_items"]), 2)


def total_gap(b: dict) -> float | None:
    """Total da fatura menos a soma das partes. Cemig: energia com impostos + iluminação + outros itens;
    Cesama: água + esgoto + outros itens (fundo municipal). None quando faltam as partes."""
    if b.get("amount") is None:
        return None
    if b.get("provider") == "cemig" and b.get("energy_value") is not None:
        parts = b["energy_value"] + (b.get("public_lighting") or 0)
    elif b.get("provider") == "cesama" and b.get("water") is not None:
        parts = b["water"] + (b.get("sewer") or 0)
    else:
        return None
    return round(b["amount"] - parts - (b.get("other_fees") or 0), 2)
