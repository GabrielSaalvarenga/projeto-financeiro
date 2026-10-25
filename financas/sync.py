"""Orquestra todas as coletas. Cada fonte falha sozinha sem derrubar as outras."""
from __future__ import annotations

import shutil

from . import analytics, backup, config
from .categorize import propagate_installment_tags, recategorize
from .connectors import binance, pluggy
from .db import log_sync, session
from .importers import bills_folder, ofx


def run_all() -> list[tuple[str, bool, str]]:
    report = []
    with session() as conn:
        for name, fn in (("pluggy", pluggy.sync_all), ("binance", lambda c: [("binance", True, binance.sync(c))])):
            try:
                report.extend(fn(conn))
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

        for r in bills_folder.import_folder(conn, config.BILLS_DIR):
            report.append((r["provider"] or "contas", r["ok"], f"{r['file']}: {r['message']}"))

        recategorize(conn, only_missing=True)
        propagate_installment_tags(conn)
        n = analytics.match_loan_payments(conn)
        if n:
            report.append(("empréstimos", True, f"{n} pagamento(s) casado(s) por Pix"))
    try:  # depois de gravar tudo: o backup do dia já pega a coleta de hoje
        made = backup.auto()
        if made:
            report.append(("backup", True, made.name))
    except Exception as e:  # noqa: BLE001
        report.append(("backup", False, str(e)))
    return report
