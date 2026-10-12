"""Importa extratos/faturas OFX (plano B ao Open Finance: app do Inter → Extrato → Exportar OFX)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import ofxparse

from ..db import log_sync


def import_file(conn, path: Path) -> int:
    with open(path, "rb") as fh:
        ofx = ofxparse.OfxParser.parse(fh)
    n = 0
    for acc in ofx.accounts:
        # número da conta nunca é guardado em claro
        acc_id = "ofx:" + hashlib.sha256(str(acc.account_id).encode()).hexdigest()[:12]
        is_card = acc.type == ofxparse.AccountType.CreditCard
        conn.execute(
            """INSERT INTO accounts(id, source, institution, name, type, balance, balance_date)
               VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET balance=excluded.balance,
               balance_date=excluded.balance_date""",
            (acc_id, "ofx", getattr(acc.institution, "organization", None) or "OFX",
             "Cartão" if is_card else "Conta", "CREDIT" if is_card else "BANK",
             float(acc.statement.balance) if getattr(acc.statement, "balance", None) is not None else None,
             acc.statement.end_date.date().isoformat() if acc.statement.end_date else None),
        )
        for t in acc.statement.transactions:
            conn.execute(
                """INSERT OR IGNORE INTO transactions(id, account_id, source, date, description, amount, payment_method)
                   VALUES (?,?,?,?,?,?,?)""",
                (f"{acc_id}:{t.id}", acc_id, "ofx", t.date.date().isoformat(),
                 (t.memo or t.payee or "").strip(), float(t.amount),
                 "PIX" if "PIX" in (t.memo or "").upper() else None),
            )
            n += 1
    log_sync(conn, "ofx", True, f"{path.name}: {n} transações")
    return n
