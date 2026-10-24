"""Linha de comando: python -m financas.cli <sync|contas|backup|recategorize|export|demo>"""
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
    elif cmd == "contas":  # só a pasta de contas de consumo (o sync também faz isso)
        from . import config
        from .importers import bills_folder
        with session() as conn:
            res = bills_folder.import_folder(conn, config.BILLS_DIR, min_age=0)
        for r in res:
            print(f"{'✔' if r['ok'] else '✘'} {r['file']}: {r['message']}")
        print(f"{len(res)} PDF(s) em {config.BILLS_DIR / 'entrada'}")
    elif cmd == "backup":  # backup manual (o automático roda no sync e ao abrir o painel)
        from .backup import make
        print(f"Backup criado: {make('manual')}")
    elif cmd == "recategorize":
        with session() as conn:
            print(f"{recategorize(conn)} transações recategorizadas")
    elif cmd == "export":
        from .obsidian import export
        print(export(dry_run="--write" not in argv))
    elif cmd == "demo":
        from .demo import seed
        seed()
        print("Dados fictícios gravados. Rode o painel com a mesma FIN_DATA_DIR (ex.: data-demo)")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
