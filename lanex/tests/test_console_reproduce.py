"""Console drawer, Command tab: the reproduce record and script of a run
(manualcmd.reproduce_info / reproduce_script, /api/run-reproduce)."""
from __future__ import annotations

import json
from pathlib import Path

from lanex.controller import manualcmd

META = {
    "pdk": "sky130A", "scl": "sky130_fd_sc_hd", "run_mode": "container",
    "config_file": "/home/u/spm/config.yaml",
    "config_hash": "0540eeca6ee88a104e3ae2ed3c3416d1afdf693b518c609d6f1afd6c62464059",
    "branched_from": {"tag": "dse-spm-02", "step": "OpenROAD.Floorplan"},
    "cli_command": {
        "container": "librelane --pdk-root /home/u/.ciel --docker-no-tty --dockerized config.yaml -f Classic -p sky130A -s sky130_fd_sc_hd --run-tag r1",
        "local": "librelane --pdk-root /home/u/.ciel /home/u/spm/config.yaml -f Classic --run-tag r1",
        "recommended": "container", "cwd": "/home/u/spm",
    },
    "tag": "r1",
    "toolchain": {"librelane_version": "3.0.4", "lanex_version": "0.1.0+3.0.4",
                  "image": "ghcr.io/librelane/librelane:3.0.4@sha256:eab07a50"},
}
RESOLVED = {"PDK_ROOT": "/home/u/.ciel/ciel/sky130/versions/8afc8346a57fe1ab7934ba5a6056ea8b43078e71",
            "PDK": "sky130A", "meta": {"librelane_version": "3.0.4"}}


def test_reproduce_info_reads_only_what_the_run_recorded(tmp_path: Path):
    info = manualcmd.reproduce_info(META, RESOLVED, str(tmp_path / "r1"))
    # The rerun gets its own tag: LibreLane appends to an existing run folder.
    assert info["recorded_command"] == META["cli_command"]["container"]
    assert info["command"] == META["cli_command"]["container"].replace("--run-tag r1", "--run-tag r1-repro")
    assert info["repro_tag"] == "r1-repro"
    assert info["commands"]["local"].endswith("--run-tag r1-repro")
    assert info["cwd"] == "/home/u/spm"
    assert info["pdk_version"] == "8afc8346a57fe1ab7934ba5a6056ea8b43078e71"
    assert info["image"].endswith("@sha256:eab07a50")
    assert info["librelane_version"] == "3.0.4"
    assert info["resolved_config"].endswith("resolved.json")
    assert info["recorded"] is True


def test_reproduce_info_without_a_record_invents_nothing(tmp_path: Path):
    info = manualcmd.reproduce_info({}, None, str(tmp_path / "term-run"))
    assert info["recorded"] is False and info["command"] is None
    assert info["image"] is None and info["pdk_version"] is None and info["resolved_config"] is None
    assert "no recorded command" in manualcmd.reproduce_script(info)


def test_reproduce_script_pins_image_and_checks_config(tmp_path: Path):
    s = manualcmd.reproduce_script(manualcmd.reproduce_info(META, RESOLVED, str(tmp_path / "r1")))
    lines = [l for l in s.splitlines() if l and not l.startswith("#")]
    assert lines[0] == "set -euo pipefail"
    assert lines[1] == "cd /home/u/spm"
    assert "sha256sum -c -" in lines[2]
    assert lines[3] == "export LIBRELANE_IMAGE_OVERRIDE=ghcr.io/librelane/librelane:3.0.4@sha256:eab07a50"
    assert lines[4] == META["cli_command"]["container"].replace("--run-tag r1", "--run-tag r1-repro")
    assert "ciel enable --pdk-family sky130 8afc8346a57fe1ab7934ba5a6056ea8b43078e71" in s


def test_local_run_gets_no_image_override(tmp_path: Path):
    meta = json.loads(json.dumps(META))
    meta["cli_command"]["recommended"] = "local"
    info = manualcmd.reproduce_info(meta, RESOLVED, str(tmp_path / "r1"))
    assert info["image"] is None
    assert "LIBRELANE_IMAGE_OVERRIDE" not in manualcmd.reproduce_script(info)


def test_retag_changes_only_the_run_tag():
    assert manualcmd.retag("librelane c.json --run-tag a-1 -i runs/a-1/s.json") == "librelane c.json --run-tag a-1-repro -i runs/a-1/s.json"
    assert manualcmd.retag("librelane c.json") == "librelane c.json"
    assert manualcmd.retag(None) is None
