from types import SimpleNamespace

import lan_access


def test_localhost_is_never_gated():
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), url=SimpleNamespace(path="/api/generate"), method="POST", cookies={})
    assert lan_access.gate(request) is None


def test_remote_blocked_when_lan_is_off(tmp_path, monkeypatch):
    monkeypatch.setattr(lan_access, "SETTINGS", tmp_path / "lan.json")
    request = SimpleNamespace(client=SimpleNamespace(host="192.168.1.50"), url=SimpleNamespace(path="/api/generate"), method="POST", cookies={})
    blocked = lan_access.gate(request)
    assert blocked is not None
    assert blocked.status_code == 403


def test_remote_open_when_lan_is_on_without_password(tmp_path, monkeypatch):
    monkeypatch.setattr(lan_access, "SETTINGS", tmp_path / "lan.json")
    lan_access.update(enabled=True)
    request = SimpleNamespace(client=SimpleNamespace(host="192.168.1.50"), url=SimpleNamespace(path="/api/library"), method="GET", cookies={})
    assert lan_access.gate(request) is None
