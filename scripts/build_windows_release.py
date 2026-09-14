#!/usr/bin/env python3
"""Unified build entry point for LanEx Windows Setup and release artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

def run_cmd(cmd: list[str] | str, cwd: Path = REPO_ROOT, shell: bool = False) -> None:
    print(f"==> Running: {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd, shell=shell)
    if res.returncode != 0:
        raise SystemExit(f"Command failed with exit code {res.returncode}")

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()

def main() -> int:
    parser = argparse.ArgumentParser(description="Build verified Windows release artifacts")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "installer-workspace" / "outputs"), help="Output directory for compiled artifacts")
    parser.add_argument("--source-sha", default="", help="Explicit source commit SHA")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Resolve source SHA
    source_sha = args.source_sha
    if not source_sha:
        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True)
        if res.returncode == 0:
            source_sha = res.stdout.strip()
    if not source_sha:
        source_sha = "bb22dc66fbc83b774dde1d302285b18350a83a42"
    print(f"[*] Building for source SHA: {source_sha}")

    # 2. Build Python wheel
    print("[*] Building Python wheel...")
    dist_dir = REPO_ROOT / "dist"
    run_cmd([sys.executable, "-m", "build", "-w"])
    wheels = sorted(dist_dir.glob("*.whl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not wheels:
        raise SystemExit("No wheel built in dist/")
    wheel_path = wheels[0]
    print(f"[*] Using wheel: {wheel_path.name} ({sha256_file(wheel_path)})")

    # 3. Build Go launcher
    launcher_exe = REPO_ROOT / "windows" / "launcher" / "LanEx.exe"
    print("[*] Compiling Windows launcher LanEx.exe...")
    wsl_go_cmd = "cd /mnt/c/Users/itsva/lanex/windows/launcher && GOOS=windows GOARCH=amd64 go build -buildvcs=false -o LanEx.exe ."
    go_distro = "Ubuntu"
    chk = subprocess.run(["wsl.exe", "-d", go_distro, "-u", "root", "--", "which", "go"], capture_output=True)
    if chk.returncode != 0:
        go_distro = "lanex"
    run_cmd(["wsl.exe", "-d", go_distro, "-u", "root", "--", "bash", "-c", wsl_go_cmd])
    if not launcher_exe.exists():
        raise SystemExit("LanEx.exe failed to build")
    print(f"[*] Built LanEx.exe: {sha256_file(launcher_exe)}")

    # 4. Generate build-manifest.json
    print("[*] Generating build-manifest.json...")
    manifest_path = REPO_ROOT / "windows" / "setup" / "build-manifest.json"
    manifest_cmd = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        f"""
        $params = @{{
            Action = 'NewManifest'
            OutputPath = '{manifest_path}'
            SourceRepository = 'AkshatIsWired/lanex'
            SourceRef = 'windows-installer-support'
            SourceSha = '{source_sha}'
            AppVersion = '1.0.0'
            WheelPath = '{wheel_path}'
            InstallScriptPath = 'scripts/install.sh'
            ProvisionScriptPath = 'windows/provision/provision.sh'
            SelftestPath = 'windows/provision/selftest.sh'
            ConstraintsPath = 'windows/setup/constraints.txt'
            CatalogPath = 'docs/windows-installer-handoff/CAPABILITY-INVENTORY.json'
            PdkPinsPath = 'windows/setup/pdk-pins.json'
            RootfsUrl = 'https://releases.ubuntu.com/24.04.4/ubuntu-24.04.4-wsl-amd64.wsl'
            RootfsSha256 = '9b2f7730dc68227dd04a9f3e5eab86ad85caf556b8606ad94f1f29ff5c4fd3f5'
            RootfsSizeBytes = 391118848
            ImageReference = 'ghcr.io/librelane/librelane:3.0.4'
            ImageDigest = 'sha256:eab07a50fa9ae481f631d904bd9fbaa99752c587fdbddb7c8cf2ac04208eecd9'
            Gds3dCommit = 'dc6d965225c9f5ed2a6faefb7ea30665429060fe'
        }}
        & windows/setup/setup.ps1 @params | Out-Null
        """
    ]
    run_cmd(manifest_cmd)
    print(f"[*] Generated manifest: {sha256_file(manifest_path)}")

    # 5. Compile Inno Setup
    print("[*] Compiling Inno Setup LanEx-Setup.exe...")
    iscc_path = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
    if not iscc_path.exists():
        raise SystemExit(f"ISCC not found at {iscc_path}")

    worker_hash = sha256_file(REPO_ROOT / "windows" / "setup" / "setup.ps1")
    inno_cmd = [
        str(iscc_path),
        "/DAppVersion=1.0.0",
        "/DAppVersionNumeric=1.0.0",
        f"/DLanexRef={source_sha}",
        f"/DLanexSourceSha={source_sha}",
        "/DLanexSourceRepo=AkshatIsWired/lanex",
        f"/DLanexWheel={wheel_path}",
        f"/DSetupWorkerSha256={worker_hash}",
        r"/DLauncherExe=..\launcher\LanEx.exe",
        f"/O{out_dir}",
        str(REPO_ROOT / "windows" / "installer" / "lanex.iss")
    ]
    run_cmd(inno_cmd)

    setup_exe = out_dir / "LanEx-Setup.exe"
    if not setup_exe.exists():
        raise SystemExit("LanEx-Setup.exe was not created")
    print(f"[*] Compiled LanEx-Setup.exe: {sha256_file(setup_exe)} ({setup_exe.stat().st_size} bytes)")

    # 6. Verify candidate bundle
    print("[*] Verifying candidate bundle...")
    verification_output = out_dir / "bundle-verification.json"
    run_cmd([
        sys.executable, str(REPO_ROOT / "scripts" / "ci" / "windows_candidate.py"), "verify-bundle",
        "--manifest", str(manifest_path),
        "--wheel", str(wheel_path),
        "--setup", str(setup_exe),
        "--launcher", str(launcher_exe),
        "--pdk-pins", str(REPO_ROOT / "windows" / "setup" / "pdk-pins.json"),
        "--source-sha", source_sha,
        "--output", str(verification_output)
    ])
    print("[+] Candidate verification complete and clean!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
