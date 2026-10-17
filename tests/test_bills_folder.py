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
    assert bills_folder.detect_provider("EDP ES DISTRIB DE ENERGIA SA") == "edp"
    assert bills_folder.detect_provider("Light Serviços de Eletricidade") is None
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


REAL_CESAMA = Path(__file__).resolve().parents[1] / "data/inbox/cesama/pdf/cesama_2026-08.pdf"  # fatura real (fora do git)


@pytest.mark.skipif(not REAL_CESAMA.exists(), reason="fatura real da Cesama não disponível nesta máquina")
def test_real_cesama_pdf_is_imported():
    base = bills_folder.ensure(Path(tempfile.mkdtemp()))
    shutil.copy(REAL_CESAMA, base / "entrada" / "Cesama out 26.pdf")
    with session() as conn:
        (r,) = bills_folder.import_folder(conn, base, min_age=0)
        b = utilities.load(conn, "cesama", "2026-08")
    assert r["ok"] and r["file"] == "cesama_2026-08.pdf"
    assert b["amount"] == 50.49 and b["consumption"] == 6 and b["meter"] == 81 and b["days"] == 30
    assert b["water"] == 29.95 and b["sewer"] == 18.6 and b["other_fees"] == 1.94
    assert b["due_date"] == "2026-10-12" and utilities.total_gap(b) == 0
    assert "matricula" not in str(b).lower() and "EUGENIO" not in str(b)  # dados pessoais não são guardados


REAL_EDP = Path(__file__).resolve().parents[1] / "data/inbox/edp/pdf/edp_es_2026-10.pdf"  # fatura de treino (fora do git)


@pytest.mark.skipif(not REAL_EDP.exists(), reason="fatura de treino da EDP não disponível nesta máquina")
def test_edp_training_bill_is_understood():
    import re
    b = utilities.edp_bill(REAL_EDP)
    assert (b["ref_month"], b["due_date"], b["amount"]) == ("2026-10", "2026-10-19", 377.48)
    assert b["consumption"] == 300 and b["days"] == 32 and (b["meter_prev"], b["meter_curr"]) == (416, 716)
    assert (b["icms"], b["pis"], b["cofins"], b["public_lighting"]) == (56.26, 3.02, 13.96, 43.53)
    assert b["flag"] == "Amarela" and b["flag_value"] == 5.89 and b["other_fees"] == 3.0
    assert utilities.total_gap(b) == 0
    assert not re.search(r"\d{11}|CPF|CEP|RUA ", str(b))  # sem CPF, endereço, UC (dados pessoais não são lidos)
