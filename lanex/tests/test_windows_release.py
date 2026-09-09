from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ci/windows_candidate.py"
WORKFLOW = REPO / ".github/workflows/windows-installer.yml"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_gate(*args: object, ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True
    )
    assert (result.returncode == 0) is ok, result.stderr
    return result


def candidate_fixture(tmp_path: Path):
    files = {}
    for name in ("wheel", "setup", "launcher", "rootfs", "inventory", "pins"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        files[name] = path
    manifest = tmp_path / "build-manifest.json"
    manifest.write_text(json.dumps({
        "source": {"sha": "a" * 40},
        "app": {"version": "1.0.0-test.1"},
        "payload": {"wheel": {"sha256": digest(files["wheel"])},
                    "pdkPinsSha256": digest(files["pins"])},
        "bakedRootfs": {"sha256": digest(files["rootfs"]),
                         "packageInventorySha256": digest(files["inventory"])},
    }))
    return files, manifest


def test_candidate_bundle_hashes_every_manifest_bound_payload(tmp_path: Path) -> None:
    files, manifest = candidate_fixture(tmp_path)
    output = tmp_path / "candidate.json"
    run_gate("verify-bundle", "--manifest", manifest, "--wheel", files["wheel"],
             "--setup", files["setup"], "--launcher", files["launcher"],
             "--rootfs", files["rootfs"], "--inventory", files["inventory"],
             "--pdk-pins", files["pins"], "--source-sha", "a" * 40,
             "--output", output)
    assert json.loads(output.read_text())["artifacts"]["rootfs"]["sha256"] == digest(files["rootfs"])
    files["rootfs"].write_bytes(b"substituted")
    result = run_gate("verify-bundle", "--manifest", manifest, "--wheel", files["wheel"],
                      "--setup", files["setup"], "--launcher", files["launcher"],
                      "--rootfs", files["rootfs"], "--source-sha", "a" * 40,
                      "--output", output, ok=False)
    assert "baked rootfs SHA256 mismatch" in result.stderr


def test_acceptance_gate_rejects_wrong_binary_and_blocked_mandatory_case(tmp_path: Path) -> None:
    evidence = tmp_path / "acceptance.json"
    cases = {case: {"result": "PASS"} for case in (
        "W01", "W02", "W04", "W08", "W09", "W10", "W11", "W12", "W13",
        "W14", "W15", "W20", "W21", "W23", "W25",
    )}
    evidence.write_text(json.dumps({"candidate": {"sourceSha": "a" * 40,
                                                    "setupSha256": "b" * 64},
                                    "cases": cases}))
    run_gate("verify-acceptance", "--evidence", evidence, "--source-sha", "a" * 40,
             "--setup-sha", "b" * 64)
    cases["W13"]["result"] = "BLOCKED"
    evidence.write_text(json.dumps({"candidate": {"sourceSha": "a" * 40,
                                                    "setupSha256": "b" * 64},
                                    "cases": cases}))
    assert "not-passed=['W13']" in run_gate(
        "verify-acceptance", "--evidence", evidence, "--source-sha", "a" * 40,
        "--setup-sha", "b" * 64, ok=False).stderr


def test_workflow_has_one_gated_publish_path_and_no_clobber() -> None:
    body = WORKFLOW.read_text(encoding="utf-8")
    assert body.count("gh release upload") == 1
    assert "--clobber" not in body
    assert "needs: candidate-gate" in body
    assert "verify-acceptance" in body
    assert "publish_release" in body
    assert "github.event_name == 'workflow_dispatch'" in body
    assert "candidate-inputs" in body
    assert "CompanionRootfsSha256" in body
