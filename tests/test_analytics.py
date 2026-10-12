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


def test_user_rules_and_manual_override():
    from financas.categorize import add_rule, delete_rule, recategorize, set_manual
    seed()
    with session() as conn:
        n = add_rule(conn, "Maria Diarista", "Moradia")
        assert n == 7
        cats = {r[0] for r in conn.execute("SELECT category FROM transactions WHERE counterparty='Maria Diarista'")}
        assert cats == {"Moradia"}
        tx = conn.execute("SELECT id FROM transactions WHERE description='SPOTIFY' LIMIT 1").fetchone()[0]
        set_manual(conn, tx, "Lazer")
        recategorize(conn)  # "recategorizar tudo" não apaga correções nem empréstimos
        assert conn.execute("SELECT category FROM transactions WHERE id=?", (tx,)).fetchone()[0] == "Lazer"
        assert conn.execute("SELECT COUNT(*) FROM transactions WHERE category='Empréstimo recebido'").fetchone()[0] == 1
        delete_rule(conn, "maria diarista")
        assert {r[0] for r in conn.execute(
            "SELECT category FROM transactions WHERE counterparty='Maria Diarista'")} == {"Pix enviado"}
