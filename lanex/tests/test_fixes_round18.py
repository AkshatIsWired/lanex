# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Round-18 lock-in tests for the platform/WSL + tooling batch:

* #1  WSL2 DNS: network_remediation surfaces the resolv.conf fix on a name
      failure; is_windows_mount_path detects WSL DrvFs / .exe binaries.
* #2  a Windows build on the WSL PATH is reported NOT installed (with a flag),
      so the GUI offers the Linux install instead of a false "installed".
* #3/#4  GDS3D's missing X11/GL dev headers map to the right Debian packages and
      the guidance names libx11-dev (the X11/keysym.h error).
* #5  graphviz is an installable EDA tool (binary `dot`) with apt/brew/conda/nix
      recipes and a verify that checks for `dot`.

All pure / tool-free — no OpenROAD, no Docker, no PDK, no network needed."""
from __future__ import annotations

from lanex.controller import installer, platform_env, tools


# ----------------------------------------------------------------- #1 WSL / DNS
def test_is_windows_mount_path():
    assert platform_env.is_windows_mount_path("/mnt/c/Tools/verilator.exe")
    assert platform_env.is_windows_mount_path("/mnt/d/x/yosys")
    assert platform_env.is_windows_mount_path("C:/HDL/iverilog.exe")
    assert not platform_env.is_windows_mount_path("/usr/bin/verilator")
    assert not platform_env.is_windows_mount_path("/home/u/.local/bin/dot")
    assert not platform_env.is_windows_mount_path("")
    assert not platform_env.is_windows_mount_path(None)


def test_network_failure_markers():
    assert platform_env.looks_like_network_failure("Could not resolve host: github.com")
    assert platform_env.looks_like_network_failure("httpx.ReadTimeout: timed out")
    assert platform_env.looks_like_network_failure("Temporary failure in name resolution")
    assert not platform_env.looks_like_network_failure("compilation succeeded")
    assert not platform_env.looks_like_network_failure("")


def test_network_remediation_on_failure(monkeypatch):
    # Even when DNS happens to resolve, output that shows a timeout returns guidance.
    monkeypatch.setattr(platform_env, "dns_ok", lambda *a, **k: True)
    assert platform_env.network_remediation("httpx.ReadTimeout") is not None
    # Clean output + working DNS → no false alarm.
    assert platform_env.network_remediation("everything fine") is None


def test_wsl_dns_remediation_mentions_resolv_conf(monkeypatch):
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    monkeypatch.setattr(platform_env, "dns_ok", lambda *a, **k: False)
    rem = platform_env.network_remediation("Could not resolve host")
    assert rem and "/etc/resolv.conf" in rem and "nameserver 8.8.8.8" in rem


# ----------------------------------------------------------- #2 WSL win-only probe
def test_wsl_windows_path_tool_reported_missing(monkeypatch):
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    monkeypatch.setattr(
        tools.shutil, "which",
        lambda c: "/mnt/c/HDL/bin/verilator.exe" if c == "verilator" else None,
    )
    res = tools._probe(["verilator"], ["--version"])
    assert res["installed"] is False
    assert res.get("windows_only") is True
    assert "/mnt/c/HDL/bin/verilator.exe" in res["error"]


def test_non_wsl_windows_path_not_filtered(monkeypatch):
    # Off WSL, the /mnt filter must not kick in (no false negatives).
    monkeypatch.setattr(platform_env, "is_wsl", lambda: False)
    res = tools._probe(["definitely_not_a_real_binary_xyz"], ["--version"])
    assert res["installed"] is False
    assert not res.get("windows_only")


# --------------------------------------------------------------- #3/#4 GDS3D deps
def test_gds3d_header_package_mapping():
    # Every X11/GL header GDS3D includes maps to a real Debian dev package.
    assert installer._GDS3D_HEADER_PACKAGES["X11/keysym.h"] == "libx11-dev"
    assert "GL/glut.h" in installer._GDS3D_HEADER_PACKAGES
    assert "libx11-dev" in installer._GDS3D_APT_PACKAGES
    assert "freeglut3-dev" in installer._GDS3D_APT_PACKAGES


def test_gds3d_dep_guidance_names_libx11(monkeypatch):
    g = installer._gds3d_dep_guidance(["libx11-dev", "freeglut3-dev"])
    assert "libx11-dev" in g
    assert "X11/keysym.h" in g
    # Cross-distro guidance, not apt-only.
    assert "dnf" in g and "pacman" in g


def test_missing_gds3d_packages_when_header_absent(monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer, "_header_present", lambda h: h != "X11/keysym.h")
    missing = installer._missing_gds3d_dev_packages()
    assert missing == ["libx11-dev"]


# ----------------------------------------------------------------- #5 graphviz
def test_graphviz_is_an_installable_tool():
    gv = next((t for t in tools.EDA_TOOLS if t["key"] == "graphviz"), None)
    assert gv is not None
    assert gv["binary"] == ["dot"]
    assert isinstance(gv["install"], dict)  # per-platform recipe → Install button


def test_graphviz_install_strategies_present():
    apt = installer._strategy_apt({"apt": True}, "graphviz")
    assert apt and apt[-1] == "graphviz"
    brew = installer._strategy_brew({"brew": True}, "graphviz")
    assert brew and brew[-1] == "graphviz"
    nix = installer._strategy_nix({"nix": True}, "graphviz")
    assert nix and nix[-1].endswith("graphviz")


def test_graphviz_verify_checks_dot(monkeypatch):
    monkeypatch.setattr(installer, "_check_cmd", lambda c: c == "dot")
    assert installer._verify_install("graphviz") is True
    monkeypatch.setattr(installer, "_check_cmd", lambda c: False)
    assert installer._verify_install("graphviz") is False
