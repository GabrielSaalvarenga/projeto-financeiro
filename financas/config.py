"""Configuração via variáveis de ambiente (.env). Segredos nunca vão para o cofre."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("FIN_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "financas.db"
INBOX = DATA_DIR / "inbox"
RULES_FILE = ROOT / "rules.yaml"

PLUGGY_CLIENT_ID = os.getenv("PLUGGY_CLIENT_ID", "")
PLUGGY_CLIENT_SECRET = os.getenv("PLUGGY_CLIENT_SECRET", "")
# ids dos "items" (conexões) criados no Meu Pluggy, separados por vírgula
PLUGGY_ITEM_IDS = [i.strip() for i in os.getenv("PLUGGY_ITEM_IDS", "").split(",") if i.strip()]

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# Nota do cofre que a exportação escreve (única nota declarada em "Escreve em")
OBSIDIAN_NOTE = os.getenv("OBSIDIAN_NOTE", "")
