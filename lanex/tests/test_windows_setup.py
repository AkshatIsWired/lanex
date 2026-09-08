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
    assert second["choices"] == {"pdks": ["sky130A"]}
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


def test_manifest_generator_hashes_exact_checkout_payloads(tmp_path: Path) -> None:
    wheel = tmp_path / "lanex.whl"; wheel.write_bytes(b"wheel from checkout")
    install = tmp_path / "install.sh"; install.write_bytes(b"installer")
    provision = tmp_path / "provision.sh"; provision.write_bytes(b"provision")
    selftest = tmp_path / "selftest.sh"; selftest.write_bytes(b"selftest")
    constraints = tmp_path / "constraints.txt"; constraints.write_bytes(b"librelane==3.0.4\n")
    catalog = tmp_path / "catalog.json"; catalog.write_text('{"pdk_catalog":{"sky130A":{"libraries":["sky130_fd_sc_hd"]}}}')
    pins = tmp_path / "pins.json"; pins.write_text('{"sky130":"pdk-hash"}')
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
        "-ImageDigest", "sha256:" + "e" * 64, "-Gds3dCommit", "f" * 40,
    )
    assert manifest["source"] == {"repository": "owner/fork", "ref": "pull/7/head", "sha": "c" * 40}
    assert manifest["payload"]["wheel"]["sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert json.loads(output.read_text())["image"]["digest"] == "sha256:" + "e" * 64


def test_provision_executes_complete_bundled_installer_not_curl_pipeline() -> None:
    body = PROVISION.read_text()
    stage = body[body.index("install_lanex()") : body.index("write_identity_marker()")]
    assert 'if [ -n "$INSTALL_SH" ]' in stage and "bash -n" in stage
    assert "curl -fL" in stage and '-o "${installer}.download"' in stage
    assert "curl -fsSL '${INSTALL_SH}' | bash" not in stage
    assert 'LANEX_FROM="$source"' in stage


def test_ci_builds_and_mounts_exact_pr_checkout() -> None:
    body = WORKFLOW.read_text()
    assert "github.event.pull_request.head.sha || github.sha" in body
    assert "LANEX_INSTALL_SCRIPT=/checkout/scripts/install.sh" in body
    assert 'LANEX_FROM=/checkout/dist/$LANEX_WHEEL_NAME' in body
    assert "NewManifest" in body and "LANEX_SOURCE_SHA=$(git rev-parse HEAD)" in body
    assert "no usable ref for scripts/install.sh" not in body


def test_inno_requires_exact_payload_and_never_deletes_distro_by_name() -> None:
    body = INNO.read_text()
    assert "#error LanexSourceSha is required" in body
    assert 'Source: "{#LanexWheel}"' in body
    assert "BindAppliance" in body and "VerifyRepairIdentity" in body
    uninstall = body[body.index("procedure CurUninstallStepChanged") :]
    assert "--unregister" not in uninstall
    assert "DelTree(AppDataRoot" not in uninstall
