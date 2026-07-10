# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Contract lock for the universal installer (scripts/install.sh).

The behavioural proof lives in container runs (Debian 12 / Ubuntu 22.04 /
Fedora 40 / Arch, plus the venv-fallback, sudo-refusal, shim and re-run cases —
all exercised live before this suite existed). These tests lock the properties
a future edit could silently drop:

  * both scripts stay valid bash,
  * the whole installer runs through main() called on the last line (a partial
    `curl | bash` download must never execute half a command),
  * no `set -e` (fallback chains must degrade, not abort),
  * the default install source is the GitHub tarball (no git dependency, no
    PyPI-name-squat window before the real PyPI release),
  * the sudo-refusal guard and the documented env knobs exist,
  * the legacy install-wsl.sh URL keeps working as a shim.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "scripts" / "install.sh"
SHIM = REPO / "scripts" / "install-wsl.sh"


def _bash_n(path: Path) -> None:
    res = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    assert res.returncode == 0, f"bash -n failed for {path.name}: {res.stderr}"


def test_install_script_is_valid_bash() -> None:
    _bash_n(INSTALL)


def test_shim_is_valid_bash() -> None:
    _bash_n(SHIM)


def test_partial_download_guard_main_on_last_line() -> None:
    lines = [ln.strip() for ln in INSTALL.read_text().splitlines() if ln.strip()]
    assert lines[-1] == 'main "$@"'
    # ... and nothing above main's definition executes stages directly.
    body = INSTALL.read_text()
    assert body.index("main() {") < body.index('\nmain "$@"')


def test_no_set_e_fallback_chains_must_degrade() -> None:
    body = INSTALL.read_text()
    assert "set -u -o pipefail" in body
    import re
    directives = [ln for ln in body.splitlines()
                  if re.match(r"^\s*set\s+-\S*e", ln.strip())]
    assert directives == [], f"set -e would abort the fallback chains: {directives}"


def test_default_source_is_github_tarball() -> None:
    body = INSTALL.read_text()
    assert "archive/refs/heads/" in body
    assert 'github) echo "$TARBALL"' in body
    # PyPI stays an explicit opt-in until the name is actually published.
    assert 'pypi)   echo "lanex"' in body


def test_sudo_refusal_guard_present() -> None:
    body = INSTALL.read_text()
    assert "SUDO_USER" in body
    assert "Don't run this installer with sudo" in body


def test_documented_env_knobs_are_wired() -> None:
    body = INSTALL.read_text()
    for knob in ("LANEX_FROM", "LANEX_REF", "LANEX_SKIP_PULL",
                 "LANEX_NO_PIPX", "LANEX_ASSUME_YES"):
        assert f"${{{knob}" in body, f"{knob} documented but not read"


def test_build_tools_retry_stage_present() -> None:
    # The Arch/py3.13 lesson: a dependency without a prebuilt wheel needs a
    # compiler; the installer must install build tools and retry, not die.
    body = INSTALL.read_text()
    assert "build_tools_stage" in body
    assert "base-devel" in body and "build-essential" in body


def test_shim_delegates_to_universal_installer() -> None:
    body = SHIM.read_text()
    assert "install.sh" in body
    assert "curl" in body and "wget" in body


def test_readme_points_at_universal_installer() -> None:
    readme = (REPO / "README.md").read_text()
    assert "scripts/install.sh | bash" in readme
    # The paste-broken `exec bash` pattern must not come back to the blocks.
    assert "&& exec bash" not in readme
    assert "&& exec zsh" not in readme
