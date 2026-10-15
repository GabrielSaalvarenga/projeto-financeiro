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
    # Pix para conta própria no Banco XP (ISPB 33264668) = investimento
    assert categorize("Pix enviado - Fulano", None, "Same person transfer", -500,
                      counterparty_ispb="33264668") == "Investimento"


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


def test_refund_reduces_spending_not_income():
    import pandas as pd
    df = pd.DataFrame({"amount": [-1500.0, 936.23, 3000.0], "category": ["Viagem", "Viagem", "Salário"],
                       "date": pd.to_datetime(["2025-11-24"] * 3)})
    df["month"] = "2025-11"
    df["is_flow"] = True
    sp, inc = analytics.spending(df), analytics.income(df)
    assert round(sp["value"].sum(), 2) == 563.77      # gasto líquido da viagem
    assert inc["amount"].sum() == 3000.0              # reembolso não vira renda
