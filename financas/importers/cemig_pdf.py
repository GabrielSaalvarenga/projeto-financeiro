"""Leitor do PDF da fatura Cemig (DANF3E — modelo de 2026, baixado do Cemig Atende).

Extrai consumo, tarifa sem impostos, preço com impostos, cada tributo (R$ e %), contribuição de
iluminação pública, bandeira tarifária e demais itens da fatura. Calibrado com faturas reais.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pdfplumber

MESES = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6, "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10,
         "NOV": 11, "DEZ": 12}
NUM = r"-?\d{1,3}(?:\.\d{3})*,\d+"


def _n(s: str | None) -> float | None:
    return float(s.replace(".", "").replace(",", ".")) if s else None


def _d(s: str | None) -> str | None:
    return datetime.strptime(s, "%d/%m/%Y").date().isoformat() if s else None


def parse(path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        t = "\n".join(p.extract_text() or "" for p in pdf.pages)

    out: dict = {"provider": "cemig", "unit": "kWh", "file": path.name}
    m = re.search(r"\b(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)/(\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(" + NUM + r")", t)
    if m:
        out["ref_month"] = f"{m.group(2)}-{MESES[m.group(1)]:02d}"
        out["due_date"] = _d(m.group(3))
        out["amount"] = _n(m.group(4))
    m = re.search(r"Data de emissão:\s*(\d{2}/\d{2}/\d{4})", t)
    out["issue_date"] = _d(m.group(1)) if m else None

    m = re.search(r"(Residencial|Comercial|Rural|Industrial)\s+\S+\s+(\S+)\s+(\S+)\s+Anterior", t)
    out["tariff_class"] = " ".join(filter(None, [m.group(1), m.group(2), m.group(3)])) if m else None
    m = re.search(r"(Monofásico|Bifásico|Trifásico)\s+(\d{2}/\d{2})\s+(\d{2}/\d{2})\s+(\d+)\s+(\d{2}/\d{2})", t)
    if m:
        out["supply"] = m.group(1)
        out["read_prev"], out["read_curr"], out["days"], out["read_next"] = m.group(2), m.group(3), int(m.group(4)), m.group(5)

    # linha da energia: kWh, quant, preço unit c/ tributos, valor, PIS/COFINS, base ICMS, alíq, ICMS, tarifa s/ tributos
    m = re.search(r"Energia Elétrica kWh\s+(\d+)\s+(" + NUM + r")\s+(" + NUM + r")\s+(" + NUM + r")\s+(" + NUM + r")\s+("
                  + NUM + r")\s+(" + NUM + r")\s+(" + NUM + r")", t)
    if m:
        out["consumption"] = int(m.group(1))
        out["unit_price_taxed"] = _n(m.group(2))
        out["energy_value"] = _n(m.group(3))
        out["pis_cofins"] = _n(m.group(4))
        out["icms_base"] = _n(m.group(5))
        out["icms_rate"] = _n(m.group(6))
        out["icms"] = _n(m.group(7))
        out["tariff_untaxed"] = _n(m.group(8))

    m = re.search(r"Contrib Ilum Publica Municipal\s+(" + NUM + r")", t)
    out["public_lighting"] = _n(m.group(1)) if m else 0.0

    # outros itens entre a energia e o TOTAL (juros, multa, créditos, etc.)
    block = re.search(r"Energia Elétrica kWh.*?\n(.*?)\nTOTAL", t, re.S)
    others = []
    if block:
        for line in block.group(1).splitlines():
            if line.startswith("Contrib Ilum"):
                continue
            # o valor do item é o 1º número da linha (as colunas seguintes são tributos do item)
            mm = re.match(r"(.+?)\s+(" + NUM + r")(?:\s+" + NUM + r")*\s*$", line.strip())
            if mm:
                others.append({"item": mm.group(1).strip(), "valor": _n(mm.group(2))})
    out["other_items"] = others

    m = re.search(r"Bandeira (Verde|Amarela|Vermelha(?: Patamar \d)?)[^\n]*?(" + NUM + r")\s*$", t, re.M)
    out["flag"] = m.group(1) if m else "Verde"
    out["flag_value"] = _n(m.group(2)) if m else 0.0

    for tax in ("PASEP", "PIS", "COFINS"):
        mm = re.search(rf"\b{tax}\s+(" + NUM + r")\s+(" + NUM + r")\s+(" + NUM + r")", t)
        if mm:
            key = "pis" if tax in ("PASEP", "PIS") else "cofins"
            out[f"{key}_base"], out[f"{key}_rate"], out[key] = _n(mm.group(1)), _n(mm.group(2)), _n(mm.group(3))

    m = re.search(r"Energia kWh\s+\S+\s+(" + r"[\d\.]+" + r")\s+([\d\.]+)\s+\d+\s+\d+", t)
    if m:
        out["meter_prev"], out["meter_curr"] = int(m.group(1).replace(".", "")), int(m.group(2).replace(".", ""))

    # derivados
    kwh, total = out.get("consumption"), out.get("amount")
    taxes = sum(v or 0 for v in (out.get("icms"), out.get("pis"), out.get("cofins")))
    out["taxes_total"] = round(taxes, 2)
    if total:
        out["taxes_pct"] = round(100 * taxes / total, 2)
        out["public_lighting_pct"] = round(100 * (out["public_lighting"] or 0) / total, 2)
    if kwh:
        out["price_kwh_full"] = round(total / kwh, 4) if total else None   # tudo incluído (impostos + iluminação)
        out["price_kwh_with_taxes"] = round(out["energy_value"] / kwh, 4) if out.get("energy_value") else None
        out["energy_untaxed"] = round(out["tariff_untaxed"] * kwh, 2) if out.get("tariff_untaxed") else None
        out["daily_kwh"] = round(kwh / out["days"], 2) if out.get("days") else None
    return out
