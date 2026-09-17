# Copyright 2026 LanEx Contributors
# Licensed under the Apache License, Version 2.0
"""Strict, headless appliance finalization and readiness checks.

The ordinary LanEx installer stays deliberately forgiving.  Windows Setup uses
this module after the private WSL appliance has rebooted with systemd: selected
components are installed synchronously and every promised outcome is checked.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


class ProvisioningInputError(ValueError):
    """The build manifest or saved selections are not safe to execute."""


_NATIVE_DEFAULTS = ("verilator", "iverilog", "graphviz", "gtkwave", "gds3d")


def _read_json(path: str | os.PathLike[str], label: str) -> Dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProvisioningInputError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise ProvisioningInputError(f"{label} must contain a JSON object")
    return value


def load_plan(
    manifest_path: str | os.PathLike[str],
    *,
    choices_path: Optional[str | os.PathLike[str]] = None,
    choices: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate immutable catalog/pins and expand saved user selections.

    ``choices_path`` may be the owner state written by Setup (with a ``choices``
    member) or a choices-only JSON file.  Strings are never passed to a shell;
    every PDK/library must occur in the signed build manifest's catalog.
    """
    manifest = _read_json(manifest_path, "build manifest")
    if manifest.get("schema") != 1:
        raise ProvisioningInputError("unsupported build manifest schema")
    catalog = manifest.get("pdkCatalog")
    pins = manifest.get("pdkPins", {}).get("variants")
    if not isinstance(catalog, dict) or not isinstance(pins, dict):
        raise ProvisioningInputError("build manifest has no PDK catalog/pins")
    image = manifest.get("image", {})
    if (
        not isinstance(image, dict)
        or not isinstance(image.get("reference"), str)
        or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", image.get("digest", ""))
    ):
        raise ProvisioningInputError("build manifest image reference/digest is invalid")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", manifest.get("gds3d", {}).get("commit", "")):
        raise ProvisioningInputError("build manifest GDS3D commit is invalid")
    if choices is None:
        raw = _read_json(choices_path, "saved selections") if choices_path else {}
        choices = raw.get("choices", raw)
    if not isinstance(choices, Mapping):
        raise ProvisioningInputError("saved selections must be an object")

    profile = choices.get("profile", "custom")
    if profile not in ("recommended", "complete", "maximum", "full", "custom", "minimal"):
        raise ProvisioningInputError("profile must be recommended, complete, custom, minimal, or maximum")
    if profile == "recommended":
        from .pdk_catalog import PRESET_EXPANSIONS

        choices = dict(PRESET_EXPANSIONS["recommended"])
    elif profile in ("complete", "maximum", "full"):
        from .pdk_catalog import PRESET_EXPANSIONS

        choices = dict(PRESET_EXPANSIONS["complete"])
    elif profile == "minimal":
        from .pdk_catalog import PRESET_EXPANSIONS

        choices = dict(PRESET_EXPANSIONS["minimal"])

    selected = choices.get("pdks", ["sky130A"])
    if (
        not isinstance(selected, list)
        or not all(isinstance(x, str) for x in selected)
    ):
        raise ProvisioningInputError("pdks must be a string array")
    selected = list(dict.fromkeys(selected))
    library_choice = choices.get("libraries", "all")
    pdks: List[Dict[str, Any]] = []
    for variant in selected:
        entry = catalog.get(variant)
        pin = pins.get(variant)
        if not isinstance(entry, dict) or not isinstance(pin, dict):
            raise ProvisioningInputError(f"unknown PDK variant: {variant}")
        family = entry.get("family")
        version = pin.get("requiredVersion")
        allowed = entry.get("libraries")
        required = entry.get("default_libraries", entry.get("defaultLibraries", []))
        if not isinstance(family, str) or not isinstance(version, str) or len(version) != 40:
            raise ProvisioningInputError(f"manifest pin is invalid for {variant}")
        if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
            raise ProvisioningInputError(f"manifest libraries are invalid for {variant}")
        if library_choice == "all":
            libs = allowed
        elif isinstance(library_choice, dict):
            requested = library_choice.get(variant, [])
            if not isinstance(requested, list) or not all(isinstance(x, str) for x in requested):
                raise ProvisioningInputError(f"libraries for {variant} must be a string array")
            libs = list(dict.fromkeys(list(required) + requested))
        else:
            raise ProvisioningInputError(
                "libraries must be 'all' or an object keyed by PDK variant"
            )
        unknown = sorted(set(libs) - set(allowed))
        if unknown:
            raise ProvisioningInputError(f"unknown libraries for {variant}: {', '.join(unknown)}")
        pdks.append(
            {
                "variant": variant,
                "family": family,
                "version": version,
                "libraries": list(dict.fromkeys(libs)),
            }
        )

    engine = choices.get("engine", "docker")
    image_selected = choices.get("image", True)
    if not isinstance(image_selected, bool):
        raise ProvisioningInputError("image must be true or false")
    if engine not in ("docker", "podman", "none"):
        raise ProvisioningInputError("engine must be docker, podman or none")
    if (image_selected or pdks) and engine == "none":
        raise ProvisioningInputError("a selected image or PDK requires docker or podman")
    if pdks and not image_selected:
        raise ProvisioningInputError("selected PDKs require the matched flow image")
    native = choices.get("nativeTools", list(_NATIVE_DEFAULTS))
    if not isinstance(native, list) or not all(x in _NATIVE_DEFAULTS for x in native):
        raise ProvisioningInputError("nativeTools contains an unsupported appliance tool")
    return {
        "schema": 1,
        "profile": profile,
        "manifest": manifest,
        "engine": engine,
        "image": image_selected,
        "nativeTools": list(dict.fromkeys(native)),
        "pdks": pdks,
    }


