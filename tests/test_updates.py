from financas import updates


def test_parse_and_compare():
    assert updates.parse("v0.3.1") == (0, 3, 1)
    assert updates.parse("abc") is None
    assert updates.is_newer("0.10.0", "0.9.9")
    assert not updates.is_newer("0.3.0", "0.3.0")
    assert not updates.is_newer("lixo", "0.3.0")


def test_available():
    assert updates.available("0.3.0", lambda: {"version": "0.4.0", "url": "u", "notes": ""})["version"] == "0.4.0"
    assert updates.available("0.4.0", lambda: {"version": "0.4.0", "url": "u", "notes": ""}) is None
    assert updates.available("0.3.0", lambda: None) is None
