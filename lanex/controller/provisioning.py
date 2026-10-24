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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


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


_GIB = 1 << 30

# Relative weights of the finalizer's steps, used only to spread Setup's
# progress bar honestly: the image and the PDK families are gigabytes of
# download, a native tool is a minute of apt.
_STEP_WEIGHTS = {"engine": 3, "native": 1, "gds3d": 3, "image": 30, "pdk": 25}


def _emit_setup_event(event: str, **fields: Any) -> None:
    """One machine-readable line for Windows Setup (``@@LANEX:{json}``)."""
    payload = {"schema": 1, "event": event}
    payload.update(fields)
    print("@@LANEX:" + json.dumps(payload, separators=(",", ":")), flush=True)


def _pdk_family_download_bytes(manifest: Mapping[str, Any], variants: List[Mapping[str, Any]]) -> int:
    catalog = manifest.get("pdkCatalog") or {}
    approx = 0.0
    for v in variants:
        entry = catalog.get(v["variant"]) or {}
        try:
            approx = max(approx, float(entry.get("approx_gb") or 0))
        except (TypeError, ValueError):
            continue
    return int((approx or 2.0) * _GIB)


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
        _emit_setup_event("component", component=component, message=message)

    def watch_cancel() -> None:
        if not cancel_path:
            return
        while not cancel_requested.is_set():
            if Path(cancel_path).is_file():
                cancel_requested.set()
                print("Cancel requested: stopping the current download safely...", flush=True)
                if current_key:
                    installer.cancel_install(current_key[0])
                # Then every other live process: the image pull never claims a
                # job key, so a per-key cancel alone missed it and its retry
                # loop started the next attempt.
                installer.cancel_all()
                return
            time.sleep(0.2)

    if cancel_path:
        threading.Thread(target=watch_cancel, name="lanex-setup-cancel", daemon=True).start()

    # ---- the step plan, so Setup can show "step 3 of 7" and a moving bar ----
    engine = plan["engine"]
    family_groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for selected in plan["pdks"]:
        family_groups.setdefault((selected["family"], selected["version"]), []).append(selected)
    steps: List[Tuple[str, int]] = []
    if engine != "none":
        steps.append((f"engine:{engine}", _STEP_WEIGHTS["engine"]))
    for key in plan["nativeTools"]:
        steps.append((f"native:{key}", _STEP_WEIGHTS["gds3d" if key == "gds3d" else "native"]))
    if plan["image"]:
        steps.append(("container:image", _STEP_WEIGHTS["image"]))
    for (family, _version) in family_groups:
        steps.append((f"pdk-family:{family}", _STEP_WEIGHTS["pdk"]))
    total_weight = sum(w for _, w in steps) or 1
    spans: Dict[str, Tuple[int, int]] = {}
    acc = 0
    for name, weight in steps:
        spans[name] = (acc * 100 // total_weight, (acc + weight) * 100 // total_weight)
        acc += weight
    step_index = {name: i + 1 for i, (name, _) in enumerate(steps)}
    active_step: List[str] = []

    sizes = plan["manifest"].get("sizeEstimates") or {}
    image_bytes = int(sizes.get("estimatedImageDownloadBytes") or 1.48 * _GIB)
    download_total = 0.0
    if plan["image"] and not initial["checks"].get("container:image", {}).get("ready"):
        download_total += image_bytes
    for (_family, _version), variants in family_groups.items():
        if not all(initial["checks"].get(f"pdk:{v['variant']}:{lib}", {}).get("ready")
                   for v in variants for lib in v["libraries"]):
            download_total += _pdk_family_download_bytes(plan["manifest"], variants)
    _emit_setup_event("plan", total=len(steps),
                      steps=[name for name, _ in steps],
                      downloadBytes=int(download_total))
    if download_total > 512 * 1024 * 1024:
        print(f"This stage downloads up to about {download_total / _GIB:.1f} GB "
              "(the LibreLane tool image and the chip PDKs). On slow or unstable Wi-Fi "
              "it can take an hour or more. Progress is shown below; if the connection "
              "drops, Setup retries and keeps what was already downloaded.", flush=True)

    def begin_step(name: str, message: str) -> None:
        active_step[:] = [name]
        lo, hi = spans.get(name, (0, 100))
        _emit_setup_event("step", index=step_index.get(name, 0), total=len(steps),
                          start=lo, end=hi, component=name, message=message)

    def skip_step(name: str, message: str) -> None:
        begin_step(name, message)
        print(f"already verified: {name}", flush=True)

    def drain() -> None:
        nonlocal cursor
        for event in bus.events_since(cursor):
            cursor = max(cursor, int(event.get("seq") or cursor))
            etype = str(event.get("type", ""))
            if not etype.startswith("installer"):
                continue
            if etype == "installer_progress":
                _emit_setup_event("progress", percent=int(event.get("percent") or 0),
                                  message=str(event.get("message") or ""),
                                  component=active_step[0] if active_step else "")
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
    if engine != "none":
        if initial["checks"].get(f"engine:{engine}", {}).get("ready"):
            skip_step(f"engine:{engine}", f"{engine} is already running")
        else:
            begin_step(f"engine:{engine}", f"Installing the {engine} container engine")
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
                    skip_step(f"native:{key}", f"{key} is already installed")
                    continue
                label = "Building GDS3D (3D layout viewer)" if key == "gds3d" else f"Installing {key}"
                begin_step(f"native:{key}", label)
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
    if not failures and plan["image"] and not cancel_requested.is_set():
        image = plan["manifest"]["image"]
        if initial["checks"].get("container:image", {}).get("ready"):
            skip_step("container:image", "The LibreLane tool image is already downloaded")
        else:
            begin_step("container:image",
                       f"Downloading the LibreLane tool image (about {image_bytes / _GIB:.1f} GB)")
            announce("container:image", "pulling and verifying the matched LibreLane image")
            print(f"  * Pulling LibreLane container image ({image['reference']}) "
                  f"[~{image_bytes / _GIB:.1f} GB download]...", flush=True)
            result = installer.pull_image_sync(
                image["reference"], image["digest"], expected_engine=plan["engine"],
                expect_bytes=image_bytes,
            )
            drain()
            if not result.get("ok"):
                failures.append({"component": "container:image", "result": result})
            else:
                print("  [OK] LibreLane container image verified ready.", flush=True)
    # The pinned SHA-256 of every PDK file: used now, and kept in ~/.lanex so a
    # PDK added later from the Tools tab is checked the same way.
    asset_pins = plan["manifest"].get("pdkAssets")
    if isinstance(asset_pins, dict) and asset_pins.get("families"):
        try:
            from . import pdkfeed

            target = pdkfeed.pins_path()
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(asset_pins, indent=1) + "\n", encoding="utf-8")
            tmp.replace(target)
        except Exception as exc:  # noqa: BLE001 - the in-memory pins still apply
            print(f"note: could not save the PDK pins for later installs: {exc}", flush=True)
    else:
        asset_pins = None
    if not failures:
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
                skip_step(f"pdk-family:{family}", f"{family} PDK is already installed")
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
            family_bytes = _pdk_family_download_bytes(plan["manifest"], variants)
            begin_step(f"pdk-family:{family}",
                       f"Downloading the {family} PDK ({var_names}, about "
                       f"{family_bytes / _GIB:.1f} GB)")
            announce(f"pdk:{variants[0]['variant']}", f"installing and verifying {family} ({var_names})")
            print(f"  * Installing PDK family: {family} for {var_names} ({len(all_libs)} unique libraries)...", flush=True)

            result = installer.install_pdk_sync(
                variants[0]["variant"],
                all_libs,
                required_version=version,
                strict=True,
                variant_libraries=variant_libs_map,
                expect_bytes=family_bytes,
                asset_pins=asset_pins,
            )
            drain()
            if not result.get("ok"):
                for v in variants:
                    failures.append({"component": f"pdk:{v['variant']}", "result": result})
                break
            for v in variants:
                print(f"  [OK] PDK verified ready: {v['variant']}", flush=True)
    _emit_setup_event("step", index=len(steps), total=len(steps), start=100, end=100,
                      component="verify", message="Verifying everything that was installed")
    if cancel_requested.is_set():
        report = {"schema": 1, "ready": False, "checks": initial["checks"]}
    else:
        report = readiness_report(plan)
    report["installFailures"] = failures
    report["cancelled"] = cancel_requested.is_set()
    report["ready"] = bool(report["ready"] and not failures)
    if not report["ready"] and not report["cancelled"]:
        # The JSON report below is for diagnostics; this is for people.
        print("Not ready yet:", flush=True)
        for failure in failures:
            res = failure.get("result") or {}
            why = res.get("reason") or res.get("error") or res.get("guidance") or "failed"
            print(f"  - {failure['component']}: {str(why).splitlines()[0][:200]}", flush=True)
        for name, check in report.get("checks", {}).items():
            if not check.get("ready"):
                missing = check.get("missing") or check.get("detail") or ""
                print(f"  - {name}: not ready {str(missing)[:160]}".rstrip(), flush=True)
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
