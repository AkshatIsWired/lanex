"""The fix loop (workflow spec 5.6, 7): where a run resumes after a setting
changes, what a resumed run keeps from the run it came from, the config edits
the fix sheet makes, and the knowledge base's diagnoses.

Run folders are shaped like LibreLane 3.0.4's (``NN-<step>`` folders with
state_in/state_out, flow.log naming each step, resolved.json, gui-run.json).
The step order and each step's variables come from the installed LibreLane,
so the variable -> step map is checked against its own source."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from lanex.controller import branch, configedit, problems, timing
from lanex.controller.container_run import build_dockerized_argv
from lanex.controller.manualcmd import cli_command_for

pytest.importorskip("librelane")
from lanex.controller import introspect, varstage  # noqa: E402

STEPS = [s["id"] for s in introspect.flow_steps("Classic")]
CONFIG = """\
DESIGN_NAME: spm
VERILOG_FILES: dir::src/*.v
CLOCK_PERIOD: 10
CLOCK_PORT: clk

pdk::sky130*:
  FP_CORE_UTIL: 45
  CLOCK_PERIOD: 10.0
  scl::sky130_fd_sc_hs:
    CLOCK_PERIOD: 8
"""


def _slug(sid: str) -> str:
    return sid.lower().replace(".", "-")


def _design(tmp: Path) -> Path:
    d = tmp / "proj"
    (d / "src").mkdir(parents=True)
    (d / "src" / "spm.v").write_text("module spm; endmodule\n")
    (d / "config.yaml").write_text(CONFIG)
    (d / "runs").mkdir()
    return d


def _run(design: Path, tag: str, upto: int, *, stopped: int | None = None, overrides=None, resolved=None,
         no_state: tuple = (), branched_from=None, flow_log: bool = True, extra_state=None) -> Path:
    """A run of the first *upto* Classic steps; step *stopped* (1-based)
    started and never finished; steps in *no_state* (ids) saved no state."""
    run = design / "runs" / tag
    run.mkdir(parents=True)
    log = []
    keep = design / "src" / "spm.v"
    for i, sid in enumerate(STEPS[:upto]):
        d = run / f"{i + 1:02d}-{_slug(sid)}"
        d.mkdir()
        (d / "state_in.json").write_text("{}")
        if i + 1 != stopped and sid not in no_state:
            (d / "state_out.json").write_text(json.dumps({"nl": str(keep), **(extra_state or {}), "metrics": {}}))
            (d / "runtime.txt").write_text("00:00:01.000")
        log.append(f"Running '{sid}' at 'runs/{tag}/{d.name}'…")
    if flow_log:
        (run / "flow.log").write_text("\n".join(log) + "\n")
    res = {"DESIGN_NAME": "spm", "PDK": "sky130A", "STD_CELL_LIBRARY": "sky130_fd_sc_hd", "CLOCK_PERIOD": 10,
           "FP_CORE_UTIL": 45, "VERILOG_FILES": [str(keep)], "meta": {"flow": None}}
    res.update(resolved or {})
    (run / "resolved.json").write_text(json.dumps(res))
    gui = {"flow": "Classic", "pdk": "sky130A", "scl": "sky130_fd_sc_hd", "overrides": overrides or {}}
    if branched_from:
        gui["branched_from"] = branched_from
    (run / "gui-run.json").write_text(json.dumps(gui))
    return run


def _old(path: Path, seconds: float = 60) -> None:
    """Make every file under *path* look *seconds* old."""
    t = time.time() - seconds
    for p in [path, *path.rglob("*")]:
        os.utime(p, (t, t))


# ------------------------------------------------------------------ variable -> first step

@pytest.mark.parametrize("var, step, stage_start", [
    ("FP_CORE_UTIL", "OpenROAD.Floorplan", True),             # its own config_vars
    ("DIE_AREA", "OpenROAD.Floorplan", True),                 # flow-common, scripts/openroad/floorplan.tcl
    ("CLOCK_PERIOD", "Yosys.Synthesis", False),               # ABC's delay target
    ("PL_TARGET_DENSITY_PCT", "OpenROAD.GlobalPlacementSkipIO", False),
    ("GPL_CELL_PADDING", "OpenROAD.GlobalPlacementSkipIO", False),
    ("RUN_POST_GRT_RESIZER_TIMING", "OpenROAD.ResizerTimingPostGRT", False),  # a switch: the step it gates
    ("IO_DELAY_CONSTRAINT", "OpenROAD.CheckSDCFiles", False),  # the first step handed the SDC
])
def test_each_change_resumes_at_its_first_reader(var, step, stage_start):
    r = varstage.resume_point([var])
    assert r["step"] == step and r["stage_start"] is stage_start


def test_the_earliest_reader_of_several_wins():
    r = varstage.resume_point(["PL_TARGET_DENSITY_PCT", "FP_CORE_UTIL"])
    assert r["step"] == "OpenROAD.Floorplan" and r["by"] == "FP_CORE_UTIL"


def test_flow_switches_are_known_variables():
    # The flow's own RUN_* switches belong to no step; a fix that names one
    # must not be dropped as unknown.
    assert "RUN_POST_GRT_RESIZER_TIMING" in introspect.known_var_names()


# ------------------------------------------------------------------ planning a resume

def test_a_fix_resumes_from_its_reader_on_the_old_runs_state(tmp_path):
    d = _design(tmp_path)
    _run(d, "try1", 28, stopped=28)
    p = branch.plan(d, "try1", {"FP_CORE_UTIL": "35"})
    r = p["resume"]
    assert r["step"] == "OpenROAD.Floorplan" and r["stage"] == "floorplan"
    # The state of the step just before it, from the old run's folder.
    assert r["state"] == "runs/try1/12-openroad-staprepnr/state_out.json"
    c = p["changes"][0]
    # Set in the pdk::sky130* section, so that is where it has to change.
    assert c["save"] == "config" and c["scope"] == ["pdk::sky130*"]
    assert [(x["op"], x["text"]) for x in p["config"]["diff"]] == [("-", "  FP_CORE_UTIL: 45"), ("+", "  FP_CORE_UTIL: 35")]
    assert p["ok"] and not p["drift"]["settings"] and not p["drift"]["files"]


def test_a_value_set_for_the_old_run_only_stays_that_way(tmp_path):
    d = _design(tmp_path)
    _run(d, "die", 28, stopped=28, overrides={"FP_SIZING": "absolute", "DIE_AREA": "0 0 60 60"},
         resolved={"FP_SIZING": "absolute", "DIE_AREA": [0, 0, 60, 60]})
    p = branch.plan(d, "die", {"FP_SIZING": "relative"})
    c = p["changes"][0]
    assert c["origin"]["layer"] == "run" and c["save"] == "run"
    # The new run keeps the old run's other settings and changes only this one.
    assert p["overrides"] == {"DIE_AREA": "0 0 60 60", "FP_SIZING": "relative"}
    assert p["config"]["diff"] == []


def test_saving_to_the_config_drops_the_old_runs_own_value(tmp_path):
    d = _design(tmp_path)
    _run(d, "die", 28, stopped=28, overrides={"FP_SIZING": "absolute", "DIE_AREA": "0 0 60 60"},
         resolved={"FP_SIZING": "absolute", "DIE_AREA": [0, 0, 60, 60]})
    p = branch.plan(d, "die", {"DIE_AREA": "0 0 125 125"}, save="config")
    assert p["overrides"] == {"FP_SIZING": "absolute"}
    assert [x["text"] for x in p["config"]["diff"] if x["op"] == "+" and x["text"]] == ["DIE_AREA: [0, 0, 125, 125]"]


def test_a_run_cant_resume_past_where_the_old_one_stopped(tmp_path):
    d = _design(tmp_path)
    _run(d, "stop", 28, stopped=28)       # GlobalPlacement raised
    p = branch.plan(d, "stop", {"RUN_POST_GRT_RESIZER_TIMING": "true"})
    assert p["resume"]["step"] == "OpenROAD.GlobalPlacement" and "stopped" in p["resume"]["reasons"]


def test_a_checker_that_failed_the_run_at_the_end_is_not_where_it_stopped(tmp_path):
    d = _design(tmp_path)
    _run(d, "late", len(STEPS), no_state=("Checker.SetupViolations",))
    p = branch.plan(d, "late", {"RUN_POST_GRT_RESIZER_TIMING": "true"})
    assert p["parent"]["stopped"] is None
    assert p["resume"]["step"] == "OpenROAD.ResizerTimingPostGRT"


def test_a_setting_changed_since_moves_the_start_earlier(tmp_path):
    d = _design(tmp_path)
    _run(d, "old", 40, resolved={"FP_CORE_UTIL": 40})     # the config says 45 now
    p = branch.plan(d, "old", {"PL_TARGET_DENSITY_PCT": "60"})
    assert [(x["var"], x["was"], x["now"]) for x in p["drift"]["settings"]] == [("FP_CORE_UTIL", "40", "45")]
    assert p["resume"]["step"] == "OpenROAD.Floorplan"


def test_an_rtl_change_since_means_the_whole_flow(tmp_path):
    d = _design(tmp_path)
    run = _run(d, "old", 40)
    _old(run)
    (d / "src" / "spm.v").write_text("module spm(input a); endmodule\n")
    p = branch.plan(d, "old", {"PL_TARGET_DENSITY_PCT": "60"})
    assert p["drift"]["files"] == [{"path": "src/spm.v", "vars": ["VERILOG_FILES"]}]
    assert p["resume"] is None          # it starts from the beginning


def test_a_resume_from_a_stage_with_nothing_changed(tmp_path):
    d = _design(tmp_path)
    _run(d, "ok", len(STEPS))
    p = branch.plan(d, "ok", {}, start="OpenROAD.GlobalPlacement")
    assert p["resume"]["step"] == "OpenROAD.GlobalPlacement" and not p["changes"]
    assert all(s["ok"] for s in p["stages"] if s["index"] > 0)


def test_a_state_whose_files_are_gone_is_refused(tmp_path):
    d = _design(tmp_path)
    _run(d, "gone", 28, stopped=28, extra_state={"def": str(tmp_path / "nowhere.def")})
    p = branch.plan(d, "gone", {"FP_CORE_UTIL": "35"})
    assert not p["ok"] and "gone" in p["blocked"]


def test_steps_are_found_without_flow_log(tmp_path):
    d = _design(tmp_path)
    _run(d, "nolog", 28, stopped=28, flow_log=False)
    p = branch.plan(d, "nolog", {"FP_CORE_UTIL": "35"})
    assert p["resume"]["state"] == "runs/nolog/12-openroad-staprepnr/state_out.json"


def test_wrong_values_and_names_are_refused(tmp_path):
    d = _design(tmp_path)
    _run(d, "r", 28, stopped=28)
    with pytest.raises(branch.BranchError):
        branch.plan(d, "r", {"FP_CORE_UTIL": "lots"})
    with pytest.raises(branch.BranchError):
        branch.plan(d, "r", {"NOT_A_SETTING": "1"})
    with pytest.raises(branch.BranchError):
        branch.plan(d, "r", {}, new_tag="r")       # that run exists


def test_values_take_the_variables_own_type():
    assert branch.coerce("35", {"kind": "number"}) == 35
    assert branch.coerce("2.4", {"kind": "number"}) == 2.4
    assert branch.coerce("true", {"kind": "bool"}) is True
    assert branch.coerce("0 0 125 125", {"kind": "numbers"}) == [0, 0, 125, 125]
    assert branch.coerce("DELAY 0", {"kind": "choice", "choices": ["AREA 0", "DELAY 0"]}) == "DELAY 0"
    with pytest.raises(branch.BranchError):
        branch.coerce("DELAY 9", {"kind": "choice", "choices": ["AREA 0", "DELAY 0"]})


def test_a_resumed_run_stands_on_the_old_runs_steps(tmp_path):
    from lanex.controller import history
    d = _design(tmp_path)
    _run(d, "parent", 28, stopped=28)
    child = d / "runs" / "child"
    child.mkdir()
    for i, sid in enumerate(STEPS[12:20]):
        sd = child / f"{i + 1:02d}-{_slug(sid)}"
        sd.mkdir()
        (sd / "state_out.json").write_text("{}")
    (child / "flow.log").write_text("".join(f"Running '{sid}' at 'runs/child/{i + 1:02d}-{_slug(sid)}'…\n"
                                            for i, sid in enumerate(STEPS[12:20])))
    (child / "gui-run.json").write_text(json.dumps({"branched_from": {"tag": "parent", "step": "OpenROAD.Floorplan"}}))
    steps = history.lineage_steps(child)
    assert [s["id"] for s in steps] == STEPS[:20]
    assert {s["run"] for s in steps[:12]} == {"parent"} and {s["run"] for s in steps[12:]} == {"child"}
    assert branch.children(d, "parent") == ["child"]


def test_branch_record_names_the_parent_and_the_change(tmp_path):
    d = _design(tmp_path)
    _run(d, "try1", 28, stopped=28)
    p = branch.plan(d, "try1", {"FP_CORE_UTIL": "35"})
    m = branch.branch_meta(p)
    assert m["tag"] == "try1" and m["step"] == "OpenROAD.Floorplan"
    assert m["changes"] == [{"var": "FP_CORE_UTIL", "from": "45", "to": "35", "saved": "config"}]


# ------------------------------------------------------------------ config edits

def test_a_section_edit_leaves_a_nested_section_alone(tmp_path):
    d = _design(tmp_path)
    res = configedit.set_keys(d, {"CLOCK_PERIOD": 12}, scope=["pdk::sky130*"])
    text = (d / "config.yaml").read_text()
    assert "  CLOCK_PERIOD: 12" in text and "    CLOCK_PERIOD: 8" in text and "CLOCK_PERIOD: 10\n" in text
    assert [x["op"] for x in res["diff"]] == ["-", "+"]


def test_undo_puts_the_file_back_and_refuses_after_another_edit(tmp_path, monkeypatch):
    from lanex.controller import platform_env
    monkeypatch.setattr(platform_env, "home", lambda: tmp_path / "home")
    d = _design(tmp_path)
    res = configedit.set_keys(d, {"PL_TARGET_DENSITY_PCT": 60})
    u = res["undo"]
    configedit.undo(d, u["backup"], u["after"])
    assert (d / "config.yaml").read_text() == CONFIG
    res = configedit.set_keys(d, {"PL_TARGET_DENSITY_PCT": 60})
    (d / "config.yaml").write_text((d / "config.yaml").read_text() + "# edited by hand\n")
    with pytest.raises(configedit.ConfigEditError):
        configedit.undo(d, res["undo"]["backup"], res["undo"]["after"])


def test_undo_gives_back_the_same_bytes_crlf_too(tmp_path, monkeypatch):
    from lanex.controller import platform_env
    monkeypatch.setattr(platform_env, "home", lambda: tmp_path / "home")
    d = _design(tmp_path)
    raw = CONFIG.replace("\n", "\r\n").encode()
    (d / "config.yaml").write_bytes(raw)
    res = configedit.set_keys(d, {"FP_CORE_UTIL": 35}, scope=["pdk::sky130*"])
    assert b"  FP_CORE_UTIL: 35\r\n" in (d / "config.yaml").read_bytes()
    configedit.undo(d, res["undo"]["backup"], res["undo"]["after"])
    assert (d / "config.yaml").read_bytes() == raw


# ------------------------------------------------------------------ the commands

def test_both_commands_start_from_the_old_runs_state(tmp_path):
    d = _design(tmp_path)
    state = d / "runs" / "try1" / "12-openroad-staprepnr" / "state_out.json"
    argv = build_dockerized_argv(config_file=d / "config.yaml", design_dir=d, tag="try2",
                                 frm="OpenROAD.Floorplan", initial_state=str(state))
    i = argv.index("-i")
    assert argv[i + 1] == "runs/try1/12-openroad-staprepnr/state_out.json"
    assert argv.index("-F") > i
    cmd = cli_command_for(design_dir=str(d), config_file=str(d / "config.yaml"), tag="try2", frm="OpenROAD.Floorplan",
                          initial_state="runs/try1/12-openroad-staprepnr/state_out.json")
    assert "-i runs/try1/12-openroad-staprepnr/state_out.json -F OpenROAD.Floorplan" in cmd["container"]


# ------------------------------------------------------------------ the knowledge base

def test_padding_is_named_first_when_it_overfilled_placement():
    card = problems.explain_error("[ERROR GPL-0301] Utilization 103.276 % exceeds 100%.",
                                  {"GPL_CELL_PADDING": 12, "FP_SIZING": "relative", "FP_CORE_UTIL": 45})
    assert card["title"] == "Placement ran out of room"
    assert [(f["var"], f["to"]) for f in card["fixes"]][0] == ("GPL_CELL_PADDING", "0")
    assert "12 sites wider" in card["plain"]


def test_a_fixed_die_offers_a_bigger_die_or_letting_librelane_size_it():
    card = problems.explain_error("[ERROR GPL-0301] Utilization 207.290 % exceeds 100%.",
                                  {"FP_SIZING": "absolute", "DIE_AREA": [0, 0, 60, 60], "FP_CORE_UTIL": 45})
    assert [f["var"] for f in card["fixes"]] == ["FP_SIZING", "DIE_AREA"]


def test_a_missing_local_tool_is_said_plainly():
    card = problems.explain_error("bash: openroad: command not found", {})
    assert card["title"] == "Openroad isn't installed here"
    assert problems.explain_error("just some line", {})["title"] is None


def test_drc_places_are_clusters_of_nearby_markers():
    items = [{"cat": "m1.2", "bbox": [x, 10, x + 0.2, 10.2]} for x in (10, 11, 12)] + \
            [{"cat": "li.3", "bbox": [80, 80, 80.3, 80.3]}]
    places = problems.cluster(items, 5)
    assert [p["count"] for p in places] == [3, 1]
    assert places[0]["rules"] == [{"name": "m1.2", "count": 3}]


def test_drc_rules_read_in_plain_words():
    assert problems.rule_in_words("m1.2", "m1.2 : min. met1 spacing : 0.14um") == "Metal 1 shapes closer than 0.14 µm"
    assert problems.rule_in_words("Metal1 width < 0.14um (met1.1)") == "Metal 1 narrower than 0.14 µm"


def _timing(monkeypatch, pre, post, cfg, checks):
    """problems.timing_problems on two timing analyses (before placement and
    after routing), each ``(corner, ws, endpoints, kinds)``."""
    def row(c, ws, n, kinds, key):
        return {c: {key + "_ws": ws, key + "_tns": ws * n, key + "_vio": n, "kinds": {key: kinds}}}
    hist = [{"id": "OpenROAD.STAPrePNR", "dir": "12-x", "run": "r", "path": "/x", "when": "before placement",
             "signoff": False, "ideal_clocks": True, "corners": row(*pre)},
            {"id": "OpenROAD.STAPostPNR", "dir": "58-x", "run": "r", "path": "/y", "when": "after routing",
             "signoff": True, "ideal_clocks": False, "corners": row(*post)}]
    monkeypatch.setattr(timing, "sta_history", lambda run_dir: hist)
    monkeypatch.setattr(timing, "worst_setup_path", lambda *a, **k: None)
    monkeypatch.setattr(problems, "_cfg", lambda run_dir: cfg)
    return {p["id"]: p for p in problems.timing_problems(Path("/nowhere"), {"checks": checks})}


CFG = {"CLOCK_PERIOD": 5, "SYNTH_STRATEGY": "AREA 0", "PL_TIMING_DRIVEN": False, "RUN_POST_GRT_RESIZER_TIMING": False,
       "IO_DELAY_CONSTRAINT": 20, "PL_RESIZER_HOLD_SLACK_MARGIN": 0.1, "PL_RESIZER_SETUP_SLACK_MARGIN": 0.05}


def test_register_paths_failing_before_placement_get_no_placement_fix(monkeypatch):
    out = _timing(monkeypatch, ("nom_ss_100C_1v60", -0.5, 10, {"reg-reg": 10}, "setup"),
                  ("max_ss_100C_1v60", -0.3, 12, {"reg-reg": 12}, "setup"), CFG, [{"id": "setup", "status": "fail"}])
    p = out["timing-setup"]
    assert p["title"] == "Setup fails before placement: too much logic for this clock"
    assert p["diag"]["logic_depth"] and not p["diag"]["physical"]
    vars_ = {f["var"] for f in p["fixes"] if f["kind"] == "setting"}
    assert vars_ == {"CLOCK_PERIOD", "SYNTH_STRATEGY"}
    assert not any(v.startswith(("PL_", "FP_", "GPL_", "DPL_", "GRT_")) for v in vars_)
    assert any("No placement or density setting" in n for n in p["notes"])


def test_io_paths_first_and_register_paths_after_routing(monkeypatch):
    out = _timing(monkeypatch, ("nom_ss_100C_1v60", -1.47, 129, {"in-reg": 128, "reg-out": 1}, "setup"),
                  ("max_ss_100C_1v60", -0.64, 75, {"reg-reg": 48, "in-reg": 26, "reg-out": 1}, "setup"),
                  CFG, [{"id": "setup", "status": "fail"}])
    p = out["timing-setup"]
    assert p["title"] == "Setup: the I/O paths fail from the start, register paths after routing"
    assert p["diag"]["io_first"] and p["diag"]["physical"]
    vars_ = [f["var"] for f in p["fixes"] if f["kind"] == "setting"]
    assert vars_[:2] == ["CLOCK_PERIOD", "IO_DELAY_CONSTRAINT"]
    # Placement help only for what fails after routing; never a density setting.
    assert "PL_TIMING_DRIVEN" in vars_ and not any(v in ("FP_CORE_UTIL", "PL_TARGET_DENSITY_PCT") for v in vars_)
    assert "for none before placement" in p["plain"]


def test_hold_never_offers_a_slower_clock(monkeypatch):
    out = _timing(monkeypatch, ("nom_ss_100C_1v60", 0.2, 0, {}, "hold"), ("min_ff_n40C_1v95", -0.1, 5, {"reg-reg": 5}, "hold"),
                  CFG, [{"id": "hold", "status": "fail"}])
    p = out["timing-hold"]
    assert "CLOCK_PERIOD" not in {f.get("var") for f in p["fixes"]}
    assert p["fixes"][0]["var"] == "PL_RESIZER_HOLD_SLACK_MARGIN"


# A worst setup path exactly as LibreLane 3.0.4's STAPostPNR wrote it
# (report_checks, -fields {slew cap input net fanout}), spm at 1.5 ns in ss.
PATH = """\
Startpoint: _314_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: y (output port clocked by clk)
Path Group: clk
Path Type: max

Fanout         Cap        Slew       Delay        Time   Description
---------------------------------------------------------------------------------------------
                                  0.000000    0.000000   clock clk (rise edge)
                                  0.000000    0.000000   clock source latency
     1    0.013478    0.105036    0.069982    0.069982 ^ clk (in)
                                                         clk (net)
                      0.105045    0.000000    0.069982 ^ clkbuf_0_clk/A (sky130_fd_sc_hd__clkbuf_16)
     8    0.081900    0.151367    0.308968    0.378950 ^ clkbuf_0_clk/X (sky130_fd_sc_hd__clkbuf_16)
                                                         clknet_0_clk (net)
                      0.151788    0.005514    0.384464 ^ clkbuf_3_1__f_clk/A (sky130_fd_sc_hd__clkbuf_16)
     8    0.025715    0.074684    0.266754    0.651219 ^ clkbuf_3_1__f_clk/X (sky130_fd_sc_hd__clkbuf_16)
                                                         clknet_3_1__leaf_clk (net)
                      0.074718    0.001397    0.652616 ^ _314_/CLK (sky130_fd_sc_hd__dfrtp_2)
     1    0.006873    0.094034    0.828277    1.480893 v _314_/Q (sky130_fd_sc_hd__dfrtp_2)
                                                         net35 (net)
                      0.094034    0.000552    1.481445 v output35/A (sky130_fd_sc_hd__buf_6)
     1    0.034791    0.076625    0.258355    1.739800 v output35/X (sky130_fd_sc_hd__buf_6)
                                                         y (net)
                      0.076680    0.001807    1.741607 v y (out)
                                              1.741607   data arrival time

                                  1.500000    1.500000   clock clk (rise edge)
                                  0.000000    1.500000   clock network delay (propagated)
                                 -0.100000    1.400000   clock uncertainty
                                  0.000000    1.400000   clock reconvergence pessimism
                                 -0.300000    1.100000   output external delay
                                              1.100000   data required time
---------------------------------------------------------------------------------------------
                                              1.100000   data required time
                                             -1.741607   data arrival time
---------------------------------------------------------------------------------------------
                                             -0.641607   slack (VIOLATED)
"""


def test_the_worst_path_splits_into_where_its_time_goes():
    b = timing.path_budget(PATH)
    assert b["start"] == "reg" and b["end"] == "out" and b["period"] == 1.5
    assert b["launch"] == pytest.approx(0.652615) and b["clk_q"] == pytest.approx(0.828277)
    assert b["cells"] == pytest.approx(0.258355) and b["levels"] == 1
    assert b["wires"] == pytest.approx(0.000552 + 0.001807)
    assert b["io_out"] == pytest.approx(0.3) and b["uncertainty"] == pytest.approx(0.1)
    # Everything adds up to LibreLane's own arrival and slack.
    assert b["launch"] + b["clk_q"] + b["cells"] + b["wires"] == pytest.approx(b["arrival"])
    assert b["required"] - b["arrival"] == pytest.approx(b["slack"])


# KLayout.XOR's report as LibreLane 3.0.4 wrote it for a 350 um die whose
# config still said DIE_AREA 0 0 150 150 (a beginner run, FP_SIZING relative).
XOR_XML = """<?xml version="1.0" encoding="utf-8"?>
<report-database>
 <categories>
  <category><name>235/4</name><description>XOR data for layer 235/4</description><categories></categories></category>
 </categories>
 <items>
  <item><tags/><category>'235/4'</category><cell>bigmul</cell><visited>false</visited><multiplicity>1</multiplicity>
   <values><value>polygon: (150,0;150,150;0,150;0,360.875;350.155,360.875;350.155,0)</value></values></item>
 </items>
</report-database>
"""


def _xor_run(tmp_path, monkeypatch, cfg, xml=XOR_XML):
    d = tmp_path / "run"
    (d / "50-klayout-xor").mkdir(parents=True)
    (d / "50-klayout-xor" / "xor.xml").write_text(xml)
    monkeypatch.setattr(problems, "_cfg", lambda run_dir: cfg)
    monkeypatch.setattr(problems, "_die", lambda run_dir: [0.0, 0.0, 350.155, 360.875])
    return problems.check_problems(d, {"checks": [{"id": "xor", "name": "Mask XOR", "status": "fail", "value": 1,
                                                   "limit": "0"}]}, set())[0]


def test_xor_on_the_outline_names_a_stale_die_area(tmp_path, monkeypatch):
    p = _xor_run(tmp_path, monkeypatch, {"PDK": "sky130A", "FP_SIZING": "relative", "DIE_AREA": [0, 0, 150, 150]})
    assert p["title"] == "Mask XOR: only the cell outline differs"
    assert "Magic" in p["plain"] and "KLayout" in p["plain"] and "DIE_AREA" in p["plain"]
    assert p["diag"]["layers"] == ["235/4"] and p["diag"]["stale_die_area"]
    fix = p["fixes"][0]
    assert fix["var"] == "DIE_AREA" and fix["to"] == "0 0 350.155 360.875"
    show = next(f for f in p["fixes"] if f["kind"] == "open" and f["go"]["tab"] == "layout")
    assert show["go"]["box"] == "0.00,0.00,350.15,360.88"


def test_xor_on_a_mask_layer_offers_no_setting(tmp_path, monkeypatch):
    p = _xor_run(tmp_path, monkeypatch, {"PDK": "sky130A", "FP_SIZING": "absolute", "DIE_AREA": [0, 0, 350.155, 360.875]},
                 XOR_XML.replace("235/4", "68/20"))
    assert p["title"].startswith("Mask XOR: Magic") and not p["diag"]["stale_die_area"]
    assert all(f["kind"] == "open" for f in p["fixes"])
    assert "real ambiguity" in p["plain"]


@pytest.mark.parametrize("cid", ["antenna", "lvs", "setup", "hold", "overlap", "pdn", "slew", "cap", "fanout",
                                 "disc_pin", "lint_errors", "unmapped", "latch", "eqy", "assign", "wire_length"])
def test_every_check_that_can_fail_lands_on_an_action(tmp_path, monkeypatch, cid):
    monkeypatch.setattr(problems, "_cfg", lambda run_dir: {})
    p = problems.check_problems(tmp_path, {"checks": [{"id": cid, "name": cid, "status": "fail", "value": 3}]}, set())[0]
    assert p["fixes"], cid
    assert p["plain"], cid
