"""Conexões com as fontes de dados, configuradas pela aba Configurações (sem editar arquivo de texto).

As chaves ficam no arquivo de ambiente (`config.ENV_FILE`, o `.env`) — nunca no banco, porque o banco vai
dentro do backup. A tela nunca mostra uma chave já salva. "Testar" faz só consultas de leitura.
Fonte nova = mais um item em SOURCES.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlencode

import requests
from dotenv import set_key

from . import config


@dataclass
class Field:
    key: str            # nome da variável no .env
    label: str
    secret: bool = True  # secreto: nunca exibido, campo mascarado
    help: str = ""


@dataclass
class Source:
    id: str
    name: str
    fields: list[Field]
    how_to: str
    test: Callable[[dict], str]  # recebe {chave: valor}; devolve mensagem ou levanta erro
    required: tuple[str, ...] = field(default=())


def _test_pluggy(slot: int) -> Callable[[dict], str]:
    return lambda v: _check_pluggy(v, slot)


def _check_pluggy(v: dict, slot: int) -> str:
    k = lambda name: config.pluggy_key(slot, name)  # noqa: E731
    r = requests.post("https://api.pluggy.ai/auth", json={"clientId": v[k("CLIENT_ID")],
                                                         "clientSecret": v[k("CLIENT_SECRET")]}, timeout=30)
    if r.status_code in (400, 401, 403):
        raise ValueError("Client ID ou Client Secret recusados pela Pluggy")
    r.raise_for_status()
    s = requests.Session()
    s.headers["X-API-KEY"] = r.json()["apiKey"]
    ids = [i.strip() for i in v.get(k("ITEM_IDS"), "").split(",") if i.strip()]
    if not ids:
        return "Chaves aceitas, mas nenhuma conexão (item) informada — nada será coletado."
    out = []
    for item_id in ids:
        g = s.get(f"https://api.pluggy.ai/items/{item_id}", timeout=30)
        if g.status_code == 404:
            out.append(f"{item_id[:8]}…: não encontrada")
            continue
        g.raise_for_status()
        item = g.json()
        name = (item.get("connector") or {}).get("name", item_id[:8])
        if name.lower() == "meupluggy":
            accts = s.get("https://api.pluggy.ai/accounts", params={"itemId": item_id}, timeout=30).json().get("results", [])
            n = accts[0]["name"].upper().replace("BANCO ", "").strip() if accts else name
            name = n if len(n) <= 3 else n.title()
        out.append(f"{name}: {item.get('status', '?')}")
    return "Conectado — " + " · ".join(out)


def _test_binance(v: dict) -> str:
    key, secret = v["BINANCE_API_KEY"], v["BINANCE_API_SECRET"]

    def get(path: str) -> dict:
        q = urlencode({"timestamp": int(time.time() * 1000)})
        sig = hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        r = requests.get(f"https://api.binance.com{path}?{q}&signature={sig}", headers={"X-MBX-APIKEY": key}, timeout=30)
        if 400 <= r.status_code < 500:  # chave errada, IP não liberado, relógio etc. — mensagem da Binance
            try:
                msg = r.json().get("msg", r.status_code)
            except ValueError:
                msg = r.status_code
            raise ValueError(f"a Binance recusou a chave ({msg})")
        r.raise_for_status()
        return r.json()

    rest = get("/sapi/v1/account/apiRestrictions")
    perigosas = [n for k, n in (("enableSpotAndMarginTrading", "negociar"), ("enableWithdrawals", "sacar"),
                                ("enableInternalTransfer", "transferir"), ("enableFutures", "futuros"),
                                ("enableMargin", "margem")) if rest.get(k)]
    if perigosas:
        raise ValueError("esta chave pode " + ", ".join(perigosas) + ". Por segurança, crie uma chave só com "
                         "\"Enable Reading\" na Binance — o painel não aceita chave que movimenta dinheiro")
    n = len([b for b in get("/api/v3/account")["balances"] if float(b["free"]) + float(b["locked"]) > 0])
    ip = "com IP restrito" if rest.get("ipRestrict") else "sem restrição de IP (recomendado restringir)"
    return f"Conectado — chave só de leitura, {ip}; {n} ativo(s) com saldo."


def _pluggy_source(slot: int) -> Source:
    k = lambda name: config.pluggy_key(slot, name)  # noqa: E731
    first = slot == 1
    return Source(
        "pluggy" if first else f"pluggy{slot}",
        "Pluggy — Open Finance (Inter, XP…)" if first else f"Pluggy — conta {slot} (outra pessoa ou outra conta Pluggy)",
        [Field(k("CLIENT_ID"), "Client ID", help="dashboard.pluggy.ai → Applications"),
         Field(k("CLIENT_SECRET"), "Client Secret", help="dashboard.pluggy.ai → Applications"),
         Field(k("ITEM_IDS"), "IDs das conexões (items)", secret=False,
               help="Um por instituição conectada no app Meu Pluggy, separados por vírgula"),
         Field(k("LABEL"), "Nome desta conta" + ("" if first else " (ex.: Esposa)"), secret=False,
               help="Ex.: Eu, Esposa, Empresa. Aparece ao lado das contas e investimentos desta conta Pluggy.")],
        how_to=("Conecte seus bancos no app **Meu Pluggy**, crie uma aplicação em **dashboard.pluggy.ai** e copie o "
                "Client ID e o Client Secret. Os IDs das conexões aparecem no Meu Pluggy. Só leitura: o painel nunca "
                "inicia pagamento ou Pix. Passo a passo completo na aba **Começar**." if first else
                "Use quando outra pessoa (ex.: cônjuge) tem a própria conta na Pluggy, ou quando você criou uma segunda "
                "conta de desenvolvedor porque o teste da primeira passou do prazo. Cada conta tem seu Client ID, "
                "Client Secret e IDs de conexão. Os dados das duas aparecem juntos no painel."),
        test=_test_pluggy(slot), required=(k("CLIENT_ID"), k("CLIENT_SECRET")))


SOURCES = [
    *[_pluggy_source(n) for n in config.PLUGGY_SLOTS],
    Source("binance", "Binance — saldos de cripto", [
        Field("BINANCE_API_KEY", "API Key"),
        Field("BINANCE_API_SECRET", "Secret Key"),
    ], how_to="Na Binance: **Perfil → Gerenciamento de API → Criar API**, marcando **apenas \"Enable Reading\"** "
              "(sem negociar, sem sacar) e, se possível, restringindo ao IP da sua casa. Passo a passo na aba **Começar**.",
       test=_test_binance, required=("BINANCE_API_KEY", "BINANCE_API_SECRET")),
]


def current(source: Source) -> dict:
    return {f.key: os.getenv(f.key, "") for f in source.fields}


def is_configured(source: Source) -> bool:
    cur = current(source)
    return all(cur[k] for k in source.required)


def merged(source: Source, typed: dict) -> dict:
    """Valores digitados por cima dos salvos (campo vazio = manter o salvo)."""
    cur = current(source)
    return {k: (typed.get(k) or "").strip() or cur[k] for k in cur}


def save(source: Source, typed: dict) -> list[str]:
    """Grava no arquivo de ambiente só os campos preenchidos. Devolve os nomes alterados (nunca os valores)."""
    changed = []
    env = config.ENV_FILE
    env.parent.mkdir(parents=True, exist_ok=True)
    env.touch(exist_ok=True)
    os.chmod(env, 0o600)  # só o dono do arquivo lê as chaves
    for f in source.fields:
        val = (typed.get(f.key) or "").strip()
        if f.key.endswith("ITEM_IDS") and val:
            val = ",".join(i.strip() for i in val.split(",") if i.strip())
        if val and val != os.getenv(f.key, ""):
            set_key(env, f.key, val, quote_mode="never")
            os.environ[f.key] = val
            changed.append(f.key)
    config.load_connections()
    return changed
