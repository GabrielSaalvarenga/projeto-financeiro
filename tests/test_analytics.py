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
        emp = loans[loans["kind"] == "emprestimo"].iloc[0]
        assert emp["paid"] > 0 and emp["remaining"] > 0  # empréstimo parcialmente pago nos dados fictícios
        assert (loans["kind"] == "venda").any()          # e uma venda parcelada em andamento
        fc = analytics.forecast(conn, 6)
        assert len(fc) == 6 and (fc["Parcelas cartão"] > 0).any()
        assert analytics.match_loan_payments(conn) == 0  # idempotente
        car = analytics.car_summary(conn)
        assert 8 < car["km_l"] < 16


def test_user_rules_and_manual_override():
    from financas.categorize import add_rule, delete_rule, recategorize, set_manual
    seed()
    with session() as conn:
        for i in range(3):  # o demo já classifica as diaristas à mão; aqui são lançamentos sem correção
            conn.execute("INSERT INTO transactions(id, source, date, description, amount, counterparty) "
                         "VALUES (?,?,?,?,?,?)", (f"rule{i}", "demo", f"2026-0{i + 1}-10", "Pix enviado", -100.0, "Maria Diarista"))
        recategorize(conn, only_missing=False)
        n = add_rule(conn, "Maria Diarista", "Moradia")
        assert n == 3
        cats = {r[0] for r in conn.execute("SELECT category FROM transactions WHERE id LIKE 'rule%'")}
        assert cats == {"Moradia"}
        tx = conn.execute("SELECT id FROM transactions WHERE description='SPOTIFY' LIMIT 1").fetchone()[0]
        set_manual(conn, tx, "Lazer")
        recategorize(conn)  # "recategorizar tudo" não apaga correções nem empréstimos
        assert conn.execute("SELECT category FROM transactions WHERE id=?", (tx,)).fetchone()[0] == "Lazer"
        assert conn.execute("SELECT COUNT(*) FROM transactions WHERE category='Empréstimo recebido'").fetchone()[0] >= 1
        delete_rule(conn, "maria diarista")
        assert {r[0] for r in conn.execute(
            "SELECT category FROM transactions WHERE id LIKE 'rule%'")} == {"Pix enviado"}


def test_refund_reduces_spending_not_income():
    import pandas as pd
    df = pd.DataFrame({"amount": [-1500.0, 936.23, 3000.0], "category": ["Viagem", "Viagem", "Salário"],
                       "date": pd.to_datetime(["2025-11-24"] * 3)})
    df["month"] = "2025-11"
    df["is_flow"] = True
    sp, inc = analytics.spending(df), analytics.income(df)
    assert round(sp["value"].sum(), 2) == 563.77      # gasto líquido da viagem
    assert inc["amount"].sum() == 3000.0              # reembolso não vira renda


def test_product_links():
    from financas.categorize import add_product_link, delete_product_link, recategorize
    seed()
    with session() as conn:
        base = {"account_id": None, "source": "t", "payment_method": "CARD"}
        for i, (d, desc, amt) in enumerate([("2026-01-19", "AMAZONMKTPLC X SAO PAULO BRA", -486.66),
                                            ("2026-02-19", "AMAZONMKTPLC X SAO PAULO BRA", -486.66),
                                            ("2026-02-20", "AMAZONMKTPLC X SAO PAULO BRA", -50.0),
                                            ("2026-03-11", "MERCADO MERCADOLIVRE CAJAMAR BRA", -111.99)]):
            conn.execute("INSERT INTO transactions(id, source, date, description, amount, category) VALUES (?,?,?,?,?,?)",
                         (f"p{i}", "demo", d, desc, amt, "Mercado" if "MERCADO" in desc else "Compras online"))
        n = add_product_link(conn, "Switch 2", pattern="amazonmktplc", amount=486.66)
        assert n == 2  # só o valor igual; a compra de R$ 50 não entra
        add_product_link(conn, "Monitor", pattern="mercado mercadolivre", amount=111.99)
        row = conn.execute("SELECT product, category FROM transactions WHERE id='p3'").fetchone()
        assert (row["product"], row["category"]) == ("Monitor", "Compras online")  # sai de 'Mercado'
        recategorize(conn)  # reaplicar tudo mantém o vínculo
        assert conn.execute("SELECT COUNT(*) FROM transactions WHERE product='Switch 2'").fetchone()[0] == 2
        assert conn.execute("SELECT product FROM transactions WHERE id='p2'").fetchone()[0] is None
        delete_product_link(conn, conn.execute("SELECT id FROM product_links WHERE product='Monitor'").fetchone()[0])
        assert conn.execute("SELECT product FROM transactions WHERE id='p3'").fetchone()[0] is None


def test_sale_installments_auto_baixa():
    from datetime import date

    from financas import loans as lo
    seed()
    with session() as conn:
        conn.execute("INSERT OR IGNORE INTO people(name, match_name) VALUES ('Zeca Comprador', 'zeca comprador')")
        cur = conn.execute("INSERT INTO loans(person, date, principal, note, kind, item) "
                           "VALUES ('Zeca Comprador', '2026-10-01', 1000, '', 'venda', 'Notebook usado')")
        sale_id = cur.lastrowid
        for due, amt in lo.make_schedule(1000, 0.0, "mes", "simples", 5, date(2026, 10, 1), start=date(2026, 10, 1)):
            conn.execute("INSERT INTO loan_schedule(loan_id, due_date, amount) VALUES (?,?,?)", (sale_id, due.isoformat(), amt))
        for i, (d, amt) in enumerate([("2026-10-01", 200.0), ("2026-10-20", 150.0), ("2026-11-02", 200.0)]):
            conn.execute("INSERT INTO transactions(id, source, date, description, amount, category) VALUES (?,?,?,?,?,?)",
                         (f"sv{i}", "demo", d, "Pix recebido - Zeca Comprador", amt, "Pix recebido"))
        assert analytics.match_loan_payments(conn) == 2  # R$ 150 não é valor de parcela: não baixa
        cats = {r["id"]: r["category"] for r in conn.execute("SELECT id, category FROM transactions WHERE id LIKE 'sv%'")}
        assert cats == {"sv0": "Venda recebida", "sv1": "Pix recebido", "sv2": "Venda recebida"}
        asof = date(2026, 12, 1)
        st = analytics.loan_status(conn, asof)
        row = st[st["id"] == sale_id].iloc[0]
        assert row["kind"] == "venda" and row["paid"] == 400 and row["remaining"] == 600
        sched = analytics.loan_schedule_open(conn, asof)
        assert len(sched[sched["loan_id"] == sale_id]) == 3  # 5 parcelas − 2 baixadas
        assert analytics.match_loan_payments(conn) == 0  # idempotente
        # Pix da pessoa sem empréstimo nunca baixa a venda por conta própria
        assert not conn.execute("SELECT 1 FROM loan_payments WHERE transaction_id='sv1'").fetchone()
        # a venda não entra no gráfico de empréstimos
        tl, _ = analytics.loan_timeline(conn)
        assert "Zeca Comprador" not in set(tl.get("person", []))
