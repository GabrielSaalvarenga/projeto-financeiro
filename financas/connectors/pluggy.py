"""Open Finance via Pluggy — SOMENTE LEITURA.

Usa apenas endpoints GET de dados (contas, transações, faturas, investimentos).
Nenhum endpoint de pagamento/iniciação de Pix é chamado por este módulo.

Fluxo de uso pessoal: conectar Inter e XP no app "Meu Pluggy", criar uma
aplicação no dashboard da Pluggy (client id/secret) e listar em PLUGGY_ITEM_IDS
os ids dos items conectados.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import requests

from .. import config
from ..db import log_sync

BASE = "https://api.pluggy.ai"


class Pluggy:
    def __init__(self, client_id: str, client_secret: str):
        r = requests.post(f"{BASE}/auth", json={"clientId": client_id, "clientSecret": client_secret}, timeout=30)
        r.raise_for_status()
        self.s = requests.Session()
        self.s.headers["X-API-KEY"] = r.json()["apiKey"]

    def get(self, path: str, **params) -> dict:
        r = self.s.get(f"{BASE}{path}", params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def transactions(self, account_id: str, date_from: str):
        """GET /v2/transactions (o /transactions v1 foi descontinuado — 410). Paginação por cursor em 'next'."""
        params: dict = {"accountId": account_id, "dateFrom": date_from}
        url = f"{BASE}/v2/transactions"
        while True:
            r = self.s.get(url, params=params, timeout=60)
            r.raise_for_status()
            data = r.json()
            yield from data.get("results", [])
            nxt = data.get("next")
            if not nxt:
                break
            if str(nxt).startswith("http"):  # 'next' pode vir como URL completa
                url, params = nxt, None
            else:
                params = {"accountId": account_id, "dateFrom": date_from, "cursor": nxt}


def _signed_amount(tx: dict) -> float:
    """Normaliza: saída negativa, entrada positiva (independe de conta ou cartão)."""
    amount = abs(float(tx.get("amount") or 0))
    return -amount if tx.get("type") == "DEBIT" else amount


def _counterparty(tx: dict) -> str | None:
    pd = tx.get("paymentData") or {}
    side = pd.get("payer") if tx.get("type") == "CREDIT" else pd.get("receiver")
    if side and side.get("name"):
        return side["name"]
    merchant = tx.get("merchant") or {}
    return merchant.get("name") or merchant.get("businessName")


def sync(conn, days: int = 365) -> str:
    if not (config.PLUGGY_CLIENT_ID and config.PLUGGY_CLIENT_SECRET and config.PLUGGY_ITEM_IDS):
        raise RuntimeError("Pluggy não configurado (.env: PLUGGY_CLIENT_ID, PLUGGY_CLIENT_SECRET, PLUGGY_ITEM_IDS)")

    api = Pluggy(config.PLUGGY_CLIENT_ID, config.PLUGGY_CLIENT_SECRET)
    since = (date.today() - timedelta(days=days)).isoformat()
    n_tx = n_inv = 0
    today = date.today().isoformat()

    for item_id in config.PLUGGY_ITEM_IDS:
        item = api.get(f"/items/{item_id}")
        institution = (item.get("connector") or {}).get("name", item_id)

        for acc in api.get("/accounts", itemId=item_id).get("results", []):
            conn.execute(
                """INSERT INTO accounts(id, source, institution, name, type, balance, balance_date)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET balance=excluded.balance, balance_date=excluded.balance_date,
                   name=excluded.name, updated_at=CURRENT_TIMESTAMP""",
                (acc["id"], "pluggy", institution, acc.get("name"), acc.get("type"), acc.get("balance"), today),
            )
            for tx in api.transactions(acc["id"], since):
                cc = tx.get("creditCardMetadata") or {}
                conn.execute(
                    """INSERT INTO transactions(id, account_id, source, date, description, amount, source_category,
                       counterparty, payment_method, installment_number, total_installments, raw)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET amount=excluded.amount, description=excluded.description,
                       source_category=excluded.source_category, raw=excluded.raw""",
                    (
                        tx["id"], acc["id"], "pluggy", tx["date"][:10], tx.get("description"), _signed_amount(tx),
                        tx.get("category"), _counterparty(tx), (tx.get("paymentData") or {}).get("paymentMethod"),
                        cc.get("installmentNumber"), cc.get("totalInstallments"), json.dumps(tx, ensure_ascii=False),
                    ),
                )
                n_tx += 1
            if acc.get("type") == "CREDIT":
                for bill in api.get("/bills", accountId=acc["id"]).get("results", []):
                    conn.execute(
                        "INSERT OR REPLACE INTO card_bills(id, account_id, due_date, total, minimum, raw) VALUES (?,?,?,?,?,?)",
                        (bill["id"], acc["id"], (bill.get("dueDate") or "")[:10], bill.get("totalAmount"),
                         bill.get("minimumPaymentAmount"), json.dumps(bill, ensure_ascii=False)),
                    )

        for inv in api.get("/investments", itemId=item_id).get("results", []):
            conn.execute(
                """INSERT OR REPLACE INTO holdings(snapshot, source, asset, asset_type, quantity, price_usd, value_brl)
                   VALUES (?,?,?,?,?,?,?)""",
                (today, institution.lower(), inv.get("name") or inv.get("code"), inv.get("type"),
                 inv.get("quantity"), None, inv.get("balance") or 0),
            )
            n_inv += 1

    msg = f"{n_tx} transações, {n_inv} investimentos"
    log_sync(conn, "pluggy", True, msg)
    return msg
