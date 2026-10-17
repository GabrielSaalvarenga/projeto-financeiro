import os
import shutil
import tempfile
from pathlib import Path

os.environ["FIN_DATA_DIR"] = tempfile.mkdtemp()

import pytest  # noqa: E402

from financas.db import session  # noqa: E402
from financas.importers import bills_folder, utilities  # noqa: E402

REAL = Path(__file__).resolve().parents[1] / "data/inbox/cemig/pdf/cemig_2026-08.pdf"  # fatura real (fora do git)


def test_detect_provider():
    assert bills_folder.detect_provider("CEMIG DISTRIBUIÇÃO S.A.") == "cemig"
    assert bills_folder.detect_provider("Cesama - Companhia de Saneamento") == "cesama"
    assert bills_folder.detect_provider("EDP Espírito Santo") is None
    assert bills_folder.detect_provider("CEMIG ... CESAMA") is None  # ambíguo → revisar


def test_unreadable_pdf_goes_to_review():
    base = bills_folder.ensure(Path(tempfile.mkdtemp()))
    (base / "entrada" / "foto.pdf").write_bytes(b"isto nao e um pdf")
    with session() as conn:
        (r,) = bills_folder.import_folder(conn, base, min_age=0)
    assert not r["ok"] and not any((base / "entrada").iterdir())
    assert (base / "revisar" / "foto.pdf").exists() and "não consegui abrir" in (base / "revisar" / "foto.txt").read_text()


def test_recent_file_waits_for_sync():
    base = bills_folder.ensure(Path(tempfile.mkdtemp()))
    (base / "entrada" / "chegando.pdf").write_bytes(b"%PDF")
    with session() as conn:
        assert bills_folder.import_folder(conn, base) == []  # menos de 30 s: pode estar sincronizando
    assert (base / "entrada" / "chegando.pdf").exists()


@pytest.mark.skipif(not REAL.exists(), reason="fatura real da Cemig não disponível nesta máquina")
def test_real_cemig_pdf_is_imported_and_keeps_manual_fields():
    base = bills_folder.ensure(Path(tempfile.mkdtemp()))
    shutil.copy(REAL, base / "entrada" / "conta luz.pdf")
    with session() as conn:
        utilities.save(conn, {"provider": "cemig", "ref_month": "2026-08", "paid_date": "2026-09-20", "note": "pago no app"})
        (r,) = bills_folder.import_folder(conn, base, min_age=0)
        b = utilities.load(conn, "cemig", "2026-08")
    assert r["ok"] and r["file"] == "cemig_2026-08.pdf" and (base / "importadas" / "cemig_2026-08.pdf").exists()
    assert b["amount"] == 175.92 and b["consumption"] == 131 and b["other_fees"] == -7.06
    assert b["paid_date"] == "2026-09-20" and b["note"] == "pago no app"  # lançado à mão continua
    # a mesma fatura de novo não duplica: só atualiza o mês e guarda o PDF com outro nome
    shutil.copy(REAL, base / "entrada" / "de novo.pdf")
    with session() as conn:
        (r2,) = bills_folder.import_folder(conn, base, min_age=0)
        n = conn.execute("SELECT COUNT(*) FROM utility_bills WHERE provider='cemig' AND ref_month='2026-08'").fetchone()[0]
    assert r2["ok"] and r2["file"] == "cemig_2026-08-2.pdf" and n == 1
