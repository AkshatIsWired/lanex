# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Packaging lock-in: every runtime data file is actually declared for the wheel.

The GUI ships non-Python assets (the frontend under ``server/static``, the
curated registries ``controller/*.json``, and the project templates). If one is
added but not covered by ``[tool.setuptools.package-data]`` it silently vanishes
from an installed wheel and the GUI 404s/crashes only for end users. This test
expands the declared globs with the *same* glob engine setuptools uses and
asserts they cover the real files — no wheel build needed, fast + deterministic.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent.parent          # .../lanex
_GUI = _REPO / "lanex"


def _load_package_data_globs() -> list[str]:
    """The ``gui`` package-data patterns from pyproject (tomllib; skip on <3.11)."""
    try:
        import tomllib
    except ModuleNotFoundError:  # py3.10 has no stdlib TOML reader
        pytest.skip("tomllib unavailable (<3.11); covered on newer interpreters")
    data = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))
    pkg = data["tool"]["setuptools"]["package-data"]
    return pkg["lanex"]


def _declared_files() -> set:
    declared = set()
    for pat in _load_package_data_globs():
        for p in glob.glob(str(_GUI / pat), recursive=True):
            if os.path.isfile(p):
                declared.add(os.path.realpath(p))
    return declared


def _needed_data_files() -> set:
    """Runtime non-Python assets that MUST ride along in the wheel."""
    needed = set()
    roots = [
        _GUI / "server" / "static",
        _GUI / "controller" / "templates",
    ]
    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            if "__pycache__" in dirpath:
                continue
            for f in files:
                if f.endswith((".py", ".pyc")):
                    continue
                needed.add(os.path.realpath(os.path.join(dirpath, f)))
    # Curated registries beside the controller code.
    for j in (_GUI / "controller").glob("*.json"):
        needed.add(os.path.realpath(str(j)))
    return needed


def test_package_data_covers_all_runtime_assets():
    declared = _declared_files()
    needed = _needed_data_files()
    missing = sorted(p for p in needed if p not in declared)
    assert not missing, (
        "These runtime asset(s) are NOT covered by [tool.setuptools.package-data] "
        "in pyproject.toml — they'd be dropped from the wheel:\n  "
        + "\n  ".join(os.path.relpath(p, _GUI) for p in missing)
    )


def test_at_least_the_known_assets_exist():
    # Guards against the walk silently matching nothing (e.g. a moved dir).
    assert (_GUI / "server" / "static" / "app.js").is_file()
    assert (_GUI / "server" / "static" / "index.html").is_file()
    assert list((_GUI / "controller").glob("*.json")), "curated registry json(s) missing"
    assert (_GUI / "controller" / "templates").is_dir()


def test_main_module_entrypoint_present():
    # `python -m lanex` must work (mirrors the librelane-gui console script).
    assert (_GUI / "__main__.py").is_file()
    text = (_GUI / "__main__.py").read_text(encoding="utf-8")
    assert "main" in text and "cli" in text
