"""How a run ended, in plain words (Flow's failure card and report card).

Synthetic run folders shaped like LibreLane 3.0.4's: step dirs with
state_in/state_out, error.log and warning.log at the root, resolved.json.
The error and warning texts are the ones the OpenROAD in LibreLane 3.0.4's
image prints (dcf36133): GPL-0301 is the error, GPL-0302 only a warning."""

import json
from pathlib import Path

from lanex.controller import runexplain

STEPS = ["01-verilator-lint", "02-yosys-synthesis", "03-openroad-floorplan", "04-openroad-generatepdn",
         "05-openroad-globalplacementskipio", "06-openroad-globalplacement"]


def _run(tmp: Path, name: str, *, upto: int, stopped: bool = False, final: bool = False,
         cfg=None, errors=(), warnings=(), outcome=None, step_log=None) -> Path:
    run = tmp / "runs" / name
    run.mkdir(parents=True)
    for i, d in enumerate(STEPS[:upto]):
        sd = run / d
        sd.mkdir()
        (sd / "state_in.json").write_text("{}")
        last = i == upto - 1
        if not (stopped and last):
            (sd / "state_out.json").write_text(json.dumps({"metrics": {}}))
        (sd / "runtime.txt").write_text("00:00:01.000")
        if last and step_log is not None:
            (sd / (d.split("-", 1)[1] + ".log")).write_text(step_log)
    if final:
        (run / "final").mkdir()
    (run / "resolved.json").write_text(json.dumps(cfg or {"FP_SIZING": "relative", "FP_CORE_UTIL": 45}))
    (run / "error.log").write_text("\n".join(errors) + ("\n" if errors else ""))
    (run / "warning.log").write_text("\n".join(warnings) + ("\n" if warnings else ""))
    if outcome:
        (run / "gui-run.json").write_text(json.dumps({"outcome": {"result": outcome}}))
    return run


def test_cells_that_dont_fit_a_fixed_die_say_so_with_the_numbers(tmp_path):
    run = _run(tmp_path, "fail", upto=6, stopped=True,
               cfg={"FP_SIZING": "absolute", "DIE_AREA": [0, 0, 60, 60], "FP_CORE_UTIL": 45},
               errors=["[GPL-0301] Utilization 207.290 % exceeds 100%."],
               step_log="[INFO GPL-0019] Utilization: 207.290 %\n[ERROR GPL-0301] Utilization 207.290 % exceeds 100%.\nError: gpl.tcl, 82 GPL-0301\n")
    rx = runexplain.explain_run(run)
    assert rx["kind"] == "halted"
    assert rx["step"]["dir"] == "06-openroad-globalplacement"
    assert rx["stage"] == "placement"
    card = rx["card"]
    assert card["code"] == "GPL-0301"
    assert card["title"] == "Placement ran out of room"
    assert "207 %" in card["plain"] and "DIE_AREA" in card["plain"]
    fixes = {f["var"]: f for f in card["fixes"]}
    assert fixes["FP_SIZING"]["from"] == "absolute" and fixes["FP_SIZING"]["to"] == "relative"
    # Room for the cells at about half the core: 60 um * sqrt(2.07 / 0.5) -> 125.
    assert fixes["DIE_AREA"]["from"] == "0 0 60 60" and fixes["DIE_AREA"]["to"] == "0 0 125 125"
    # The failure card opens the step's log at the first error line.
    assert rx["at"] == {"path": "06-openroad-globalplacement/openroad-globalplacement.log",
                        "line": 2, "text": "[ERROR GPL-0301] Utilization 207.290 % exceeds 100%."}


def test_a_too_full_relative_core_asks_for_a_lower_utilisation(tmp_path):
    run = _run(tmp_path, "fail", upto=6, stopped=True, cfg={"FP_SIZING": "relative", "FP_CORE_UTIL": 99},
               errors=["[GPL-0301] Utilization 104.100 % exceeds 100%."])
    card = runexplain.explain_run(run)["card"]
    assert [f["var"] for f in card["fixes"]] == ["FP_CORE_UTIL"]
    assert card["fixes"][0]["from"] == "99"
    assert 20 <= int(card["fixes"][0]["to"]) <= 50


def test_gpl_0302_is_a_warning_with_what_openroad_did(tmp_path):
    base = _run(tmp_path, "base", upto=6, final=True, warnings=["[STA-1140] library defined twice"])
    run = _run(tmp_path, "clean", upto=6, final=True,
               warnings=["[GPL-0302] Target density 0.1200 is too low for the available free area.",
                         "[STA-1140] library defined twice", "[STA-1140] library defined twice", "no code here"],
               step_log="[WARNING GPL-0302] Target density 0.1200 is too low for the available free area.\n"
                        "Automatically adjusting to uniform density 0.5300.\n")
    rx = runexplain.explain_run(run, base)
    assert rx["kind"] == "clean" and rx["card"] is None
    w = rx["warnings"]
    assert w["total"] == 4 and w["other"] == 1 and w["compared_with"] == "base"
    by = {g["code"]: g for g in w["by_code"]}
    assert by["STA-1140"]["count"] == 2 and by["STA-1140"]["new"] is False
    assert by["GPL-0302"]["new"] is True
    assert by["GPL-0302"]["note"].startswith("PL_TARGET_DENSITY_PCT asked for 12 %, below what this design can reach, so OpenROAD used 53 %")
    assert w["by_code"][0]["code"] == "GPL-0302", "the warning worth reading comes first"


def test_stopped_by_the_user_is_not_a_failure(tmp_path):
    run = _run(tmp_path, "stop", upto=4, stopped=True, outcome="cancelled")
    rx = runexplain.explain_run(run)
    assert rx["kind"] == "stopped"
    assert rx["card"] is None


def test_a_folder_that_just_ends_is_incomplete(tmp_path):
    run = _run(tmp_path, "cut", upto=3)
    rx = runexplain.explain_run(run)
    assert rx["kind"] == "incomplete"
    assert rx["step"]["dir"] == "03-openroad-floorplan"


def test_failed_checks_after_the_last_step(tmp_path):
    run = tmp_path / "runs" / "late"
    run.mkdir(parents=True)
    for d in ["01-yosys-synthesis", "02-checker-setupviolations"]:
        (run / d).mkdir()
        (run / d / "state_in.json").write_text("{}")
    (run / "01-yosys-synthesis" / "state_out.json").write_text("{}")
    (run / "final").mkdir()
    (run / "error.log").write_text("[Checker.SetupViolations] 3 setup violations were found.\n")
    rx = runexplain.explain_run(run)
    assert rx["kind"] == "checks-failed"
    assert [c["dir"] for c in rx["raised_checkers"]] == ["02-checker-setupviolations"]
