"""Preferências do painel guardadas no próprio banco (vão junto no backup)."""
from __future__ import annotations

DEFAULTS = {
    "backup_interval_h": "24",  # 0 = backup automático desligado
    "theme": "system",          # system | light | dark
    "update_check": "1",        # 1 = avisa quando houver versão nova no GitHub
}
BACKUP_CHOICES = {0: "Desligado", 6: "A cada 6 horas", 12: "A cada 12 horas", 24: "1 vez ao dia", 168: "1 vez por semana"}
THEMES = {"system": "Seguir o sistema", "light": "Claro", "dark": "Escuro"}


def get(conn, key: str) -> str:
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else DEFAULTS[key]


def set_(conn, key: str, value) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, str(value)))
