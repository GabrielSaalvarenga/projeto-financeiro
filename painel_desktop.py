"""Painel Financeiro como aplicativo (Mac .app / Windows .exe), empacotado com PyInstaller.

Abre uma janela própria (pywebview) com o painel dentro; não precisa de Python, Docker nem navegador.
Como funciona:
  1. o processo principal escolhe uma porta livre e inicia a si mesmo de novo com --servidor;
  2. esse segundo processo roda o Streamlit (o mesmo painel de sempre) só em 127.0.0.1;
  3. quando o painel responde, a janela abre; fechou a janela, o servidor é encerrado.
Os dados ficam na pasta do usuário (não dentro do app), então atualizar ou apagar o app não apaga nada:
  Mac:     ~/Library/Application Support/Painel Financeiro
  Windows: %APPDATA%\\Painel Financeiro
Para desenvolver sem empacotar: python painel_desktop.py
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

APP_NAME = "Painel Financeiro"
FROZEN = getattr(sys, "frozen", False)
# onde estão financas/ e rules.yaml: dentro do pacote (PyInstaller) ou na pasta do projeto
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
SCRIPT = BASE / "financas" / "ui" / "app.py"


def data_dir() -> Path:
    if os.getenv("FIN_DATA_DIR"):
        return Path(os.environ["FIN_DATA_DIR"]).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        return Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    return Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_NAME


def prepare_env() -> Path:
    """Pasta de dados + variáveis que o painel lê (financas/config.py). Também vira a pasta atual,
    porque o Streamlit grava/lê o tema em ./.streamlit/config.toml."""
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.environ["FIN_DATA_DIR"] = str(d)
    os.environ.setdefault("FIN_ENV_FILE", str(d / ".env"))
    os.chdir(d)
    return d


def free_port(start: int = 8765) -> int:
    for port in range(start, start + 200):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Nenhuma porta livre entre 8765 e 8964")


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ processo do servidor (Streamlit)
def _wait_stdin_closed_posix() -> None:
    # os.read direto no descritor 0: NÃO usar sys.stdin aqui. Uma thread presa em sys.stdin.read()
    # segura a trava do buffer e o Python aborta ao encerrar ("encerrou inesperadamente" no Mac).
    try:
        while os.read(0, 1024):
            pass
    except OSError:
        pass


def _kernel32():
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32")  # instância própria: não mexe nos argtypes que outras bibliotecas usam
    k32.GetFileType.argtypes = [wintypes.HANDLE]
    k32.GetFileType.restype = wintypes.DWORD
    k32.PeekNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                  wintypes.LPDWORD, wintypes.LPDWORD, wintypes.LPDWORD]
    k32.PeekNamedPipe.restype = wintypes.BOOL
    return k32


def _stdin_pipe_windows():
    """Handle do stdin se for um pipe (é o que a janela passa); senão None."""
    import msvcrt
    try:
        handle = msvcrt.get_osfhandle(0)
    except OSError:
        return None
    file_type_pipe = 3
    return handle if _kernel32().GetFileType(handle) == file_type_pipe else None


def _wait_stdin_closed_windows(handle) -> None:
    # NÃO deixar uma leitura bloqueante (os.read) pendente no pipe: enquanto ela espera, o Windows segura
    # qualquer outra consulta ao mesmo handle — e a DLL do numpy (OpenBLAS) consulta o stdin ao carregar,
    # com a trava do carregador de DLLs na mão. O painel congelava no "import pandas" (janela branca) e o
    # servidor parava de responder até a outras threads. PeekNamedPipe só espia o pipe, sem deixar nada
    # pendente, e falha quando a janela fecha o stdin ou morre.
    import ctypes
    from ctypes import wintypes
    peek = _kernel32().PeekNamedPipe
    avail = wintypes.DWORD()
    while peek(handle, None, 0, None, ctypes.byref(avail), None):
        if avail.value:  # a janela não escreve nada; se escrever, descarta (já está no pipe, não bloqueia)
            os.read(0, avail.value)
        time.sleep(0.3)


def watch_parent() -> None:
    """A janela mantém o stdin deste processo aberto; se ela some (fechou, travou, foi forçada a sair),
    o pipe fecha e o servidor se encerra — nunca fica um painel órfão rodando escondido."""
    import threading

    if os.name == "nt":
        handle = _stdin_pipe_windows()
        if handle is None:  # rodando à mão num terminal: não há janela para vigiar
            return
        wait_closed = lambda: _wait_stdin_closed_windows(handle)  # noqa: E731
    else:
        wait_closed = _wait_stdin_closed_posix

    def wait() -> None:
        wait_closed()
        os._exit(0)  # sai na hora, sem a finalização do Python

    threading.Thread(target=wait, daemon=True).start()


def run_server(port: int) -> None:
    watch_parent()
    sys.path.insert(0, str(BASE))
    from streamlit.web import cli as stcli

    sys.argv = ["streamlit", "run", str(SCRIPT),
                f"--server.port={port}", "--server.address=127.0.0.1", "--server.headless=true",
                "--browser.gatherUsageStats=false", "--global.developmentMode=false",
                "--server.fileWatcherType=none", "--server.runOnSave=false",
                "--client.toolbarMode=minimal"]  # sem o botão "Deploy" do Streamlit
    sys.exit(stcli.main())


# ------------------------------------------------------------------ processo principal (janela)
def start_server(port: int, log: Path) -> subprocess.Popen:
    cmd = [sys.executable] if FROZEN else [sys.executable, str(Path(__file__).resolve())]
    cmd += ["--servidor", str(port)]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    if log.exists():  # guarda a saída da vez anterior (útil se o app fechou sozinho)
        log.replace(log.with_suffix(".anterior.log"))
    out = open(log, "w", encoding="utf-8")  # noqa: SIM115 — fica aberto enquanto o servidor roda
    return subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
                            creationflags=flags, env=os.environ.copy())


def error_html(msg: str, log: Path) -> str:
    return (f"<html><body style='font-family:system-ui;padding:32px;max-width:640px'>"
            f"<h2>O painel não conseguiu abrir</h2><p>{msg}</p>"
            f"<p>Detalhes técnicos no arquivo:<br><code>{log}</code></p></body></html>")


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--servidor":
        prepare_env()
        run_server(int(sys.argv[2]))
        return

    import webview

    d = prepare_env()
    log = d / "painel.log"
    # app aberto duas vezes: a segunda janela usa o servidor da primeira (um só servidor mexendo no banco)
    lock = d / "painel.porta"
    try:
        old = int(lock.read_text().strip())
    except (OSError, ValueError):
        old = 0
    if old and healthy(old):
        port, server = old, None
    else:
        port = free_port()
        server = start_server(port, log)
        lock.write_text(str(port))
    url = f"http://127.0.0.1:{port}"

    loading = ("<html><body style='font-family:system-ui;display:flex;align-items:center;justify-content:center;"
               "height:100vh;margin:0;color:#555'><div style='text-align:center'><h2>Abrindo o Painel Financeiro…</h2>"
               "<p>Na primeira vez pode levar alguns segundos.</p></div></body></html>")
    window = webview.create_window(APP_NAME, html=loading, width=1360, height=880, min_size=(900, 600),
                                   text_select=True)  # deixa selecionar/copiar valores

    def wait_and_load() -> None:
        deadline = time.time() + 90
        while time.time() < deadline:
            if server is not None and server.poll() is not None:
                window.load_html(error_html("O servidor do painel fechou sozinho.", log))
                return
            if healthy(port):
                window.load_url(url)
                return
            time.sleep(0.3)
        window.load_html(error_html("O servidor demorou demais para responder.", log))

    webview.settings["ALLOW_DOWNLOADS"] = True  # botão "Baixar backup (.zip)"
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True  # links do GitHub etc. vão para o navegador
    try:
        webview.start(wait_and_load, private_mode=False, storage_path=str(d / "janela"))
    finally:
        if server is not None:  # só quem iniciou o servidor o encerra
            try:
                server.stdin.close()  # o cão de guarda do servidor vê o fim e sai sozinho (os._exit)
                server.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                server.kill()
            lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
