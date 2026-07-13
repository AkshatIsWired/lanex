# Copyright 2026 LanEx Contributors
"""GTKWave integration: catalog entry, installer strategies, launch argv,
VCD-header parsing, .gtkw generation, and the /api/ide/open-wave route."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from lanex.controller import desktop, installer, platform_env, tools, waveview


# ---------------------------------------------------------------------------
# Catalog + installer wiring
# ---------------------------------------------------------------------------

def _tool(key):
    hits = [t for t in tools.EDA_TOOLS if t["key"] == key]
    assert hits, f"{key} missing from EDA_TOOLS"
    return hits[0]


def test_gtkwave_in_eda_tools_optional_and_not_in_image():
    t = _tool("gtkwave")
    assert t.get("optional") is True
    # Verified absent from the LibreLane image — must never grow an
    # "in container" pill it can't deliver on.
    assert not t.get("in_image")
    assert t["binary"] == ["gtkwave"]
    assert "linux" in t["install"] and "darwin" in t["install"]


def test_gtkwave_apt_strategy():
    argv = installer._strategy_apt({"os": "linux", "apt": True}, "gtkwave")
    assert argv is not None and argv[-1] == "gtkwave" and "install" in argv


def test_gtkwave_brew_strategy_is_formula_not_cask():
    argv = installer._strategy_brew({"os": "darwin", "brew": True}, "gtkwave")
    assert argv is not None and argv[-1] == "gtkwave"
    # The old CASK is broken on modern macOS; the 2024 core FORMULA is the path.
    assert "--cask" not in argv


def test_gtkwave_nix_strategy():
    argv = installer._strategy_nix({"os": "linux", "nix": True}, "gtkwave")
    assert argv is not None and argv[-1].endswith("#gtkwave")


def test_gtkwave_verify_and_uninstall_wired():
    src = Path(installer.__file__).read_text()
    assert '"gtkwave": lambda: _check_cmd("gtkwave")' in src
    assert '"gtkwave": ["sudo", apt, "remove", "-y", "gtkwave"]' in src
    assert '"gtkwave": ["brew", "uninstall", "gtkwave"]' in src


def test_gtkwave_in_desktop_whitelist():
    assert "gtkwave" in desktop._TOOLS
    assert desktop._TOOLS["gtkwave"]["bin"] == "gtkwave"


# ---------------------------------------------------------------------------
# Launch argv
# ---------------------------------------------------------------------------

def test_build_argv_plain_open():
    argv = desktop._build_argv("gtkwave", "/usr/bin/gtkwave", "/d/dump.vcd", {}, False)
    assert argv == ["/usr/bin/gtkwave", "/d/dump.vcd"]


def test_build_argv_with_save_file():
    tech = {"gtkw_save": "/d/.lanex-wave.gtkw"}
    argv = desktop._build_argv("gtkwave", "gtkwave", "/d/dump.vcd", tech, False)
    assert argv == ["gtkwave", "-a", "/d/.lanex-wave.gtkw", "/d/dump.vcd"]


def test_open_in_tool_missing_gtkwave_reports_need(monkeypatch, tmp_path):
    vcd = tmp_path / "dump.vcd"
    vcd.write_text("$enddefinitions $end\n")
    monkeypatch.setattr(desktop, "_resolve_bin", lambda spec: None)
    res = desktop.open_in_tool("gtkwave", vcd, use_tech=False)
    assert res["ok"] is False and res["need"] == "gtkwave"


# ---------------------------------------------------------------------------
# VCD header parsing
# ---------------------------------------------------------------------------

VCD = """$date today $end
$timescale 1ns $end
$scope module tb $end
$var wire 1 ! clk $end
$var wire 1 " reset $end
$var wire 8 # data [7:0] $end
$scope module dut $end
$var reg 4 $ count [3:0] $end
$var wire 1 ! clk $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
"""


def test_vcd_signals_scopes_vectors_and_alias_dedupe(tmp_path):
    p = tmp_path / "dump.vcd"
    p.write_text(VCD)
    sigs = waveview.vcd_signals(p)
    names = [n for n, _ in sigs]
    # Scope-qualified, vector range preserved (the exact .gtkw spelling).
    assert names == ["tb.clk", "tb.reset", "tb.data[7:0]", "tb.dut.count[3:0]"]
    # The aliased id "!" appears once (first name wins), widths carried.
    widths = dict(sigs)
    assert widths["tb.data[7:0]"] == 8 and widths["tb.clk"] == 1


def test_vcd_signals_limit(tmp_path):
    body = "$scope module t $end\n" + "".join(
        f"$var wire 1 s{i} sig{i} $end\n" for i in range(100)
    ) + "$upscope $end\n$enddefinitions $end\n"
    p = tmp_path / "big.vcd"
    p.write_text(body)
    assert len(waveview.vcd_signals(p, limit=10)) == 10


def test_vcd_signals_malformed_and_missing(tmp_path):
    p = tmp_path / "junk.vcd"
    p.write_bytes(b"\x00\x01 this is not a vcd at all")
    assert waveview.vcd_signals(p) == []          # no $enddefinitions → []
    assert waveview.vcd_signals(tmp_path / "absent.vcd") == []


def test_gtkw_text_flags_and_dumpfile(tmp_path):
    dump = tmp_path / "dump.vcd"
    dump.write_text("x")
    text = waveview.gtkw_text(dump, [("tb.clk", 1), ("tb.data[7:0]", 8), ("tb.rst", 1)])
    lines = text.splitlines()
    assert f'[dumpfile] "{dump.resolve()}"' in lines
    # Flag words only when the width class changes: bit → bus → bit.
    joined = "\n".join(lines)
    assert joined.index("@28") < joined.index("tb.clk") < joined.index("@22") \
        < joined.index("tb.data[7:0]")
    assert joined.count("@28") == 2  # re-emitted after the bus


def test_write_gtkw_roundtrip(tmp_path):
    dump = tmp_path / "dump.vcd"
    dump.write_text("x")
    out = waveview.write_gtkw(tmp_path / ".lanex-wave.gtkw", dump, [("tb.clk", 1)])
    assert Path(out).is_file()
    assert "tb.clk" in Path(out).read_text()


# ---------------------------------------------------------------------------
# Route: /api/ide/open-wave
# ---------------------------------------------------------------------------

class _FakeHandler:
    def __init__(self, body):
        self._body = body
        self.command = "POST"
        self.sent = None

    # routes._respond uses handler._send_json / _send_text depending on type —
    # capture whatever comes through.
    def _send_json(self, obj, code=200):
        self.sent = (code, obj)

    def _send_text(self, text, code=200):
        self.sent = (code, text)


@pytest.fixture()
def _design(tmp_path, monkeypatch):
    from lanex.server import routes
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(tmp_path))
    return tmp_path


def _call(body):
    from lanex.server import routes
    h = _FakeHandler(body)
    routes.h_ide_open_wave(h)
    code, obj = h.sent
    # _respond wraps 2xx payloads as {"ok": True, "data": …} — unwrap like the
    # frontend's _fetch does, so assertions read the handler's own dict.
    if isinstance(obj, dict) and obj.get("ok") is True and "data" in obj:
        return code, obj["data"]
    return code, obj


def test_open_wave_route_registered():
    from lanex.server import routes
    assert any(p == "/api/ide/open-wave" for p, _ in routes.ROUTES)


def test_open_wave_rejects_traversal(_design):
    code, _ = _call({"path": "../../etc/passwd"})
    assert code == 400


def test_open_wave_rejects_non_dump(_design):
    (_design / "notes.txt").write_text("hi")
    code, obj = _call({"path": "notes.txt"})
    assert code == 200 and obj["ok"] is False and "not a waveform" in obj["error"]


def test_open_wave_missing_file_is_honest(_design):
    code, obj = _call({"path": "dump.vcd"})
    assert code == 200 and obj["ok"] is False and "run a simulation" in obj["error"]


def test_open_wave_missing_gtkwave_needs_install(_design, monkeypatch):
    (_design / "dump.vcd").write_text(VCD)
    monkeypatch.setattr(desktop, "_resolve_bin", lambda spec: None)
    code, obj = _call({"path": "dump.vcd"})
    assert code == 200 and obj["ok"] is False and obj["need"] == "gtkwave"
    # The save file was still generated before the resolve — prove the VCD
    # parse ran against the real dump (data-correctness of the handoff).
    save = _design / ".lanex-wave.gtkw"
    assert save.is_file()
    body = save.read_text()
    assert "tb.data[7:0]" in body and str((_design / "dump.vcd").resolve()) in body


def test_open_wave_launches_with_save_file(_design, monkeypatch):
    (_design / "dump.vcd").write_text(VCD)
    seen = {}

    def fake_open(tool, target, **kw):
        seen.update({"tool": tool, "target": str(target), **kw})
        return {"ok": True, "tool": tool}

    monkeypatch.setattr(desktop, "open_in_tool", fake_open)
    code, obj = _call({"path": "dump.vcd"})
    assert code == 200 and obj["ok"] is True
    assert seen["tool"] == "gtkwave"
    assert seen["save_file"].endswith(".lanex-wave.gtkw")
    assert obj["signals"] == 4  # tb.clk, tb.reset, tb.data, dut.count


def test_open_wave_fst_plain_open_no_save(_design, monkeypatch):
    (_design / "dump.fst").write_bytes(b"binary-fst")
    seen = {}

    def fake_open(tool, target, **kw):
        seen.update(kw)
        return {"ok": True}

    monkeypatch.setattr(desktop, "open_in_tool", fake_open)
    code, obj = _call({"path": "dump.fst"})
    assert code == 200 and obj["ok"] is True
    assert seen.get("save_file") is None  # FST header is binary — plain open


def test_frontend_wiring_present():
    """The button + api method exist in the served static (both IDE surfaces)."""
    static = Path(__file__).resolve().parents[1] / "server" / "static"
    assert 'id="ide-wave-gtkwave"' in (static / "ide.html").read_text()
    assert 'id="ide-wave-gtkwave"' in (static / "index.html").read_text()
    assert "/api/ide/open-wave" in (static / "modules" / "api.js").read_text()
    assert "openInGtkwave" in (static / "modules" / "ide" / "main.js").read_text()


def test_cli_install_tool_flag_exists():
    src = Path(desktop.__file__).resolve().parents[1] / "cli.py"
    body = src.read_text()
    assert "--install-tool" in body and "_install_tool_cli" in body


# ---------------------------------------------------------------------------
# WSL launch transport — the [WARN: COPY MODE] blank-window class.
# GTKWave is the only GTK3 tool LanEx launches; GTK3 picks WSLg's Wayland
# backend first, and that path degrades to a blank taskbar-only window. The
# launch env must pin it to X11/XWayland — the transport every other tool
# (Qt/Tk/GL) already uses and the one the software-GL fix was proven on.
# ---------------------------------------------------------------------------

def _clear_gui_env(monkeypatch):
    for var in ("LANEX_WAYLAND", "LANEX_HW_GL", "LIBRELANE_GUI_WSL_HW_GL",
                "LANEX_SOFTWARE_GL", "GDK_BACKEND", "QT_QPA_PLATFORM"):
        monkeypatch.delenv(var, raising=False)


def test_wsl_gui_env_pins_gtk_and_qt_to_x11(monkeypatch):
    _clear_gui_env(monkeypatch)
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    env = platform_env.wsl_gui_env({"PATH": "/usr/bin"})
    assert env["GDK_BACKEND"].startswith("x11")
    assert env["QT_QPA_PLATFORM"].startswith("xcb")
    # Fallback entries: a no-X11 system still gets a window, never an abort.
    assert "," in env["GDK_BACKEND"] or "*" in env["GDK_BACKEND"]
    # Superset of wsl_gl_env — the GL forcing must ride along.
    assert env["LIBGL_ALWAYS_SOFTWARE"] == "1"
    assert env["PATH"] == "/usr/bin"


def test_wsl_gui_env_noop_off_wsl(monkeypatch):
    _clear_gui_env(monkeypatch)
    monkeypatch.setattr(platform_env, "is_wsl", lambda: False)
    env = platform_env.wsl_gui_env({"PATH": "/usr/bin"})
    assert "GDK_BACKEND" not in env and "QT_QPA_PLATFORM" not in env
    assert "LIBGL_ALWAYS_SOFTWARE" not in env


def test_wsl_gui_env_wayland_opt_out(monkeypatch):
    _clear_gui_env(monkeypatch)
    monkeypatch.setenv("LANEX_WAYLAND", "1")
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    env = platform_env.wsl_gui_env({})
    assert "GDK_BACKEND" not in env and "QT_QPA_PLATFORM" not in env
    # The opt-out is transport-only — software GL stays (separate escape hatch).
    assert env["LIBGL_ALWAYS_SOFTWARE"] == "1"


def test_wsl_gui_env_respects_caller_value(monkeypatch):
    _clear_gui_env(monkeypatch)
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    env = platform_env.wsl_gui_env({"GDK_BACKEND": "wayland"})
    assert env["GDK_BACKEND"] == "wayland"  # setdefault, never clobber


def test_gtkwave_launch_env_pins_x11_under_wsl(tmp_path, monkeypatch):
    """End-to-end through open_in_tool: the Popen env for a gtkwave launch on
    WSL must carry the X11 pin + software GL — the fix for the user-reported
    blank [WARN: COPY MODE] window on a fresh WSL2 install."""
    _clear_gui_env(monkeypatch)
    dump = tmp_path / "dump.vcd"
    dump.write_text(VCD)
    captured = {}
    monkeypatch.setattr(desktop, "_resolve_bin", lambda spec: "gtkwave")
    monkeypatch.setattr(desktop.subprocess, "Popen",
                        lambda argv, **k: captured.update(argv=argv, env=k.get("env")))
    monkeypatch.setattr(platform_env, "host_display_available", lambda: True)
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)

    res = desktop.open_in_tool("gtkwave", dump, use_tech=False)
    assert res["ok"] is True
    assert captured["env"]["GDK_BACKEND"].startswith("x11")
    assert captured["env"]["QT_QPA_PLATFORM"].startswith("xcb")
    assert captured["env"]["LIBGL_ALWAYS_SOFTWARE"] == "1"
    assert captured["argv"][0] == "gtkwave"
