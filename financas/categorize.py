"""Define a categoria de cada transação.

Ordem de prioridade (a primeira que decidir vence):
1. correção manual só daquele lançamento (transactions.manual_category)
2. regras criadas pelo usuário no painel (tabela user_rules)
3. regras padrão em rules.yaml
4. categoria sugerida pelo banco (Open Finance)
5. fallback: Pix enviado/recebido, Outros, Outras entradas
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import yaml

from .config import RULES_FILE


def normalize(s: str | None) -> str:
    """Sem acento, minúsculo, só letras/números separados por um espaço."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@lru_cache
def load_rules() -> dict:
    with open(RULES_FILE, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    data["_compiled"] = [(re.compile(r["match"], re.IGNORECASE), r["categoria"]) for r in data.get("regras", [])]
    return data


def non_spending() -> set[str]:
    return set(load_rules().get("nao_gasto", []))


def all_categories(conn=None) -> list[str]:
    rules = load_rules()
    cats = {c for _, c in rules["_compiled"]} | set(rules.get("pluggy", {}).values()) | set(rules.get("nao_gasto", []))
    cats |= {"Pix enviado", "Pix recebido", "Outros", "Outras entradas"}
    if conn is not None:
        cats |= {r[0] for r in conn.execute("SELECT DISTINCT category FROM transactions WHERE category IS NOT NULL")}
        cats |= {r[0] for r in conn.execute("SELECT category FROM user_rules")}
    return sorted(cats)


def user_rules(conn) -> list[tuple[str, str]]:
    # padrões mais longos primeiro: "maria silva santos" vence "maria silva"
    return [(r["pattern"], r["category"]) for r in
            conn.execute("SELECT pattern, category FROM user_rules ORDER BY LENGTH(pattern) DESC")]


def categorize(description: str | None, counterparty: str | None, source_category: str | None, amount: float,
               custom: list[tuple[str, str]] | None = None) -> str:
    rules = load_rules()
    text = f"{description or ''} {counterparty or ''}"
    norm = f" {normalize(text)} "
    for pattern, cat in custom or []:
        if f" {pattern} " in norm:
            return cat
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
    custom = user_rules(conn)
    sql = "SELECT id, description, counterparty, source_category, amount, manual_category FROM transactions"
    if only_missing:
        sql += " WHERE category IS NULL"
    rows = conn.execute(sql).fetchall()
    for r in rows:
        cat = r["manual_category"] or categorize(r["description"], r["counterparty"], r["source_category"],
                                                 r["amount"], custom)
        conn.execute("UPDATE transactions SET category=? WHERE id=?", (cat, r["id"]))
    return len(rows)


def set_manual(conn, tx_id: str, category: str) -> None:
    """Corrige só um lançamento."""
    conn.execute("UPDATE transactions SET manual_category=?, category=? WHERE id=?", (category, category, tx_id))


def add_rule(conn, name: str, category: str) -> int:
    """Cria/atualiza regra 'sempre que aparecer este nome' e reaplica em tudo. Retorna nº de lançamentos afetados."""
    pattern = normalize(name)
    if not pattern:
        raise ValueError("nome vazio")
    conn.execute("INSERT INTO user_rules(pattern, category) VALUES (?,?) "
                 "ON CONFLICT(pattern) DO UPDATE SET category=excluded.category", (pattern, category))
    recategorize(conn)
    rows = conn.execute("SELECT description, counterparty FROM transactions WHERE manual_category IS NULL")
    return sum(f" {pattern} " in f" {normalize(f'{r[0] or ''} {r[1] or ''}')} " for r in rows)


def delete_rule(conn, pattern: str) -> None:
    conn.execute("DELETE FROM user_rules WHERE pattern=?", (pattern,))
    recategorize(conn)
