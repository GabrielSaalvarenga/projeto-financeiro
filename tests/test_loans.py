import os
import tempfile
from datetime import date

os.environ["FIN_DATA_DIR"] = tempfile.mkdtemp()

import pytest  # noqa: E402

from financas import analytics, loans  # noqa: E402
from financas.db import session  # noqa: E402


def L(i, d, p=1000.0, **kw):
    return loans.Loan(i, "Ana", d, p, **kw)


def R(i, d, amt, **kw):
    return loans.Receipt(i, 1, d, amt, directed=False, **kw)


A, B = date(2026, 1, 1), date(2026, 2, 1)
NOW = date(2026, 3, 1)


def bal(states):
    return {i: round(s.balance(), 2) for i, s in states.items()}


def test_baixa_mais_antigas_primeiro():
    st = loans.replay([L(1, A), L(2, B)], [R(1, date(2026, 2, 10), 1500)], NOW)
    assert bal(st) == {1: 0.0, 2: 500.0}


def test_valor_menor_que_o_primeiro_emprestimo():
    st = loans.replay([L(1, A), L(2, B)], [R(1, date(2026, 2, 10), 700)], NOW)
    assert bal(st) == {1: 300.0, 2: 1000.0}


def test_baixa_mais_recentes_primeiro():
    st = loans.replay([L(1, A), L(2, B)], [R(1, date(2026, 2, 10), 1500, order="recentes")], NOW)
    assert bal(st) == {1: 500.0, 2: 0.0}


def test_recebimento_nao_baixa_emprestimo_futuro():
    st = loans.replay([L(1, A), L(2, B)], [R(1, date(2026, 1, 15), 1500)], NOW)
    assert bal(st) == {1: 0.0, 2: 1000.0}  # o 2º ainda não existia


def test_recebimento_direcionado():
    r = loans.Receipt(1, 2, date(2026, 2, 10), 400, directed=True)
    assert bal(loans.replay([L(1, A), L(2, B)], [r], NOW)) == {1: 1000.0, 2: 600.0}


def test_juros_simples_e_composto_a_12_meses():
    d1 = date(2027, 1, 1)
    simples = loans.replay([L(1, date(2026, 1, 1), rate=0.02, compounding="simples")], [], d1)[1].balance()
    comp = loans.replay([L(1, date(2026, 1, 1), rate=0.02, compounding="composto")], [], d1)[1].balance()
    assert simples == pytest.approx(1240.0, abs=1e-6)          # 12 meses exatos
    assert comp == pytest.approx(1268.2418, abs=1e-3)          # 1000 × 1,02^12 (HP: n=12, i=2, PV=-1000)
    assert comp > simples


def test_taxa_ao_ano():
    s = loans.replay([L(1, date(2026, 1, 1), rate=0.12, period="ano")], [], date(2027, 1, 1))[1].balance()
    assert s == pytest.approx(1120.0, abs=1e-6)


@pytest.mark.parametrize("comp", ["simples", "composto"])
def test_descobrir_taxa_na_quitacao(comp):
    base = L(1, date(2026, 1, 1), rate=0.0, compounding=comp)
    when = date(2026, 7, 1)
    true = loans.replay([L(1, base.date, rate=0.03, compounding=comp)], [], when)[1].balance()
    found = loans.solve_rate([base], [], 1, when, round(true, 2))
    assert found == pytest.approx(0.03, abs=1e-5)


def test_descobrir_taxa_com_pagamento_parcial():
    base = L(1, date(2026, 1, 1), compounding="composto")
    part = loans.Receipt(1, 1, date(2026, 3, 1), 400, directed=True)
    when = date(2026, 6, 1)
    true = loans.replay([L(1, base.date, rate=0.02, compounding="composto")], [part], when)[1].balance()
    assert loans.solve_rate([base], [part], 1, when, round(true, 2)) == pytest.approx(0.02, abs=1e-5)


def test_descobrir_taxa_valor_menor_que_emprestado():
    assert loans.solve_rate([L(1, A)], [], 1, NOW, 900) is None


def test_parcelas_price_e_simples():
    price = loans.make_schedule(1000, 0.02, "mes", "composto", 12, date(2026, 2, 1))
    assert len(price) == 12 and price[0][1] == pytest.approx(94.56, abs=0.01)
    assert sum(a for _, a in price) == pytest.approx(94.56 * 12, abs=0.1)
    simples = loans.make_schedule(1000, 0.02, "mes", "simples", 10, date(2026, 2, 1))
    assert round(sum(a for _, a in simples), 2) == 1200.0
    assert loans.make_schedule(1000, 0, "mes", "simples", 4, date(2026, 1, 31))[1][0] == date(2026, 2, 28)
    assert sum(a for _, a in loans.make_schedule(1000, 0, "mes", "simples", 3, A)) == 1000


