"""Linha de comando: python -m financas.cli <sync|recategorize|export|demo>"""
from __future__ import annotations

import sys

from .categorize import recategorize
from .db import session


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "sync"
    if cmd == "sync":
        from .sync import run_all
        for name, ok, msg in run_all():
            print(f"{'✔' if ok else '✘'} {name}: {msg}")
    elif cmd == "recategorize":
        with session() as conn:
            print(f"{recategorize(conn)} transações recategorizadas")
    elif cmd == "export":
        from .obsidian import export
        print(export(dry_run="--write" not in argv))
    elif cmd == "demo":
        from .demo import seed
        seed()
        print("Dados fictícios gravados. Rode o painel com FIN_DATA_DIR=data/demo")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
