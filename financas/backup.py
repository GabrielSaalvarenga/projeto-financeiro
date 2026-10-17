"""Backup do painel: um .zip com o banco (cópia consistente) e os PDFs de contas importadas.

Manual (botão na aba Configurações) ou automático: quando o painel abre ou o `sync` roda, se já passou o
intervalo escolhido (padrão 1x ao dia), um backup é feito. Guarda os KEEP_AUTO automáticos mais recentes;
os manuais nunca são apagados sozinhos. Tudo fica em <pasta de dados>/backups — nada depende da máquina.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from . import config, settings
from .db import session

KEEP_AUTO = 30
FMT = "%Y-%m-%d-%H%M%S"


def backup_dir() -> Path:
    d = config.DATA_DIR / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def make(kind: str = "manual") -> Path:
    """Cria um backup agora. `kind`: manual | auto."""
    now = datetime.now()
    dest = backup_dir() / f"backup-{now.strftime(FMT)}-{kind}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "financas.db"
        src, dst = sqlite3.connect(config.DB_PATH), sqlite3.connect(copy)
        with dst:
            src.backup(dst)  # cópia consistente mesmo com o banco em uso
        src.close()
        dst.close()
        pdfs = sorted((config.BILLS_DIR / "importadas").glob("*.pdf")) if (config.BILLS_DIR / "importadas").exists() else []
        part = dest.with_suffix(".part")
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(copy, "financas.db")
            for p in pdfs:
                z.write(p, f"contas/importadas/{p.name}")
            z.writestr("backup.json", json.dumps({"created": now.isoformat(timespec="seconds"), "kind": kind,
                                                   "pdfs": len(pdfs)}, ensure_ascii=False))
        part.rename(dest)  # só aparece na lista quando está completo
    if kind == "auto":
        prune()
    return dest


def list_backups() -> list[dict]:
    out = []
    for p in backup_dir().glob("backup-*.zip"):
        try:
            stamp, kind = p.stem.removeprefix("backup-").rsplit("-", 1)
            created = datetime.strptime(stamp, FMT)
        except ValueError:
            continue
        out.append({"path": p, "created": created, "kind": kind, "size": p.stat().st_size})
    return sorted(out, key=lambda b: b["created"], reverse=True)


def prune(keep: int = KEEP_AUTO) -> int:
    autos = [b for b in list_backups() if b["kind"] == "auto"]
    for b in autos[keep:]:
        b["path"].unlink()
    return max(0, len(autos) - keep)


def interval_h(conn) -> int:
    return int(settings.get(conn, "backup_interval_h"))


def next_due(conn) -> datetime | None:
    """Quando o próximo backup automático vence (None = desligado). Qualquer backup, manual ou não, conta."""
    h = interval_h(conn)
    if h <= 0:
        return None
    last = list_backups()
    return last[0]["created"] + timedelta(hours=h) if last else datetime.min


def auto() -> Path | None:
    """Faz o backup automático se já passou o intervalo. Devolve o arquivo criado ou None."""
    if not config.DB_PATH.exists():
        return None
    with session() as conn:
        due = next_due(conn)
    if due is None or datetime.now() < due:
        return None
    return make("auto")


def open_for_view(path: Path) -> Path:
    """Extrai o banco de um backup para visualização (atualizado para a versão atual do app, depois só leitura)."""
    view = backup_dir() / ".visualizar"
    view.mkdir(exist_ok=True)
    db = view / f"{path.stem}.db"
    if not db.exists():
        with zipfile.ZipFile(path) as z:
            db.write_bytes(z.read("financas.db"))
        with session(db):  # cria tabelas/colunas que um backup antigo não tinha
            pass
    return db
