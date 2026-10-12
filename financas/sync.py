"""Orquestra todas as coletas. Cada fonte falha sozinha sem derrubar as outras."""
from __future__ import annotations

import shutil

from . import analytics, config
from .categorize import recategorize
from .connectors import binance, pluggy
from .db import log_sync, session
from .importers import ofx, utility_pdf


def run_all() -> list[tuple[str, bool, str]]:
    report = []
    with session() as conn:
        for name, fn in (("pluggy", pluggy.sync), ("binance", binance.sync)):
            try:
                report.append((name, True, fn(conn)))
            except Exception as e:  # noqa: BLE001 — registrar e seguir
                log_sync(conn, name, False, str(e))
                report.append((name, False, str(e)))
            conn.commit()

        ofx_dir = config.INBOX / "ofx"
        done = ofx_dir / "processados"
        for f in sorted(ofx_dir.glob("*.ofx")):
            try:
                n = ofx.import_file(conn, f)
                done.mkdir(exist_ok=True)
                shutil.move(str(f), done / f.name)
                report.append(("ofx", True, f"{f.name}: {n}"))
            except Exception as e:  # noqa: BLE001
                report.append(("ofx", False, f"{f.name}: {e}"))

        for bill in utility_pdf.import_inbox(conn, config.INBOX):
            ok = bool(bill["amount"] and bill["ref_month"])
            report.append((bill["provider"], ok, f"{bill['file']}: {bill['amount']} ({bill['ref_month']})"))

        recategorize(conn, only_missing=True)
        n = analytics.match_loan_payments(conn)
        if n:
            report.append(("empréstimos", True, f"{n} pagamento(s) casado(s) por Pix"))
    return report
