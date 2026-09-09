#!/usr/bin/env python3
"""Verify Windows candidate artifacts and real-machine acceptance evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


MANDATORY_WINDOWS_CASES = {
    "W01", "W02", "W04", "W08", "W09", "W10", "W11", "W12", "W13",
    "W14", "W15", "W20", "W21", "W23", "W25",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{label} is unavailable or malformed: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be a JSON object")
    return value


def require_hash(path: Path, expected: str, label: str) -> str:
    actual = sha256(path)
    if actual != str(expected).lower():
        raise SystemExit(f"{label} SHA256 mismatch: expected {expected}, got {actual}")
    return actual


def verify_bundle(args: argparse.Namespace) -> int:
    manifest = load_json(args.manifest, "build manifest")
    source_sha = str(manifest.get("source", {}).get("sha", ""))
    if source_sha != args.source_sha.lower():
        raise SystemExit(f"manifest source SHA is {source_sha}, expected {args.source_sha}")

    require_hash(args.wheel, manifest["payload"]["wheel"]["sha256"], "candidate wheel")
    if args.pdk_pins:
        require_hash(args.pdk_pins, manifest["payload"]["pdkPinsSha256"], "PDK pins")

    baked = manifest.get("bakedRootfs")
    if args.rootfs:
        if not isinstance(baked, dict):
            raise SystemExit("candidate includes a rootfs but the build manifest does not")
        require_hash(args.rootfs, baked["sha256"], "baked rootfs")
        if args.inventory:
            require_hash(
                args.inventory,
                baked.get("packageInventorySha256", ""),
                "baked package inventory",
            )

    artifacts = {
        "setup": {"file": args.setup.name, "sha256": sha256(args.setup)},
        "launcher": {"file": args.launcher.name, "sha256": sha256(args.launcher)},
        "buildManifest": {"file": args.manifest.name, "sha256": sha256(args.manifest)},
        "wheel": {"file": args.wheel.name, "sha256": sha256(args.wheel)},
    }
    if args.rootfs:
        artifacts["rootfs"] = {"file": args.rootfs.name, "sha256": sha256(args.rootfs)}
    output = {
        "schema": 1,
        "sourceSha": source_sha,
        "version": manifest.get("app", {}).get("version"),
        "signed": args.signed,
        "artifacts": artifacts,
    }
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"verified Windows candidate for {source_sha}")
    return 0


def verify_acceptance(args: argparse.Namespace) -> int:
    evidence = load_json(args.evidence, "acceptance evidence")
    candidate = evidence.get("candidate", {})
    if candidate.get("sourceSha") != args.source_sha.lower():
        raise SystemExit("acceptance evidence belongs to a different source SHA")
    if candidate.get("setupSha256") != args.setup_sha.lower():
        raise SystemExit("acceptance evidence belongs to a different Setup binary")
    cases = evidence.get("cases", {})
    if not isinstance(cases, dict):
        raise SystemExit("acceptance evidence cases must be an object")
    missing = sorted(MANDATORY_WINDOWS_CASES - cases.keys())
    failed = sorted(case for case in MANDATORY_WINDOWS_CASES if cases.get(case, {}).get("result") != "PASS")
    if missing or failed:
        raise SystemExit(f"release acceptance is incomplete; missing={missing}, not-passed={failed}")
    print("mandatory real-Windows acceptance evidence matches this candidate")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    bundle = commands.add_parser("verify-bundle")
    for name in ("manifest", "wheel", "setup", "launcher", "output"):
        bundle.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
    bundle.add_argument("--rootfs", type=Path)
    bundle.add_argument("--inventory", type=Path)
    bundle.add_argument("--pdk-pins", type=Path)
    bundle.add_argument("--source-sha", required=True)
    bundle.add_argument("--signed", action="store_true")
    bundle.set_defaults(func=verify_bundle)

    acceptance = commands.add_parser("verify-acceptance")
    acceptance.add_argument("--evidence", type=Path, required=True)
    acceptance.add_argument("--source-sha", required=True)
    acceptance.add_argument("--setup-sha", required=True)
    acceptance.set_defaults(func=verify_acceptance)
    return root


if __name__ == "__main__":
    parsed = parser().parse_args()
    raise SystemExit(parsed.func(parsed))
