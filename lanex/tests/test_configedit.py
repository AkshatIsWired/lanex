"""configedit: LanEx changes only the keys it is asked to, and never corrupts
anything else in a design's config file."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from lanex.controller import configedit
from lanex.controller.configedit import ConfigEditError

SPM_YAML = """\
# Basics
DESIGN_NAME: spm
VERILOG_FILES: dir::src/*.v
CLOCK_PERIOD: 10
CLOCK_PORT: clk
PNR_SDC_FILE: dir::src/impl.sdc
SIGNOFF_SDC_FILE: dir::src/signoff.sdc

# PDN
PDN_VOFFSET: 5
PDN_SKIPTRIM: true

# Pin Order
IO_PIN_ORDER_CFG: dir::pin_order.cfg

# Technology-Specific Configs
pdk::sky130*:
  FP_CORE_UTIL: 45
  CLOCK_PERIOD: 10.0
  scl::sky130_fd_sc_hs:
    CLOCK_PERIOD: 8
pdk::gf180mcu*:
  CLOCK_PERIOD: 24.0
"""


def _design(tmp_path: Path, name: str = "config.yaml", text: str = SPM_YAML) -> Path:
    d = tmp_path / "spm"
    (d / "src").mkdir(parents=True)
    (d / "src" / "spm.v").write_text("module spm(input clk); endmodule\n")
    (d / "src" / "alu.v").write_text("module alu(input a); endmodule\n")
    (d / name).write_bytes(text.encode("utf-8"))
    return d


def _changed_lines(a: str, b: str):
    al, bl = a.splitlines(), b.splitlines()
    return [(x, y) for x, y in zip(al, bl) if x != y], len(al) - len(bl)


def test_set_scalar_changes_exactly_one_line(tmp_path):
    d = _design(tmp_path)
    res = configedit.set_keys(d, {"CLOCK_PERIOD": 12.5})
    new = (d / "config.yaml").read_text()
    diff, dlen = _changed_lines(SPM_YAML, new)
    assert dlen == 0 and diff == [("CLOCK_PERIOD: 10", "CLOCK_PERIOD: 12.5")]
    assert res["changed"] == ["CLOCK_PERIOD"]
    # The per-PDK sections that also set it are reported so the UI can say so.
    scopes = {e["scope"]: e["value"] for e in res["scoped"]["CLOCK_PERIOD"]}
    assert scopes == {"pdk::sky130*": 10.0, "pdk::sky130* / scl::sky130_fd_sc_hs": 8,
                      "pdk::gf180mcu*": 24.0}


def test_scoped_applies_matches_pdk_and_scl():
    data = yaml.safe_load(SPM_YAML)
    entries = configedit.scoped_values(data, "CLOCK_PERIOD")
    hit = [e["scope"] for e in entries if configedit.applies(e, "sky130A", "sky130_fd_sc_hd")]
    assert hit == ["pdk::sky130*"]
    hit = [e["scope"] for e in entries if configedit.applies(e, "sky130A", "sky130_fd_sc_hs")]
    assert hit == ["pdk::sky130*", "pdk::sky130* / scl::sky130_fd_sc_hs"]


def test_new_key_goes_above_scoped_sections_and_keeps_everything(tmp_path):
    d = _design(tmp_path)
    configedit.set_keys(d, {"USE_SLANG": True})
    new = (d / "config.yaml").read_text()
    assert new.index("USE_SLANG: true") < new.index("# Technology-Specific Configs")
    want = yaml.safe_load(SPM_YAML)
    want["USE_SLANG"] = True
    assert yaml.safe_load(new) == want
    for comment in ("# Basics", "# PDN", "# Pin Order", "# Technology-Specific Configs"):
        assert comment in new


def test_remove_key(tmp_path):
    d = _design(tmp_path)
    configedit.set_keys(d, removes=["IO_PIN_ORDER_CFG"])
    want = yaml.safe_load(SPM_YAML)
    del want["IO_PIN_ORDER_CFG"]
    assert yaml.safe_load((d / "config.yaml").read_text()) == want


def test_block_list_replaced_including_column0_dashes(tmp_path):
    text = "DESIGN_NAME: t\nVERILOG_FILES:\n- dir::src/a.v\n- dir::src/b.v\nCLOCK_PORT: clk  # the clock\n"
    d = _design(tmp_path, text=text)
    configedit.set_keys(d, {"VERILOG_FILES": ["dir::src/c.v"]})
    new = (d / "config.yaml").read_text()
    assert yaml.safe_load(new) == {"DESIGN_NAME": "t", "VERILOG_FILES": ["dir::src/c.v"], "CLOCK_PORT": "clk"}
    assert "CLOCK_PORT: clk  # the clock" in new


def test_inline_comment_kept_on_scalar(tmp_path):
    d = _design(tmp_path, text="CLOCK_PERIOD: 10  # ns\nCLOCK_PORT: clk\n")
    configedit.set_keys(d, {"CLOCK_PERIOD": 20})
    assert (d / "config.yaml").read_text() == "CLOCK_PERIOD: 20  # ns\nCLOCK_PORT: clk\n"


def test_crlf_line_endings_preserved(tmp_path):
    d = _design(tmp_path, text=SPM_YAML.replace("\n", "\r\n"))
    configedit.set_keys(d, {"CLOCK_PORT": "clk_i"})
    raw = (d / "config.yaml").read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    assert b"CLOCK_PORT: clk_i\r\n" in raw


@pytest.mark.parametrize("value", ["a: b", "true", "10", "has # hash", "x'y\"z", "dir::src/*.sv", ""])
def test_awkward_strings_round_trip(tmp_path, value):
    d = _design(tmp_path)
    configedit.set_keys(d, {"DESIGN_NAME": value})
    assert yaml.safe_load((d / "config.yaml").read_text())["DESIGN_NAME"] == value


def test_json_edit_keeps_order_indent_and_scoped_keys(tmp_path):
    data = {"DESIGN_NAME": "spm", "CLOCK_PERIOD": 10, "pdk::sky130*": {"CLOCK_PERIOD": 10.0}, "meta": {"version": 2}}
    text = json.dumps(data, indent=2) + "\n"
    d = _design(tmp_path, name="config.json", text=text)
    configedit.set_keys(d, {"CLOCK_PERIOD": 15, "PNR_SDC_FILE": "dir::src/impl.sdc"})
    new = (d / "config.json").read_text()
    got = json.loads(new)
    assert list(got) == ["DESIGN_NAME", "CLOCK_PERIOD", "PNR_SDC_FILE", "pdk::sky130*", "meta"]
    assert got["CLOCK_PERIOD"] == 15 and got["pdk::sky130*"] == {"CLOCK_PERIOD": 10.0}
    assert new.startswith('{\n  "DESIGN_NAME"')


def test_refusals_leave_file_untouched(tmp_path):
    d = _design(tmp_path)
    before = (d / "config.yaml").read_bytes()
    with pytest.raises(ConfigEditError):
        configedit.set_keys(d, {"not a var": 1})
    with pytest.raises(ConfigEditError):
        configedit.set_keys(d, {"MACROS": {"a": 1}})
    assert (d / "config.yaml").read_bytes() == before


def test_duplicate_top_level_key_refused(tmp_path):
    d = _design(tmp_path, text="CLOCK_PERIOD: 10\nCLOCK_PERIOD: 12\n")
    with pytest.raises(ConfigEditError):
        configedit.set_keys(d, {"CLOCK_PERIOD": 5})


def test_edit_that_would_break_other_keys_is_refused(tmp_path):
    # B aliases A's anchor: rewriting A's line drops the anchor, which would
    # break B. The validation must catch it and write nothing.
    text = "A_KEY: &x 1\nB_KEY: *x\n"
    d = _design(tmp_path, text=text)
    with pytest.raises(ConfigEditError):
        configedit.set_keys(d, {"A_KEY": 2})
    assert (d / "config.yaml").read_text() == text


def test_tcl_and_missing_configs_refused(tmp_path):
    d = _design(tmp_path, name="config.tcl", text="set ::env(DESIGN_NAME) spm\n")
    with pytest.raises(ConfigEditError, match="Tcl"):
        configedit.set_keys(d, {"CLOCK_PERIOD": 5})
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ConfigEditError):
        configedit.set_keys(empty, {"CLOCK_PERIOD": 5})


def test_dry_run_and_no_op_write_nothing(tmp_path):
    d = _design(tmp_path)
    p = d / "config.yaml"
    mtime = p.stat().st_mtime_ns
    res = configedit.set_keys(d, {"CLOCK_PERIOD": 99}, dry_run=True)
    assert "CLOCK_PERIOD: 99" in res["text"] and p.read_text() == SPM_YAML
    res = configedit.set_keys(d, {"CLOCK_PERIOD": 10})
    assert res["changed"] == [] and p.stat().st_mtime_ns == mtime


def test_backup_kept_outside_the_project(tmp_path):
    d = _design(tmp_path)
    configedit.set_keys(d, {"CLOCK_PERIOD": 11})
    assert sorted(x.name for x in d.iterdir()) == ["config.yaml", "src"]
    from lanex.controller import platform_env
    backups = list((platform_env.home() / "config-backups").rglob("*config.yaml"))
    assert any(b.read_text() == SPM_YAML for b in backups)


def test_resolve_sources_glob_and_list(tmp_path):
    d = _design(tmp_path)
    info = configedit.read_config(d)
    r = configedit.resolve_sources(d, info["data"])
    assert r["mode"] == "list" and r["globbed"]
    assert sorted(Path(f).name for f in r["files"]) == ["alu.v", "spm.v"]
    r = configedit.resolve_sources(d, {"VERILOG_FILES": ["ref::$DESIGN_DIR/x.v"]})
    assert r["mode"] == "unknown"
    r = configedit.resolve_sources(d, {})
    assert r["mode"] == "none"


def test_set_sources_keeps_glob_when_same_and_writes_list_otherwise(tmp_path):
    d = _design(tmp_path)
    both = [str(d / "src" / "alu.v"), str(d / "src" / "spm.v")]
    res = configedit.set_sources(d, both)
    assert res["changed"] == [] and res["kept_glob"]
    assert "VERILOG_FILES: dir::src/*.v" in (d / "config.yaml").read_text()
    configedit.set_sources(d, [str(d / "src" / "spm.v")])
    got = yaml.safe_load((d / "config.yaml").read_text())
    assert got["VERILOG_FILES"] == ["dir::src/spm.v"]
    want = yaml.safe_load(SPM_YAML)
    want["VERILOG_FILES"] = ["dir::src/spm.v"]
    assert got == want


def test_same_config_file_as_the_run_uses():
    # The editor must change the file a run reads: same names, same order.
    from lanex.server import routes
    assert configedit.CONFIG_NAMES == tuple(f"config.{e}" for e in routes._CONFIG_EXTS)
