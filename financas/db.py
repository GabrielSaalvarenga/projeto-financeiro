"""Banco SQLite local — fonte única dos dados consumidos.

Tudo aqui é leitura/registro. Nenhuma tabela representa uma ordem de pagamento.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id            TEXT PRIMARY KEY,          -- id externo (Pluggy) ou 'ofx:<conta>'
    source        TEXT NOT NULL,             -- pluggy | ofx | manual
    institution   TEXT,
    name          TEXT,
    type          TEXT,                      -- BANK | CREDIT | INVESTMENT
    balance       REAL,
    balance_date  TEXT,
    updated_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    id                 TEXT PRIMARY KEY,     -- id externo estável (dedupe)
    account_id         TEXT REFERENCES accounts(id),
    source             TEXT NOT NULL,
    date               TEXT NOT NULL,        -- AAAA-MM-DD
    description        TEXT,
    amount             REAL NOT NULL,        -- negativo = saída, positivo = entrada
    category           TEXT,                 -- categoria final (regras > origem)
    source_category    TEXT,                 -- categoria que veio da origem
    counterparty       TEXT,                 -- pagador/recebedor (Pix)
    counterparty_ispb  TEXT,                 -- código (ISPB) do banco do outro lado do Pix/TED
    payment_method     TEXT,                 -- PIX | TED | BOLETO | CARD ...
    installment_number INTEGER,
    total_installments INTEGER,
    raw                TEXT,                 -- JSON original, para reprocessar
    manual_category    TEXT,                 -- correção do usuário só para este lançamento (vence tudo)
    tag                TEXT                  -- subdivisão livre (ex.: viagem 'Capitólio 2025')
);
CREATE INDEX IF NOT EXISTS ix_tx_date ON transactions(date);

CREATE TABLE IF NOT EXISTS card_bills (
    id          TEXT PRIMARY KEY,
    account_id  TEXT,
    due_date    TEXT,
    total       REAL,
    minimum     REAL,
    raw         TEXT
);

CREATE TABLE IF NOT EXISTS utility_bills (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    provider     TEXT NOT NULL,              -- cemig | cesama | ...
    ref_month    TEXT NOT NULL,              -- AAAA-MM
    due_date     TEXT,
    amount       REAL,
    consumption  REAL,
    unit         TEXT,                       -- kWh | m3
    file         TEXT,
    UNIQUE(provider, ref_month)
);

CREATE TABLE IF NOT EXISTS holdings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot    TEXT NOT NULL,               -- AAAA-MM-DD
    source      TEXT NOT NULL,               -- binance | xp | ...
    asset       TEXT NOT NULL,
    asset_type  TEXT,                        -- CRYPTO | FIXED_INCOME | STOCK | FUND ...
    quantity    REAL,
    price_usd   REAL,
    value_brl   REAL NOT NULL,
    UNIQUE(snapshot, source, asset)
);

CREATE TABLE IF NOT EXISTS loans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person      TEXT NOT NULL,
    match_name  TEXT,                        -- trecho do nome no Pix recebido
    date        TEXT NOT NULL,
    principal   REAL NOT NULL,
    note        TEXT,
    transaction_id TEXT,                     -- Pix de saída que originou o empréstimo
    closed      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS loan_schedule (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id   INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    due_date  TEXT NOT NULL,
    amount    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS loan_payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id         INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    date            TEXT NOT NULL,
    amount          REAL NOT NULL,
    transaction_id  TEXT UNIQUE,             -- Pix casado automaticamente
    note            TEXT
);

CREATE TABLE IF NOT EXISTS car_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    date      TEXT NOT NULL,
    kind      TEXT NOT NULL,                 -- combustivel | manutencao | outro
    odometer  REAL,
    liters    REAL,
    full_tank INTEGER DEFAULT 1,
    trip      TEXT,                          -- cidade | estrada | misto
    amount    REAL NOT NULL,
    note      TEXT
);

CREATE TABLE IF NOT EXISTS car_fixed (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    year      INTEGER NOT NULL,
    item      TEXT NOT NULL,                 -- seguro | ipva | licenciamento | ...
    amount    REAL NOT NULL,
    UNIQUE(year, item)
);

CREATE TABLE IF NOT EXISTS fipe_history (
    ref_month TEXT PRIMARY KEY,              -- AAAA-MM
    value     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS other_income (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,          -- ex.: 'Vale-alimentação (Flash)'
    amount    REAL NOT NULL,                 -- valor mensal fixo
    day       INTEGER,                       -- dia do mês em que cai
    category  TEXT NOT NULL DEFAULT 'Salário',
    active    INTEGER NOT NULL DEFAULT 1,
    note      TEXT
);

CREATE TABLE IF NOT EXISTS user_rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern    TEXT NOT NULL UNIQUE,         -- nome normalizado (sem acento, minúsculo)
    category   TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT DEFAULT CURRENT_TIMESTAMP,
    source    TEXT,
    ok        INTEGER,
    message   TEXT
);
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session(path: Path | str = DB_PATH):
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Adiciona colunas novas em bancos criados por versões anteriores."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(transactions)")}
    if "manual_category" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN manual_category TEXT")
    if "counterparty_ispb" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN counterparty_ispb TEXT")
    if "tag" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN tag TEXT")
    acols = {r["name"] for r in conn.execute("PRAGMA table_info(accounts)")}
    for col in ("credit_limit REAL", "available_limit REAL", "bill_due_date TEXT"):
        if col.split()[0] not in acols:
            conn.execute(f"ALTER TABLE accounts ADD COLUMN {col}")


def log_sync(conn: sqlite3.Connection, source: str, ok: bool, message: str) -> None:
    conn.execute("INSERT INTO sync_log(source, ok, message) VALUES (?,?,?)", (source, int(ok), message))