def _command_probe(argv: List[str], timeout: float = 30.0) -> Dict[str, Any]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return {
            "ready": proc.returncode == 0,
            "rc": proc.returncode,
            "detail": (proc.stdout or proc.stderr or "").strip()[-500:],
        }
    except Exception as exc:
        return {"ready": False, "detail": str(exc)}


def _binary_probe(name: str, args: Iterable[str] = ("--version",)) -> Dict[str, Any]:
    from . import platform_env

    path = platform_env.usable_which(name)
    if not path:
        return {"ready": False, "missing": [name]}
    result = _command_probe([path, *args])
    result["path"] = path
    return result


def readiness_report(plan: Mapping[str, Any], *, functional: bool = True) -> Dict[str, Any]:
    """Read-only report for every selected appliance postcondition."""
    from . import installer, pdk, tools

    checks: Dict[str, Any] = {}
    try:
        pid1 = Path("/proc/1/comm").read_text(encoding="utf-8").strip()
    except Exception:
        pid1 = ""
    checks["runtime:systemd"] = {"ready": pid1 == "systemd", "pid1": pid1}
    dependencies = plan["manifest"].get("dependencies", {})
    for package in ("librelane", "ciel"):
        wanted = dependencies.get(package)
        try:
            actual = importlib.metadata.version(package)
        except Exception:
            actual = None
        checks[f"python:{package}"] = {
            "ready": actual == wanted,
            "expected": wanted,
            "actual": actual,
        }

    binary_args = {"iverilog": ("-V",), "graphviz": ("-V",), "gtkwave": ("--version",)}
    binary_names = {"graphviz": "dot"}
    for key in plan["nativeTools"]:
        name = binary_names.get(key, key)
        if key == "gds3d":
            from . import platform_env

            path = platform_env.resolve_user_bin("gds3d", ["GDS3D"])
            probe = {
                "ready": bool(path and os.access(path, os.X_OK)),
                "path": path,
                "missing": [] if path else ["gds3d"],
            }
        else:
            probe = _binary_probe(name, binary_args.get(key, ("--version",)))
        if key == "gds3d" and probe.get("ready"):
            path = probe.get("path")
            probe["linkage"] = (
                _command_probe(["ldd", str(path)]) if shutil.which("ldd") else {"ready": False}
            )
            probe["compiler"] = _binary_probe("g++", ("--version",))
            missing_headers = installer._missing_gds3d_dev_packages()
            probe["headers"] = {"ready": not missing_headers, "missingPackages": missing_headers}
            wanted_commit = plan["manifest"].get("gds3d", {}).get("commit")
            from . import platform_env

            fonts = platform_env.x11_fixed_fonts_present()
            mesa = platform_env.mesa_dri_present()
            probe["runtime"] = {
                "ready": fonts is True and mesa is True,
                "x11FixedFonts": fonts,
                "mesaDri": mesa,
            }
            source = platform_env.home() / "tools" / "GDS3D"
            provenance = _command_probe(["git", "-C", str(source), "rev-parse", "HEAD"])
            provenance["expected"] = wanted_commit
            provenance["ready"] = bool(
                provenance.get("ready") and provenance.get("detail") == wanted_commit
            )
            probe["provenance"] = provenance
            probe["ready"] = bool(
                probe["linkage"].get("ready")
                and "not found" not in probe["linkage"].get("detail", "").lower()
                and probe["compiler"].get("ready")
                and probe["headers"].get("ready")
                and probe["runtime"].get("ready")
                and provenance.get("ready")
            )
        checks[f"native:{key}"] = probe

    engine = plan["engine"]
    resolved = {"ready": True, "engine": "none"} if engine == "none" else tools.resolve_engine(engine)
    engine_ready = bool(resolved.get("ready") and resolved.get("engine") == engine)
    engine_check: Dict[str, Any] = {"ready": engine_ready, "resolved": resolved}
    if engine_ready and engine == "docker":
        context = _command_probe(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]
        )
        endpoint = context.get("detail", "")
        context["localSocket"] = endpoint == "unix:///var/run/docker.sock"
        engine_check["context"] = context
        engine_check["ready"] = bool(context.get("ready") and context["localSocket"])
        engine_ready = bool(engine_check["ready"])
    if engine != "none":
        checks[f"engine:{engine}"] = engine_check
    image = plan["manifest"]["image"]["reference"]
    image_digest = plan["manifest"].get("image", {}).get("digest")
    image_target = f"{image.split('@', 1)[0]}@{image_digest}"
    if not plan["image"]:
        image_check = {"ready": True, "selected": False}
    elif engine_ready:
        inspect = [engine, "image", "inspect", image_target, "--format", "{{json .RepoDigests}}"]
        if resolved.get("sg_wrap"):
            inspect = tools.sg_wrap_argv(inspect)
        image_check = _command_probe(inspect)
        image_check["expectedDigest"] = image_digest
        image_check["ready"] = bool(
            image_check.get("ready") and image_digest in image_check.get("detail", "")
        )
        if image_check["ready"]:
            probe_bins = list(
                dict.fromkeys(
                    [
                        *(t["key"] for t in tools.EDA_TOOLS if t.get("in_image")),
                        "librelane",
                        "yosys",
                        "openroad",
                        "klayout",
                        "magic",
                        "netgen",
                        "verilator",
                        "iverilog",
                    ]
                )
            )
            check_script = (
                "missing=''; for b in "
                + " ".join(probe_bins)
                + "; do command -v \"$b\" >/dev/null 2>&1 || missing=\"$missing $b\"; done; "
                "if [ -n \"$missing\" ]; then echo \"MISSING:$missing\"; exit 1; fi"
            )
            run = [
                engine,
                "run",
                "--pull=never",
                "--rm",
                "--entrypoint",
                "sh",
                image_target,
                "-c",
                check_script,
            ]
            if resolved.get("sg_wrap"):
                run = tools.sg_wrap_argv(run)
            image_check["toolProbe"] = _command_probe(run, timeout=120.0)
            detail = image_check["toolProbe"].get("detail", "")
            missing_bins = []
            if "MISSING:" in detail:
                missing_bins = [b for b in detail.split("MISSING:", 1)[1].strip().split() if b]
            image_check["missingBinaries"] = missing_bins
            if missing_bins:
                image_check.setdefault("missing", []).extend(missing_bins)
            image_check["ready"] = bool(image_check["toolProbe"].get("ready") and not missing_bins)
        else:
            image_check["toolProbe"] = {"ready": False, "skipped": "image not present"}
    else:
        image_check = {
            "ready": False,
            "expectedDigest": image_digest,
            "missing": ["usable selected container engine"],
        }
    if plan["image"]:
        checks["container:image"] = image_check

    for selected in plan["pdks"]:
        for library in selected["libraries"]:
            result = pdk.check_pdk_library_ready(
                selected["variant"], library, required_version=selected["version"]
            )
            result["expectedVersion"] = selected["version"]
            result["ready"] = bool(
                result.get("ready") and result.get("required_version") == selected["version"]
            )
            checks[f"pdk:{selected['variant']}:{library}"] = result

    if functional and "iverilog" in plan["nativeTools"]:
        with tempfile.TemporaryDirectory(prefix="lanex-setup-check-") as temp:
            source = Path(temp) / "smoke.v"
            output = Path(temp) / "smoke.out"
            source.write_text(
                'module smoke; initial begin $display("LANEX_SMOKE_OK"); $finish; end endmodule\n'
            )
            compile_probe = _command_probe(["iverilog", "-o", str(output), str(source)])
            run_probe = (
                _command_probe(["vvp", str(output)])
                if compile_probe.get("ready")
                else {"ready": False}
            )
            checks["functional:iverilog"] = {
                "ready": bool(
                    run_probe.get("ready") and "LANEX_SMOKE_OK" in run_probe.get("detail", "")
                ),
                "compile": compile_probe,
                "run": run_probe,
            }
    ready = all(bool(item.get("ready")) for item in checks.values())
    return {"schema": 1, "ready": ready, "checks": checks}


