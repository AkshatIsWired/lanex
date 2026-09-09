from __future__ import annotations

import json
from pathlib import Path

import pytest

from lanex.controller import installer, provisioning


def _manifest() -> dict:
    return {
        "schema": 1,
        "dependencies": {"librelane": "3.0.4", "ciel": "2.6.1"},
        "image": {"reference": "ghcr.io/librelane/librelane:3.0.4", "digest": "sha256:" + "d" * 64},
        "gds3d": {"commit": "e" * 40},
        "pdkPins": {
            "variants": {
                "sky130A": {"family": "sky130", "requiredVersion": "a" * 40},
                "sky130B": {"family": "sky130", "requiredVersion": "a" * 40},
            }
        },
        "pdkCatalog": {
            "sky130A": {
                "family": "sky130",
                "libraries": ["io", "hd", "sram"],
                "default_libraries": ["io", "hd"],
            },
            "sky130B": {
                "family": "sky130",
                "libraries": ["io", "hd"],
                "default_libraries": ["io", "hd"],
            },
        },
    }


def _write(tmp_path: Path, value: dict, name: str = "manifest.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_default_plan_selects_every_sky130_library(tmp_path: Path) -> None:
    plan = provisioning.load_plan(_write(tmp_path, _manifest()))
    assert plan["engine"] == "docker"
    assert plan["pdks"] == [
        {
            "variant": "sky130A",
            "family": "sky130",
            "version": "a" * 40,
            "libraries": ["io", "hd", "sram"],
        }
    ]
    assert {"verilator", "iverilog", "graphviz", "gtkwave", "gds3d"} == set(plan["nativeTools"])


def test_advanced_libraries_include_required_and_reject_unknown(tmp_path: Path) -> None:
    path = _write(tmp_path, _manifest())
    plan = provisioning.load_plan(
        path, choices={"pdks": ["sky130A"], "libraries": {"sky130A": ["sram"]}, "engine": "podman"}
    )
    assert plan["pdks"][0]["libraries"] == ["io", "hd", "sram"]
    with pytest.raises(provisioning.ProvisioningInputError, match="unknown libraries"):
        provisioning.load_plan(
            path, choices={"pdks": ["sky130A"], "libraries": {"sky130A": ["$(touch /tmp/pwn)"]}}
        )


def test_same_family_variants_cannot_run_concurrently(tmp_path: Path) -> None:
    with pytest.raises(provisioning.ProvisioningInputError, match="one sky130 variant"):
        provisioning.load_plan(
            _write(tmp_path, _manifest()),
            choices={"pdks": ["sky130A", "sky130B"], "libraries": "all"},
        )


def test_gds3d_requires_linux_cpp_driver_not_cc(monkeypatch: pytest.MonkeyPatch) -> None:
    from lanex.controller import platform_env

    monkeypatch.setattr(
        platform_env,
        "usable_which",
        lambda name: "/usr/bin/" + name if name in {"git", "make", "cc"} else None,
    )
    assert installer._missing_gds3d_build_tools() == ["a C++ compiler"]


def _mock_pdk_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from lanex.controller import pdk, platform_env

    monkeypatch.setattr(platform_env, "dns_ok", lambda: True)
    monkeypatch.setattr(installer, "ciel_permission_status", lambda: {"needs_root": False})
    monkeypatch.setattr(installer, "_pinned_pdk_version", lambda family: "a" * 40)
    monkeypatch.setattr(installer, "_ciel_argv", lambda: ["python", "-m", "ciel"])
    monkeypatch.setattr(installer, "ciel_home", lambda: "/owned/pdks")
    monkeypatch.setattr(
        pdk,
        "check_pdk_library_ready",
        lambda *a, **k: {"ready": True, "required_version": "a" * 40},
    )
    monkeypatch.setattr(installer.time, "sleep", lambda seconds: None)


def test_pdk_sync_retries_transient_then_enables_with_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_pdk_environment(monkeypatch)
    calls = []

    def run(argv, *, label, key):
        calls.append(argv)
        if "fetch" in argv and sum("fetch" in c for c in calls) < 3:
            return {"ok": False, "rc": 1, "output": ["connection reset"]}
        return {"ok": True, "rc": 0, "output": []}

    monkeypatch.setattr(installer, "_run_argv", run)
    result = installer.install_pdk_sync(
        "sky130A", ["io", "hd"], required_version="a" * 40, strict=True
    )
    assert result["ok"] is True and result["attempts"] == 3
    assert sum("fetch" in c for c in calls) == 3
    assert sum("enable" in c for c in calls) == 1
    assert all(c[:3] == ["python", "-m", "ciel"] for c in calls)
    assert calls[-1][-4:] == ["-l", "io", "-l", "hd"]


def test_pdk_permanent_or_exhausted_failure_never_enables(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_pdk_environment(monkeypatch)
    calls = []
    monkeypatch.setattr(
        installer,
        "_run_argv",
        lambda argv, **kwargs: (
            calls.append(argv) or {"ok": False, "rc": 1, "output": ["Permission denied"]}
        ),
    )
    result = installer.install_pdk_sync("sky130A", ["hd"], required_version="a" * 40, strict=True)
    assert result["ok"] is False and result["permanent"] is True
    assert len(calls) == 1 and "enable" not in calls[0]


def test_pdk_family_lock_serializes_variants() -> None:
    assert installer._begin_pdk_family("sky130") is True
    try:
        result = installer.install_pdk_sync("sky130B", ["hd"])
        assert result["ok"] is False
        assert result["status"] == "family-already-running"
    finally:
        installer._end_pdk_family("sky130")


def test_image_pull_uses_manifest_digest_and_selected_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lanex.controller import tools

    monkeypatch.setattr(
        tools,
        "resolve_engine",
        lambda *args: {"ready": True, "engine": "docker", "sg_wrap": False},
    )
    calls = []
    monkeypatch.setattr(
        installer,
        "_run_argv",
        lambda argv, **kwargs: (calls.append(argv) or {"ok": True, "rc": 0, "output": []}),
    )
    monkeypatch.setattr(
        installer,
        "_shell_exec_quiet",
        lambda argv, timeout: (0, "unix:///var/run/docker.sock\n", ""),
    )
    monkeypatch.setattr(installer, "record_image_digest", lambda *a, **k: "sha256:" + "d" * 64)
    digest = "sha256:" + "d" * 64
    result = installer.pull_image_sync("ghcr.io/librelane/librelane:3.0.4", digest)
    assert result["ok"] is True
    assert calls == [["docker", "pull", f"ghcr.io/librelane/librelane:3.0.4@{digest}"]]


def test_engine_resolver_honors_selected_podman(monkeypatch: pytest.MonkeyPatch) -> None:
    from lanex.controller import tools

    monkeypatch.setattr(tools.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(tools, "_engine_usable", lambda name, **kwargs: (True, ""))
    assert tools.resolve_engine("podman")["engine"] == "podman"
    assert tools.resolve_engine("docker")["engine"] == "docker"


def test_readiness_is_strict_if_any_selected_requirement_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lanex.controller import pdk, tools
    from lanex.controller import container_run

    plan = provisioning.load_plan(
        _write(tmp_path, _manifest()),
        choices={
            "pdks": ["sky130A"],
            "libraries": {"sky130A": []},
            "nativeTools": [],
            "engine": "docker",
        },
    )
    monkeypatch.setattr(
        provisioning.importlib.metadata,
        "version",
        lambda name: {"librelane": "3.0.4", "ciel": "2.6.1"}[name],
    )
    monkeypatch.setattr(tools, "resolve_engine", lambda *args: {"ready": True, "engine": "docker"})
    monkeypatch.setattr(container_run, "image_ref", lambda: "example/image:3.0.4")

    def probe(argv, timeout=30):
        if "context" in argv:
            return {"ready": True, "detail": "unix:///var/run/docker.sock"}
        return {"ready": "run" not in argv, "detail": "sha256:" + "d" * 64}

    monkeypatch.setattr(provisioning, "_command_probe", probe)
    monkeypatch.setattr(
        pdk,
        "check_pdk_library_ready",
        lambda *a, **k: {"ready": True, "required_version": "a" * 40},
    )
    report = provisioning.readiness_report(plan)
    assert report["ready"] is False
    assert report["checks"]["container:image"]["toolProbe"]["ready"] is False


def test_readiness_names_missing_gds_daemon_image_and_library(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lanex.controller import pdk, platform_env, tools

    plan = provisioning.load_plan(
        _write(tmp_path, _manifest()),
        choices={
            "pdks": ["sky130A"],
            "libraries": {"sky130A": []},
            "nativeTools": ["gds3d"],
            "engine": "docker",
        },
    )
    monkeypatch.setattr(
        provisioning.importlib.metadata,
        "version",
        lambda name: {"librelane": "3.0.4", "ciel": "2.6.1"}[name],
    )
    monkeypatch.setattr(platform_env, "resolve_user_bin", lambda *a, **k: None)
    monkeypatch.setattr(
        tools,
        "resolve_engine",
        lambda *args: {"ready": False, "engine": "docker", "reason": "daemon unavailable"},
    )
    monkeypatch.setattr(
        pdk,
        "check_pdk_library_ready",
        lambda *a, **k: {"ready": False, "required_version": "a" * 40, "missing": ["library"]},
    )
    report = provisioning.readiness_report(plan, functional=False)
    assert report["ready"] is False
    assert report["checks"]["native:gds3d"]["ready"] is False
    assert report["checks"]["engine:docker"]["ready"] is False
    assert report["checks"]["container:image"]["ready"] is False
    assert report["checks"]["pdk:sky130A:hd"]["ready"] is False


def test_finalizer_waits_for_synchronous_pdk_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan = provisioning.load_plan(
        _write(tmp_path, _manifest()),
        choices={
            "pdks": ["sky130A"],
            "libraries": {"sky130A": []},
            "nativeTools": [],
            "engine": "docker",
        },
    )
    initial_checks = {
        "engine:docker": {"ready": True},
        "container:image": {"ready": True},
        "pdk:sky130A:io": {"ready": False},
        "pdk:sky130A:hd": {"ready": False},
    }
    reports = iter(
        [
            {"schema": 1, "ready": False, "checks": initial_checks},
            {"schema": 1, "ready": False, "checks": initial_checks},
        ]
    )
    monkeypatch.setattr(provisioning, "readiness_report", lambda *a, **k: next(reports))
    called = []
    monkeypatch.setattr(
        installer,
        "install_pdk_sync",
        lambda *a, **k: (called.append((a, k)) or {"ok": False, "reason": "fetch exhausted"}),
    )
    report = provisioning.finalize(plan)
    assert called and report["ready"] is False
    assert report["installFailures"][0]["component"] == "pdk:sky130A"


def test_shell_and_setup_sequence_base_restart_finalize() -> None:
    repo = Path(__file__).resolve().parents[2]
    provision = (repo / "windows/provision/provision.sh").read_text()
    inno = (repo / "windows/installer/lanex.iss").read_text()
    assert "base|finalize" in provision
    assert "DEFERRED(selected-components)" in provision
    assert 'runuser -m -u "$APP_USER"' in provision and "--provision-finalize" in provision
    assert 'case "$SELECTED_ENGINE"' in provision
    assert "LANEX_SETUP_CHOICES=" in inno
    assert 'bash "' + "' + LinuxPath + '" + '" base' in inno
    assert inno.index("--terminate") < inno.index("Result := FinalizeDistro")
    assert "wsl --shutdown" not in inno
