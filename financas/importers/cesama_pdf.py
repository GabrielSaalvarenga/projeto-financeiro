"""Leitor do PDF da fatura Cesama (Juiz de Fora — modelo de 2026). Regras fixas, sem IA.

Extrai mês de referência, vencimento, total, leituras do hidrômetro (atual/anterior com datas), consumo,
média, itens da conta (água, esgoto, Fundo Municipal de Saneamento) e o histórico de consumo.
A fatura não destaca impostos. Nome, endereço e matrícula não são lidos.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pdfplumber

DATE = r"(\d{2}/\d{2}/\d{4})"
NUM = r"(\d{1,3}(?:\.\d{3})*,\d{1,2})"
ITEMS = {"ÁGUA": "water", "ESGOTO": "sewer"}


def _n(s: str | None) -> float | None:
    return float(s.replace(".", "").replace(",", ".")) if s else None


def _d(s: str | None) -> str | None:
    return datetime.strptime(s, "%d/%m/%Y").date().isoformat() if s else None


def parse(path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        t = "\n".join(p.extract_text() or "" for p in pdf.pages)

    out: dict = {"provider": "cesama", "unit": "m3", "file": path.name}
    m = re.search(r"Refer[êe]ncia\s+Categoria\s*\n\s*(\d{2})/(\d{4})", t)
    if m:
        out["ref_month"] = f"{m.group(2)}-{m.group(1)}"
    m = re.search(rf"VENCIMENTO:\s*{DATE}\s+TOTAL:\s*{NUM}", t)
    if m:
        out["due_date"], out["amount"] = _d(m.group(1)), _n(m.group(2))

    # "81 6 75 30/10/2026 30/09/2026" (atual, consumo, anterior, datas de emissão/próxima leitura)
    # "30/09/2026 31/08/2026"           (data da leitura atual, data da leitura anterior)
    m = re.search(rf"Pr[óo]xima Leitura\s*\n\s*(\d+)\s+(\d+)\s+(\d+)\s+{DATE}\s+{DATE}\s*\n\s*{DATE}\s+{DATE}", t)
    if m:
        out["meter"], out["consumption"], out["meter_prev"] = int(m.group(1)), int(m.group(2)), int(m.group(3))
        d1, d2 = _d(m.group(4)), _d(m.group(5))
        out["issue_date"], out["next_read"] = min(d1, d2), max(d1, d2)
        out["read_date"], out["read_prev_date"] = _d(m.group(6)), _d(m.group(7))
        out["days"] = (datetime.fromisoformat(out["read_date"]) - datetime.fromisoformat(out["read_prev_date"])).days

    other = []
    for line in t.splitlines():
        im = re.match(r"\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ .]+?)\s+(\d{1,3}(?:\.\d{3})*,\d{1,2})\b", line)
        if not im or "VENCIMENTO" in im.group(1) or "TOTAL" in im.group(1):
            continue
        name, val = im.group(1).strip(), _n(im.group(2))
        if name in ITEMS:
            out[ITEMS[name]] = val
        else:
            other.append({"item": "Fundo Municipal de Saneamento" if name.startswith("FUNDO MUNIC") else name.title(),
                          "valor": val})
    out["other_items"] = other
    out["other_fees"] = round(sum(i["valor"] for i in other), 2)

    m = re.search(r"M[ée]dia\s+0*(\d+)", t)
    out["avg_m3"] = int(m.group(1)) if m else None
    m = re.search(r"TRF_FIXA\s+\d+\s+[\d.]+\s+[\d.]+\s+([\d.]+)", t)
    out["fixed_fee"] = float(m.group(1)) if m else None  # tarifa fixa (água + esgoto), cobrada mesmo sem consumo
    out["history"] = {f"{y}-{mo}": int(c) for mo, y, c in re.findall(r"\b(\d{2})/(\d{4})\s+0*(\d+)\s*$", t, re.M)}
    return out
