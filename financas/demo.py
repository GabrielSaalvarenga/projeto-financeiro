"""Dados FICTÍCIOS para ver o painel funcionando antes de conectar as fontes reais."""
from __future__ import annotations

import random
from datetime import date

import pandas as pd

from . import analytics
from .categorize import recategorize
from .db import session


def seed() -> None:
    rnd = random.Random(42)
    today = date.today()
    months = [(pd.Period(today, "M") - k) for k in range(6, -1, -1)]
    with session() as conn:
        for t in ("transactions", "accounts", "utility_bills", "holdings", "loans", "loan_schedule",
                  "loan_payments", "car_events", "car_fixed", "fipe_history", "card_bills", "user_rules",
                  "other_income"):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("INSERT INTO accounts(id, source, institution, name, type, balance, balance_date) "
                     "VALUES ('demo-cc','demo','Inter','Conta','BANK',4210.55,?)",
                     (today.isoformat(),))
        conn.execute("INSERT INTO accounts(id, source, institution, name, type, balance, balance_date, credit_limit, "
                     "available_limit) VALUES ('demo-card','demo','Inter','Cartão','CREDIT',2380.10,?,8000,5619.90)",
                     (today.isoformat(),))
        n = 0

        def tx(acc, d, desc, amount, cp=None, method=None, inst=None, tot=None):
            nonlocal n
            n += 1
            conn.execute("INSERT INTO transactions(id, account_id, source, date, description, amount, counterparty,"
                         " payment_method, installment_number, total_installments) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (f"demo{n}", acc, "demo", d, desc, amount, cp, method, inst, tot))

        for i, p in enumerate(months):
            last = p.end_time.day if p != pd.Period(today, "M") else today.day
            d = lambda day: f"{p.year}-{p.month:02d}-{min(day, last):02d}"  # noqa: E731
            if last >= 5:
                tx("demo-cc", d(5), "Crédito salário", 7800.00, "EMPRESA EXEMPLO LTDA", "TED")
            tx("demo-cc", d(3), "Pix enviado", -1500.00, "Imobiliária Exemplo", "PIX")
            tx("demo-cc", d(10), "Pix enviado", -320.00, "Maria Diarista", "PIX")
            tx("demo-cc", d(12), "Pagamento fatura cartão", -2100.00 - rnd.randint(0, 600))
            tx("demo-cc", d(8), "Aplicação XP", -1000.00)
            for day, desc in ((2, "NETFLIX.COM"), (2, "SPOTIFY"), (15, "CLARO INTERNET")):
                tx("demo-card", d(day), desc, -{"NETFLIX.COM": 44.90, "SPOTIFY": 21.90}.get(desc, 119.90))
            for _ in range(rnd.randint(8, 12)):
                desc, lo, hi = rnd.choice([("SUPERMERCADO BAHAMAS", 80, 420), ("IFOOD *RESTAURANTE", 35, 110),
                                           ("POSTO IPIRANGA", 150, 260), ("UBER *TRIP", 12, 45),
                                           ("DROGARIA PACHECO", 20, 120), ("AMAZON MARKETPLACE", 40, 300)])
                tx("demo-card", d(rnd.randint(1, 28)), desc, -round(rnd.uniform(lo, hi), 2))
            if i >= 3:  # compra parcelada em 10x iniciada há 3 meses
                tx("demo-card", d(20), "MAGALU GELADEIRA", -389.90, inst=i - 2, tot=10)
            ref = (p - 1).strftime("%Y-%m")
            conn.execute("INSERT INTO utility_bills(provider, ref_month, due_date, amount, consumption, unit) "
                         "VALUES ('cemig',?,?,?,?, 'kWh')", (ref, d(18), round(rnd.uniform(160, 260), 2),
                                                              rnd.randint(140, 220)))
            conn.execute("INSERT INTO utility_bills(provider, ref_month, due_date, amount, consumption, unit) "
                         "VALUES ('cesama',?,?,?,?, 'm3')", (ref, d(22), round(rnd.uniform(70, 110), 2),
                                                              rnd.randint(9, 15)))
            tx("demo-cc", d(18), "Pagamento CEMIG", -200.00)
            tx("demo-cc", d(22), "Pagamento CESAMA", -90.00)

        # empréstimo: R$ 1.200 ao "João", 4x de R$ 300 a partir de 2 meses atrás
        start = months[-3]
        loan_id = conn.execute("INSERT INTO loans(person, match_name, date, principal, note) VALUES (?,?,?,?,?)",
                     ("João (exemplo)", "Joao Exemplo", f"{start.year}-{start.month:02d}-01", 1200.0, "Conserto do carro")).lastrowid
        for k in range(4):
            p = start + k + 1
            conn.execute("INSERT INTO loan_schedule(loan_id, due_date, amount) VALUES (?, ?, 300)",
                         (loan_id, f"{p.year}-{p.month:02d}-10"))
        p = start + 1
        tx("demo-cc", f"{p.year}-{p.month:02d}-11", "Pix recebido", 300.00, "JOAO EXEMPLO DA SILVA", "PIX")

        # carro
        odo = 18000
        for k in range(10):
            dt = (pd.Timestamp(today) - pd.Timedelta(days=18 * (10 - k))).date().isoformat()
            odo += rnd.randint(380, 520)
            liters = round(rnd.uniform(33, 40), 1)
            conn.execute("INSERT INTO car_events(date, kind, odometer, liters, full_tank, trip, amount) "
                         "VALUES (?,?,?,?,1,?,?)", (dt, "combustivel", odo, liters, rnd.choice(["cidade", "estrada"]),
                                                    round(liters * 6.49, 2)))
        conn.execute("INSERT INTO car_events(date, kind, odometer, amount, note) VALUES (?,?,?,?,?)",
                     (months[-2].start_time.date().isoformat(), "manutencao", odo - 900, 680.0, "Revisão 20 mil km"))
        for item, v in (("seguro", 2900.0), ("ipva", 2290.0), ("licenciamento", 160.0)):
            conn.execute("INSERT INTO car_fixed(year, item, amount) VALUES (?,?,?)", (today.year, item, v))
        for k, v in enumerate([79800, 79100, 78400, 77700, 77100, 76436]):
            conn.execute("INSERT INTO fipe_history VALUES (?,?)", ((months[k + 1]).strftime("%Y-%m"), v))

        # investimentos
        for k, p in enumerate(months):
            snap = p.start_time.date().isoformat()
            g = 1 + 0.03 * k
            for src, asset, typ, v in (("binance", "BTC", "CRYPTO", 5200), ("binance", "SOL", "CRYPTO", 1700),
                                       ("binance", "ETH", "CRYPTO", 1100), ("xp", "CDB Exemplo 110% CDI", "FIXED_INCOME", 15000),
                                       ("xp", "Tesouro Selic", "FIXED_INCOME", 8000)):
                conn.execute("INSERT INTO holdings(snapshot, source, asset, asset_type, value_brl) VALUES (?,?,?,?,?)",
                             (snap, src, asset, typ, round(v * g * (1 + rnd.uniform(-0.05, 0.05)), 2)))

        recategorize(conn)
        analytics.match_loan_payments(conn)
