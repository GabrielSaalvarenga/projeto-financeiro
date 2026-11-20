"""painel_desktop.py --servidor: a vigia do stdin (encerra o servidor quando a janela fecha)."""
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Igual ao servidor do app: liga a vigia e depois carrega o numpy (o painel importa o pandas).
# No Windows, com uma leitura bloqueante pendente no stdin, o import do numpy travava para sempre
# e a janela do app ficava branca.
SERVIDOR = (
    "import time, painel_desktop as d\n"
    "d.watch_parent()\n"
    "time.sleep(0.5)\n"  # a vigia já está esperando no stdin
    "import numpy\n"
    "print('importou', flush=True)\n"
    "time.sleep(60)\n"
)


def _readline(proc: subprocess.Popen, timeout: float) -> str | None:
    out: list[str] = []
    t = threading.Thread(target=lambda: out.append(proc.stdout.readline()), daemon=True)
    t.start()
    t.join(timeout)
    return out[0].strip() if out else None


def test_vigia_do_stdin_nao_trava_o_import_e_sai_quando_a_janela_fecha():
    proc = subprocess.Popen([sys.executable, "-c", SERVIDOR], cwd=ROOT, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        assert _readline(proc, 30) == "importou", "o import do numpy travou com a vigia do stdin ligada"
        assert proc.poll() is None  # stdin aberto: o servidor continua rodando
        proc.stdin.close()  # a janela fechou
        assert proc.wait(timeout=10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
