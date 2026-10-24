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
    cats |= set((rules.get("por_banco") or {}).values())
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
               custom: list[tuple[str, str]] | None = None, counterparty_ispb: str | None = None) -> str:
    rules = load_rules()
    text = f"{description or ''} {counterparty or ''}"
    norm = f" {normalize(text)} "
    for pattern, cat in custom or []:
        if f" {pattern} " in norm:
            return cat
    by_bank = {str(k): v for k, v in (rules.get("por_banco") or {}).items()}
    if counterparty_ispb and counterparty_ispb in by_bank:
        return by_bank[counterparty_ispb]
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
    inv_inst = {i.lower() for i in (load_rules().get("contas_investimento") or [])}
    for a in conn.execute("SELECT id, institution FROM accounts"):
        conn.execute("UPDATE accounts SET force_category=? WHERE id=?",
                     ("Investimento" if (a["institution"] or "").lower() in inv_inst else None, a["id"]))
    sql = ("SELECT t.id, t.description, t.counterparty, t.source_category, t.amount, t.manual_category, "
           "t.counterparty_ispb, a.force_category FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id")
    if only_missing:
        sql += " WHERE t.category IS NULL"
    rows = conn.execute(sql).fetchall()
    for r in rows:
        cat = r["manual_category"] or r["force_category"] or categorize(r["description"], r["counterparty"], r["source_category"],
                                                 r["amount"], custom, r["counterparty_ispb"])
        conn.execute("UPDATE transactions SET category=? WHERE id=?", (cat, r["id"]))
    apply_product_links(conn)
    return len(rows)


def set_manual(conn, tx_id: str, category: str) -> None:
    """Corrige só um lançamento."""
    conn.execute("UPDATE transactions SET manual_category=?, category=? WHERE id=?", (category, category, tx_id))


def set_tag(conn, tx_id: str, tag: str | None) -> None:
    """Subdivisão de um lançamento (vazio remove)."""
    conn.execute("UPDATE transactions SET tag=? WHERE id=?", ((tag or "").strip() or None, tx_id))


def all_tags(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT tag FROM transactions WHERE tag IS NOT NULL ORDER BY tag")]


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


def propagate_installment_tags(conn) -> int:
    """Parcela nova sem subdivisão herda a subdivisão das parcelas anteriores da mesma compra."""
    rows = conn.execute("""
        SELECT t.id, (SELECT p.tag FROM transactions p
                      WHERE p.tag IS NOT NULL AND p.account_id=t.account_id AND p.description=t.description
                        AND p.total_installments=t.total_installments AND p.installment_number<t.installment_number
                      ORDER BY p.installment_number DESC LIMIT 1) AS inherited
        FROM transactions t WHERE t.tag IS NULL AND t.total_installments IS NOT NULL""").fetchall()
    n = 0
    for r in rows:
        if r["inherited"]:
            conn.execute("UPDATE transactions SET tag=? WHERE id=?", (r["inherited"], r["id"]))
            n += 1
    return n


def store_pattern(description: str | None) -> str:
    """Sugestão de nome da loja: as 2 primeiras palavras da descrição ('amazon marketplace')."""
    return " ".join(normalize(description).split()[:2])


def apply_product_links(conn) -> int:
    """Marca cada lançamento com o produto vinculado (loja + valor, ou um lançamento) e põe na categoria do vínculo.

    Roda do zero a cada chamada, então apagar um vínculo desfaz a marca. Correção manual de categoria vence.
    """
    links = conn.execute("SELECT product, pattern, amount, tx_id, category FROM product_links ORDER BY id").fetchall()
    conn.execute("UPDATE transactions SET product=NULL WHERE product IS NOT NULL")
    n = 0
    for t in conn.execute("SELECT id, description, counterparty, amount, manual_category FROM transactions WHERE amount < 0").fetchall():
        norm = f" {normalize(f'{t['description'] or ''} {t['counterparty'] or ''}')} "
        for ln in links:  # o vínculo mais antigo vence
            if ln["tx_id"]:
                hit = ln["tx_id"] == t["id"]
            else:
                hit = bool(ln["pattern"]) and f" {ln['pattern']} " in norm and (
                    ln["amount"] is None or abs(abs(t["amount"]) - ln["amount"]) < 0.01)
            if hit:
                cat = t["manual_category"] or ln["category"] or "Compras online"
                conn.execute("UPDATE transactions SET product=?, category=? WHERE id=?", (ln["product"], cat, t["id"]))
                n += 1
                break
    return n


def add_product_link(conn, product: str, *, pattern: str | None = None, amount: float | None = None,
                     tx_id: str | None = None, category: str = "Compras online") -> int:
    """Vincula produto a uma loja+valor (toda parcela igual) ou a um lançamento. Retorna nº de lançamentos marcados."""
    product = (product or "").strip()
    if not product:
        raise ValueError("nome do produto vazio")
    pattern = normalize(pattern) if pattern else None
    if not tx_id and not pattern:
        raise ValueError("informe a loja ou o lançamento")
    conn.execute("INSERT INTO product_links(product, pattern, amount, tx_id, category) VALUES (?,?,?,?,?)",
                 (product, pattern, round(abs(amount), 2) if amount is not None else None, tx_id, category))
    return apply_product_links(conn) and conn.execute("SELECT COUNT(*) FROM transactions WHERE product=?",
                                                      (product,)).fetchone()[0]


def delete_product_link(conn, link_id: int) -> None:
    conn.execute("DELETE FROM product_links WHERE id=?", (link_id,))
    recategorize(conn)
