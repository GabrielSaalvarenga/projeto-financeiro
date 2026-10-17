import os
import tempfile
import zipfile
from datetime import datetime, timedelta

os.environ["FIN_DATA_DIR"] = tempfile.mkdtemp()

import pytest  # noqa: E402

from financas import backup, config, settings  # noqa: E402
from financas.db import session  # noqa: E402


@pytest.fixture(autouse=True)
def clean_backups():
    for b in backup.list_backups():
        b["path"].unlink()
    with session() as conn:
        conn.execute("DELETE FROM settings")


def test_manual_backup_contains_db_and_bill_pdfs():
    (config.BILLS_DIR / "importadas").mkdir(parents=True, exist_ok=True)
    (config.BILLS_DIR / "importadas" / "cemig_2026-09.pdf").write_bytes(b"%PDF-fake")
    made = backup.make("manual")
    with zipfile.ZipFile(made) as z:
        names = set(z.namelist())
    assert {"financas.db", "backup.json", "contas/importadas/cemig_2026-09.pdf"} <= names
    (b,) = backup.list_backups()
    assert b["kind"] == "manual" and b["path"] == made


def test_auto_respects_interval_and_off():
    assert backup.auto() is not None          # nunca houve backup → faz
    assert backup.auto() is None              # padrão 1x ao dia → não repete
    with session() as conn:
        settings.set_(conn, "backup_interval_h", 0)
        assert backup.next_due(conn) is None
    for b in backup.list_backups():
        b["path"].unlink()
    assert backup.auto() is None              # desligado → nunca faz sozinho


def test_prune_keeps_recent_autos_and_all_manuals():
    d = backup.backup_dir()
    base = datetime(2026, 1, 1)
    for i in range(35):
        (d / f"backup-{(base + timedelta(hours=i)).strftime(backup.FMT)}-auto.zip").write_bytes(b"x")
    (d / f"backup-{base.strftime(backup.FMT)}-manual.zip").write_bytes(b"x")
    assert backup.prune() == 5
    kinds = [b["kind"] for b in backup.list_backups()]
    assert kinds.count("auto") == backup.KEEP_AUTO and kinds.count("manual") == 1


def test_view_backup_is_read_only():
    import sqlite3
    db = backup.open_for_view(backup.make("manual"))
    with session(db, readonly=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] >= 0
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO settings(key, value) VALUES ('x', 'y')")
