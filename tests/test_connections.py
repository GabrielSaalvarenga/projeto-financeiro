import os
import stat

import pytest

from financas import config, connections

PLUGGY, BINANCE = connections.SOURCES


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# comentário que deve continuar\nOUTRA=1\nBINANCE_API_KEY=antiga\n")
    monkeypatch.setattr(config, "ENV_FILE", f)
    for k in config.CONNECTION_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BINANCE_API_KEY", "antiga")
    yield f
    config.load_connections()


def test_save_writes_only_filled_fields_and_protects_file(env_file):
    changed = connections.save(BINANCE, {"BINANCE_API_KEY": "", "BINANCE_API_SECRET": " nova-secreta "})
    assert changed == ["BINANCE_API_SECRET"]
    text = env_file.read_text()
    assert "# comentário que deve continuar" in text and "OUTRA=1" in text
    assert "BINANCE_API_KEY=antiga" in text and "BINANCE_API_SECRET=nova-secreta" in text
    assert stat.S_IMODE(os.stat(env_file).st_mode) == 0o600
    assert config.BINANCE_API_SECRET == "nova-secreta"  # vale na hora, sem reiniciar


def test_merged_keeps_saved_when_blank(env_file):
    assert connections.merged(BINANCE, {"BINANCE_API_KEY": "", "BINANCE_API_SECRET": "x"}) == {
        "BINANCE_API_KEY": "antiga", "BINANCE_API_SECRET": "x"}
    assert not connections.is_configured(BINANCE)


def test_item_ids_are_normalized(env_file):
    connections.save(PLUGGY, {"PLUGGY_ITEM_IDS": " a , b,,c "})
    assert config.PLUGGY_ITEM_IDS == ["a", "b", "c"]


class _Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.text = data, status, str(data)

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


def test_binance_key_that_can_trade_is_refused(monkeypatch):
    def fake_get(url, **_):
        if "apiRestrictions" in url:
            return _Resp({"enableReading": True, "enableSpotAndMarginTrading": True, "enableWithdrawals": True})
        return _Resp({"balances": []})
    monkeypatch.setattr(connections.requests, "get", fake_get)
    with pytest.raises(ValueError, match="negociar, sacar"):
        BINANCE.test({"BINANCE_API_KEY": "k", "BINANCE_API_SECRET": "s"})


def test_binance_read_only_key_passes(monkeypatch):
    def fake_get(url, **_):
        if "apiRestrictions" in url:
            return _Resp({"enableReading": True, "ipRestrict": True})
        return _Resp({"balances": [{"asset": "BTC", "free": "0.1", "locked": "0"}, {"asset": "X", "free": "0", "locked": "0"}]})
    monkeypatch.setattr(connections.requests, "get", fake_get)
    assert "só de leitura, com IP restrito; 1 ativo" in BINANCE.test({"BINANCE_API_KEY": "k", "BINANCE_API_SECRET": "s"})
