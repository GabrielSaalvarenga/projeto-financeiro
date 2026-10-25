"""Abre o Painel Financeiro com um comando só (Windows, Mac e Linux).

Na primeira vez cria a pasta .venv e instala as dependências; nas seguintes só abre o painel.
Use pelos atalhos Iniciar.bat (Windows), Iniciar.command (Mac) ou Iniciar.sh (Linux). Usa apenas a biblioteca padrão.
"""
from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQ = ROOT / "requirements.txt"
STAMP = VENV / "requirements.sha256"
MIN_PY = (3, 10)


def say(msg: str) -> None:
    print(f"\n>>> {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"\n[ERRO] {msg}\n", flush=True)
    sys.exit(1)


def ensure_venv() -> None:
    if PY.exists() and subprocess.run([str(PY), "-c", "pass"], capture_output=True).returncode == 0:
        return
    say("Preparando o painel pela primeira vez (cria uma pasta .venv)…")
    try:
        venv.create(VENV, with_pip=True, clear=VENV.exists())
    except Exception as e:  # noqa: BLE001
        fail(f"Não consegui criar o ambiente do Python: {e}\nNo Linux, instale também o pacote python3-venv.")


def ensure_requirements() -> None:
    digest = hashlib.sha256(REQ.read_bytes()).hexdigest()
    if STAMP.exists() and STAMP.read_text().strip() == digest:
        return
    say("Instalando as dependências (na primeira vez leva alguns minutos; precisa de internet)…")
    cmd = [str(PY), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQ)]
    if subprocess.run(cmd).returncode != 0:
        fail("A instalação das dependências falhou. Confira a internet e rode de novo.")
    STAMP.write_text(digest)


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def is_panel(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/_stcore/health", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def skip_streamlit_email_prompt() -> None:
    """Na primeira execução o Streamlit pergunta um e-mail no terminal; um credentials.toml vazio dispensa a pergunta."""
    cred = Path.home() / ".streamlit" / "credentials.toml"
    if not cred.exists():
        cred.parent.mkdir(exist_ok=True)
        cred.write_text('[general]\nemail = ""\n')


def main() -> None:
    if sys.version_info < MIN_PY:
        fail(f"Python {sys.version_info.major}.{sys.version_info.minor} é antigo demais. Instale o Python 3.12 (python.org).")
    os.chdir(ROOT)
    ensure_venv()
    ensure_requirements()
    skip_streamlit_email_prompt()
    port = int(os.getenv("PORTA", "8501"))
    if not port_free(port):
        if is_panel(port):
            say(f"O painel já está aberto em http://localhost:{port} — abrindo o navegador.")
            webbrowser.open(f"http://localhost:{port}")
            return
        while not port_free(port):
            port += 1
    say(f"Abrindo o painel em http://localhost:{port}   (para fechar: feche esta janela ou aperte Ctrl+C)")
    try:
        subprocess.run([str(PY), "-m", "streamlit", "run", "financas/ui/app.py", f"--server.port={port}",
                        "--browser.gatherUsageStats=false"])
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