def test_pessoas_existentes_entram_na_lista_ao_abrir_o_banco():
    with session() as conn:
        conn.execute("DELETE FROM people")
        conn.execute("INSERT INTO loans(person, date, principal) VALUES ('Bia','2026-01-01',10)")
    with session() as conn:  # a migração cadastra quem já tem empréstimo
        assert conn.execute("SELECT COUNT(*) FROM people WHERE name='Bia'").fetchone()[0] == 1


def test_banco_e_pessoas_no_banco_de_dados():
    with session() as conn:
        for t in ("loans", "people", "bank_loans"):
            conn.execute(f"DELETE FROM {t}")
        first = conn.execute("INSERT INTO loans(person, date, principal, rate, rate_period, compounding) "
                             "VALUES ('Ana','2026-01-01',1000,0,'mes','simples')").lastrowid
        conn.execute("INSERT INTO loans(person, date, principal) VALUES ('Ana','2026-02-01',1000)")
        conn.execute("INSERT INTO loan_payments(loan_id, date, amount, directed, order_mode) "
                     "VALUES (?,'2026-02-10',1500,0,'antigas')", (first,))
        st = analytics.loan_status(conn, date(2026, 3, 1))
        assert list(st["remaining"]) == [0.0, 500.0] and list(st["closed"]) == [1, 0]

        bid = conn.execute("INSERT INTO bank_loans(bank, date, principal, rate, installments, first_due) "
                           "VALUES ('Banco X','2026-01-05',1200,0,4,'2026-02-05')").lastrowid
        conn.execute("INSERT INTO bank_loan_payments(bank_loan_id, date, amount) VALUES (?,'2026-02-05',300)", (bid,))
        bl, openp = analytics.bank_loan_status(conn)
        assert bl.iloc[0]["remaining"] == 900 and len(openp) == 3


def test_memoria_de_calculo_bate_com_o_saldo():
    with session() as conn:
        for t in ("loans", "people"):
            conn.execute(f"DELETE FROM {t}")
        lid = conn.execute("INSERT INTO loans(person, date, principal, rate, rate_period, compounding) "
                           "VALUES ('Caio','2026-01-01',1000,0.02,'mes','composto')").lastrowid
        st = analytics.loan_status(conn, date(2026, 7, 1))
        memo = analytics.loan_statement(conn, lid, date(2026, 7, 1))
        assert memo.iloc[-1]["saldo"] == pytest.approx(st.iloc[0]["remaining"], abs=0.01)
        assert st.iloc[0]["remaining"] == pytest.approx(1126.16, abs=0.01)  # 6 meses exatos


def test_meses_de_calendario():
    assert loans.months_between(date(2026, 10, 17), date(2027, 10, 17)) == 12
    assert loans.months_between(date(2026, 1, 31), date(2026, 2, 28)) == pytest.approx(1.0, abs=0.04)
    assert loans.months_between(date(2026, 10, 17), date(2027, 1, 2)) == pytest.approx(2 + 16 / 30.4375)
    assert loans.months_between(date(2026, 10, 17), date(2026, 10, 17)) == 0


def test_parcela_unica_um_ano_depois_usa_a_data_real():
    comp = loans.make_schedule(1000, 0.02, "mes", "composto", 1, date(2027, 10, 17), start=date(2026, 10, 17))
    assert comp == [(date(2027, 10, 17), pytest.approx(1268.24, abs=0.005))]
    simples = loans.make_schedule(1000, 0.02, "mes", "simples", 1, date(2027, 10, 17), start=date(2026, 10, 17))
    assert simples[0][1] == 1240.0
    price = loans.make_schedule(1000, 0.02, "mes", "composto", 12, date(2026, 11, 17), start=date(2026, 10, 17))
    assert price[0][1] == pytest.approx(94.56, abs=0.01)  # igual à Price da HP quando o 1º vence em 1 mês


def test_linha_do_tempo_dos_emprestimos():
    with session() as conn:
        for t in ("loans", "people"):
            conn.execute(f"DELETE FROM {t}")
        lid = conn.execute("INSERT INTO loans(person, date, principal, rate, rate_period, compounding) "
                           "VALUES ('Duda','2026-01-15',1000,0.02,'mes','composto')").lastrowid
        conn.execute("INSERT INTO loan_payments(loan_id, date, amount, directed) VALUES (?,'2026-03-20',500,0)", (lid,))
        who, tot = analytics.loan_timeline(conn, date(2026, 5, 31))
        last = who[who["month"] == "2026-05"].iloc[0]["saldo"]
        assert list(tot["month"])[:3] == ["2026-01", "2026-02", "2026-03"] and tot["emprestado"].iloc[-1] == 1000
        assert last == pytest.approx(analytics.loan_status(conn, date(2026, 5, 31)).iloc[0]["remaining"], abs=0.01)
