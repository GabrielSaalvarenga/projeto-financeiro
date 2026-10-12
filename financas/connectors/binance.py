"""Binance — SOMENTE LEITURA.

Criar a chave na Binance com APENAS "Enable Reading" marcado (sem trade, sem
saque) e, de preferência, com restrição de IP. Só endpoints de consulta são usados.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict
from datetime import date
from urllib.parse import urlencode

import requests

from .. import config
from ..db import log_sync

BASE = "https://api.binance.com"
STABLES = {"USDT", "USDC", "FDUSD", "BUSD"}


def _signed_get(path: str, **params) -> dict | list:
    params["timestamp"] = int(time.time() * 1000)
    query = urlencode(params)
    sig = hmac.new(config.BINANCE_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    r = requests.get(f"{BASE}{path}?{query}&signature={sig}",
                     headers={"X-MBX-APIKEY": config.BINANCE_API_KEY}, timeout=30)
    r.raise_for_status()
    return r.json()


def _price(symbol: str) -> float | None:
    r = requests.get(f"{BASE}/api/v3/ticker/price", params={"symbol": symbol}, timeout=15)
    return float(r.json()["price"]) if r.ok else None


def balances() -> dict[str, float]:
    total: dict[str, float] = defaultdict(float)
    for b in _signed_get("/api/v3/account", omitZeroBalances="true")["balances"]:
        asset = b["asset"][2:] if b["asset"].startswith("LD") else b["asset"]  # LDBTC = Earn legado
        total[asset] += float(b["free"]) + float(b["locked"])
    for path in ("/sapi/v1/simple-earn/flexible/position", "/sapi/v1/simple-earn/locked/position"):
        try:
            for row in _signed_get(path, size=100).get("rows", []):
                total[row["asset"]] += float(row.get("totalAmount") or row.get("amount") or 0)
        except requests.HTTPError:
            pass  # conta sem Earn ou permissão não concedida
    return {a: q for a, q in total.items() if q > 0}


def sync(conn) -> str:
    if not (config.BINANCE_API_KEY and config.BINANCE_API_SECRET):
        raise RuntimeError("Binance não configurada (.env: BINANCE_API_KEY, BINANCE_API_SECRET)")
    usd_brl = _price("USDTBRL")
    snap = date.today().isoformat()
    total_brl = 0.0
    for asset, qty in balances().items():
        if asset == "BRL":
            price_usd, value_brl = 1 / usd_brl, qty
        else:
            price_usd = 1.0 if asset in STABLES else _price(f"{asset}USDT")
            if price_usd is None:
                continue
            value_brl = qty * price_usd * usd_brl
        if value_brl < 1:  # poeira
            continue
        conn.execute(
            """INSERT OR REPLACE INTO holdings(snapshot, source, asset, asset_type, quantity, price_usd, value_brl)
               VALUES (?,?,?,?,?,?,?)""",
            (snap, "binance", asset, "CRYPTO", qty, price_usd, value_brl),
        )
        total_brl += value_brl
    msg = f"total R$ {total_brl:,.2f} (USDT/BRL {usd_brl:.2f})"
    log_sync(conn, "binance", True, msg)
    return msg
