"""Empréstimos: juros (simples/composto), parcelas, baixa dos recebimentos e taxa efetiva.

Funções puras (sem banco) — `analytics.py` carrega os dados e chama aqui.

Convenções:
- taxa é uma fração por período (0.013 = 1,3%), com `period` = "mes" ou "ano";
- tempo decorrido em períodos = dias / 30,4375 (mês) ou dias / 365,25 (ano);
- juros simples: rendem só sobre o principal em aberto; composto: rendem sobre o saldo todo (principal + juros);
- um recebimento paga primeiro os juros acumulados e depois o principal.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

import pandas as pd

DAYS_MONTH = 30.4375
DAYS_YEAR = 365.25
EPS = 0.005


def periods(d0: date, d1: date, period: str) -> float:
    days = max((d1 - d0).days, 0)
    return days / (DAYS_YEAR if period == "ano" else DAYS_MONTH)


def monthly_rate(rate: float, period: str, compounding: str) -> float:
    if period == "mes":
        return rate
    return (1 + rate) ** (1 / 12) - 1 if compounding == "composto" else rate / 12


def annual_rate(rate: float, period: str, compounding: str) -> float:
    if period == "ano":
        return rate
    return (1 + rate) ** 12 - 1 if compounding == "composto" else rate * 12


def make_schedule(principal: float, rate: float, period: str, compounding: str, n: int, first_due: date,
                  installment: float | None = None) -> list[tuple[date, float]]:
    """Parcelas iguais. Composto = tabela Price; simples = (principal + juros sobre o principal) / n.
    `installment` (valor da parcela do contrato) tem prioridade sobre o cálculo."""
    if n <= 0:
        return []
    i = monthly_rate(rate, period, compounding)
    if installment:
        pmt, total = round(installment, 2), round(installment, 2) * n
    else:
        if i == 0:
            total = principal
        elif compounding == "composto":
            total = principal * i / (1 - (1 + i) ** -n) * n
        else:
            total = principal * (1 + i * n)
        total = round(total, 2)
        pmt = round(total / n, 2)
    amounts = [pmt] * (n - 1) + [round(total - pmt * (n - 1), 2)]
    return [((pd.Timestamp(first_due) + pd.DateOffset(months=k)).date(), a) for k, a in enumerate(amounts)]


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
        self.scheduled = bool(loan.schedule)

    def accrue(self, to: date) -> None:
        if self.scheduled or to <= self.at:
            return
        t = periods(self.at, to, self.loan.period)
        if self.loan.compounding == "composto":
            self.interest += (self.princ + self.interest) * ((1 + self.loan.rate) ** t - 1)
        else:
            self.interest += self.princ * self.loan.rate * t
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
