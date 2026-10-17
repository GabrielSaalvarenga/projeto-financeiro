"""Pasta de contas de consumo: o PDF colocado em `entrada/` é lido e lançado sozinho.

Sem IA: o fornecedor é reconhecido pelo nome escrito na fatura e os valores, por regras fixas
(`cemig_pdf`, `cesama_pdf`). O que não for reconhecido vai para `revisar/` com um .txt explicando o motivo, para
lançar pelo formulário do painel. Lançado com sucesso → `importadas/<fornecedor>_<AAAA-MM>.pdf`.

A pasta vem de FIN_BILLS_DIR (padrão: <pasta de dados>/contas) — nada aqui depende da máquina.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import pdfplumber

from ..db import log_sync
from . import cemig_pdf, utilities

SUBDIRS = ("entrada", "importadas", "revisar")
# fornecedor → marcas no texto da fatura (maiúsculas). Basta uma das alternativas; cada alternativa exige todos os
# termos. A Cesama traz o nome só no logotipo (imagem), então vale também o modelo da conta (esgoto + tarifa fixa).
PROVIDERS = {
    "cemig": [("CEMIG",)],
    "cesama": [("CESAMA",), ("ESGOTO", "TRF_FIXA", "FUNDO MUNIC")],
}
# fornecedores com leitor de PDF; os demais vão para revisar/
PARSERS = {"cemig": utilities.cemig_bill, "cesama": utilities.cesama_bill}
MAX_GAP = 0.05  # R$ de tolerância entre o total e a soma das partes


def _brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def ensure(base: Path) -> Path:
    for d in SUBDIRS:
        (base / d).mkdir(parents=True, exist_ok=True)
    return base


def detect_provider(text: str) -> str | None:
    up = text.upper()
    hits = {prov for prov, alts in PROVIDERS.items() if any(all(t in up for t in alt) for alt in alts)}
    return hits.pop() if len(hits) == 1 else None


def _free(path: Path) -> Path:
    n = 2
    out = path
    while out.exists():
        out = path.with_name(f"{path.stem}-{n}{path.suffix}")
        n += 1
    return out


def _review(base: Path, pdf: Path, reason: str) -> Path:
    dest = _free(base / "revisar" / pdf.name)
    shutil.move(str(pdf), dest)
    dest.with_suffix(".txt").write_text(reason + "\nLance pelo formulário do painel (Contas de consumo) ou "
                                        "devolva o PDF para entrada/ depois de corrigido.\n")
    return dest


def import_one(conn, base: Path, pdf: Path) -> dict:
    """Processa um PDF de `entrada/`. Devolve {file, ok, provider, ref_month, amount, message}."""
    res = {"file": pdf.name, "ok": False, "provider": None, "ref_month": None, "amount": None}
    try:
        with pdfplumber.open(pdf) as doc:
            text = "\n".join(p.extract_text() or "" for p in doc.pages)
    except Exception as e:  # noqa: BLE001 — PDF corrompido/protegido
        res["message"] = f"não consegui abrir o PDF ({e})"
    else:
        prov = res["provider"] = detect_provider(text)
        if not prov:
            res["message"] = "não reconheci o fornecedor (Cemig ou Cesama) no texto da fatura"
        elif prov not in PARSERS:
            res["message"] = f"ainda não existe leitor de PDF para {prov.title()}"
        else:
            bill = PARSERS[prov](pdf)
            gap = utilities.total_gap(bill)
            if not (bill.get("ref_month") and bill.get("amount")):
                res["message"] = "não encontrei o mês de referência e o valor na fatura"
            elif gap is not None and abs(gap) > MAX_GAP:
                res["message"] = (f"o total ({_brl(bill['amount'])}) não fecha com a soma das partes "
                                  f"(diferença {_brl(gap)}); nada foi gravado")
            else:
                res.update(ref_month=bill["ref_month"], amount=bill["amount"])
                dest = _free(base / "importadas" / f"{prov}_{bill['ref_month']}.pdf")
                bill["file"] = dest.name
                utilities.save(conn, utilities.merge(conn, bill))
                shutil.move(str(pdf), dest)
                res.update(ok=True, file=dest.name, message=f"{_brl(bill['amount'])} ({bill['ref_month']})")
    if not res["ok"]:
        _review(base, pdf, f"{pdf.name}: {res['message']}.")
    log_sync(conn, res["provider"] or "contas", res["ok"], f"{pdf.name}: {res['message']}")
    return res


def import_folder(conn, base: Path, min_age: float = 30) -> list[dict]:
    """Importa os PDFs de `entrada/`. `min_age` (s) evita pegar arquivo que ainda está sincronizando."""
    ensure(base)
    now = time.time()
    pdfs = sorted(p for p in (base / "entrada").iterdir() if p.suffix.lower() == ".pdf")
    return [import_one(conn, base, p) for p in pdfs if now - p.stat().st_mtime >= min_age]
