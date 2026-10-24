"""Aviso de versão nova: consulta o último release público no GitHub (sem enviar nenhum dado do usuário)."""
from __future__ import annotations

import json
import re
import urllib.request

REPO = "GabrielSaalvarenga/projeto-financeiro"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"


def parse(version: str) -> tuple[int, ...] | None:
    """'v0.3.1' -> (0, 3, 1); None se não parecer uma versão."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (version or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def is_newer(latest: str, current: str) -> bool:
    a, b = parse(latest), parse(current)
    return a is not None and b is not None and a > b


def latest_release(timeout: float = 4.0) -> dict | None:
    """{'version', 'url', 'notes'} do último release, ou None se offline/sem release (nunca levanta erro)."""
    try:
        req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": "painel-financeiro"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
        tag = str(data.get("tag_name", ""))
        if parse(tag) is None:
            return None
        return {"version": tag.lstrip("v"), "url": data.get("html_url") or RELEASES_URL, "notes": data.get("body") or ""}
    except Exception:  # noqa: BLE001 — sem internet, limite da API etc.: simplesmente não avisa
        return None


def available(current: str, fetch=latest_release) -> dict | None:
    rel = fetch()
    return rel if rel and is_newer(rel["version"], current) else None
