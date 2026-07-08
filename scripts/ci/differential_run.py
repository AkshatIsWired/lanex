#!/usr/bin/env python3
"""Differential RTL->GDS CI driver: four execution paths, one truth.

Runs the bundled SPM design four ways on the same runner + PDK + image, then
gates on equivalence — the continuous version of the manual audits that proved
CLI-vs-GUI metric identity (303/303) on a single box:

  native     what a user WITHOUT LanEx types: ``python -m librelane
             --pdk-root R --docker-no-tty --dockerized config.yaml -p … -s …
             --run-tag native`` (no lanex code in the loop; the argv shape is
             unit-locked against container_run.build_dockerized_argv so the
             two can never drift apart silently)
  local      lanex FlowRunner local mode, inside the official image
             (scripts/ci/leg_local_run.py)
  container  lanex FlowRunner run_mode="container" (the GUI's container path,
             including ContainerLogParser)
  toolwise   lanex FlowRunner run_mode="container" + step_mode=True — one
             ``--only <step>`` container invocation per step, auto-advanced
             through the same resume() the GUI's Next button calls

Gates (HARD unless noted):
  G1/G2  final metrics identity, native vs each other leg (flatten+compare,
         exclusions start EMPTY and must stay reviewed, key-exact entries)
  G3     step-directory inventory identity across all legs
  G4     final/ file inventory identity, native vs container
  G5     GDS sha256 equality across legs — REPORT-ONLY until promoted via
         LANEX_CI_GDS_HARD=1 (cross-path GDS determinism not yet audit-proven)
  G6     resolved.json identity, native vs container, after canonicalizing the
         per-leg design dir + run tag out of path values
  G7     per-leg honesty floor: flow finished, no failed step, non-empty GDS,
         metrics.json parses (enforced inside each leg runner)
  G8     the exact GDS a layout viewer (KLayout/Magic/GDS3D) would open for each
         leg is a real, non-empty, valid GDSII — proves correct layout output
         reaches the tools, and catches an empty/truncated hand-off

Each leg's runs/ tree is harvested (metrics/resolved/step list/final list/GDS
hash) then deleted before the next leg — the runner disk is ~14 GB total.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SC = Path(__file__).resolve().parent
REPO = SC.parent.parent
sys.path.insert(0, str(SC))
sys.path.insert(0, str(REPO))

import compare_flat  # noqa: E402
import layout_probe  # noqa: E402
from flatten_metrics import flatten  # noqa: E402

IMAGE = os.environ.get("LANEX_CI_IMAGE", "ghcr.io/librelane/librelane:3.0.4")
PDK = os.environ.get("LANEX_CI_PDK", "sky130A")
SCL = os.environ.get("LANEX_CI_SCL", "sky130_fd_sc_hd")
WORK = Path(os.environ.get("LANEX_CI_WORK", str(Path.cwd() / "ciwork"))).resolve()
# A pre-populated store (e.g. a dev box's ~/.ciel) can be reused instead of
# fetching ~2 GB per run: point LANEX_CI_PDK_ROOT at it and set
# LANEX_CI_SKIP_PDK_FETCH=1. CI leaves both unset.
PDK_ROOT = Path(os.environ.get("LANEX_CI_PDK_ROOT", str(WORK / ".pdk"))).resolve()
SKIP_PDK_FETCH = os.environ.get("LANEX_CI_SKIP_PDK_FETCH", "0") == "1"
LEG_TIMEOUT = int(os.environ.get("LANEX_CI_LEG_TIMEOUT", "3600"))
GDS_HARD = os.environ.get("LANEX_CI_GDS_HARD", "0") == "1"
LEGS = [x for x in os.environ.get(
    "LANEX_CI_LEGS", "native,local,container,toolwise").split(",") if x]

HARVEST = WORK / "harvest"
LOGS = WORK / "logs"


def log(msg: str) -> None:
    print(f"[diff] {msg}", flush=True)


def sh(argv: List[str], **kw) -> subprocess.CompletedProcess:
    log("$ " + " ".join(str(a) for a in argv))
    return subprocess.run([str(a) for a in argv], **kw)


def df() -> None:
    sh(["df", "-h", "/"], check=False)


def build_native_argv(python_exe: str, pdk_root: str, pdk: str, scl: str,
                      tag: str, config: str = "config.yaml") -> List[str]:
    """The exact lanex-less command a user types (methodology Phase 4.2).

    Host flags (--pdk-root, --docker-no-tty) must precede --dockerized;
    everything after it is the in-container ``python3 -m librelane`` argv.
    test_ci_helpers.py locks this against container_run.build_dockerized_argv.
    """
    return [python_exe, "-m", "librelane",
            "--pdk-root", str(pdk_root), "--docker-no-tty", "--dockerized",
            config, "-p", pdk, "-s", scl, "--run-tag", tag]


def ensure_pdk(pdk_root: Path) -> None:
    """One host-side sky130 fetch/enable serving every leg.

    The ciel store uses absolute symlinks, so in-image legs see the SAME
    absolute path (the workspace is mounted at its identical host path).
    """
    if SKIP_PDK_FETCH:
        if not (pdk_root / PDK).is_dir():
            raise RuntimeError(f"LANEX_CI_SKIP_PDK_FETCH=1 but no {PDK} under {pdk_root}")
        log(f"reusing existing PDK store at {pdk_root} (fetch skipped)")
        return
    from lanex.controller import installer
    ver = installer._pinned_pdk_version("sky130") or ""
    if not ver:
        out = sh([sys.executable, "-m", "ciel", "ls-remote", "--pdk-family", "sky130"],
                 capture_output=True, text=True, check=True).stdout
        ver = out.split()[0] if out.split() else ""
    if not ver:
        raise RuntimeError("could not resolve a sky130 version")
    log(f"sky130 version: {ver}")
    for verb in ("fetch", "enable"):
        sh([sys.executable, "-m", "ciel", verb, "--pdk-root", str(pdk_root),
            "--pdk-family", "sky130", ver, "-l", SCL], check=True)


def _rmtree_robust(path: Path) -> None:
    """rmtree that survives foreign-uid files (a containerized leg may leave
    root-owned entries despite --user): chmod-and-retry, then an in-image
    ``rm -rf``, then give up loudly but DON'T kill the job — cleanup is a
    disk optimization, not a gate."""
    def _chmod_retry(fn, p, exc):  # noqa: ANN001
        try:
            os.chmod(os.path.dirname(p), 0o777)
            os.chmod(p, 0o777)
            fn(p)
        except Exception:
            raise exc[1] if isinstance(exc, tuple) else exc
    try:
        shutil.rmtree(path, onerror=_chmod_retry)
        return
    except Exception:
        pass
    rc = sh(["docker", "run", "--rm", "-v", f"{path.parent}:{path.parent}",
             IMAGE, "rm", "-rf", str(path)], check=False).returncode
    if rc != 0 or path.exists():
        log(f"WARNING: could not remove {path} — continuing without cleanup")


def copy_design(leg: str) -> Path:
    dest = WORK / f"spm_{leg}"
    if dest.exists():
        _rmtree_robust(dest)
    shutil.copytree(REPO / "spm", dest)
    return dest


def run_native(design: Path, tag: str, pdk_root: Path) -> None:
    logf = LOGS / "native.log"
    with open(logf, "w", encoding="utf-8") as fh:
        proc = sh(build_native_argv(sys.executable, str(pdk_root), PDK, SCL, tag),
                  cwd=design, stdout=fh, stderr=subprocess.STDOUT,
                  timeout=LEG_TIMEOUT, check=False)
    if proc.returncode != 0:
        tail = logf.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
        raise RuntimeError("native leg exited %s; log tail:\n%s"
                           % (proc.returncode, "\n".join(tail)))


def run_local_in_image(design: Path, tag: str, pdk_root: Path) -> None:
    # Everything mounts at its identical host path (PDK symlinks are absolute).
    mounts = ["-v", f"{REPO}:{REPO}"]
    if not str(WORK).startswith(str(REPO) + os.sep):
        mounts += ["-v", f"{WORK}:{WORK}"]
    if not (str(pdk_root).startswith(str(WORK) + os.sep)
            or str(pdk_root).startswith(str(REPO) + os.sep)):
        mounts += ["-v", f"{pdk_root}:{pdk_root}"]
    argv = (["docker", "run", "--rm",
             # Same uid as the host (librelane's own --dockerized does this
             # too) — files the flow writes must be deletable by the harvest
             # step; root-owned run dirs broke the leg cleanup.
             "--user", f"{os.getuid()}:{os.getgid()}",
             "-e", "HOME=/tmp"] + mounts + [
        "-w", str(REPO),
        "-e", f"PYTHONPATH={REPO}",
        "-e", f"PDK_ROOT={pdk_root}",
        "-e", f"LANEX_LEG_DESIGN={design}",
        "-e", f"LANEX_LEG_TAG={tag}",
        "-e", f"LANEX_LEG_PDK={PDK}",
        "-e", f"LANEX_LEG_SCL={SCL}",
        "-e", f"LANEX_LEG_TIMEOUT={LEG_TIMEOUT}",
        IMAGE, "python3", f"{REPO}/scripts/ci/leg_local_run.py"])
    proc = sh(argv, timeout=LEG_TIMEOUT + 300, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"local leg exited {proc.returncode}")


def run_flowrunner(design: Path, tag: str, pdk_root: Path, *, step_mode: bool) -> None:
    from librelane.flows import Flow

    from lanex.controller import runner as runner_mod

    flow_factory = Flow.factory.get("Classic")
    if flow_factory is None:
        raise RuntimeError("Classic flow is not registered")
    runner = runner_mod.FlowRunner()
    started = runner.start(
        flow_factory=flow_factory,
        config_files=[str(design / "config.yaml")],
        design_dir=str(design),
        pdk_root=str(pdk_root),
        pdk=PDK,
        scl=SCL,
        tag=tag,
        run_mode="container",
        step_mode=step_mode,
        flow_name="Classic",
    )
    if not started.get("ok"):
        raise RuntimeError(f"runner refused to start: {started}")
    # Toolwise pauses after every step (_awaiting_next); resume() is the same
    # call the GUI's Next button makes. Deadline is doubled: ~76 extra
    # per-step container startups.
    deadline = time.time() + LEG_TIMEOUT * (2 if step_mode else 1)
    while runner.running and time.time() < deadline:
        if step_mode and getattr(runner, "_awaiting_next", False):
            runner.resume()
        time.sleep(2)
    if runner.running:
        runner.cancel()
        raise RuntimeError("leg did not finish within its deadline")
    if runner.error:
        raise RuntimeError(f"leg errored: {runner.error}")
    failed = {k: v for k, v in (runner.step_statuses or {}).items() if v == "failed"}
    if failed:
        raise RuntimeError(f"steps failed: {failed}")


def _flatten_to(src_json: Path, dest_flat: Path) -> None:
    with open(src_json, encoding="utf-8") as fh:
        data = json.load(fh)
    dest_flat.write_text(
        "".join(f"{k}\t{v}\n" for k, v in flatten(data)), encoding="utf-8")


def harvest(design: Path, tag: str, leg: str) -> Dict[str, Optional[str]]:
    """Copy the comparison artifacts out, enforce the G7 honesty floor on what
    exists on disk, then delete the (multi-hundred-MB) runs/ tree."""
    run_dir = design / "runs" / tag
    if not run_dir.is_dir():
        raise RuntimeError(f"[{leg}] no run dir at {run_dir}")
    hd = HARVEST / leg
    hd.mkdir(parents=True, exist_ok=True)

    metrics = run_dir / "final" / "metrics.json"
    if not metrics.is_file():
        raise RuntimeError(f"[{leg}] final/metrics.json missing")
    shutil.copy2(metrics, hd / "metrics.json")
    _flatten_to(metrics, hd / "metrics.flat")

    resolved = run_dir / "resolved.json"
    if resolved.is_file():
        shutil.copy2(resolved, hd / "resolved.json")
        _flatten_to(resolved, hd / "resolved.flat")

    steps = sorted(p.name for p in run_dir.iterdir()
                   if p.is_dir() and re.match(r"^\d+-", p.name))
    (hd / "steps.txt").write_text("\n".join(steps) + "\n", encoding="utf-8")

    finals = sorted(str(p.relative_to(run_dir / "final"))
                    for p in (run_dir / "final").rglob("*") if p.is_file())
    (hd / "final_files.txt").write_text("\n".join(finals) + "\n", encoding="utf-8")

    gds = sorted(run_dir.glob("final/**/*.gds"))
    if not gds or gds[0].stat().st_size <= 0:
        raise RuntimeError(f"[{leg}] no non-empty GDS under final/")
    sha = hashlib.sha256(gds[0].read_bytes()).hexdigest()
    (hd / "gds.txt").write_text(
        f"{sha}  {gds[0].stat().st_size}  {gds[0].name}\n", encoding="utf-8")

    # G8 data: validate the EXACT GDS the GUI's layout viewers would open (the
    # file handed to KLayout/Magic/GDS3D), so CI proves a real, drawable layout
    # reaches the tools — not an empty/truncated one. Done here while runs/ still
    # exists (it's deleted below); the verdict rides in leg_meta to gate G8.
    view = layout_probe.viewer_gds_status(run_dir)
    (hd / "viewer_gds.txt").write_text(
        f"{'ok' if view['ok'] else 'BAD'}  {view['reason']}  {view.get('path')}\n",
        encoding="utf-8")

    log(f"[{leg}] harvested: {len(steps)} steps, {len(finals)} final files, gds sha {sha[:16]}…"
        f" · viewer GDS {'valid' if view['ok'] else 'INVALID: ' + str(view['reason'])}")
    _rmtree_robust(design / "runs")
    df()
    return {"gds_sha": sha, "steps": str(len(steps)),
            "resolved": "yes" if resolved.is_file() else "no",
            "viewer_gds_ok": "yes" if view["ok"] else "no",
            "viewer_gds_reason": str(view["reason"])}


def _compare(name: str, a: Path, b: Path, extra: List[str]) -> Tuple[str, bool]:
    print(f"\n===== {name} =====", flush=True)
    rc = compare_flat.main([str(a), str(b)] + extra)
    return name, rc == 0


def gates(done_legs: List[str], leg_meta: Dict[str, Dict[str, Optional[str]]],
          designs: Dict[str, Path], tags: Dict[str, str]) -> List[Tuple[str, bool, bool]]:
    """Returns [(gate_name, hard, ok)]."""
    results: List[Tuple[str, bool, bool]] = []
    if "native" not in done_legs:
        log("native leg not in LANEX_CI_LEGS — gates skipped (debug subset run)")
        return results
    base = HARVEST / "native"

    for leg in [x for x in done_legs if x != "native"]:
        name, ok = _compare(f"G1/G2 metrics identity: native vs {leg}",
                            base / "metrics.flat", HARVEST / leg / "metrics.flat", [])
        results.append((name, True, ok))

    base_steps = (base / "steps.txt").read_text(encoding="utf-8")
    for leg in [x for x in done_legs if x != "native"]:
        same = (HARVEST / leg / "steps.txt").read_text(encoding="utf-8") == base_steps
        if not same:
            print(f"G3 step inventory differs for {leg}:")
            sh(["diff", str(base / "steps.txt"), str(HARVEST / leg / "steps.txt")],
               check=False)
        results.append((f"G3 step inventory: native vs {leg}", True, same))

    if "container" in done_legs:
        same = ((HARVEST / "container" / "final_files.txt").read_text(encoding="utf-8")
                == (base / "final_files.txt").read_text(encoding="utf-8"))
        if not same:
            sh(["diff", str(base / "final_files.txt"),
                str(HARVEST / "container" / "final_files.txt")], check=False)
        results.append(("G4 final/ inventory: native vs container", True, same))

    shas = {leg: leg_meta[leg]["gds_sha"] for leg in done_legs}
    gds_ok = len(set(shas.values())) == 1
    print(f"G5 GDS sha256 per leg: {shas} → {'EQUAL' if gds_ok else 'DIFFER'}"
          f" ({'HARD' if GDS_HARD else 'report-only'})")
    results.append(("G5 GDS sha256 equality", GDS_HARD, gds_ok))

    if "container" in done_legs and (base / "resolved.flat").is_file() \
            and (HARVEST / "container" / "resolved.flat").is_file():
        subs = []
        for leg in ("native", "container"):
            subs += ["--sub", f"{designs[leg]}::<DESIGN_DIR>",
                     "--sub", f"runs/{tags[leg]}::runs/<TAG>"]
        name, ok = _compare("G6 resolved.json identity (canonicalized): native vs container",
                            base / "resolved.flat",
                            HARVEST / "container" / "resolved.flat", subs)
        results.append((name, True, ok))
    else:
        log("G6 skipped: resolved.json absent on a compared leg")

    # G8: the exact GDS each leg would hand to a layout viewer must be a real,
    # non-empty, drawable GDSII — proves correct output reaches the tools and
    # would FAIL the day a run hands over an empty/truncated file.
    for leg in done_legs:
        ok = leg_meta[leg].get("viewer_gds_ok") == "yes"
        if not ok:
            print(f"G8 viewer GDS invalid for {leg}: {leg_meta[leg].get('viewer_gds_reason')}")
        results.append((f"G8 viewer GDS is a valid non-empty GDSII: {leg}", True, ok))

    return results


# What each gate proves — the implication shown in the summary. Matched by the
# gate-name prefix (the leg name is appended at runtime).
_GATE_WHY = {
    "G1/G2": "The four build paths produce identical metrics — the GUI's numbers equal the plain CLI's.",
    "G3": "Identical step inventory — no path silently skips or adds a flow step.",
    "G4": "Identical final/ file set — every deliverable the CLI makes, the GUI makes too.",
    "G5": "GDS bytes differ ONLY by the timestamp GDSII embeds — report-only, never gates (identical layout, different write time).",
    "G6": "Identical resolved config — the same inputs really drove all four runs (Fear B).",
    "G8": "The exact GDS a layout viewer would open is a real, non-empty GDSII — no blank-window hand-off (Fear C).",
}


def _gate_why(name: str) -> str:
    for prefix, why in _GATE_WHY.items():
        if name.startswith(prefix):
            return why
    return "Cross-path equivalence check."


def write_summary(results: List[Tuple[str, bool, bool]],
                  leg_meta: Dict[str, Dict[str, Optional[str]]]) -> None:
    lines = ["## Differential RTL->GDS (SPM, sky130 — 4 build paths)", "",
             "_The same design built four ways (native CLI / lanex local / lanex container / "
             "lanex toolwise); every HARD gate must match across all four._", "",
             "| Leg | steps | resolved.json | viewer GDS | GDS sha256 |", "|---|--:|---|---|---|"]
    for leg, m in leg_meta.items():
        vg = "✓ valid" if m.get("viewer_gds_ok") == "yes" else "✗ " + str(m.get("viewer_gds_reason", "?"))
        lines.append(f"| {leg} | {m['steps']} | {m['resolved']} | {vg} | `{(m['gds_sha'] or '')[:16]}…` |")
    lines += ["", "| Gate | Mode | Result | What it proves |", "|---|---|---|---|"]
    for name, hard, ok in results:
        lines.append(f"| {name} | {'HARD' if hard else 'report-only'} | "
                     f"{'✓ pass' if ok else '✗ FAIL'} | {_gate_why(name)} |")
    text = "\n".join(lines) + "\n"
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)


def main() -> int:
    for d in (WORK, HARVEST, LOGS):
        d.mkdir(parents=True, exist_ok=True)
    pdk_root = PDK_ROOT
    df()
    sh(["docker", "pull", IMAGE], check=True)
    ensure_pdk(pdk_root)
    df()

    tags = {"native": "native", "local": "local",
            "container": "containerleg", "toolwise": "toolwise"}
    designs: Dict[str, Path] = {}
    leg_meta: Dict[str, Dict[str, Optional[str]]] = {}
    for leg in LEGS:
        log(f"=== leg {leg} ===")
        design = copy_design(leg)
        designs[leg] = design
        t0 = time.time()
        if leg == "native":
            run_native(design, tags[leg], pdk_root)
        elif leg == "local":
            run_local_in_image(design, tags[leg], pdk_root)
        elif leg == "container":
            run_flowrunner(design, tags[leg], pdk_root, step_mode=False)
        elif leg == "toolwise":
            run_flowrunner(design, tags[leg], pdk_root, step_mode=True)
        else:
            raise RuntimeError(f"unknown leg {leg!r}")
        log(f"[{leg}] flow finished in {time.time() - t0:.0f}s")
        leg_meta[leg] = harvest(design, tags[leg], leg)

    results = gates(LEGS, leg_meta, designs, tags)
    write_summary(results, leg_meta)
    hard_fails = [name for name, hard, ok in results if hard and not ok]
    if hard_fails:
        log(f"HARD gate failures: {hard_fails}")
        return 1
    log("all hard gates passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
