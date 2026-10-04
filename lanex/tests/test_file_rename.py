"""Renaming a project file from the RTL IDE keeps the config pointing at it."""
import json
from pathlib import Path

from lanex.controller import configedit, editor


def _project(tmp_path: Path, cfg: dict) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "top.v").write_text("module top; endmodule\n")
    (tmp_path / "constraints").mkdir()
    (tmp_path / "constraints" / "timing.sdc").write_text("# sdc\n")
    (tmp_path / "config.json").write_text(json.dumps(cfg, indent=2))
    return tmp_path


def _rename(d: Path, old: str, new: str) -> dict:
    before = configedit.resolve_sources(d, configedit.read_config(d)["data"])
    r = editor.rename_file(d, old, new)
    assert r["ok"], r
    return configedit.follow_rename(d, str(d / old), r["abs"], before)


def test_rename_refuses_overwrite_and_escape(tmp_path):
    d = _project(tmp_path, {"DESIGN_NAME": "top"})
    (d / "src" / "other.v").write_text("module other; endmodule\n")
    assert not editor.rename_file(d, "src/top.v", "src/other.v")["ok"]
    assert not editor.rename_file(d, "src/top.v", "../top.v")["ok"]
    assert not editor.rename_file(d, "src/top.v", "src/top.exe")["ok"]
    assert (d / "src" / "top.v").read_text().startswith("module top")


def test_explicit_list_and_sdc_follow_the_rename(tmp_path):
    d = _project(tmp_path, {"DESIGN_NAME": "top", "VERILOG_FILES": ["dir::src/top.v"],
                            "PNR_SDC_FILE": "dir::constraints/timing.sdc"})
    res = _rename(d, "src/top.v", "src/core.v")
    assert res["changed"] == ["VERILOG_FILES"]
    _rename(d, "constraints/timing.sdc", "constraints/chip.sdc")
    cfg = json.loads((d / "config.json").read_text())
    assert cfg["VERILOG_FILES"] == ["dir::src/core.v"]
    assert cfg["PNR_SDC_FILE"] == "dir::constraints/chip.sdc"


def test_glob_kept_when_it_still_matches(tmp_path):
    d = _project(tmp_path, {"DESIGN_NAME": "top", "VERILOG_FILES": "dir::src/*.v"})
    assert _rename(d, "src/top.v", "src/core.v")["changed"] == []
    assert json.loads((d / "config.json").read_text())["VERILOG_FILES"] == "dir::src/*.v"


def test_v_to_sv_under_a_v_glob_stays_in_the_build(tmp_path):
    d = _project(tmp_path, {"DESIGN_NAME": "top", "VERILOG_FILES": "dir::src/*.v"})
    _rename(d, "src/top.v", "src/top.sv")
    assert json.loads((d / "config.json").read_text())["VERILOG_FILES"] == ["dir::src/top.sv"]


def test_tcl_config_that_does_not_name_the_file_is_fine(tmp_path):
    d = _project(tmp_path, {})
    (d / "config.json").unlink()
    (d / "config.tcl").write_text('set ::env(DESIGN_NAME) top\n')
    assert _rename(d, "src/top.v", "src/core.v")["changed"] == []
