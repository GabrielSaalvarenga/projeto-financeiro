"""Leitor do PDF da fatura EDP (DANF3E da EDP Espírito Santo — modelo de 2026). Regras fixas, sem IA.

Calibrado com uma fatura de treino. Extrai referência, vencimento, total, leituras e datas, consumo, cada item
(TUSD, TE, bandeira, iluminação pública, multa, juros), ICMS, PIS, COFINS, tarifa sem tributos, bandeiras do
período e histórico. Os valores dos itens já incluem os tributos (a soma dos itens = total a pagar).
Nome, CPF, endereço, número da UC e do medidor não são lidos.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pdfplumber

MESES = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6, "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10,
         "NOV": 11, "DEZ": 12}
NUM = r"(-?\d{1,3}(?:\.\d{3})*,\d+)"
DATE = r"(\d{2}/\d{2}/\d{4})"


def _n(s: str | None) -> float | None:
    return float(s.replace(".", "").replace(",", ".")) if s else None


def _d(s: str | None) -> str | None:
    return datetime.strptime(s, "%d/%m/%Y").date().isoformat() if s else None


def parse(path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        t = "\n".join(p.extract_text() or "" for p in pdf.pages)

    out: dict = {"provider": "edp", "unit": "kWh", "file": path.name}
    m = re.search(r"\b(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)/(\d{4})\s+" + DATE + r"\s+" + NUM, t)
    if m:
        out["ref_month"] = f"{m.group(2)}-{MESES[m.group(1)]:02d}"
        out["due_date"], out["amount"] = _d(m.group(3)), _n(m.group(4))
    m = re.search(r"DATA DE EMISSÃO:\s*" + DATE, t)
    out["issue_date"] = _d(m.group(1)) if m else None
    m = re.search(r"Classificação:\s*\S+\s*-\s*(\S+)", t)
    out["tariff_class"] = m.group(1).replace("-", " ").title().replace("B1 ", "B1 · ") if m else None
    m = re.search(r"Tipo de Fornecimento:\s*(\S+)", t)
    out["supply"] = m.group(1).title() if m else None

    m = re.search(rf"DE LEITURAS\s+{DATE}\s+{DATE}\s+(\d+)\s+{DATE}", t)
    if m:
        out["read_prev"], out["read_curr"] = m.group(1)[:5], m.group(2)[:5]
        out["days"], out["read_next"] = int(m.group(3)), m.group(4)[:5]
    m = re.search(r"Energia Ativa - kWh\s+\S+\s+(\d+)\s+(\d+)\s+[\d,]+\s+([\d.,]+)", t)
    if m:
        out["meter_prev"], out["meter_curr"] = int(m.group(1)), int(m.group(2))
        out["consumption"] = float(m.group(3).replace(",", "."))

    # itens de energia: qtd, preço c/ tributos, valor, PIS/COFINS, base ICMS, alíquota, ICMS, tarifa sem tributos
    energy = re.findall(rf"^(TUSD - Consumo|TE - Consumo|Adicional Bandeira [^\n]*?)\s+kWh\s+{NUM}\s+{NUM}\s+{NUM}\s+"
                        rf"{NUM}\s+{NUM}\s+{NUM}\s+{NUM}\s+{NUM}", t, re.M)
    out["energy_items"] = [{"item": e[0], "kwh": _n(e[1]), "valor": _n(e[3]), "icms": _n(e[7]), "tarifa": _n(e[8])}
                           for e in energy]
    out["energy_value"] = round(sum(i["valor"] for i in out["energy_items"]), 2) if energy else None
    out["icms"] = round(sum(i["icms"] for i in out["energy_items"]), 2) if energy else None
    out["icms_rate"] = _n(energy[0][6]) if energy else None
    flag_items = [i for i in out["energy_items"] if i["item"].startswith("Adicional Bandeira")]
    out["flag_value"] = round(sum(i["valor"] for i in flag_items), 2)
    for tax in ("PIS", "COFINS"):
        m = re.search(rf"\b{tax}\s+{NUM}\s+{NUM}\s+{NUM}", t)
        out[tax.lower()] = _n(m.group(3)) if m else None
    out["taxes_total"] = round(sum(out.get(k) or 0 for k in ("icms", "pis", "cofins")), 2)
    if out["energy_value"] is not None and out.get("consumption"):
        untaxed = out["energy_value"] - out["taxes_total"]
        out["energy_untaxed"] = round(untaxed, 2)
        out["tariff_untaxed"] = round(untaxed / out["consumption"], 5)

    # demais itens: descrição, valor e preço unitário zerado (iluminação pública, multa, juros, créditos)
    other = []
    for name, val, credit in re.findall(rf"^(.+?)\s+{NUM}(-?)\s+0,0+\s*$", t, re.M):
        v = -abs(_n(val)) if credit else _n(val)  # "10,00-" = crédito
        if "Ilum" in name:
            out["public_lighting"] = round((out.get("public_lighting") or 0) + v, 2)
        else:
            other.append({"item": re.sub(r"\s+", " ", name).strip(), "valor": v})
    out["other_items"] = other
    out["other_fees"] = round(sum(i["valor"] for i in other), 2)

    periods = re.findall(rf"^(VERDE|AMARELA|VERMELHA[^\n]*)\n{DATE} a {DATE}\s+(\d+) dias", t, re.M)
    out["flag_periods"] = [{"bandeira": b.title(), "de": _d(a), "ate": _d(z), "dias": int(n)} for b, a, z, n in periods]
    if flag_items:
        out["flag"] = flag_items[0]["item"].removeprefix("Adicional Bandeira ").strip().title()
    elif periods:
        out["flag"] = max(out["flag_periods"], key=lambda p: p["dias"])["bandeira"]
    out["history"] = {f"20{y}-{mo}": int(k) for mo, y, k, _v in re.findall(rf"^(\d{{2}})/(\d{{2}})\s+(\d+)\s+{NUM}\s*$", t, re.M)}
    return out
