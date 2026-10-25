"""Configuração via variáveis de ambiente (.env). Segredos nunca vão para o cofre."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# arquivo das chaves (a aba Configurações grava aqui). No Docker, aponte para um arquivo no volume de dados.
ENV_FILE = Path(os.getenv("FIN_ENV_FILE") or ROOT / ".env").expanduser()
load_dotenv(ENV_FILE, override=True)  # o que foi salvo pela tela vale mais que variáveis antigas do ambiente

DATA_DIR = Path(os.getenv("FIN_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "financas.db"
INBOX = DATA_DIR / "inbox"
# pasta de contas de consumo (entrada/ importadas/ revisar/); pode apontar para uma pasta sincronizada (OneDrive etc.)
BILLS_DIR = Path(os.getenv("FIN_BILLS_DIR") or DATA_DIR / "contas").expanduser()
RULES_FILE = ROOT / "rules.yaml"

# Contas da Pluggy: cada pessoa (ou conta de desenvolvedor) ocupa uma "vaga". A 1 mantém os nomes antigos
# (PLUGGY_CLIENT_ID…); a 2 usa PLUGGY_2_CLIENT_ID… Mais vagas = mais um número aqui.
PLUGGY_SLOTS = (1, 2)


def pluggy_key(slot: int, name: str) -> str:
    """Nome da variável no .env: PLUGGY_CLIENT_ID (vaga 1) ou PLUGGY_2_CLIENT_ID (vaga 2)."""
    return f"PLUGGY_{name}" if slot == 1 else f"PLUGGY_{slot}_{name}"


CONNECTION_KEYS = tuple(pluggy_key(n, k) for n in PLUGGY_SLOTS for k in ("CLIENT_ID", "CLIENT_SECRET", "ITEM_IDS", "LABEL")) + (
    "BINANCE_API_KEY", "BINANCE_API_SECRET")


def load_connections() -> None:
    """(Re)lê as chaves das conexões do ambiente — chamado de novo quando a aba Configurações salva."""
    global PLUGGY_CLIENT_ID, PLUGGY_CLIENT_SECRET, PLUGGY_ITEM_IDS, BINANCE_API_KEY, BINANCE_API_SECRET, PLUGGY_ACCOUNTS
    # Pluggy (Open Finance, somente leitura): ids dos "items" (conexões) do Meu Pluggy, separados por vírgula
    PLUGGY_CLIENT_ID = os.getenv("PLUGGY_CLIENT_ID", "")
    PLUGGY_CLIENT_SECRET = os.getenv("PLUGGY_CLIENT_SECRET", "")
    PLUGGY_ITEM_IDS = [i.strip() for i in os.getenv("PLUGGY_ITEM_IDS", "").split(",") if i.strip()]
    PLUGGY_ACCOUNTS = []  # só as vagas completas (chaves + ao menos uma conexão)
    for n in PLUGGY_SLOTS:
        acc = {"slot": n, "client_id": os.getenv(pluggy_key(n, "CLIENT_ID"), ""),
               "client_secret": os.getenv(pluggy_key(n, "CLIENT_SECRET"), ""),
               "item_ids": [i.strip() for i in os.getenv(pluggy_key(n, "ITEM_IDS"), "").split(",") if i.strip()],
               "label": os.getenv(pluggy_key(n, "LABEL"), "").strip()}
        if n > 1 and not acc["label"]:
            acc["label"] = f"Conta {n}"
        if acc["client_id"] and acc["client_secret"] and acc["item_ids"]:
            PLUGGY_ACCOUNTS.append(acc)
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")


load_connections()

# Nota do cofre que a exportação escreve (única nota declarada em "Escreve em")
OBSIDIAN_NOTE = os.getenv("OBSIDIAN_NOTE", "")
