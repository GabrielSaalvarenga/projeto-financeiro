"""Duas contas Pluggy ao mesmo tempo (marido e mulher, ou segunda conta de desenvolvedor). Sem rede: API falsa."""
import pytest

from financas import config, connections
from financas.connectors import pluggy
from financas.db import session


class FakeApi:
    """Cada Client ID enxerga só as próprias conexões, como na Pluggy de verdade."""
    DATA = {"idA": {"items": {"i1": ("Inter", "a-acc", 100.0)}}, "idB": {"items": {"i2": ("Inter", "b-acc", 50.0)}}}

    def __init__(self, client_id, client_secret):
        if client_secret == "ruim":
            raise RuntimeError("Client Secret recusado")
        self.items = self.DATA[client_id]["items"]

    def get(self, path, **params):
        if path.startswith("/items/"):
            return {"connector": {"name": self.items[path.split("/")[-1]][0]}}
        if path == "/accounts":
            _, acc_id, bal = self.items[params["itemId"]]
            return {"results": [{"id": acc_id, "name": "Conta", "type": "BANK", "balance": bal}]}
        if path == "/investments":
            return {"results": [{"id": "x", "name": "CDB", "type": "FIXED_INCOME", "balance": 10}]}
        return {"results": []}

    def transactions(self, account_id, date_from):
        yield {"id": f"tx-{account_id}", "date": "2026-10-01T00:00:00Z", "description": "Mercado", "amount": 20, "type": "DEBIT"}


@pytest.fixture
def two_accounts(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    for k in config.CONNECTION_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PLUGGY_CLIENT_ID", "idA")
    monkeypatch.setenv("PLUGGY_CLIENT_SECRET", "sA")
    monkeypatch.setenv("PLUGGY_ITEM_IDS", "i1")
    monkeypatch.setenv("PLUGGY_2_CLIENT_ID", "idB")
    monkeypatch.setenv("PLUGGY_2_CLIENT_SECRET", "sB")
    monkeypatch.setenv("PLUGGY_2_ITEM_IDS", "i2")
    monkeypatch.setenv("PLUGGY_2_LABEL", "Esposa")
    monkeypatch.setattr(pluggy, "Pluggy", FakeApi)
    config.load_connections()
    yield
    config.load_connections()


def test_config_reads_both_slots(two_accounts):
    a, b = config.PLUGGY_ACCOUNTS
    assert (a["slot"], a["client_id"], a["item_ids"]) == (1, "idA", ["i1"])
    assert (b["slot"], b["client_id"], b["label"]) == (2, "idB", "Esposa")


def test_second_slot_unnamed_gets_default_label(two_accounts, monkeypatch):
    monkeypatch.delenv("PLUGGY_2_LABEL")
    config.load_connections()
    assert config.PLUGGY_ACCOUNTS[1]["label"] == "Conta 2"


def test_incomplete_second_slot_is_ignored(two_accounts, monkeypatch):
    monkeypatch.delenv("PLUGGY_2_ITEM_IDS")
    config.load_connections()
    assert [a["slot"] for a in config.PLUGGY_ACCOUNTS] == [1]


def test_sync_all_collects_both_without_mixing(two_accounts, tmp_path):
    with session(tmp_path / "t.db") as conn:
        report = pluggy.sync_all(conn)
        assert [ok for _, ok, _ in report] == [True, True]
        rows = {r["id"]: r["owner"] for r in conn.execute("SELECT id, owner FROM accounts")}
        assert rows == {"a-acc": None, "b-acc": "Esposa"}
        # mesma corretora nas duas contas: investimentos não se sobrepõem
        sources = {r["source"] for r in conn.execute("SELECT source FROM holdings")}
        assert sources == {"inter", "inter (Esposa)"}
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_one_failing_account_does_not_stop_the_other(two_accounts, monkeypatch, tmp_path):
    monkeypatch.setenv("PLUGGY_CLIENT_SECRET", "ruim")
    config.load_connections()
    with session(tmp_path / "t2.db") as conn:
        report = pluggy.sync_all(conn)
        assert [ok for _, ok, _ in report] == [False, True]
        assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1


def test_save_second_slot_writes_numbered_keys(two_accounts, tmp_path):
    changed = connections.save(connections.SOURCES[1], {"PLUGGY_2_LABEL": " Marido ", "PLUGGY_2_ITEM_IDS": " a , b "})
    assert set(changed) == {"PLUGGY_2_LABEL", "PLUGGY_2_ITEM_IDS"}
    assert config.PLUGGY_ACCOUNTS[1]["item_ids"] == ["a", "b"] and config.PLUGGY_ACCOUNTS[1]["label"] == "Marido"


def test_connection_test_uses_second_slot_keys(two_accounts, monkeypatch):
    seen = {}

    class R:
        status_code = 200
        def __init__(self, data): self.data = data
        def json(self): return self.data
        def raise_for_status(self): pass

    def fake_post(url, json=None, **_):
        seen["client"] = json["clientId"]
        return R({"apiKey": "k"})

    monkeypatch.setattr(connections.requests, "post", fake_post)
    monkeypatch.setattr(connections.requests.Session, "get", lambda self, url, **kw: R(
        {"connector": {"name": "Inter"}, "status": "UPDATED"}))
    msg = connections.SOURCES[1].test({"PLUGGY_2_CLIENT_ID": "idB", "PLUGGY_2_CLIENT_SECRET": "sB", "PLUGGY_2_ITEM_IDS": "i2"})
    assert seen["client"] == "idB" and "Inter: UPDATED" in msg
