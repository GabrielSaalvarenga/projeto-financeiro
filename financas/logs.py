"""Registro de erros em <pasta de dados>/erros.log, para analisar falhas que acontecem de vez em quando.

Guarda o detalhe técnico (traceback) dos erros do painel e das sincronizações. Fica só no seu computador;
nada é enviado. Tamanho limitado: até 5 arquivos de 1 MB (erros.log, erros.log.1 … erros.log.4).
Pode conter nomes de lojas, valores ou ids de conexão: olhe antes de mandar para alguém. Chaves e senhas
não são gravadas de propósito, mas confira mesmo assim.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import DATA_DIR

LOG_FILE = DATA_DIR / "erros.log"
_FMT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup() -> logging.Logger:
    """Liga o registro (pode chamar várias vezes: só configura uma). Devolve o logger 'financas'."""
    log = logging.getLogger("financas")
    if any(getattr(h, "_financas", False) for h in log.handlers):
        return log
    try:
        handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=4, encoding="utf-8")
    except OSError:  # pasta sem permissão de escrita: segue sem registro, nunca derruba o painel
        return log
    handler._financas = True
    handler.setFormatter(logging.Formatter(_FMT, "%Y-%m-%d %H:%M:%S"))
    handler.setLevel(logging.WARNING)
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    # erros não tratados nas telas: o Streamlit os registra em "streamlit.error_util" ("Uncaught app
    # execution"), e os loggers dele não repassam para o pai (propagate=False): ligar em cada um
    for name in ("streamlit", "streamlit.error_util"):
        st_log = logging.getLogger(name)
        if handler not in st_log.handlers:
            st_log.addHandler(handler)
    return log


def tail(lines: int = 200) -> str:
    """Últimas linhas do registro (para mostrar na tela)."""
    if not LOG_FILE.exists():
        return ""
    return "\n".join(LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
