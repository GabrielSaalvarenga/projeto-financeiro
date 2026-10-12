import os
import tempfile

os.environ["FIN_DATA_DIR"] = tempfile.mkdtemp()

from financas import analytics  # noqa: E402
from financas.categorize import categorize  # noqa: E402
from financas.db import session  # noqa: E402
from financas.demo import seed  # noqa: E402


def test_categorize_rules():
    assert categorize("Pagamento fatura cartão", None, None, -100) == "Pagamento de fatura"
    assert categorize("PIX recebido", "Fulano", None, 50) == "Pix recebido"
    assert categorize("x", None, "Groceries", -10) == "Mercado"


def test_demo_pipeline():
    seed()
    with session() as conn:
        df = analytics.transactions(conn)
        sp = analytics.spending(df)
        assert "Pagamento de fatura" not in set(sp["category"])  # não conta em dobro
        loans = analytics.loan_status(conn)
        assert loans.iloc[0]["paid"] == 300 and loans.iloc[0]["remaining"] == 900
        fc = analytics.forecast(conn, 6)
        assert len(fc) == 6 and (fc["Parcelas cartão"] > 0).all()
        assert analytics.match_loan_payments(conn) == 0  # idempotente
        car = analytics.car_summary(conn)
        assert 8 < car["km_l"] < 16
