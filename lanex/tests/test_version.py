from __future__ import annotations

import importlib.metadata

from lanex import _version


def test_version_is_the_installed_distribution_version() -> None:
    try:
        expected = importlib.metadata.version("lanex")
    except importlib.metadata.PackageNotFoundError:
        expected = _version.__version__
    assert _version.get_version() == expected
    assert not _version.get_version().startswith("0.1.0+")


def test_version_line_names_librelane(monkeypatch) -> None:
    monkeypatch.setattr(_version, "get_version", lambda: "1.2.3")
    line = _version.get_version_line()
    assert line.startswith("1.2.3")
    try:
        from librelane.__version__ import __version__ as librelane_version
    except Exception:
        assert line == "1.2.3"
    else:
        assert line == f"1.2.3 (librelane {librelane_version})"
