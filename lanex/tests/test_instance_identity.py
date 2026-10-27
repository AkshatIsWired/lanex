from __future__ import annotations

from lanex.controller import instance_identity


def test_windows_instance_identity_is_validated(monkeypatch):
    monkeypatch.setenv("LANEX_INSTANCE_ID", "11111111-2222-3333-4444-555555555555")
    monkeypatch.setenv("LANEX_SOURCE_SHA", "a" * 40)
    monkeypatch.setenv("LANEX_MANIFEST_HASH", "b" * 64)
    assert instance_identity.current() == {
        "instanceId": "11111111-2222-3333-4444-555555555555",
        "source": {"sha": "a" * 40, "manifestHash": "b" * 64},
    }


def test_partial_or_malformed_identity_is_never_advertised(monkeypatch):
    monkeypatch.setenv("LANEX_INSTANCE_ID", "not-an-install-id")
    monkeypatch.setenv("LANEX_SOURCE_SHA", "a" * 40)
    monkeypatch.setenv("LANEX_MANIFEST_HASH", "b" * 64)
    assert instance_identity.current() == {
        "instanceId": None,
        "source": {"sha": None, "manifestHash": None},
    }
