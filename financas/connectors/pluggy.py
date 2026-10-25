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


def _counterparty_ispb(tx: dict) -> str | None:
    pd = tx.get("paymentData") or {}
    side = (pd.get("payer") if tx.get("type") == "CREDIT" else pd.get("receiver")) or {}
    return side.get("routingNumberISPB")


def _counterparty(tx: dict) -> str | None:
    pd = tx.get("paymentData") or {}
    side = pd.get("payer") if tx.get("type") == "CREDIT" else pd.get("receiver")
    if side and side.get("name"):
        return side["name"]
    merchant = tx.get("merchant") or {}
    return merchant.get("name") or merchant.get("businessName")


def sync_all(conn, days: int = 365) -> list[tuple[str, bool, str]]:
    """Coleta cada conta Pluggy configurada; uma falhar não impede as outras. Devolve (nome, ok, mensagem)."""
    accounts = config.PLUGGY_ACCOUNTS
    if not accounts:
        raise RuntimeError("Pluggy não configurado (.env: PLUGGY_CLIENT_ID, PLUGGY_CLIENT_SECRET, PLUGGY_ITEM_IDS)")
    report = []
    for acc in accounts:
        name = "pluggy" if acc["slot"] == 1 and len(accounts) == 1 else f"pluggy ({acc['label'] or acc['slot']})"
        try:
            report.append((name, True, sync(conn, days, acc)))
        except Exception as e:  # noqa: BLE001
            log_sync(conn, "pluggy", False, f"{name}: {e}")
            report.append((name, False, str(e)))
        conn.commit()
    return report


def sync(conn, days: int = 365, cfg: dict | None = None) -> str:
    """Coleta uma conta Pluggy (`cfg` = um item de config.PLUGGY_ACCOUNTS; sem ele, a primeira configurada)."""
    if cfg is None:
        if not config.PLUGGY_ACCOUNTS:
            raise RuntimeError("Pluggy não configurado (.env: PLUGGY_CLIENT_ID, PLUGGY_CLIENT_SECRET, PLUGGY_ITEM_IDS)")
        cfg = config.PLUGGY_ACCOUNTS[0]
    # só vagas extras (2, 3…) ganham o nome como dono; a vaga 1 fica como sempre foi, a menos que tenha nome
    owner = cfg["label"] or None
    api = Pluggy(cfg["client_id"], cfg["client_secret"])
    since = (date.today() - timedelta(days=days)).isoformat()
    n_tx = n_inv = 0
    today = date.today().isoformat()

    for item_id in cfg['item_ids']:
        item = api.get(f"/items/{item_id}")
        institution = (item.get("connector") or {}).get("name", item_id)
        accounts = api.get("/accounts", itemId=item_id).get("results", [])
        if institution.lower() == "meupluggy" and accounts:  # a ponte não é a instituição: usa o nome da conta
            n = accounts[0].get("name", "").upper().replace("BANCO ", "").strip()
            institution = n if len(n) <= 3 else n.title()

        for acc in accounts:
            conn.execute(
                """INSERT INTO accounts(id, source, institution, name, type, balance, balance_date,
                   credit_limit, available_limit, bill_due_date, owner)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET balance=excluded.balance, balance_date=excluded.balance_date,
                   name=excluded.name, institution=excluded.institution, owner=excluded.owner,
                   credit_limit=excluded.credit_limit, available_limit=excluded.available_limit,
                   bill_due_date=excluded.bill_due_date, updated_at=CURRENT_TIMESTAMP""",
                (acc["id"], "pluggy", institution, acc.get("name"), acc.get("type"), acc.get("balance"), today,
                 (acc.get("creditData") or {}).get("creditLimit"),
                 (acc.get("creditData") or {}).get("availableCreditLimit"),
                 ((acc.get("creditData") or {}).get("balanceDueDate") or "")[:10] or None, owner),
            )
            for tx in api.transactions(acc["id"], since):
                cc = tx.get("creditCardMetadata") or {}
                conn.execute(
                    """INSERT INTO transactions(id, account_id, source, date, description, amount, source_category,
                       counterparty, payment_method, installment_number, total_installments, raw, counterparty_ispb)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET amount=excluded.amount, description=excluded.description,
                       source_category=excluded.source_category, raw=excluded.raw,
                       counterparty_ispb=excluded.counterparty_ispb""",
                    (
                        tx["id"], acc["id"], "pluggy", tx["date"][:10], tx.get("description"), _signed_amount(tx),
                        tx.get("category"), _counterparty(tx), (tx.get("paymentData") or {}).get("paymentMethod"),
                        cc.get("installmentNumber"), cc.get("totalInstallments"), json.dumps(tx, ensure_ascii=False),
                        _counterparty_ispb(tx),
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

        # duas pessoas na mesma corretora não podem se sobrepor: o nome vira parte da origem (só vaga 2 em diante)
        holdings_source = f"{institution.lower()} ({owner})" if cfg["slot"] > 1 else institution.lower()
        used: dict[str, int] = {}
        for inv in api.get("/investments", itemId=item_id).get("results", []):
            # vários títulos têm o mesmo nome (ex.: 4 CDBs do mesmo banco): diferencia pelo vencimento
            label = inv.get("name") or inv.get("code") or inv["id"]
            if inv.get("dueDate"):
                label += f" (venc. {inv['dueDate'][:10]})"
            used[label] = used.get(label, 0) + 1
            if used[label] > 1:
                label += f" #{used[label]}"
            conn.execute(
                """INSERT OR REPLACE INTO holdings(snapshot, source, asset, asset_type, quantity, price_usd, value_brl)
                   VALUES (?,?,?,?,?,?,?)""",
                (today, holdings_source, label, inv.get("type"),
                 inv.get("quantity"), None, inv.get("balance") or 0),
            )
            n_inv += 1

    msg = f"{n_tx} transações, {n_inv} investimentos"
    log_sync(conn, "pluggy", True, msg)
    return msg
