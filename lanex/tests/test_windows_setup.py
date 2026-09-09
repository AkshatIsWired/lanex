"""Hermetic contract tests for Windows Setup identity and durable state."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SETUP = REPO / "windows" / "setup" / "setup.ps1"
INSTALL = REPO / "scripts" / "install.sh"
PROVISION = REPO / "windows" / "provision" / "provision.sh"
INNO = REPO / "windows" / "installer" / "lanex.iss"
WORKFLOW = REPO / ".github" / "workflows" / "windows-installer.yml"
LAUNCHER = REPO / "windows" / "launcher"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


def _bash_executable() -> str | None:
    # Windows' System32 bash.exe is only a WSL forwarding shim and cannot open
    # C:\ paths. Prefer Git Bash explicitly, as the handoff requires.
    for candidate in (Path(os.environ.get("ProgramFiles", "")) / "Git" / "bin" / "bash.exe",
                      Path(os.environ.get("ProgramFiles", "")) / "Git" / "usr" / "bin" / "bash.exe"):
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    return None


BASH = _bash_executable()
OWNER = "S-1-5-21-1000-1000-1000-1001"
INSTALL_ID = "11111111-2222-3333-4444-555555555555"


def _run_setup(*args: object, env: dict[str, str] | None = None, ok: bool = True):
    if not POWERSHELL:
        pytest.skip("PowerShell is required for Windows Setup state tests")
    cmd = [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-File", str(SETUP), *map(str, args)]
    merged = os.environ.copy()
    merged["LANEX_SETUP_TESTING"] = "1"
    if env:
        merged.update(env)
    result = subprocess.run(cmd, capture_output=True, text=True, env=merged)
    if ok:
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout.strip().splitlines()[-1])
    assert result.returncode != 0
    return result


def _manifest(path: Path, sha: str = "a" * 40, app_fp: str = "app-1") -> None:
    path.write_text(json.dumps({
        "schema": 1,
        "source": {"repository": "owner/fork", "ref": "feature/pr", "sha": sha},
        "rootfs": {"sizeBytes": 400_000_000},
        "pdkCatalog": {
            "sky130A": {"family": "sky130", "approx_gb": 2.5,
                         "libraries": ["sky130_fd_sc_hd", "sky130_fd_io"],
                         "default_libraries": ["sky130_fd_sc_hd"]},
            "sky130B": {"family": "sky130", "approx_gb": 2.5,
                         "libraries": ["sky130_fd_sc_hd"],
                         "default_libraries": ["sky130_fd_sc_hd"]},
            "gf180mcuD": {"family": "gf180mcu", "approx_gb": 1.8,
                           "libraries": ["gf180mcu_fd_sc_mcu7t5v0"],
                           "default_libraries": ["gf180mcu_fd_sc_mcu7t5v0"]},
        },
        "componentFingerprints": {"app": app_fp, "rootfs": "root-1"},
    }), encoding="utf-8")


def _initialize(tmp_path: Path, *, operation: str = "install", manifest: Path | None = None):
    manifest = manifest or tmp_path / "manifest.json"
    if not manifest.exists():
        _manifest(manifest)
    installer = tmp_path / "LanEx-Setup.exe"
    installer.write_bytes(b"exact candidate")
    state = tmp_path / "state.json"
    value = _run_setup("-Action", "InitializeState", "-StatePath", state,
                       "-ManifestPath", manifest, "-Operation", operation,
                       "-ChoicesJson", '{"pdks":["sky130A"]}',
                       "-InstallerPath", installer, "-TestOwnerSid", OWNER,
                       "-TestInstallId", INSTALL_ID)
    return state, manifest, installer, value


def _preflight(tmp_path: Path, facts: dict):
    fixture = tmp_path / "preflight.json"
    fixture.write_text(json.dumps(facts), encoding="utf-8")
    return _run_setup("-Action", "Preflight", "-PreflightFixturePath", fixture)


def _base_preflight(**overrides: object) -> dict:
    facts = {
        "nativeArchitecture": "AMD64",
        "windowsBuild": 22631,
        "computer": {"manufacturer": "Fixture Corp", "model": "Model 1"},
        "hypervisorPresent": True,
        "firmwareVirtualization": "enabled",
        "features": {"wsl": "enabled", "virtualMachinePlatform": "enabled"},
        "pendingReboot": False,
        "bootIdentity": "boot-a",
        "wsl": {"present": True, "statusUsable": True, "version": "2.3.26.0",
                "systemdCapable": True},
    }
    facts.update(overrides)
    return facts


@pytest.mark.parametrize("ref", ["feature/windows", "v1.2.3", "a" * 40])
def test_universal_source_resolves_branch_tag_and_sha(ref: str) -> None:
    if not BASH:
        pytest.skip("bash is required for universal installer source tests")
    env = os.environ.copy()
    env.update(LANEX_REPO="someone/lanex-fork", LANEX_REF=ref)
    result = subprocess.run([BASH, str(INSTALL), "--print-source"], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"https://codeload.github.com/someone/lanex-fork/tar.gz/{ref}"


def test_universal_source_preserves_local_wheel(tmp_path: Path) -> None:
    if not BASH:
        pytest.skip("bash is required for universal installer source tests")
    wheel = tmp_path / "lanex-1.0.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    env = os.environ.copy()
    env["LANEX_FROM"] = str(wheel)
    result = subprocess.run([BASH, str(INSTALL), "--print-source"], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(wheel)


def test_state_preserves_choices_and_exact_source_on_repair(tmp_path: Path) -> None:
    state, manifest, installer, first = _initialize(tmp_path)
    second = _run_setup(
        "-Action", "InitializeState", "-StatePath", state,
        "-ManifestPath", manifest, "-Operation", "repair",
        "-ChoicesJson", '{"pdks":["gf180mcuD"]}',
        "-InstallerPath", installer, "-TestOwnerSid", OWNER,
    )
    assert second["installId"] == first["installId"]
    assert second["choices"]["profile"] == "custom"
    assert second["choices"]["pdks"] == ["sky130A"]
    assert second["choices"]["engine"] == "docker"
    assert second["source"]["sha"] == "a" * 40


def test_repair_rejects_changed_manifest_and_update_invalidates_changed_component(tmp_path: Path) -> None:
    state, manifest, installer, _ = _initialize(tmp_path)
    _run_setup("-Action", "SetComponent", "-StatePath", state,
               "-Component", "app", "-ComponentStatus", "complete",
               "-InputFingerprint", "app-1", "-TestOwnerSid", OWNER)
    changed = tmp_path / "changed.json"
    _manifest(changed, sha="b" * 40, app_fp="app-2")
    failed = _run_setup("-Action", "InitializeState", "-StatePath", state,
                        "-ManifestPath", changed, "-Operation", "repair",
                        "-InstallerPath", installer, "-TestOwnerSid", OWNER, ok=False)
    assert "Repair cannot change build identity" in failed.stderr
    updated = _run_setup("-Action", "InitializeState", "-StatePath", state,
                         "-ManifestPath", changed, "-Operation", "update",
                         "-InstallerPath", installer, "-TestOwnerSid", OWNER)
    assert updated["components"]["app"]["status"] == "pending"
    assert updated["source"]["sha"] == "b" * 40
    assert updated["previousBuild"]["source"]["sha"] == "a" * 40
    rolled_back = _run_setup("-Action", "RollbackUpdate", "-StatePath", state,
                             "-TestOwnerSid", OWNER)
    assert rolled_back["source"]["sha"] == "a" * 40
    assert rolled_back["components"]["app"]["status"] == "complete"
    assert "previousBuild" not in rolled_back


def test_successful_update_commit_keeps_new_identity(tmp_path: Path) -> None:
    state, _, installer, _ = _initialize(tmp_path)
    changed = tmp_path / "changed.json"
    _manifest(changed, sha="b" * 40, app_fp="app-2")
    _run_setup("-Action", "InitializeState", "-StatePath", state,
               "-ManifestPath", changed, "-Operation", "update",
               "-InstallerPath", installer, "-TestOwnerSid", OWNER)
    committed = _run_setup("-Action", "CommitUpdate", "-StatePath", state,
                           "-TestOwnerSid", OWNER)
    assert committed["source"]["sha"] == "b" * 40
    assert "previousBuild" not in committed


def test_interrupted_atomic_write_preserves_previous_state(tmp_path: Path) -> None:
    state, manifest, installer, before = _initialize(tmp_path)
    old_bytes = state.read_bytes()
    result = _run_setup("-Action", "InitializeState", "-StatePath", state,
                        "-ManifestPath", manifest, "-Operation", "repair",
                        "-InstallerPath", installer, "-TestOwnerSid", OWNER,
                        env={"LANEX_SETUP_TEST_FAIL_BEFORE_REPLACE": "1"}, ok=False)
    assert "Injected interruption" in result.stderr
    assert state.read_bytes() == old_bytes
    assert json.loads(state.read_text())["installId"] == before["installId"]


def test_foreign_name_collision_gets_distinct_owned_name_and_exact_binding(tmp_path: Path) -> None:
    state, _, _, _ = _initialize(tmp_path)
    expected = tmp_path / "appliance"
    foreign = tmp_path / "someone-elses-distro"
    snapshot = tmp_path / "registry.json"
    snapshot.write_text(json.dumps([{
        "registryId": "{FOREIGN}", "name": "LanEx", "basePath": str(foreign),
    }]), encoding="utf-8")
    appliance = _run_setup("-Action", "ResolveAppliance", "-StatePath", state,
                           "-PreferredDistroName", "lanex", "-ExpectedBasePath", expected,
                           "-RegistrySnapshotPath", snapshot, "-TestOwnerSid", OWNER)
    assert appliance["name"] == "lanex-11111111"
    assert appliance["name"].lower() != "lanex"
    owned_snapshot = tmp_path / "owned-registry.json"
    owned_snapshot.write_text(json.dumps([
        {"registryId": "{FOREIGN}", "name": "LanEx", "basePath": str(foreign)},
        {"registryId": "{OWNED}", "name": appliance["name"], "basePath": str(expected)},
    ]), encoding="utf-8")
    bound = _run_setup("-Action", "BindAppliance", "-StatePath", state,
                       "-RegistrySnapshotPath", owned_snapshot, "-TestOwnerSid", OWNER)
    assert bound["registryId"] == "{OWNED}"


def test_wrong_owner_and_newer_schema_are_rejected(tmp_path: Path) -> None:
    state, _, _, _ = _initialize(tmp_path)
    wrong = _run_setup("-Action", "ReadState", "-StatePath", state,
                       "-TestOwnerSid", "S-1-5-21-9999", ok=False)
    assert "different Windows user" in wrong.stderr
    data = json.loads(state.read_text())
    data["schema"] = 99
    state.write_text(json.dumps(data), encoding="utf-8")
    newer = _run_setup("-Action", "ReadState", "-StatePath", state,
                       "-TestOwnerSid", OWNER, ok=False)
    assert "newer than this Setup supports" in newer.stderr


def test_corrupt_state_is_rejected_without_replacement(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    installer = tmp_path / "LanEx-Setup.exe"
    installer.write_bytes(b"exact candidate")
    state = tmp_path / "state.json"
    state.write_text('{not-json', encoding="utf-8")
    before = state.read_bytes()
    failed = _run_setup("-Action", "InitializeState", "-StatePath", state,
                        "-ManifestPath", manifest, "-InstallerPath", installer,
                        "-TestOwnerSid", OWNER, ok=False)
    assert "malformed JSON" in failed.stderr
    assert state.read_bytes() == before


@pytest.mark.parametrize(
    ("changes", "decision"),
    [
        ({}, "ready"),
        ({"nativeArchitecture": "ARM64"}, "unsupported-architecture"),
        ({"windowsBuild": 19043}, "unsupported-windows"),
        ({"hypervisorPresent": False, "firmwareVirtualization": "disabled",
          "features": {"wsl": "disabled", "virtualMachinePlatform": "disabled"},
          "wsl": {"present": False, "statusUsable": False, "version": "",
                  "systemdCapable": False}}, "firmware-disabled"),
        ({"hypervisorPresent": False, "firmwareVirtualization": "enabled",
          "features": {"wsl": "disabled", "virtualMachinePlatform": "disabled"},
          "wsl": {"present": False, "statusUsable": False, "version": "",
                  "systemdCapable": False}}, "features-required"),
        ({"features": {"wsl": "enable-pending", "virtualMachinePlatform": "enabled"},
          "pendingReboot": True, "wsl": {"present": True, "statusUsable": False,
                                           "version": "2.3.26.0", "systemdCapable": True}},
         "restart-required"),
        ({"wsl": {"present": True, "statusUsable": False, "version": "0.66.2.0",
                  "systemdCapable": False}}, "wsl-update-required"),
        ({"features": {"wsl": "unknown", "virtualMachinePlatform": "unknown"}},
         "preflight-query-failed"),
    ],
)
def test_preflight_truth_table(tmp_path: Path, changes: dict, decision: str) -> None:
    result = _preflight(tmp_path, _base_preflight(**changes))
    assert result["schema"] == 1
    assert result["decision"]["code"] == decision


def test_hypervisor_presence_overrides_misleading_firmware_false(tmp_path: Path) -> None:
    result = _preflight(tmp_path, _base_preflight(
        hypervisorPresent=True, firmwareVirtualization="disabled"))
    assert result["decision"]["code"] == "ready"


def test_unknown_firmware_is_warning_not_disabled_claim(tmp_path: Path) -> None:
    result = _preflight(tmp_path, _base_preflight(
        hypervisorPresent=False, firmwareVirtualization="unknown",
        features={"wsl": "disabled", "virtualMachinePlatform": "disabled"},
        wsl={"present": False, "statusUsable": False, "version": "",
             "systemdCapable": False}))
    assert result["decision"]["code"] == "features-required"
    assert result["decision"]["firmwareNotice"] is True


def test_feature_helper_checks_both_results_and_preserves_errors(tmp_path: Path) -> None:
    fixture = tmp_path / "feature-results.json"
    fixture.write_text(json.dumps({
        "wsl": {"exitCode": 0, "output": "enabled"},
        "virtualMachinePlatform": {"exitCode": 5, "output": "blocked by policy"},
    }), encoding="utf-8")
    output = tmp_path / "feature-output.json"
    failed = _run_setup("-Action", "EnableFeatures", "-FeatureFixturePath", fixture,
                        "-OutputPath", output, ok=False)
    assert "VirtualMachinePlatform" in failed.stderr
    result = json.loads(output.read_text())
    assert result["wsl"]["success"] is True
    assert result["virtualMachinePlatform"]["success"] is False
    assert "blocked by policy" in result["virtualMachinePlatform"]["output"]


def test_elevated_worker_is_bound_to_compile_time_hash(tmp_path: Path) -> None:
    fixture = tmp_path / "feature-results.json"
    fixture.write_text(json.dumps({
        "wsl": {"exitCode": 0, "output": "ok"},
        "virtualMachinePlatform": {"exitCode": 0, "output": "ok"},
    }), encoding="utf-8")
    rejected = _run_setup("-Action", "EnableFeatures", "-FeatureFixturePath", fixture,
                          "-ExpectedSelfSha256", "0" * 64, ok=False)
    assert "integrity check failed" in rejected.stderr
    accepted = _run_setup(
        "-Action", "EnableFeatures", "-FeatureFixturePath", fixture,
        "-ExpectedSelfSha256", hashlib.sha256(SETUP.read_bytes()).hexdigest(),
    )
    assert accepted["wsl"]["success"] is True


def test_owner_bound_resume_is_verified_and_bounded(tmp_path: Path) -> None:
    state, _, installer, before = _initialize(tmp_path)
    resume_root = tmp_path / "resume"
    staged = tmp_path / "cache" / "LanEx-Setup.exe"
    staged.parent.mkdir()
    shutil.copy2(installer, staged)
    staged_state = _run_setup(
        "-Action", "StageInstaller", "-StatePath", state,
        "-ResumeInstallerPath", staged, "-TestResumeRoot", resume_root,
        "-TestOwnerSid", OWNER,
    )
    assert staged_state["resume"]["installerSha256"] == before["currentInstallerSha256"]
    registered = _run_setup(
        "-Action", "RegisterResume", "-StatePath", state,
        "-BootIdentity", "boot-a", "-TestResumeRoot", resume_root,
        "-TestOwnerSid", OWNER,
    )
    assert registered["boot"]["restartAttempts"] == 1
    assert (resume_root / "runonce.txt").exists()
    assert (resume_root / "Continue LanEx Setup.lnk.json").exists()

    same_boot = _run_setup(
        "-Action", "InitializeState", "-StatePath", state,
        "-ManifestPath", tmp_path / "manifest.json", "-Operation", "repair",
        "-InstallerPath", staged, "-ResumeMode", "1", "-BootIdentity", "boot-a",
        "-TestOwnerSid", OWNER, ok=False,
    )
    assert "restart has not been observed" in same_boot.stderr

    resumed = _run_setup(
        "-Action", "InitializeState", "-StatePath", state,
        "-ManifestPath", tmp_path / "manifest.json", "-Operation", "repair",
        "-InstallerPath", staged, "-ResumeMode", "1", "-BootIdentity", "boot-b",
        "-TestOwnerSid", OWNER,
    )
    assert resumed["choices"]["profile"] == "custom"
    assert resumed["choices"]["pdks"] == ["sky130A"]
    _run_setup("-Action", "RegisterResume", "-StatePath", state,
               "-BootIdentity", "boot-b", "-TestResumeRoot", resume_root,
               "-TestOwnerSid", OWNER)
    exhausted = _run_setup("-Action", "RegisterResume", "-StatePath", state,
                           "-BootIdentity", "boot-c", "-TestResumeRoot", resume_root,
                           "-TestOwnerSid", OWNER, ok=False)
    assert "restart limit" in exhausted.stderr


def test_recommended_and_minimal_plans_are_canonical_and_honest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    recommended = _run_setup(
        "-Action", "PlanChoices", "-ManifestPath", manifest,
        "-ChoicesJson", '{"profile":"recommended"}',
    )
    assert recommended["choices"] == {
        "schema": 1, "profile": "recommended", "engine": "docker", "image": True,
        "nativeTools": ["verilator", "iverilog", "graphviz", "gtkwave", "gds3d"],
        "pdks": ["sky130A"], "libraries": "all",
    }
    assert recommended["estimates"]["downloadBytes"] > 6 * 1024**3
    assert recommended["estimates"]["volumes"]["tempRequiredBytes"] == 400_000_000
    assert "restarts" in recommended["estimates"]["notes"][1]

    minimal = _run_setup(
        "-Action", "PlanChoices", "-ManifestPath", manifest,
        "-ChoicesJson", '{"profile":"minimal"}',
    )
    assert minimal["choices"]["engine"] == "none"
    assert minimal["choices"]["image"] is False
    assert minimal["choices"]["pdks"] == []
    assert minimal["estimates"]["downloadBytes"] < recommended["estimates"]["downloadBytes"]


@pytest.mark.parametrize(
    ("choices", "message"),
    [
        ({"profile": "custom", "engine": "none", "image": True, "pdks": []},
         "requires Docker or Podman"),
        ({"profile": "custom", "engine": "docker", "image": True,
          "pdks": ["sky130A", "sky130B"]}, "Select only one sky130 variant"),
        ({"profile": "custom", "engine": "docker", "image": True,
          "pdks": ["sky130A"], "libraries": {"sky130A": ["not-a-library"]}},
         "Unknown library"),
    ],
)
def test_selection_plan_rejects_impossible_or_unbound_choices(
    tmp_path: Path, choices: dict, message: str,
) -> None:
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    failed = _run_setup(
        "-Action", "PlanChoices", "-ManifestPath", manifest,
        "-ChoicesJson", json.dumps(choices), ok=False,
    )
    assert message in failed.stderr


def test_selection_file_is_validated_and_normalized(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    selections = tmp_path / "selections.json"
    selections.write_text(json.dumps({"choices": {
        "profile": "custom", "engine": "podman", "image": True,
        "nativeTools": ["iverilog"], "pdks": ["gf180mcuD"],
        "libraries": {"gf180mcuD": []},
    }}), encoding="utf-8")
    plan = _run_setup(
        "-Action", "PlanChoices", "-ManifestPath", manifest,
        "-ChoicesPath", selections,
    )
    assert plan["choices"]["engine"] == "podman"
    assert plan["choices"]["libraries"]["gf180mcuD"] == ["gf180mcu_fd_sc_mcu7t5v0"]


def test_selection_estimate_credits_only_completed_state(tmp_path: Path) -> None:
    state, manifest, _, _ = _initialize(tmp_path)
    cold = _run_setup(
        "-Action", "PlanChoices", "-ManifestPath", manifest,
        "-ChoicesPath", state,
    )
    for component in ("app", "image", "pdks"):
        _run_setup(
            "-Action", "SetComponent", "-StatePath", state,
            "-Component", component, "-ComponentStatus", "complete",
            "-InputFingerprint", f"fixture-{component}", "-TestOwnerSid", OWNER,
        )
    warm = _run_setup(
        "-Action", "PlanChoices", "-ManifestPath", manifest,
        "-ChoicesPath", state,
    )
    assert warm["estimates"]["reusedInstalledBytes"] > 0
    assert warm["estimates"]["downloadBytes"] < cold["estimates"]["downloadBytes"]
    assert warm["estimates"]["volumes"]["appDataRequiredBytes"] < cold["estimates"]["volumes"]["appDataRequiredBytes"]


def test_setup_outcomes_distinguish_ready_failure_cancel_and_restart(tmp_path: Path) -> None:
    state, _, _, _ = _initialize(tmp_path)
    for outcome in ("failed", "cancelled", "restart-required"):
        value = _run_setup(
            "-Action", "RecordOutcome", "-StatePath", state,
            "-Outcome", outcome, "-OutcomeMessage", f"fixture {outcome}",
            "-TestOwnerSid", OWNER,
        )
        assert value["phase"] == outcome
        assert value["failure"]["kind"] == outcome
    ready = _run_setup(
        "-Action", "RecordOutcome", "-StatePath", state,
        "-Outcome", "ready", "-OutcomeMessage", "all checks passed",
        "-TestOwnerSid", OWNER,
    )
    assert ready["phase"] == "ready"
    assert ready["failure"] is None


def test_inno_m5_wizard_progress_cancel_and_silent_contract() -> None:
    body = INNO.read_text()
    assert "Recommended" in body and "Docker, all supported tools" in body
    assert "Minimal" in body and "LanEx application only" in body
    assert "gf180mcuD" in body and "ihp-sg13g2" in body
    assert "Advanced PDK libraries" in body and "sky130_fd_pr_reram" in body
    assert "PlanChoices" in body and "CheckSelectionSpace" in body
    assert "ExecAndLogOutput" in body and "Lines.Count > 400" in body
    assert "install.previous.log" in body and "ProgressTimerProc" in body
    assert "Stopping safely" in body and "/run/lanex/setup.cancel" in body
    assert "Result := not CancelRequested" in body
    assert "did not start the fallback download" in body
    assert "WizardSilent then Answer := IDCANCEL" in body
    assert "ALLOWWSLUPDATE" in body and "SELECTIONS" in body
    assert "RecordSetupOutcome('ready'" in body


def test_inno_pdk_and_advanced_library_catalog_is_complete() -> None:
    body = INNO.read_text()
    inventory = json.loads(
        (REPO / "docs/windows-installer-handoff/CAPABILITY-INVENTORY.json").read_text()
    )["pdk_catalog"]
    for variant, entry in inventory.items():
        assert variant in body
        advanced = set(entry["libraries"]) - set(entry["default_libraries"])
        for library in advanced:
            assert library in body, f"advanced library missing from installer UI: {variant}/{library}"


def test_resume_rejects_tampered_installer_and_trigger_failure(tmp_path: Path) -> None:
    state, _, installer, _ = _initialize(tmp_path)
    resume_root = tmp_path / "resume"
    staged = tmp_path / "cache" / "LanEx-Setup.exe"
    staged.parent.mkdir()
    shutil.copy2(installer, staged)
    staged.write_bytes(b"tampered")
    bad = _run_setup("-Action", "StageInstaller", "-StatePath", state,
                     "-ResumeInstallerPath", staged, "-TestResumeRoot", resume_root,
                     "-TestOwnerSid", OWNER, ok=False)
    assert "does not match" in bad.stderr

    shutil.copy2(installer, staged)
    _run_setup("-Action", "StageInstaller", "-StatePath", state,
               "-ResumeInstallerPath", staged, "-TestResumeRoot", resume_root,
               "-TestOwnerSid", OWNER)
    failed = _run_setup("-Action", "RegisterResume", "-StatePath", state,
                        "-BootIdentity", "boot-a", "-TestResumeRoot", resume_root,
                        "-TestOwnerSid", OWNER,
                        env={"LANEX_SETUP_TEST_TRIGGER_FAIL": "1"}, ok=False)
    assert "Could not verify" in failed.stderr


def test_manifest_generator_hashes_exact_checkout_payloads(tmp_path: Path) -> None:
    wheel = tmp_path / "lanex.whl"
    wheel.write_bytes(b"wheel from checkout")
    install = tmp_path / "install.sh"
    install.write_bytes(b"installer")
    provision = tmp_path / "provision.sh"
    provision.write_bytes(b"provision")
    selftest = tmp_path / "selftest.sh"
    selftest.write_bytes(b"selftest")
    constraints = tmp_path / "constraints.txt"
    constraints.write_bytes(b"librelane==3.0.4\n")
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"pdk_catalog":{"sky130A":{"libraries":["sky130_fd_sc_hd"]}}}')
    pins = tmp_path / "pins.json"
    pins.write_text('{"sky130":"pdk-hash"}')
    inventory = tmp_path / "baked-inventory.json"
    inventory.write_text('{"schema":1,"packages":{"python3":"3.12.3"}}')
    output = tmp_path / "build-manifest.json"
    manifest = _run_setup(
        "-Action", "NewManifest", "-OutputPath", output,
        "-SourceRepository", "owner/fork", "-SourceRef", "pull/7/head",
        "-SourceSha", "c" * 40, "-WheelPath", wheel,
        "-InstallScriptPath", install, "-ProvisionScriptPath", provision,
        "-SelftestPath", selftest,
        "-ConstraintsPath", constraints, "-CatalogPath", catalog,
        "-PdkPinsPath", pins, "-RootfsUrl", "https://example.invalid/rootfs",
        "-RootfsSha256", "d" * 64, "-RootfsSizeBytes", "123",
        "-BakedRootfsSha256", "1" * 64, "-BakedRootfsSizeBytes", "456",
        "-BakedPackageInventoryPath", inventory,
        "-ImageDigest", "sha256:" + "e" * 64, "-Gds3dCommit", "f" * 40,
    )
    assert manifest["source"] == {"repository": "owner/fork", "ref": "pull/7/head", "sha": "c" * 40}
    assert manifest["payload"]["wheel"]["sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert manifest["bakedRootfs"]["url"] is None
    assert manifest["bakedRootfs"]["packageInventory"]["packages"]["python3"] == "3.12.3"
    assert manifest["bakedRootfs"]["packageInventorySha256"] == hashlib.sha256(inventory.read_bytes()).hexdigest()
    assert json.loads(output.read_text())["image"]["digest"] == "sha256:" + "e" * 64


def test_provision_executes_complete_bundled_installer_not_curl_pipeline() -> None:
    body = PROVISION.read_text()
    stage = body[body.index("install_lanex()") : body.index("write_identity_marker()")]
    assert 'if [ -n "$INSTALL_SH" ]' in stage and "bash -n" in stage
    assert "-fL --retry" in stage and '-o "${installer}.download"' in stage
    assert "curl -fsSL '${INSTALL_SH}' | bash" not in stage
    assert 'LANEX_FROM="$source"' in stage


def test_ci_builds_and_mounts_exact_pr_checkout() -> None:
    body = WORKFLOW.read_text()
    assert "github.event.pull_request.head.sha || github.sha" in body
    assert "LANEX_INSTALL_SCRIPT=/checkout/scripts/install.sh" in body
    assert 'LANEX_FROM=/candidate/$LANEX_WHEEL_NAME' in body
    assert "name: lanex-candidate-inputs" in body
    assert "NewManifest" in body and "LANEX_SOURCE_SHA=$(git rev-parse HEAD)" in body
    assert "SetupWorkerSha256" in body and "Get-FileHash ..\\setup\\setup.ps1" in body
    assert "no usable ref for scripts/install.sh" not in body


def test_inno_requires_exact_payload_and_never_deletes_distro_by_name() -> None:
    body = INNO.read_text()
    assert "#error LanexSourceSha is required" in body
    assert 'Source: "{#LanexWheel}"' in body
    assert 'DestName: "{#LanexWheelFile}"' in body
    assert "lanex-candidate.whl" not in body
    assert "BindAppliance" in body and "VerifyRepairIdentity" in body
    uninstall = body[body.index("procedure CurUninstallStepChanged") :]
    assert "DelTree(AppDataRoot" not in uninstall
    assert "RemoveAppliance" in body and "ConfirmedInstallId" in body
    assert "Validate-UninstallOwnership" in SETUP.read_text()


def _owned_uninstall_fixture(tmp_path: Path):
    data = tmp_path / "LanEx"
    data.mkdir()
    state, _, _, _ = _initialize(data)
    base = data / "appliance" / "distro"
    base.mkdir(parents=True)
    empty_registry = tmp_path / "empty-registry.json"
    empty_registry.write_text("[]", encoding="utf-8")
    _run_setup("-Action", "ResolveAppliance", "-StatePath", state,
               "-ExpectedBasePath", base, "-RegistrySnapshotPath", empty_registry,
               "-TestOwnerSid", OWNER)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps([{
        "registryId": "{OWNED}", "name": "lanex", "basePath": str(base),
    }]), encoding="utf-8")
    _run_setup("-Action", "BindAppliance", "-StatePath", state,
               "-RegistrySnapshotPath", registry, "-TestOwnerSid", OWNER)
    saved = json.loads(state.read_text())
    marker = tmp_path / "marker.json"
    marker.write_text(json.dumps({
        "schema": 1, "installId": saved["installId"],
        "manifestHash": saved["manifestHash"], "sourceSha": saved["source"]["sha"],
    }), encoding="utf-8")
    return data, state, registry, marker


def test_uninstall_export_failure_never_transitions_into_delete(tmp_path: Path) -> None:
    data, state, registry, marker = _owned_uninstall_fixture(tmp_path)
    sentinel = data / "appliance" / "distro" / "project-sentinel"
    sentinel.write_text("keep me")
    wsl = tmp_path / "wsl.json"
    wsl.write_text(json.dumps({"exportExitCode": 1, "unregisterExitCode": 0}))
    export = tmp_path / "backup.tar"
    failed = _run_setup(
        "-Action", "ExportAppliance", "-StatePath", state,
        "-RegistrySnapshotPath", registry, "-LinuxMarkerFixturePath", marker,
        "-TestWslFixturePath", wsl, "-ExportPath", export,
        "-TestOwnerSid", OWNER, ok=False,
    )
    assert "all data were preserved" in failed.stderr
    assert sentinel.read_text() == "keep me"
    assert state.exists() and not export.exists()


def test_uninstall_unregister_failure_preserves_vhdx_state_and_profile(tmp_path: Path) -> None:
    data, state, registry, marker = _owned_uninstall_fixture(tmp_path)
    saved = json.loads(state.read_text())
    original_phase = saved["phase"]
    sentinels = [
        data / "appliance" / "distro" / "ext4.vhdx",
        data / "installer-cache" / "payload",
        data / "app-profile" / saved["installId"] / "Preferences",
    ]
    for path in sentinels:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("sentinel")
    wsl = tmp_path / "wsl.json"
    wsl.write_text(json.dumps({"exportExitCode": 0, "unregisterExitCode": 1}))
    failed = _run_setup(
        "-Action", "RemoveAppliance", "-StatePath", state,
        "-RegistrySnapshotPath", registry, "-LinuxMarkerFixturePath", marker,
        "-TestWslFixturePath", wsl, "-OwnedDataRoot", data,
        "-TestResumeRoot", data / "resume-fixture",
        "-ConfirmedInstallId", saved["installId"], "-TestOwnerSid", OWNER, ok=False,
    )
    # pwsh formats long error lines to the current terminal width on Linux,
    # including ANSI spans; assert the stable tail plus the preserved sentinels.
    assert "caches, and logs were preserved" in failed.stderr
    assert all(path.exists() for path in sentinels) and state.exists()
    assert json.loads(state.read_text())["phase"] == original_phase


def test_explicit_owned_removal_preserves_generic_profile(tmp_path: Path) -> None:
    data, state, registry, marker = _owned_uninstall_fixture(tmp_path)
    saved = json.loads(state.read_text())
    generic = data / "app-profile" / "legacy-generic-profile"
    generic.mkdir(parents=True)
    (generic / "Preferences").write_text("preserve")
    owned = data / "app-profile" / saved["installId"]
    owned.mkdir()
    (owned / "Preferences").write_text("remove")
    wsl = tmp_path / "wsl.json"
    wsl.write_text(json.dumps({"exportExitCode": 0, "unregisterExitCode": 0}))
    result = _run_setup(
        "-Action", "RemoveAppliance", "-StatePath", state,
        "-RegistrySnapshotPath", registry, "-LinuxMarkerFixturePath", marker,
        "-TestWslFixturePath", wsl, "-OwnedDataRoot", data,
        "-TestResumeRoot", data / "resume-fixture",
        "-ConfirmedInstallId", saved["installId"], "-TestOwnerSid", OWNER,
    )
    assert result["removed"] is True
    assert (generic / "Preferences").read_text() == "preserve"
    assert not owned.exists() and not state.exists()


def test_m6_launcher_identity_and_port_takeover_contract() -> None:
    config = (LAUNCHER / "config.go").read_text()
    probe = (LAUNCHER / "probe.go").read_text()
    wsl = (LAUNCHER / "wsl.go").read_text()
    main = (LAUNCHER / "main.go").read_text()
    assert "validateOwnedReadyState" in config and "validateOwnedRegistration" in config
    assert "OwnerSID" in config and "RegistryID" in config and "BasePath" in config
    assert "InstanceID" in probe and "ManifestHash" in probe
    assert "bytes.Contains" not in probe and "scanForServer" not in probe
    assert '"-u", appUser' in wsl and '"LANEX_INSTANCE_ID="' in wsl
    assert '"home", appUser' in probe
    assert "scopedMutexName" in main and "Global\\LanExLauncher" not in main


def test_m6_update_rollback_and_uninstall_are_narrowly_scoped() -> None:
    provision = PROVISION.read_text()
    worker = SETUP.read_text()
    inno = INNO.read_text()
    assert "prepare_update_rollback" in provision
    assert "rollback_update" in provision and "commit_update" in provision
    assert "previousBuild" in worker and "RollbackUpdate" in worker and "CommitUpdate" in worker
    assert "Validate-UninstallOwnership" in worker
    assert "--export" in worker and "--unregister" in worker
    assert "Remove-Item -LiteralPath ([IO.Path]::GetFullPath($OwnedDataRoot)) -Recurse" not in worker
    assert "legacy-generic-profile" not in worker
    assert "InitializeUninstall" in inno and "MB_DEFBUTTON1" in inno
    assert "The export did not complete, so uninstall stopped" in inno
    assert "CompleteUpdateCheckpoint(True)" in inno


def test_inno_keeps_user_work_unelevated_and_limits_uac_to_features() -> None:
    body = INNO.read_text()
    assert "PrivilegesRequired=lowest" in body
    assert "DefaultDirName={localappdata}\\Programs\\{#AppName}" in body
    assert "ShellExec('runas'" in body and "-Action EnableFeatures" in body
    assert "ExpectedSelfSha256" in body and "SetupWorkerSha256 is required" in body
    assert "-Action RegisterResume" in body
    assert "HKEY_CURRENT_USER" in body
    assert "HKEY_LOCAL_MACHINE" not in body[body.index("function ScheduleResume"):
                                               body.index("function OnDownloadProgress")]
    assert "--set-default-version" not in body
    assert "support.microsoft.com/en-US/Windows/Experience/enable-virtualization-on-windows" in body
