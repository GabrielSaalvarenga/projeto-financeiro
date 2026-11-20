"""Retrato dos números-chave do painel para comparar antes/depois de cada incremento de interface.

Uso (na raiz do repositório):
    FIN_DATA_DIR=data-demo/base-2026-11-14 FIN_ENV_FILE=/dev/null .venv/bin/python docs/ui-evolucao/valores.py > saida.json
Os cálculos usam a data do dia: compare retratos tirados no mesmo dia.
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from financas import analytics  # noqa: E402
from financas.db import session  # noqa: E402

r2 = lambda v: round(float(v), 2)  # noqa: E731
with session() as conn:
    df = analytics.transactions(conn)
    sp, inc = analytics.spending(df), analytics.income(df)
    hold = analytics.latest_holdings(conn)
    loans = analytics.loan_status(conn)
    sched = analytics.loan_schedule_open(conn)
    bl, bsched = analytics.bank_loan_status(conn)
    cards = analytics.card_summary(conn)
    fc = analytics.forecast(conn, 6)
    car = analytics.car_summary(conn)
    bank = conn.execute("SELECT COALESCE(SUM(balance),0) FROM accounts WHERE type='BANK'").fetchone()[0]
cur, day = date.today().strftime("%Y-%m"), date.today().day
mtd = sp[sp["date"].dt.day <= day].groupby("month")["value"].sum()
out = {
    "data": date.today().isoformat(),
    "investimentos": r2(hold["value_brl"].sum()),
    "investimentos_por_fonte": {k: r2(v) for k, v in hold.groupby("source")["value_brl"].sum().items()},
    "saldo_em_conta": r2(bank),
    "gasto_mes_ate_hoje": r2(mtd.get(cur, 0)),
    "gasto_media_3m_mesmo_periodo": r2(mtd[mtd.index < cur].tail(3).mean()),
    "gasto_por_mes": {k: r2(v) for k, v in sp.groupby("month")["value"].sum().items()},
    "entradas_por_mes": {k: r2(v) for k, v in inc.groupby("month")["amount"].sum().items()},
    "gasto_mes_por_categoria": {k: r2(v) for k, v in sp[sp["month"] == cur].groupby("category")["value"].sum().items()},
    "a_receber_total": r2(loans["remaining"].sum()),
    "a_receber_por_tipo": {k: r2(v) for k, v in loans.groupby("kind")["remaining"].sum().items()},
    "em_atraso_por_tipo": {k: r2(v) for k, v in loans.groupby("kind")["overdue"].sum().items()},
    "parcelas_a_receber": [[r.person, r.due_date, r2(r.remaining)] for r in sched.itertuples()],
    "divida_banco_falta": r2(bl["remaining"].sum()) if not bl.empty else 0.0,
    "parcelas_banco": [[r.bank, r.due_date, r2(r.remaining)] for r in bsched.itertuples()],
    "cartoes": [{"nome": c["name"], "usado": r2(c["used"]), "fatura_aberta": r2(c["open_bill_estimate"]),
                 "parcelas_futuras": r2(c["future_installments"])} for c in cards],
    "previsao": json.loads(fc.round(2).to_json(orient="records")),
    "carro": {k: (r2(v) if isinstance(v, (int, float)) else str(v)) for k, v in car.items()
              if not hasattr(v, "columns")},
}
print(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True, default=str))
