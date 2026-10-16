import os
import tempfile
from datetime import date

os.environ["FIN_DATA_DIR"] = tempfile.mkdtemp()

from financas.db import session  # noqa: E402
from financas.importers import utilities  # noqa: E402


def test_manual_cemig_derives_like_the_pdf():
    # números da fatura real de 09/2026
    with session() as conn:
        b = utilities.manual(conn, {
            "provider": "cemig", "ref_month": "2026-09", "due_date": date(2026, 10, 22), "amount": 199.60,
            "meter_prev": 4410, "meter_curr": 4556, "read_prev_date": date(2026, 8, 14),
            "read_curr_date": date(2026, 9, 15), "energy_untaxed": 134.63, "icms": 30.81, "pis": 1.02,
            "cofins": 4.73, "public_lighting": 28.41, "flag": "Amarela", "flag_value": 3.48, "other_items": []})
        assert b["consumption"] == 146 and b["days"] == 32 and b["read_curr"] == "15/09"
        assert b["taxes_total"] == 36.56 and b["energy_value"] == 171.19
        assert abs(b["tariff_untaxed"] - 0.92212) < 1e-4
        assert utilities.total_gap(b) == 0
        assert conn.execute("SELECT due_date FROM utility_bills WHERE ref_month='2026-09'").fetchone()[0] == "2026-10-22"


def test_manual_keeps_imported_detail_when_field_is_blank():
    with session() as conn:
        utilities.save(conn, {"provider": "cemig", "ref_month": "2026-08", "amount": 175.92, "consumption": 131,
                              "icms": 27.82, "tariff_class": "Residencial Convencional B1",
                              "other_items": [{"item": "Bônus ITAIPU", "valor": -7.06}], "other_fees": -7.06})
        utilities.manual(conn, {"provider": "cemig", "ref_month": "2026-08", "paid_date": date(2026, 9, 20),
                                "amount": None, "icms": None, "other_items": None, "note": ""})
        b = utilities.load(conn, "cemig", "2026-08")
        assert b["paid_date"] == "2026-09-20"
        assert b["amount"] == 175.92 and b["icms"] == 27.82 and b["other_fees"] == -7.06
        assert b["tariff_class"] == "Residencial Convencional B1" and b["other_items"][0]["valor"] == -7.06


def test_manual_cesama_consumption_from_previous_reading():
    with session() as conn:
        utilities.save(conn, {"provider": "cesama", "ref_month": "2026-08", "amount": 50.49, "consumption": 6,
                              "unit": "m3", "meter": 81})
        b = utilities.manual(conn, {"provider": "cesama", "ref_month": "2026-09", "amount": 45.0, "meter": 86,
                                    "read_date": date(2026, 10, 30), "taxes_total": None})
        assert b["consumption"] == 5 and b["unit"] == "m3" and b["read_date"] == "2026-10-30"
