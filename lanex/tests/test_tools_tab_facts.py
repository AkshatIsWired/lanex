"""Read-only facts the Tools tab shows: PDK installed vs pinned version, the
image's tested digest, and host facts for "Copy diagnostics"."""

from pathlib import Path

from lanex.controller import container_run, pdk as pdk_mod, tools


def _ciel_store(root: Path, family: str, ver: str, variant: str) -> None:
    store = root / "ciel" / family / "versions" / ver / variant
    (store / "libs.ref").mkdir(parents=True)
    (root / variant).symlink_to(store)


def test_pdk_versions_reads_the_enabled_version_and_the_pin(tmp_path, monkeypatch):
    _ciel_store(tmp_path, "sky130", "a" * 40, "sky130A")
    (tmp_path / "manualB" / "libs.ref").mkdir(parents=True)
    monkeypatch.setattr(tools, "_pdk_roots", lambda: [tmp_path])
    monkeypatch.setattr(pdk_mod, "required_pdk_version", lambda fam: {"sky130": "b" * 40}.get(fam))
    catalog = {"sky130A": {"family": "sky130"}, "manualB": {"family": "manual"}}
    out = tools.pdk_versions(["sky130A", "manualB"], catalog)
    assert out["sky130A"] == {"installed": "a" * 40, "pinned": "b" * 40}
    # A manual (non-ciel) install has no version hash; never invent one.
    assert out["manualB"] == {"installed": "", "pinned": ""}


def test_image_provenance_flags_overrides_and_other_digests(monkeypatch):
    monkeypatch.setattr(container_run, "_KNOWN_IMAGE_DIGESTS", {"9.9.9": "sha256:abc"})
    import librelane  # type: ignore

    monkeypatch.setattr(librelane, "__version__", "9.9.9", raising=False)
    monkeypatch.delenv("LIBRELANE_IMAGE_OVERRIDE", raising=False)
    monkeypatch.setattr(container_run, "image_ref", lambda: "ghcr.io/librelane/librelane:9.9.9@sha256:abc")
    p = container_run.image_provenance()
    assert p["image_tested_digest"] == "sha256:abc" and p["image_custom"] is False
    monkeypatch.setattr(container_run, "image_ref", lambda: "ghcr.io/librelane/librelane:9.9.9@sha256:other")
    assert container_run.image_provenance()["image_custom"] is True
    monkeypatch.setenv("LIBRELANE_IMAGE_OVERRIDE", "my/image:dev")
    assert container_run.image_provenance()["image_custom"] is True
    monkeypatch.delenv("LIBRELANE_IMAGE_OVERRIDE")
    monkeypatch.setattr(container_run, "_KNOWN_IMAGE_DIGESTS", {})
    assert container_run.image_provenance()["image_custom"] is None


def test_host_facts_are_plain_strings():
    h = tools.host_facts()
    assert set(h) >= {"kernel", "os", "python", "wsl"}
    assert all(isinstance(v, str) for v in h.values())
