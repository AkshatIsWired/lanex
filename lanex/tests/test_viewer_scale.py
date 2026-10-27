"""Desktop viewers match the host display scale (HiDPI under WSLg).

WSLg shows X11 apps 1:1 in physical pixels and reports 96 DPI, so on a 4K /
175 % Windows laptop KLayout, GTKWave, Magic and the OpenROAD GUI opened at
about half the size of the Windows UI. LanEx now reads the Windows scale and
sets each toolkit's own scale knob per launch.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lanex.controller import container_tools, desktop, platform_env

# Trimmed from a real WSLg 1.0.65 weston.log (Windows at 175 %, 2880x1800).
WESTON_175 = """\
[18:30:30.286] RDP backend: enable_hi_dpi_support = 1
[18:30:30.286] \trdpMonitor[0]: x:0, y:0, width:0, height:0, is_primary:1
[18:30:30.286] \trdpMonitor[0]: desktopScaleFactor:0, deviceScaleFactor:0
[18:30:30.286] \trdpMonitor[0]: scale:1, clientScale:1.00
[18:30:34.142]   DesktopWidth:2880, DesktopHeight:1800
[18:30:34.144] \trdpMonitor[0]: x:0, y:0, width:2880, height:1800, is_primary:1
[18:30:34.144] \trdpMonitor[0]: desktopScaleFactor:175, deviceScaleFactor:180
[18:30:34.144] \trdpMonitor[0]: scale:1, client scale :1.00
[18:30:34.149] \trdpMonitor[0]: x:0, y:0, width:2880, height:1800, is_primary:1
[18:30:34.149] \trdpMonitor[0]: desktopScaleFactor:0, deviceScaleFactor:180
[18:30:34.149] \trdpMonitor[0]: scale:1, clientScale:1.00
"""

_SCALE_ENV = platform_env.VIEWER_SCALE_VARS + ("LANEX_VIEWER_SCALE",)


@pytest.fixture
def clean_env(monkeypatch):
    for var in _SCALE_ENV + ("LANEX_WAYLAND", "LANEX_HW_GL", "LIBRELANE_GUI_WSL_HW_GL",
                             "GDK_BACKEND", "QT_QPA_PLATFORM"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def _wsl_with_log(monkeypatch, tmp_path: Path, text: str) -> None:
    log = tmp_path / "weston.log"
    log.write_text(text)
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    monkeypatch.setattr(platform_env, "_WESTON_LOG", log)
    monkeypatch.setattr(platform_env, "_windows_applied_dpi_scale", lambda: None)


def test_parse_real_wslg_log_finds_windows_scale():
    # The applied-layout re-log says desktopScaleFactor:0; the client's 175 wins.
    assert platform_env.parse_weston_scale(WESTON_175) == 1.75


def test_parse_uses_primary_monitor():
    text = (
        "rdpMonitor[0]: x:0, y:0, width:1920, height:1080, is_primary:0\n"
        "rdpMonitor[0]: desktopScaleFactor:100, deviceScaleFactor:100\n"
        "rdpMonitor[1]: x:1920, y:0, width:3840, height:2160, is_primary:1\n"
        "rdpMonitor[1]: desktopScaleFactor:150, deviceScaleFactor:140\n"
    )
    assert platform_env.parse_weston_scale(text) == 1.5


def test_parse_never_double_scales_when_weston_already_magnifies():
    # A user .wslgconfig with WESTON_RDP_HI_DPI_SCALING: Weston already draws
    # X11 apps at 2x, so LanEx must add nothing.
    text = (WESTON_175.replace("scale:1, client scale :1.00", "scale:2, client scale :2.00")
            .replace("scale:1, clientScale:1.00", "scale:2, clientScale:2.00"))
    assert platform_env.parse_weston_scale(text) == 1.0


def test_parse_without_layout_is_none():
    assert platform_env.parse_weston_scale("Output repaint window is 7 ms\n") is None


def test_scale_env_qt_exact_gtk_rounded(clean_env):
    env = platform_env.viewer_scale_env({}, scale=1.75)
    assert env["QT_SCALE_FACTOR"] == "1.75"
    assert env["GDK_SCALE"] == "2" and env["GDK_DPI_SCALE"] == "0.875"
    assert env["XCURSOR_SIZE"] == "42"
    env = platform_env.viewer_scale_env({}, scale=1.25)
    assert env["GDK_SCALE"] == "1" and env["GDK_DPI_SCALE"] == "1.25"


def test_scale_env_noop_at_100_percent(clean_env):
    assert platform_env.viewer_scale_env({"PATH": "/bin"}, scale=1.0) == {"PATH": "/bin"}


def test_scale_env_keeps_users_own_choice(clean_env):
    env = platform_env.viewer_scale_env({"GDK_SCALE": "1", "QT_SCALE_FACTOR": "1.2"}, scale=2.0)
    assert env["GDK_SCALE"] == "1" and "GDK_DPI_SCALE" not in env
    assert env["QT_SCALE_FACTOR"] == "1.2"


def test_override_variable(clean_env):
    clean_env.setattr(platform_env, "is_wsl", lambda: False)
    clean_env.setenv("LANEX_VIEWER_SCALE", "150%")
    assert platform_env.viewer_scale() == 1.5
    clean_env.setenv("LANEX_VIEWER_SCALE", "1")
    assert platform_env.viewer_scale() == 1.0
    clean_env.setenv("LANEX_VIEWER_SCALE", "nonsense")
    assert platform_env.viewer_scale() == 1.0


def test_native_linux_is_left_to_the_desktop(clean_env):
    clean_env.setattr(platform_env, "is_wsl", lambda: False)
    assert platform_env.viewer_scale() == 1.0


def test_registry_fallback_when_log_unreadable(clean_env, tmp_path):
    clean_env.setattr(platform_env, "is_wsl", lambda: True)
    clean_env.setattr(platform_env, "_WESTON_LOG", tmp_path / "missing.log")
    clean_env.setattr(platform_env, "_windows_applied_dpi_scale", lambda: 1.5)
    assert platform_env.viewer_scale() == 1.5


def test_tk_snippet_scales_fonts_and_tkcon():
    tcl = platform_env.tk_scale_tcl(1.75)
    assert "tk scaling" in tcl and "font configure" in tcl
    assert "tkcon master eval" in tcl            # Magic/Netgen console interpreter
    assert "::lanex_tk_scaled" in tcl       # idempotent
    assert tcl.count("{") == tcl.count("}")
    assert platform_env.tk_scale_tcl(1.0) == ""


def _capture_popen(monkeypatch, captured):
    class _Proc:
        def poll(self):
            return 0
    def fake(argv, **kw):
        captured.update(argv=argv, env=kw.get("env"))
        return _Proc()
    monkeypatch.setattr(desktop.subprocess, "Popen", fake)


def test_gtkwave_launch_is_scaled_on_hidpi_wsl(clean_env, tmp_path):
    _wsl_with_log(clean_env, tmp_path, WESTON_175)
    dump = tmp_path / "dump.vcd"
    dump.write_text("$enddefinitions $end\n")
    captured: dict = {}
    clean_env.setattr(desktop, "_resolve_bin", lambda spec: "gtkwave")
    clean_env.setattr(platform_env, "host_display_available", lambda: True)
    _capture_popen(clean_env, captured)
    assert desktop.open_in_tool("gtkwave", dump, use_tech=False)["ok"] is True
    assert captured["env"]["GDK_SCALE"] == "2"
    assert captured["env"]["QT_SCALE_FACTOR"] == "1.75"


def test_native_magic_starts_through_scaling_rcfile(clean_env, tmp_path):
    _wsl_with_log(clean_env, tmp_path, WESTON_175)
    clean_env.setenv("LANEX_HOME", str(tmp_path / "home"))
    gds = tmp_path / "top.gds"
    gds.write_bytes(b"\0")
    pdk_rc = tmp_path / "sky130A.magicrc"
    pdk_rc.write_text("# pdk rc\n")
    captured: dict = {}
    clean_env.setattr(desktop, "_resolve_bin", lambda spec: "magic")
    clean_env.setattr(platform_env, "host_display_available", lambda: True)
    clean_env.setattr(desktop, "_pdk_tech_files",
                      lambda pdk, root: {"magicrc": str(pdk_rc), "klayout_lyp": None, "root": str(tmp_path)})
    _capture_popen(clean_env, captured)
    assert desktop.open_in_tool("magic", gds, pdk="sky130A", pdk_root=str(tmp_path))["ok"] is True
    argv = captured["argv"]
    assert argv[1] == "-rcfile" and argv[-1] == str(gds)
    startup = Path(argv[2]).read_text()
    assert "font configure" in startup
    assert f"source {{{pdk_rc}}}" in startup


def test_native_magic_unchanged_at_100_percent(clean_env, tmp_path):
    _wsl_with_log(clean_env, tmp_path, WESTON_175.replace(":175,", ":100,"))
    gds = tmp_path / "top.gds"
    gds.write_bytes(b"\0")
    captured: dict = {}
    clean_env.setattr(desktop, "_resolve_bin", lambda spec: "magic")
    clean_env.setattr(platform_env, "host_display_available", lambda: True)
    _capture_popen(clean_env, captured)
    assert desktop.open_in_tool("magic", gds, use_tech=False)["ok"] is True
    assert captured["argv"] == ["magic", str(gds)]


def test_container_flags_carry_scale(clean_env, tmp_path):
    _wsl_with_log(clean_env, tmp_path, WESTON_175)
    flags = container_tools._x11_flags()
    assert "QT_SCALE_FACTOR=1.75" in flags and "GDK_SCALE=2" in flags


def test_container_flags_forward_host_desktop_scale(clean_env):
    # Native Linux desktop at 200 %: the container gets the host's own values.
    clean_env.setattr(platform_env, "is_wsl", lambda: False)
    clean_env.setenv("GDK_SCALE", "2")
    clean_env.setenv("QT_SCALE_FACTOR", "2")
    flags = container_tools._x11_flags()
    assert "GDK_SCALE=2" in flags and "QT_SCALE_FACTOR=2" in flags


def test_container_magic_and_netgen_scripts(clean_env, tmp_path):
    _wsl_with_log(clean_env, tmp_path, WESTON_175)
    work = tmp_path / "run"
    work.mkdir()
    sp = container_tools._write_startup_script("magic", work, odb=None, pdk=None, pdk_root=None)
    assert sp is not None and sp.parent == work and "font configure" in sp.read_text()
    argv = container_tools._tool_command("magic", gds=work / "x.gds", pdk=None, pdk_root=None,
                                         odb=None, script=sp)
    assert argv == ["magic", "-rcfile", str(sp), str(work / "x.gds")]
    ng = container_tools._write_startup_script("netgen", work, odb=None, pdk=None, pdk_root=None)
    assert "font configure" in ng.read_text()
