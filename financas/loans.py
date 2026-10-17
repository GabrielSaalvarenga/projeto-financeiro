"""Empréstimos: juros (simples/composto), parcelas, baixa dos recebimentos e taxa efetiva.

Funções puras (sem banco) — `analytics.py` carrega os dados e chama aqui.

Convenções:
- taxa é uma fração por período (0.013 = 1,3%), com `period` = "mes" ou "ano";
- tempo decorrido = meses de calendário completos + dias que sobram / 30,4375 (17/10 → 17/10 do ano seguinte = 12
  meses exatos, como `n = 12` na HP 12C); taxa ao ano usa meses / 12;
- juros simples: rendem só sobre o principal em aberto; composto: rendem sobre o saldo todo (principal + juros);
- um recebimento paga primeiro os juros acumulados e depois o principal.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

import pandas as pd

DAYS_MONTH = 30.4375
EPS = 0.005


def months_between(d0: date, d1: date) -> float:
    """Meses de calendário completos entre as datas + dias restantes / 30,4375."""
    if d1 <= d0:
        return 0.0
    m = (d1.year - d0.year) * 12 + (d1.month - d0.month)
    anchor = (pd.Timestamp(d0) + pd.DateOffset(months=m)).date()
    if anchor > d1:
        m -= 1
        anchor = (pd.Timestamp(d0) + pd.DateOffset(months=m)).date()
    return m + (d1 - anchor).days / DAYS_MONTH


def periods(d0: date, d1: date, period: str) -> float:
    months = months_between(d0, d1)
    return months / 12 if period == "ano" else months


def monthly_rate(rate: float, period: str, compounding: str) -> float:
    if period == "mes":
        return rate
    return (1 + rate) ** (1 / 12) - 1 if compounding == "composto" else rate / 12


def annual_rate(rate: float, period: str, compounding: str) -> float:
    if period == "ano":
        return rate
    return (1 + rate) ** 12 - 1 if compounding == "composto" else rate * 12


def make_schedule(principal: float, rate: float, period: str, compounding: str, n: int, first_due: date,
                  installment: float | None = None, start: date | None = None) -> list[tuple[date, float]]:
    """Parcelas iguais, respeitando as datas reais (`start` = data do empréstimo).
    Composto: valor presente das parcelas = principal (Price, com carência se o 1º vencimento for depois de 1 mês).
    Simples: principal × (1 + taxa × meses até o último vencimento) ÷ n.
    `installment` (parcela do contrato) tem prioridade. Sem `start`, assume o 1º vencimento 1 mês após o empréstimo."""
    if n <= 0:
        return []
    dues = [(pd.Timestamp(first_due) + pd.DateOffset(months=k)).date() for k in range(n)]
    t = [months_between(start, d) for d in dues] if start else [float(k + 1) for k in range(n)]
    i = monthly_rate(rate, period, compounding)
    if installment:
        pmt, total = round(installment, 2), round(installment, 2) * n
    else:
        if i == 0:
            total = principal
        elif compounding == "composto":
            total = principal / sum((1 + i) ** -x for x in t) * n
        else:
            total = principal * (1 + i * t[-1])
        total = round(total, 2)
        pmt = round(total / n, 2)
    amounts = [pmt] * (n - 1) + [round(total - pmt * (n - 1), 2)]
    return list(zip(dues, amounts))


def open_installments(schedule: list[tuple[date, float]], paid: float) -> list[tuple[date, float, float]]:
    """(vencimento, valor, em aberto): abate o já pago das parcelas mais antigas primeiro."""
    out, credit = [], paid
    for due, amt in sorted(schedule):
        used = min(credit, amt)
        credit -= used
        out.append((due, amt, round(amt - used, 2)))
    return out


# ---------------------------------------------------------------- empréstimos a receber

@dataclass
class Loan:
    id: int
    person: str
    date: date
    principal: float
    rate: float = 0.0
    period: str = "mes"
    compounding: str = "simples"
    schedule: list = field(default_factory=list)   # [(vencimento, valor)] — vazio = sem data combinada
    closed: bool = False                           # marcado como quitado à mão (legado)


@dataclass
class Receipt:
    id: int
    loan_id: int          # empréstimo de referência (define a pessoa)
    date: date
    amount: float
    directed: bool = True  # True: abate só deste empréstimo; False: baixa os da pessoa na ordem escolhida
    order: str = "antigas"  # "antigas" (mais antigos primeiro) ou "recentes"


class _State:
    def __init__(self, loan: Loan):
        self.loan = loan
        self.princ, self.interest, self.at = loan.principal, 0.0, loan.date
        self.paid = 0.0
        self.allocs: list[tuple[date, float]] = []
        self.trace: list[dict] = []   # memória de cálculo (para conferir na calculadora)
        self.scheduled = bool(loan.schedule)

    def accrue(self, to: date) -> None:
        if self.scheduled or to <= self.at:
            return
        t = periods(self.at, to, self.loan.period)
        before = self.interest
        if self.loan.compounding == "composto":
            self.interest += (self.princ + self.interest) * ((1 + self.loan.rate) ** t - 1)
        else:
            self.interest += self.princ * self.loan.rate * t
        if self.loan.rate:
            self.trace.append({"data": to, "evento": "juros do período", "dias": (to - self.at).days,
                               "períodos": t, "juros": self.interest - before, "pago": 0.0,
                               "saldo": self.princ + self.interest})
        self.at = to

    def balance(self) -> float:
        if self.scheduled:
            return max(sum(a for _, a in self.loan.schedule) - self.paid, 0.0)
        return max(self.princ + self.interest, 0.0)

    def pay(self, amount: float, when: date) -> float:
        self.accrue(when)
        applied = round(min(amount, self.balance()), 2)
        if applied <= 0:
            return 0.0
        if not self.scheduled:
            to_interest = min(applied, self.interest)
            self.interest -= to_interest
            self.princ -= applied - to_interest
        self.paid += applied
        self.allocs.append((when, applied))
        if not self.scheduled:
            self.trace.append({"data": when, "evento": "recebimento", "dias": 0, "períodos": 0.0, "juros": 0.0,
                               "pago": applied, "saldo": self.princ + self.interest})
        return applied


def replay(loans: list[Loan], receipts: list[Receipt], asof: date) -> dict[int, _State]:
    """Reaplica os recebimentos em ordem de data e devolve o estado de cada empréstimo em `asof`."""
    states = {l.id: _State(l) for l in loans}
    by_id = {l.id: l for l in loans}
    for r in sorted(receipts, key=lambda r: (r.date, r.id)):
        if r.date > asof or r.loan_id not in by_id:
            continue
        if r.directed:
            targets = [by_id[r.loan_id]]
        else:
            person = by_id[r.loan_id].person
            targets = sorted((l for l in loans if l.person == person and l.date <= r.date and not l.closed),
                             key=lambda l: (l.date, l.id), reverse=(r.order == "recentes"))
        left = r.amount
        for l in targets:
            if left <= 0.004:
                break
            left -= states[l.id].pay(left, r.date)
    for s in states.values():
        s.accrue(asof)
    return states


def solve_rate(loans: list[Loan], receipts: list[Receipt], loan_id: int, when: date, amount: float) -> float | None:
    """Taxa (por período do empréstimo) para que o saldo em `when` seja exatamente `amount`.
    None se o valor recebido for menor que o saldo sem juros (taxa seria negativa)."""
    base = next(l for l in loans if l.id == loan_id)
    if base.schedule:
        raise ValueError("Empréstimo com parcelas combinadas não tem taxa a descobrir.")

    def bal(rate: float) -> float:
        mod = [replace(l, rate=rate) if l.id == loan_id else l for l in loans]
        return replay(mod, receipts, when)[loan_id].balance()

    if amount <= bal(0.0) + EPS:
        return None
    hi = 0.01
    while bal(hi) < amount and hi < 1000:
        hi *= 2
    lo = 0.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if bal(mid) < amount else (lo, mid)
    return (lo + hi) / 2