def finalize(plan: Mapping[str, Any]) -> Dict[str, Any]:
    """Install selected components synchronously, then return strict readiness."""
    from . import installer, tools
    from .events import bus

    cursor = bus.max_seq
    initial = readiness_report(plan, functional=False)
    cancel_path = os.environ.get("LANEX_SETUP_CANCEL_FILE", "")
    cancel_requested = threading.Event()
    current_key: List[str] = []

    def announce(component: str, message: str) -> None:
        current_key[:] = [component]
        print("@@LANEX:" + json.dumps({
            "schema": 1, "event": "component", "component": component,
            "message": message,
        }, separators=(",", ":")), flush=True)

    def watch_cancel() -> None:
        if not cancel_path:
            return
        while not cancel_requested.is_set():
            if Path(cancel_path).is_file():
                cancel_requested.set()
                if current_key:
                    installer.cancel_install(current_key[0])
                return
            time.sleep(0.2)

    if cancel_path:
        threading.Thread(target=watch_cancel, name="lanex-setup-cancel", daemon=True).start()

    def drain() -> None:
        nonlocal cursor
        for event in bus.events_since(cursor):
            cursor = max(cursor, int(event.get("seq") or cursor))
            if not str(event.get("type", "")).startswith("installer"):
                continue
            line = event.get("line") or event.get("message")
            if line:
                print(str(line).rstrip(), flush=True)

    draining = threading.Event()

    def periodic_drain() -> None:
        while not draining.is_set():
            drain()
            time.sleep(0.2)
        drain()

    drain_thread = threading.Thread(target=periodic_drain, name="lanex-setup-drain", daemon=True)
    drain_thread.start()

    failures: List[Dict[str, Any]] = []
    engine = plan["engine"]
    if engine != "none" and not initial["checks"].get(f"engine:{engine}", {}).get("ready"):
        announce(engine, f"installing {engine}")
        result = installer.install_tool(engine)
        drain()
        if not result.get("ok"):
            failures.append({"component": f"engine:{engine}", "result": result})
        else:
            for attempt in range(1, 61):
                if cancel_requested.is_set():
                    failures.append({"component": f"engine:{engine}", "cancelled": True})
                    break
                if tools.resolve_engine(engine).get("ready"):
                    print(f"selected engine is reachable: {engine}", flush=True)
                    break
                if attempt % 5 == 0:
                    print(f"waiting for {engine} readiness ({attempt * 2}s)...", flush=True)
                time.sleep(2)
            else:
                failures.append(
                    {
                        "component": f"engine:{engine}",
                        "result": {
                            "ok": False,
                            "reason": "engine did not become reachable within two minutes",
                        },
                    }
                )
    previous_commit = os.environ.get("LANEX_GDS3D_COMMIT")
    os.environ["LANEX_GDS3D_COMMIT"] = plan["manifest"]["gds3d"]["commit"]
    try:
        if not failures:
            for key in plan["nativeTools"]:
                if cancel_requested.is_set():
                    failures.append({"component": f"native:{key}", "cancelled": True})
                    break
                if initial["checks"].get(f"native:{key}", {}).get("ready"):
                    print(f"already verified: native:{key}", flush=True)
                    continue
                announce(key, f"installing and verifying native tool {key}")
                print(f"  * Installing native tool: {key}...", flush=True)
                result = installer.install_tool(key)
                drain()
                if not result.get("ok"):
                    failures.append({"component": f"native:{key}", "result": result})
                    break
                print(f"  [OK] Native tool ready: {key}", flush=True)
    finally:
        if previous_commit is None:
            os.environ.pop("LANEX_GDS3D_COMMIT", None)
        else:
            os.environ["LANEX_GDS3D_COMMIT"] = previous_commit
    if not failures and plan["image"]:
        image = plan["manifest"]["image"]
        if initial["checks"].get("container:image", {}).get("ready"):
            print("already verified: container:image", flush=True)
        else:
            announce("container:image", "pulling and verifying the matched LibreLane image")
            print(f"  * Pulling LibreLane container image ({image['reference']}) [~3.4 GB]...", flush=True)
            result = installer.pull_image_sync(
                image["reference"], image["digest"], expected_engine=plan["engine"]
            )
            drain()
            if not result.get("ok"):
                failures.append({"component": "container:image", "result": result})
            else:
                print("  [OK] LibreLane container image verified ready.", flush=True)
    if not failures:
        family_groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for selected in plan["pdks"]:
            f_key = (selected["family"], selected["version"])
            family_groups.setdefault(f_key, []).append(selected)

        for (family, version), variants in family_groups.items():
            if cancel_requested.is_set():
                for v in variants:
                    failures.append({"component": f"pdk:{v['variant']}", "cancelled": True})
                break

            all_ready = True
            for v in variants:
                keys = [f"pdk:{v['variant']}:{lib}" for lib in v["libraries"]]
                if not all(initial["checks"].get(k, {}).get("ready") for k in keys):
                    all_ready = False
                    break
            if all_ready:
                for v in variants:
                    print(f"already verified: pdk:{v['variant']}", flush=True)
                continue

            all_libs: List[str] = []
            variant_libs_map: Dict[str, List[str]] = {}
            for v in variants:
                variant_libs_map[v["variant"]] = list(v["libraries"])
                for lib in v["libraries"]:
                    if lib not in all_libs:
                        all_libs.append(lib)

            var_names = ", ".join(v["variant"] for v in variants)
            announce(f"pdk:{variants[0]['variant']}", f"installing and verifying {family} ({var_names})")
            print(f"  * Installing PDK family: {family} for {var_names} ({len(all_libs)} unique libraries)...", flush=True)

            result = installer.install_pdk_sync(
                variants[0]["variant"],
                all_libs,
                required_version=version,
                strict=True,
                variant_libraries=variant_libs_map,
            )
            drain()
            if not result.get("ok"):
                for v in variants:
                    failures.append({"component": f"pdk:{v['variant']}", "result": result})
                break
            for v in variants:
                print(f"  [OK] PDK verified ready: {v['variant']}", flush=True)
    if cancel_requested.is_set():
        report = {"schema": 1, "ready": False, "checks": initial["checks"]}
    else:
        report = readiness_report(plan)
    report["installFailures"] = failures
    report["cancelled"] = cancel_requested.is_set()
    report["ready"] = bool(report["ready"] and not failures)
    draining.set()
    drain_thread.join(timeout=1.0)
    current_key.clear()
    if report["ready"]:
        try:
            from . import platform_env

            home = platform_env.home()
            home.mkdir(parents=True, exist_ok=True)
            img_info = plan["manifest"].get("image", {})
            ref = img_info.get("reference", "")
            dig = img_info.get("digest", "")
            rt_contract = {
                "schema": 1,
                "engine": plan["engine"],
                "image": ref,
                "digest": dig,
                "imageRef": f"{ref}@{dig}" if (ref and dig) else ref,
                "pdks": plan["pdks"],
            }
            tmp_path = home / "runtime.json.tmp"
            tmp_path.write_text(
                json.dumps(rt_contract, indent=2) + "\n", encoding="utf-8"
            )
            tmp_path.replace(home / "runtime.json")
        except Exception as exc:
            report["ready"] = False
            report["installFailures"].append({
                "component": "runtime:contract",
                "result": {"ok": False, "reason": f"could not write runtime contract: {exc}"}
            })
    return report
