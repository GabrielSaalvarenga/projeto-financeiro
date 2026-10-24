"""Dados FICTÍCIOS para mostrar o painel a outras pessoas sem expor dados reais.

Tudo aqui é inventado (nomes, valores, datas relativas a hoje). Nada é copiado nem embaralhado a partir de um banco real.
Roda em uma pasta de dados própria: FIN_DATA_DIR=data-demo python -m financas.cli demo
"""
from __future__ import annotations

import json
import random
from datetime import date

import pandas as pd

from . import analytics
from .categorize import recategorize
from .db import session

TABLES = ("transactions", "accounts", "utility_bills", "holdings", "loans", "loan_schedule", "loan_payments", "people",
          "bank_loans", "bank_loan_payments", "car_events", "car_fixed", "car_profile", "fipe_history", "card_bills",
          "user_rules", "other_income", "product_links", "sync_log")


def seed() -> None:
    rnd = random.Random(42)
    today = date.today()
    months = [pd.Period(today, "M") - k for k in range(11, -1, -1)]  # 12 meses, o último é o atual
    with session() as conn:
        real = conn.execute("SELECT COUNT(*) FROM transactions WHERE source <> 'demo'").fetchone()[0]
        if real:  # o seed apaga tudo: nunca roda em cima de dados reais
            raise SystemExit("Este banco tem dados reais. Use outra pasta: FIN_DATA_DIR=data-demo")
        for t in TABLES:
            conn.execute(f"DELETE FROM {t}")
        conn.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({','.join('?' * len(TABLES))})", TABLES)  # ids voltam a 1
        iso = today.isoformat()
        conn.execute("INSERT INTO accounts(id, source, institution, name, type, balance, balance_date) "
                     "VALUES ('demo-cc','demo','Inter','Conta Corrente','BANK',6842.30,?)", (iso,))
        conn.execute("INSERT INTO accounts(id, source, institution, name, type, balance, balance_date, credit_limit, "
                     "available_limit, bill_due_date) VALUES ('demo-card','demo','Inter','Cartão Mastercard','CREDIT',"
                     "3120.45,?,9000,5879.55,?)", (iso, f"{months[-1].year}-{months[-1].month:02d}-10"))
        conn.execute("INSERT INTO accounts(id, source, institution, name, type, balance, balance_date) "
                     "VALUES ('demo-xp','demo','XP','Conta XP','BANK',320.00,?)", (iso,))
        n = 0

        def tx(acc, d, desc, amount, cp=None, method=None, inst=None, tot=None, cat=None, tag=None):
            nonlocal n
            if d > iso:  # nada no futuro
                return
            n += 1
            conn.execute("INSERT INTO transactions(id, account_id, source, date, description, amount, counterparty,"
                         " payment_method, installment_number, total_installments, manual_category, tag) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (f"demo{n}", acc, "demo", d, desc, amount, cp, method, inst, tot, cat, tag))

        for i, p in enumerate(months):
            last = p.end_time.day
            d = lambda day, p=p, last=last: f"{p.year}-{p.month:02d}-{min(day, last):02d}"  # noqa: E731
            cc, card = "demo-cc", "demo-card"
            # entradas
            tx(cc, d(5), "Crédito salário", 9400.00 if i < 6 else 9850.00, "EMPRESA EXEMPLO LTDA", "TED")
            tx(cc, d(7), "Pix recebido", 600.00, "FAMILIAR EXEMPLO", "PIX", cat="Mesada / ajuda de custos")
            if i % 4 == 1:
                tx(cc, d(20), "Pix recebido", round(rnd.uniform(80, 260), 2), "AMIGO EXEMPLO", "PIX")
            # saídas fixas
            tx(cc, d(3), "Pix enviado", -1650.00, "Imobiliária Exemplo", "PIX", cat="Moradia")
            tx(cc, d(10), "Pix enviado", -380.00, "Maria Diarista", "PIX", cat="Moradia")
            tx(cc, d(8), "Aplicação CDB XP", -1200.00)
            tx(cc, d(9), "Pix enviado", -289.90, "Academia Forma Física", "PIX", cat="Saúde")
            for day, desc, v in ((2, "NETFLIX.COM", 55.90), (2, "SPOTIFY", 21.90), (14, "CLARO INTERNET", 129.90),
                                 (21, "GOOGLE ONE", 9.99)):
                tx(card, d(day), desc, -v)
            # cartão: gastos variáveis
            lojas = [("SUPERMERCADO BAHAMAS", 90, 430), ("IFOOD *RESTAURANTE", 35, 120), ("POSTO IPIRANGA", 180, 290),
                     ("UBER *TRIP", 12, 48), ("DROGARIA PACHECO", 20, 130), ("AMAZON MARKETPLACE", 40, 320),
                     ("PADARIA DONA MARIA", 15, 60), ("CINEMA CENTER EXEMPLO", 40, 90)]
            for _ in range(rnd.randint(18, 26)):
                desc, lo, hi = rnd.choice(lojas)
                cat = "Lazer" if desc.startswith("CINEMA") else None
                tx(card, d(rnd.randint(1, 28)), desc, -round(rnd.uniform(lo, hi), 2), cat=cat)
            if rnd.random() < 0.5:
                tx(card, d(rnd.randint(1, 28)), "LOJA SEM NOME 4821", -round(rnd.uniform(30, 180), 2))  # cai em "Outros"
            # compras parceladas
            if i >= 4:
                tx(card, d(20), "MAGALU GELADEIRA", -389.90, inst=i - 3, tot=10)
            if i >= 8:
                tx(card, d(12), "AMAZON FONE BLUETOOTH", -149.90, inst=i - 7, tot=6)
            # contas de consumo
            ref = (p - 1).strftime("%Y-%m")
            cons = rnd.randint(150, 240)
            tariff = 0.74
            energy_untaxed = round(cons * tariff, 2)
            energy_value = round(energy_untaxed * 1.31, 2)
            icms = round(energy_value * 0.18 / 1.18, 2)
            pis = round(energy_value * 0.0079, 2)
            cofins = round(energy_value * 0.0363, 2)
            light = round(rnd.uniform(16, 24), 2)
            flag, flag_v = rnd.choice([("Verde", 0.0), ("Amarela", round(cons * 0.0188, 2)), ("Vermelha 1", round(cons * 0.0446, 2))])
            amount_e = round(energy_value + light + flag_v, 2)
            details = {"tariff_class": "Residencial Convencional B1", "supply": "Bifásico", "icms_rate": 18.0,
                       "icms_base": energy_value, "pis_rate": 0.79, "cofins_rate": 3.63,
                       "unit_price_taxed": round(energy_value / cons, 4),
                       "read_prev": "13/" + ref[5:], "read_curr": "15/" + p.strftime("%m"),
                       "read_next": "15/" + (p + 1).strftime("%m"), "other_items": []}
            conn.execute(
                "INSERT INTO utility_bills(provider, ref_month, due_date, amount, consumption, unit, issue_date, paid_date, days,"
                " tariff_untaxed, energy_value, icms, pis, cofins, taxes_total, public_lighting, flag, flag_value, other_fees, details)"
                " VALUES ('cemig',?,?,?,?,'kWh',?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ref, d(18), amount_e, cons, d(8), d(17), 32, tariff, energy_value, icms, pis, cofins,
                 round(icms + pis + cofins, 2), light, flag, flag_v, 0.0, json.dumps(details)))
            m3 = rnd.randint(8, 15)
            amount_w = round(m3 * rnd.uniform(7.2, 8.4) + 18, 2)
            conn.execute(
                "INSERT INTO utility_bills(provider, ref_month, due_date, amount, consumption, unit, issue_date, paid_date, days,"
                " other_fees, details) VALUES ('cesama',?,?,?,?,'m3',?,?,?,?,?)",
                (ref, d(22), amount_w, m3, d(12), d(21), 30, round(amount_w * 0.01, 2), json.dumps({"avg_m3": 11})))
            tx(cc, d(18), "Pagamento CEMIG", -amount_e)
            tx(cc, d(22), "Pagamento CESAMA", -amount_w)
            # fatura do cartão
            bill = round(rnd.uniform(3300, 4800), 2)
            tx(cc, d(10), "Pagamento fatura cartão", -bill)
            conn.execute("INSERT INTO card_bills(id, account_id, due_date, total, minimum) VALUES (?,?,?,?,?)",
                         (f"demo-bill-{p}", "demo-card", d(10), bill, round(bill * 0.15, 2)))

        # viagem com subdivisão (tag)
        trip = "Gramado 2026"
        t0 = months[-4]
        td = lambda day: f"{t0.year}-{t0.month:02d}-{day:02d}"  # noqa: E731
        for day, desc, v in ((12, "HOTEL SERRA EXEMPLO", 1480.00), (12, "POSTO SHELL ESTRADA", 240.00),
                             (13, "RESTAURANTE VALE DO VINHO", 312.40), (13, "PARQUE TEMATICO EXEMPLO", 420.00),
                             (14, "CHOCOLATERIA EXEMPLO", 138.50), (14, "RESTAURANTE CAFE COLONIAL", 189.00),
                             (15, "POSTO IPIRANGA VOLTA", 255.00)):
            tx("demo-card", td(day), desc, -v, cat="Viagem", tag=trip)

        # presentes e outras pontuais
        tx("demo-cc", f"{months[-6].year}-{months[-6].month:02d}-18", "Pix enviado", -250.00, "Familiar Exemplo", "PIX",
           cat="Presentes e doações")
        tx("demo-cc", f"{months[-2].year}-{months[-2].month:02d}-25", "Pix recebido", 430.00, "Cliente Freelance Exemplo", "PIX")

        # XP: aportes e rendimentos (conta de investimento)
        for k, p in enumerate(months):
            tx("demo-xp", f"{p.year}-{p.month:02d}-08", "Aporte CDB", -1200.00)
            tx("demo-xp", f"{p.year}-{p.month:02d}-28", "Rendimento", round(60 + 9 * k + rnd.uniform(-5, 5), 2))

        # empréstimo com juros a uma pessoa: R$ 6.000, 6x, 1,5% a.m. composto sobre o total
        start = months[-5]
        total = round(6000 * (1.015 ** 6), 2)
        parcela = round(total / 6, 2)
        conn.execute("INSERT INTO people(name, match_name) VALUES (?,?)", ("Renato (exemplo)", "Renato Exemplo"))
        conn.execute("INSERT INTO people(name, match_name) VALUES (?,?)", ("Marina (exemplo)", "Marina Exemplo"))
        loan_id = conn.execute(
            "INSERT INTO loans(person, match_name, date, principal, note, rate, rate_period, compounding, kind) "
            "VALUES (?,?,?,?,?,?,?,?,'emprestimo')",
            ("Renato (exemplo)", "Renato Exemplo", f"{start.year}-{start.month:02d}-01", 6000.0, "Entrada de um apartamento",
             0.015, "mes", "composto")).lastrowid
        tx("demo-cc", f"{start.year}-{start.month:02d}-01", "Pix enviado", -6000.00, "Renato Exemplo Pereira", "PIX",
           cat="Empréstimo concedido")
        for k in range(6):
            p = start + k + 1
            conn.execute("INSERT INTO loan_schedule(loan_id, due_date, amount) VALUES (?,?,?)",
                         (loan_id, f"{p.year}-{p.month:02d}-10", parcela))
            if k < 3:  # três parcelas já recebidas por Pix
                tx("demo-cc", f"{p.year}-{p.month:02d}-11", "Pix recebido", parcela, "RENATO EXEMPLO PEREIRA", "PIX")
        # venda parcelada sem juros: notebook usado em 6x de R$ 300
        sale_start = months[-4]
        sale_id = conn.execute(
            "INSERT INTO loans(person, match_name, date, principal, note, rate, rate_period, compounding, kind, item) "
            "VALUES (?,?,?,?,?,0,'mes','simples','venda',?)",
            ("Marina (exemplo)", "Marina Exemplo", f"{sale_start.year}-{sale_start.month:02d}-05", 1800.0, None,
             "Notebook usado")).lastrowid
        for k in range(6):
            p = sale_start + k + 1
            conn.execute("INSERT INTO loan_schedule(loan_id, due_date, amount) VALUES (?,?,300)",
                         (sale_id, f"{p.year}-{p.month:02d}-15"))
            if k < 3:
                tx("demo-cc", f"{p.year}-{p.month:02d}-15", "Pix recebido", 300.00, "MARINA EXEMPLO SOUZA", "PIX")

        # dívida minha com banco: 24x, parcela do contrato, 9 já pagas
        bstart = months[-9]
        conn.execute("INSERT INTO bank_loans(bank, date, principal, rate, rate_period, compounding, installments, first_due, "
                     "installment_amount, note) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     ("Banco Exemplo", f"{bstart.year}-{bstart.month:02d}-02", 15000.0, 0.0189, "mes", "composto", 24,
                      f"{(bstart + 1).year}-{(bstart + 1).month:02d}-05", 773.50, "Crédito pessoal"))
        for k in range(9):
            p = bstart + k + 1
            conn.execute("INSERT INTO bank_loan_payments(bank_loan_id, date, amount) VALUES (1,?,773.50)",
                         (f"{p.year}-{p.month:02d}-05",))
            tx("demo-cc", f"{p.year}-{p.month:02d}-05", "Parcela empréstimo", -773.50, "Banco Exemplo", cat="Moradia")

        # carro
        conn.execute("INSERT INTO car_profile(id, brand, model, year, km_now, km_now_date, next_service_km, next_service_price) "
                     "VALUES (1,'Volkswagen','Polo',2022,41850,?,50000,980)", (iso,))
        odo = 36200
        for k in range(14):
            dt = (pd.Timestamp(today) - pd.Timedelta(days=20 * (14 - k))).date().isoformat()
            odo += rnd.randint(380, 520)
            liters = round(rnd.uniform(32, 40), 1)
            conn.execute("INSERT INTO car_events(date, kind, odometer, liters, full_tank, trip, amount) VALUES (?,?,?,?,1,?,?)",
                         (dt, "combustivel", odo, liters, rnd.choice(["cidade", "estrada", "misto"]), round(liters * 6.19, 2)))
        conn.execute("INSERT INTO car_events(date, kind, odometer, amount, note) VALUES (?,?,?,?,?)",
                     (months[-6].start_time.date().isoformat(), "manutencao", odo - 2400, 760.0, "Revisão 40 mil km"))
        for item, v in (("seguro", 3100.0), ("ipva", 2480.0), ("licenciamento", 160.0)):
            conn.execute("INSERT INTO car_fixed(year, item, amount) VALUES (?,?,?)", (today.year, item, v))
        for k, p in enumerate(months):
            conn.execute("INSERT INTO fipe_history VALUES (?,?)", (p.strftime("%Y-%m"), round(74200 - 310 * k, 2)))

        # investimentos: 12 fotos mensais
        carteira = (("binance", "BTC", "CRYPTO", 5200, 0.021), ("binance", "ETH", "CRYPTO", 1900, 0.38),
                    ("binance", "SOL", "CRYPTO", 1400, 8.2), ("binance", "BNB", "CRYPTO", 800, 1.1),
                    ("xp", "CDB Banco Exemplo 110% CDI", "FIXED_INCOME", 16000, None),
                    ("xp", "Tesouro Selic 2029", "FIXED_INCOME", 9000, None),
                    ("xp", "Fundo Multimercado Exemplo", "MUTUAL_FUND", 4000, None),
                    ("inter", "LCI Exemplo 95% CDI", "FIXED_INCOME", 7000, None),
                    ("inter", "Ação EXEM3", "EQUITY", 2300, 85.0))
        for k, p in enumerate(months):
            g = 1 + 0.025 * k
            for src, asset, typ, v, qty in carteira:
                vol = 0.12 if typ == "CRYPTO" else 0.01
                conn.execute("INSERT INTO holdings(snapshot, source, asset, asset_type, quantity, value_brl) VALUES (?,?,?,?,?,?)",
                             (p.start_time.date().isoformat() if p != months[-1] else iso, src, asset, typ, qty,
                              round(v * g * (1 + rnd.uniform(-vol, vol)), 2)))

        # renda fixa extra, regras e vínculos de produto
        conn.execute("INSERT INTO other_income(name, amount, day, category, active) VALUES "
                     "('Vale-alimentação (Flash)', 1300, 5, 'Salário', 1)")
        conn.execute("INSERT INTO other_income(name, amount, day, category, active) VALUES "
                     "('Aluguel de vaga de garagem', 250, 10, 'Outras entradas', 1)")
        conn.execute("INSERT INTO user_rules(pattern, category) VALUES ('padaria dona maria','Alimentação fora')")
        conn.execute("INSERT INTO product_links(product, pattern, amount, category) VALUES "
                     "('Geladeira Frost Free','magalu geladeira',389.90,'Compra de produtos')")
        conn.execute("INSERT INTO product_links(product, pattern, amount, category) VALUES "
                     "('Fone Bluetooth','amazon fone bluetooth',149.90,'Compra de produtos')")
        conn.execute("INSERT INTO sync_log(source, ok, message) VALUES ('demo', 1, 'Dados fictícios gerados para demonstração')")

        recategorize(conn)
        analytics.match_loan_payments(conn)
