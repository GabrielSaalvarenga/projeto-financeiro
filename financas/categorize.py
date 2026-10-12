"""Aplica rules.yaml às transações."""
from __future__ import annotations

import re
from functools import lru_cache

import yaml

from .config import RULES_FILE


@lru_cache
def load_rules() -> dict:
    with open(RULES_FILE, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    data["_compiled"] = [(re.compile(r["match"], re.IGNORECASE), r["categoria"]) for r in data.get("regras", [])]
    return data


def non_spending() -> set[str]:
    return set(load_rules().get("nao_gasto", []))


def categorize(description: str | None, counterparty: str | None, source_category: str | None, amount: float) -> str:
    rules = load_rules()
    text = f"{description or ''} {counterparty or ''}"
    for rx, cat in rules["_compiled"]:
        if rx.search(text):
            return cat
    if source_category and source_category in rules.get("pluggy", {}):
        return rules["pluggy"][source_category]
    if amount > 0:
        return "Pix recebido" if "pix" in text.lower() else "Outras entradas"
    return "Pix enviado" if "pix" in text.lower() else "Outros"


def recategorize(conn, only_missing: bool = False) -> int:
    load_rules.cache_clear()
    sql = "SELECT id, description, counterparty, source_category, amount FROM transactions"
    if only_missing:
        sql += " WHERE category IS NULL"
    rows = conn.execute(sql).fetchall()
    for r in rows:
        conn.execute("UPDATE transactions SET category=? WHERE id=?",
                     (categorize(r["description"], r["counterparty"], r["source_category"], r["amount"]), r["id"]))
    return len(rows)
