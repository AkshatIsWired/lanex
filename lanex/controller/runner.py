# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Drive a flow in a worker thread; stream real per-step events to a queue.

The :class:`FlowRunner` bridges LibreLane's synchronous ``flow.start()`` and
the SSE world used by the SPA. It exposes:

* a ``start()`` that returns immediately once the worker thread is up,
* an in-memory event queue the SSE handler drains,
* **cooperative cancel** that aborts cleanly at the next step boundary (and
  kills any EDA subprocess that is currently executing), and
* **live per-step status** by wrapping LibreLane's own ``FlowProgressBar``,
  so the pipeline view lights up green/red exactly as the engine advances.

The per-step status is obtained without parsing logs: LibreLane's
``SequentialFlow.run`` calls ``progress_bar.start_stage()`` /
``end_stage()`` once per step in ``flow.Steps`` order. We wrap those methods
for the duration of a run and correlate each call with the corresponding
``Step.id`` by ordinal.
"""
from __future__ import annotations

import logging
import os
import queue
import shutil
import subprocess
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .container_run import (
    ContainerLogParser,
    build_dockerized_argv,
    is_progress_bar,
    strip_ansi,
)
from .events import bus
from .models import EventType, StepStatus

_log = logging.getLogger("librelane.gui.runner")


class _Cancelled(Exception):
    """Raised at a step boundary to abort a flow that the user cancelled."""


# The currently-active runner, referenced by the FlowProgressBar wrappers.
# Only one flow runs per server process at a time (``start`` guards this), so a
# module global is safe and avoids depending on librelane internals threading a
# reference through to the progress bar.
_ACTIVE_RUNNER: "Optional[FlowRunner]" = None
_PATCH_LOCK = threading.Lock()
_ORIG_PROGRESS: Dict[str, Any] = {}


def _safe_jsonable(value: Any) -> Any:
    from .models import to_json

    return to_json(value)


def _toolchain_provenance(run_mode: Optional[str]) -> Dict[str, Any]:
    """Identity of the toolchain that produced a run, recorded into gui-run.json.

    Answers the one question a metric alone cannot: *would I get the same numbers
    if I ran this manually?* — which depends entirely on the versions of LanEx,
    LibreLane, and (in container mode) the exact image the flow executed in.
    Without this stamp an exported/reproduced run is un-auditable across time or
    machines. Best-effort: every field degrades to ``"unknown"`` and this never
    raises (a failure here must not derail persisting the rest of the meta)."""
    tc: Dict[str, Any] = {"run_mode": run_mode or "local"}
    try:
        from . import compat
        tc["librelane_version"] = compat.get_version()
    except Exception:
        tc["librelane_version"] = "unknown"
    try:
        from .. import _version as _lanex_version
        tc["lanex_version"] = _lanex_version.get_version()
    except Exception:
        tc["lanex_version"] = "unknown"
    if (run_mode or "local") == "container":
        # The image tag is version-pinned to the installed librelane, so it names
        # the exact tool set the flow ran inside (container_run.image_ref()).
        try:
            from . import container_run
            tc["image"] = container_run.image_ref()
        except Exception:
            tc["image"] = "unknown"
    return tc


def _relativize_to(paths: Optional[Sequence[str]], base: Path) -> List[str]:
    """Return each path relative to *base* when it lives under it; otherwise keep
    it unchanged. Used for VERILOG_FILES/EXTRA_FILES so they resolve inside the
    container (cwd = mounted design dir) and don't break on a space in *base*."""
    out: List[str] = []
    for p in (paths or []):
        if not p:
            continue
        try:
            rp = Path(p)
            if rp.is_absolute():
                rp = rp.resolve()
                rel = rp.relative_to(base)
                out.append(str(rel))
                continue
        except Exception:
            pass
        out.append(str(p))
    return out


def _containers_mounting(engine: str, design_dir: str) -> List[str]:
    """IDs of running containers executing a flow on *design_dir*.

    The cancel path uses this to find the LibreLane container when its name is
    unknown (librelane 3.0.4 never echoes the ``--name`` it generates). Two
    signals identify this run's container, either suffices:

    - a bind mount whose Source IS the design dir (librelane mounts the design
      dir itself when it lies outside the home tree, e.g. under /tmp);
    - the container's ``Config.WorkingDir`` == the design dir. This is the one
      that fires in the COMMON layout: for a design under the user's home,
      librelane mounts the whole home directory (Mounts shows ``/home/user``,
      never the design dir), so a mount-only match silently finds nothing and
      a "cancelled" flow keeps running — proven live. The workdir is set to
      the design dir in every ``--dockerized`` invocation and pins exactly
      this design, so the match stays surgical.
    """
    try:
        ps = subprocess.run(
            [engine, "ps", "-q"], capture_output=True, text=True, timeout=10
        )
        ids = ps.stdout.split()
    except Exception:  # pragma: no cover - engine/platform dependent
        return []
    want = None
    try:
        want = Path(design_dir).resolve()
    except Exception:
        return []
    matches: List[str] = []
    for cid in ids:
        try:
            ins = subprocess.run(
                [engine, "inspect", "--format",
                 "{{.Config.WorkingDir}}\t{{json .Mounts}}", cid],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            workdir, _, mounts_json = ins.partition("\t")
            if workdir and want in (Path(workdir), Path(workdir).resolve()):
                matches.append(cid)
                continue
            import json as _json
            mounts = _json.loads(mounts_json) if mounts_json else []
            for m in mounts or []:
                src = str((m or {}).get("Source", ""))
                if src and Path(src).resolve() == want:
                    matches.append(cid)
                    break
        except Exception:
            continue
    return matches


def _install_progress_patch() -> None:
    """Wrap FlowProgressBar methods so step transitions emit SSE events.

    Idempotent and reference-counted via ``_ORIG_PROGRESS``. The wrappers call
    the active runner (if any) and then defer to the original implementation so
    LibreLane's own terminal progress bar keeps working.
    """
    with _PATCH_LOCK:
        if _ORIG_PROGRESS:
            return
        try:
            from librelane.flows.flow import FlowProgressBar
        except Exception:  # pragma: no cover - librelane missing
            return

        orig_set_max = FlowProgressBar.set_max_stage_count
        orig_start = FlowProgressBar.start_stage
        orig_end = FlowProgressBar.end_stage
        _ORIG_PROGRESS.update(
            {"set_max": orig_set_max, "start": orig_start, "end": orig_end, "cls": FlowProgressBar}
        )

        def set_max_stage_count(self: Any, count: int):
            r = _ACTIVE_RUNNER
            if r is not None:
                r._on_set_max(count)
            return orig_set_max(self, count)

        def start_stage(self: Any, name: str):
            r = _ACTIVE_RUNNER
            if r is not None:
                r._on_stage_start(name)  # may raise _Cancelled to abort the flow
            return orig_start(self, name)

        def end_stage(self: Any, *args: Any, **kwargs: Any):
            r = _ACTIVE_RUNNER
            if r is not None:
                r._on_stage_end(kwargs.get("increment_ordinal", True))
            return orig_end(self, *args, **kwargs)

        FlowProgressBar.set_max_stage_count = set_max_stage_count  # type: ignore[assignment]
        FlowProgressBar.start_stage = start_stage  # type: ignore[assignment]
        FlowProgressBar.end_stage = end_stage  # type: ignore[assignment]


class FlowRunner:
    """One-shot async driver for a configured flow.

    A second ``start()`` is refused while the first is running.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._seq = 0
        self._events: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=10000)
        self._cancel = threading.Event()
        self._resume = threading.Event()
        self._resume.set()  # not paused
        self._state_out: Any = None
        self._run_dir: Optional[str] = None
        self._worker: Optional[threading.Thread] = None
        self._running = False
        self._error: Optional[str] = None
        self._step_statuses: Dict[str, str] = {}
        # progress bookkeeping
        self._flow: Any = None
        self._stage_idx = -1
        self._stage_total = 0
        self._current_step_id: Optional[str] = None
        self._step_mode = False
        # ETA bookkeeping: per-step start time + this run's observed durations,
        # combined with the learned per-step history for a live "time remaining".
        self._step_start_ts: Optional[float] = None
        self._observed_durations: List[float] = []
        self._run_start_ts: Optional[float] = None
        # container run mode bookkeeping
        self._run_mode = "local"
        self._flow_name: Optional[str] = None
        self._container_proc: Optional[subprocess.Popen] = None
        self._container_name: Optional[str] = None
        # container step-by-step bookkeeping: one `--only <step>` container
        # invocation per step, resuming the same run tag. ``_cstep`` holds the
        # ordered step ids + the saved invocation args; ``_awaiting_next`` is set
        # between steps (the runner stays "running" but no subprocess is live).
        self._cstep: Dict[str, Any] = {}
        self._awaiting_next = False
        # GUI run settings to persist into the run dir for reproducibility
        # (issue #4). Written once, the first time the run dir is known.
        self._gui_meta: Optional[Dict[str, Any]] = None
        self._gui_meta_written = False

    # ---------------------------------------------------------------- lifecycle

    @property
    def running(self) -> bool:
        return self._running

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    @property
    def run_dir(self) -> Optional[str]:
        return self._run_dir

    @property
    def step_statuses(self) -> Dict[str, str]:
        return dict(self._step_statuses)

    def cancel(self) -> None:
        """Request a stop. The worker aborts at the next step boundary.

        We also terminate any EDA subprocess currently executing so a long
        OpenROAD/Magic call is interrupted instead of running to completion.

        Note: we deliberately do **not** delete the run directory — partial
        results are often exactly what the user wants to inspect.
        """
        self._cancel.set()
        self._resume.set()  # unblock a paused worker so it can see the cancel
        self._emit(EventType.INFO, {"message": "cancel requested — stopping after the current step"})
        self._kill_child_processes()
        self._kill_container()
        # Container step-by-step paused between steps: no live process to kill, so
        # finalize the run here (otherwise it'd hang "running" forever).
        if self._awaiting_next:
            self._awaiting_next = False
            self._running = False
            self._emit(EventType.INFO, {"message": "flow cancelled by user"})
            self._emit(EventType.FLOW_DONE, {"tag": self._run_dir or "", "cancelled": True})

    def _kill_container(self) -> None:
        """Force-remove this run's LibreLane container, if one is running.

        Killing the host-side processes is NOT enough: terminating the
        ``docker run`` client does not stop the container, and the in-container
        librelane runs as PID 1, which ignores an unhandled SIGTERM — so a
        "cancelled" containerized flow kept executing to completion (proven
        live). Two removal paths, both best-effort and cross-engine:

        - By NAME, when the log parser captured librelane's ``docker run --rm
          --name <uuid>`` echo. LibreLane 3.0.4 does not print that line (its
          stdout shows only "Running containerized command:"), so the name is
          usually unknown.
        - By MOUNT DISCOVERY otherwise: list running containers and force-remove
          any that bind-mount this run's design directory. Matching on the
          design-dir mount keeps this surgical — a container belonging to a
          different design (or a different tool entirely) can never match.
        """
        proc = self._container_proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        engines = [e for e in (shutil.which("docker"), shutil.which("podman")) if e]
        if not engines:
            return
        name = self._container_name
        for engine in engines:
            if name:
                try:
                    subprocess.run(
                        [engine, "rm", "-f", name],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                    )
                except Exception:  # pragma: no cover - engine/platform dependent
                    pass
            design_dir = self._design_dir_of_run()
            if not design_dir:
                continue
            for cid in _containers_mounting(engine, design_dir):
                try:
                    subprocess.run(
                        [engine, "rm", "-f", cid],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                    )
                except Exception:  # pragma: no cover - engine/platform dependent
                    pass

    def _design_dir_of_run(self) -> Optional[str]:
        """The design dir this run mounts (parent of ``runs/<tag>``), resolved.

        ``_run_dir`` is assigned before the container subprocess is spawned, so
        this is available for the whole window a container could exist in.
        """
        if not self._run_dir:
            return None
        try:
            p = Path(self._run_dir).resolve()
            return str(p.parent.parent) if p.parent.name == "runs" else str(p.parent)
        except Exception:
            return None

    def _kill_child_processes(self) -> None:
        """Best-effort, cross-platform termination of EDA subprocesses."""
        try:
            import psutil  # librelane depends on psutil, so this is always present

            me = psutil.Process()
            children = me.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except Exception:
                    pass
            gone, alive = psutil.wait_procs(children, timeout=3)
            for child in alive:
                try:
                    child.kill()
                except Exception:
                    pass
        except Exception as ex:  # pragma: no cover - platform dependent
            self._emit(EventType.INFO, {"message": f"could not terminate subprocesses: {ex}"})

    def resume(self) -> None:
        # Container step-by-step: "Resume"/"Next" launches the next single-step
        # container invocation rather than releasing an in-process Event (there
        # is no live process to release between steps).
        if self._run_mode == "container" and self._step_mode and self._awaiting_next:
            self._advance_container_step()
            return
        self._resume.set()
        self._emit(EventType.INFO, {"message": "resumed"})

    @property
    def error(self) -> Optional[str]:
        """The last run's error string (``None`` on success/clean cancel).

        Public so callers like the DSE queue can tell a failed run from a
        successful one without reaching into a private attribute."""
        return self._error

    def drain(self, *, block: bool = True, timeout: float = 0.5) -> List[Dict[str, Any]]:
        """Pop the events this runner has buffered.

        SSE no longer uses this — it reads the shared :data:`events.bus` ring
        non-destructively so multiple clients can coexist. This remains for
        in-process callers/tests that want just this runner's emissions.
        """
        out: List[Dict[str, Any]] = []
        deadline = time.time() + timeout
        while True:
            try:
                ev = self._events.get(block=block, timeout=max(0.001, deadline - time.time()))
                out.append(ev)
            except queue.Empty:
                break
        return out

    # --------------------------------------------------------------- start/stop

    def start(
        self,
        *,
        flow_factory: Any,
        config_files: Sequence[str],
        design_dir: str | Path,
        pdk_root: Optional[str] = None,
        pdk: Optional[str] = None,
        scl: Optional[str] = None,
        pad: Optional[str] = None,
        tag: Optional[str] = None,
        frm: Optional[str] = None,
        to: Optional[str] = None,
        skip: Optional[Iterable[str]] = None,
        overwrite: bool = False,
        reproducible_step: Optional[str] = None,
        config_overrides: Optional[Dict[str, Any]] = None,
        extra_sources: Optional[Sequence[str]] = None,
        extra_extras: Optional[Sequence[str]] = None,
        extra_config_files: Optional[Sequence[str]] = None,
        step_mode: bool = False,
        run_mode: str = "local",
        flow_name: Optional[str] = None,
        last_run: bool = False,
        gui_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Spawn the worker. Returns ``{"ok": bool, "reason": str}``.

        ``run_mode`` selects the engine: ``"local"`` drives LibreLane in-process
        (per-step status via the FlowProgressBar patch); ``"container"`` shells
        out to ``librelane --dockerized`` and parses its stdout. Step-by-step
        pausing is only available in local mode (there is no in-process hook
        across the container boundary).
        """
        # Source/extra paths go into VERILOG_FILES / EXTRA_FILES, which LibreLane
        # parses as WHITESPACE-separated. Host-absolute paths (a) don't exist
        # inside the container and (b) corrupt the list when the design dir has a
        # space (e.g. "…/processor codes/control.v" → two bogus paths). Both are
        # fixed by making each source relative to the design dir (= the flow base
        # / container cwd): "control.v" resolves everywhere and has no space.
        _dd = Path(design_dir).resolve()
        extra_sources = _relativize_to(extra_sources, _dd)
        extra_extras = _relativize_to(extra_extras, _dd)

        with self._lock:
            if self._running:
                return {"ok": False, "reason": "already running"}
            self._reset()
            self._running = True
            self._run_mode = "container" if run_mode == "container" else "local"
            self._flow_name = flow_name
            self._gui_meta = dict(gui_meta) if gui_meta else None
            # Step-by-step works in BOTH modes: local pauses the in-process flow
            # between steps; container runs one `--only <step>` invocation per
            # step, resuming the same run tag (see _run_container_stepwise).
            self._step_mode = bool(step_mode)
            self._cancel.clear()
            self._resume.set()
            if self._run_mode == "container" and self._step_mode:
                worker_target = self._run_container_stepwise
            elif self._run_mode == "container":
                worker_target = self._run_container
            else:
                worker_target = self._run
            self._worker = threading.Thread(
                target=worker_target,
                args=(flow_factory, list(config_files), Path(design_dir).resolve()),
                kwargs={
                    "pdk_root": pdk_root,
                    "pdk": pdk,
                    "scl": scl,
                    "pad": pad,
                    "tag": tag,
                    "frm": frm,
                    "to": to,
                    "skip": list(skip) if skip is not None else None,
                    "overwrite": overwrite,
                    "reproducible_step": reproducible_step,
                    "config_overrides": config_overrides or {},
                    "extra_sources": list(extra_sources or []),
                    "extra_extras": list(extra_extras or []),
                    "extra_config_files": list(extra_config_files or []),
                    "last_run": last_run,
                },
                daemon=True,
                name="librelane.gui.FlowRunner.worker",
            )
            self._worker.start()
        return {"ok": True, "reason": "started"}

    def _reset(self) -> None:
        with self._lock:
            # NOTE: deliberately do NOT reset the sequence counter. Event seq is
            # process-global + monotonic (see events.next_seq) so a reconnecting
            # browser EventSource doesn't drop the next run's events as "already
            # seen" via a stale Last-Event-ID.
            try:
                while not self._events.empty():
                    self._events.get_nowait()
            except queue.Empty:
                pass
            self._state_out = None
            self._run_dir = None
            self._error = None
            self._step_statuses = {}
            self._flow = None
            self._stage_idx = -1
            self._stage_total = 0
            self._current_step_id = None
            self._container_proc = None
            self._container_name = None
            self._cstep = {}
            self._awaiting_next = False
            self._gui_meta_written = False

    # --------------------------------------------------------------- worker body

    def _emit(self, kind: EventType, payload: Optional[Dict[str, Any]] = None) -> None:
        seq = self._next_seq()
        body = _safe_jsonable(payload) if payload else {}
        tag = Path(self._run_dir).name if self._run_dir else None
        evt = {"type": kind.value, "seq": seq, "ts": time.time(), "tag": tag, **body}
        try:
            self._events.put_nowait(evt)
        except queue.Full:
            try:
                self._events.get_nowait()
                self._events.put_nowait(evt)
            except queue.Empty:
                pass
        bus.emit(kind.value, {**body, "seq": seq, "ts": evt["ts"], "tag": tag})

    def _next_seq(self) -> int:
        from .events import next_seq

        return next_seq()

    def _persist_gui_meta(self) -> None:
        """Write the GUI's run settings into the run dir as ``gui-run.json`` so a
        run can be reproduced from the GUI later (issue #4). Idempotent + best
        effort — a failure here must never derail the flow. LibreLane already
        writes the resolved ``config.json``; this adds the GUI-only context
        (preset/overrides as set, run mode, from/to/skip, sources, the CLI line)."""
        if self._gui_meta_written or not self._gui_meta or not self._run_dir:
            return
        try:
            run_dir = Path(self._run_dir)
            if not run_dir.is_dir():
                return
            meta = dict(self._gui_meta)
            meta.setdefault("tag", run_dir.name)
            meta["run_dir"] = str(run_dir)
            meta["written_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            # Stamp the toolchain identity (LanEx/LibreLane versions + container
            # image) so an export or reproduce can prove which tools produced
            # these numbers — the "would I get the same manually?" contract.
            meta.setdefault("toolchain", _toolchain_provenance(self._run_mode))
            import json as _json

            from . import platform_env
            platform_env.atomic_write_text(
                run_dir / "gui-run.json",
                _json.dumps(_safe_jsonable(meta), indent=2) + "\n",
            )
            self._gui_meta_written = True
        except Exception:  # pragma: no cover - fs/permission dependent
            _log.debug("could not persist gui-run.json", exc_info=True)
            self._gui_meta_written = True  # don't retry every step

    # ---- progress hooks (called from the patched FlowProgressBar) ----

    def _on_set_max(self, count: int) -> None:
        self._stage_total = int(count)
        self._emit(EventType.PROGRESS, {"done": 0, "total": self._stage_total, "current": ""})

    def _step_id_for_index(self, idx: int) -> Optional[str]:
        steps = list(getattr(self._flow, "Steps", []) or [])
        if 0 <= idx < len(steps):
            return steps[idx].id
        return None

    def _eta_payload(self) -> Dict[str, Any]:
        """``{eta_seconds, elapsed_seconds}`` for the live progress bar.

        ETA = estimated time for the steps not yet done (learned per-step history
        + this run's observed average). ``None`` when nothing can be estimated.
        """
        out: Dict[str, Any] = {"eta_seconds": None, "elapsed_seconds": None}
        if self._run_start_ts is not None:
            out["elapsed_seconds"] = round(time.time() - self._run_start_ts, 1)
        try:
            from . import runtimings
            all_ids = [s.id for s in (getattr(self._flow, "Steps", []) or [])]
            done = {sid for sid, st in self._step_statuses.items()
                    if st in (StepStatus.DONE.value, StepStatus.SKIPPED.value)}
            remaining = [sid for sid in all_ids if sid not in done]
            out["eta_seconds"] = runtimings.estimate_remaining(remaining, self._observed_durations)
        except Exception:
            pass
        return out

    def _on_stage_start(self, name: str) -> None:
        # Honour pause between steps, then check for cancellation.
        if not self._resume.is_set():
            self._emit(EventType.INFO, {"message": "paused — click Resume to continue"})
            self._resume.wait()
        if self._cancel.is_set():
            raise _Cancelled()

        # The flow assigns its run directory before the first step executes;
        # capture it now so the UI and cancel logic have it mid-run.
        if not self._run_dir:
            rd = getattr(self._flow, "run_dir", None)
            if rd:
                self._run_dir = str(rd)
        self._persist_gui_meta()
        if self._run_start_ts is None:
            self._run_start_ts = time.time()
        self._step_start_ts = time.time()
        self._stage_idx += 1
        step_id = self._step_id_for_index(self._stage_idx) or name
        self._current_step_id = step_id
        self._step_statuses[step_id] = StepStatus.RUNNING.value
        self._emit(
            EventType.STEP_STARTED,
            {
                "step_id": step_id,
                "name": name,
                "index": self._stage_idx,
                "total": self._stage_total,
            },
        )
        self._emit(
            EventType.PROGRESS,
            {"done": self._stage_idx, "total": self._stage_total, "current": step_id,
             **self._eta_payload()},
        )

    def _on_stage_end(self, increment_ordinal: bool) -> None:
        step_id = self._current_step_id
        if step_id is None:
            return
        # Learn this step's duration (only for genuinely executed, non-skipped
        # steps) so future runs get a sharper ETA.
        if increment_ordinal and self._step_start_ts is not None:
            dur = time.time() - self._step_start_ts
            if dur >= 0:
                self._observed_durations.append(dur)
                try:
                    from . import runtimings
                    runtimings.record(step_id, dur)
                except Exception:
                    pass
        self._step_start_ts = None
        if increment_ordinal:
            self._step_statuses[step_id] = StepStatus.DONE.value
            self._emit(EventType.STEP_DONE, {"step_id": step_id, "index": self._stage_idx})
        else:
            self._step_statuses[step_id] = StepStatus.SKIPPED.value
            self._emit(EventType.STEP_SKIPPED, {"step_id": step_id, "index": self._stage_idx})
        self._current_step_id = None
        done = sum(
            1 for s in self._step_statuses.values() if s in (StepStatus.DONE.value, StepStatus.SKIPPED.value)
        )
        self._emit(EventType.PROGRESS, {"done": done, "total": self._stage_total, "current": "",
                                        **self._eta_payload()})
        # Step-by-step mode: hold the flow after each executed step so the user
        # can inspect results, then resume to advance to the next step.
        if self._step_mode and increment_ordinal and not self._cancel.is_set():
            self._resume.clear()
            self._emit(
                EventType.INFO,
                {"message": f"step '{step_id}' complete — click Resume for the next step", "paused": True},
            )

    # ---- flow execution ----

    def _run(
        self,
        flow_factory: Any,
        config_files: Sequence[str],
        design_dir: Path,
        *,
        pdk_root: Optional[str],
        pdk: Optional[str],
        scl: Optional[str],
        pad: Optional[str],
        tag: Optional[str],
        frm: Optional[str],
        to: Optional[str],
        skip: Optional[List[str]],
        overwrite: bool,
        reproducible_step: Optional[str],
        config_overrides: Dict[str, Any],
        extra_sources: Optional[List[str]],
        extra_extras: Optional[List[str]],
        extra_config_files: Optional[List[str]] = None,
        last_run: bool = False,
    ) -> None:
        global _ACTIVE_RUNNER
        self._setup_log_bridge()
        _install_progress_patch()
        _ACTIVE_RUNNER = self
        try:
            self._emit(EventType.INFO, {"message": f"loading flow (config={list(config_files)})"})

            # Build the Flow with construction-time options. PDK/SCL/PAD/PDK_ROOT
            # and config overrides MUST go to the constructor — the engine reads
            # them when it loads the configuration, not at flow.start().
            override_strings = [f"{k}={v}" for k, v in (config_overrides or {}).items()]
            if extra_sources:
                # LibreLane parses list overrides as whitespace-separated paths.
                override_strings.append("VERILOG_FILES=" + " ".join(extra_sources))
            if extra_extras:
                override_strings.append("EXTRA_FILES=" + " ".join(extra_extras))

            ctor_kwargs: Dict[str, Any] = {"design_dir": str(design_dir)}
            for key, val in (("pdk_root", pdk_root), ("pdk", pdk), ("scl", scl), ("pad", pad)):
                if val:
                    ctor_kwargs[key] = val
            if override_strings:
                ctor_kwargs["config_override_strings"] = override_strings

            # Append any GUI-generated overlay configs (e.g. the custom-macro
            # MACROS overlay). Config.load merges a sequence of config sources, so
            # the overlay augments the user's config without a -c string (a Dict
            # variable can't round-trip through a KEY=VALUE override).
            all_configs = list(config_files) + list(extra_config_files or [])
            flow = flow_factory(all_configs, **ctor_kwargs)
            self._flow = flow
            self._seed_step_graph(flow)

            self._emit(
                EventType.INFO,
                {
                    "message": "starting flow",
                    "flow": getattr(flow, "name", "flow"),
                    "tag": tag,
                    "frm": frm,
                    "to": to,
                    "skip": skip,
                    "reproducible": reproducible_step,
                },
            )

            start_kwargs: Dict[str, Any] = {
                "tag": tag,
                "overwrite": overwrite,
                "with_initial_state": None,
            }
            # Continue a prior run's state (targeted re-verify of a single step).
            # Without this, a local ``-F step -T step`` has no input state and
            # the step has nothing to operate on. Container mode resumes via
            # ``--run-tag`` so it doesn't need this.
            if last_run:
                start_kwargs["last_run"] = True
            # frm/to/skip/reproducible are consumed by SequentialFlow.run via
            # **kwargs; only pass the ones that were actually requested.
            if frm:
                start_kwargs["frm"] = frm
            if to:
                start_kwargs["to"] = to
            if skip:
                start_kwargs["skip"] = tuple(skip)
            if reproducible_step:
                start_kwargs["reproducible"] = reproducible_step

            state_out = flow.start(**start_kwargs)
            self._state_out = state_out
            self._run_dir = flow.run_dir
            self._persist_gui_meta()  # covers fast runs that skip the step hook
            self._emit(
                EventType.FLOW_DONE,
                {"tag": flow.run_dir, "metrics": (getattr(state_out, "metrics", {}) or {})},
            )
        except _Cancelled:
            self._run_dir = getattr(self._flow, "run_dir", None) or self._run_dir
            self._mark_current_failed("cancelled")
            self._mark_remaining_aborted()
            self._emit(EventType.INFO, {"message": "flow cancelled by user"})
            self._emit(EventType.FLOW_DONE, {"tag": self._run_dir or "", "cancelled": True})
        except Exception as ex:
            tb = traceback.format_exc()
            self._run_dir = getattr(self._flow, "run_dir", None) or self._run_dir
            self._error = f"{type(ex).__name__}: {ex}"
            self._mark_current_failed(str(ex))
            self._emit(
                EventType.STEP_FAILED,
                {
                    "step_id": self._current_step_id,
                    "message": str(ex),
                    "traceback": tb[-4000:],
                    "cancelled": self._cancel.is_set(),
                },
            )
            self._mark_remaining_aborted()
            self._emit(EventType.FLOW_DONE, {"tag": self._run_dir or "", "error": self._error})
        finally:
            self._running = False
            _ACTIVE_RUNNER = None
            self._teardown_log_bridge()

    # ---- container execution ----

    _PARSED_EVENT_TYPES = {
        "step_started": EventType.STEP_STARTED,
        "step_done": EventType.STEP_DONE,
        "step_skipped": EventType.STEP_SKIPPED,
        "step_failed": EventType.STEP_FAILED,
        "progress": EventType.PROGRESS,
        "flow_done": EventType.FLOW_DONE,
    }
    _PARSED_STATUS = {
        "step_started": StepStatus.RUNNING,
        "step_done": StepStatus.DONE,
        "step_skipped": StepStatus.SKIPPED,
        "step_failed": StepStatus.FAILED,
    }

    def _dispatch_parsed(self, ev: Dict[str, Any]) -> None:
        """Translate a :class:`ContainerLogParser` event into an SSE emit."""
        t = ev.get("type")
        if t == "container":
            self._container_name = ev.get("name")
            return
        if t == "phase":
            self._emit(EventType.PHASE, {"label": ev.get("label", "")})
            return
        sid = ev.get("step_id")
        if t in self._PARSED_STATUS and sid:
            self._step_statuses[sid] = self._PARSED_STATUS[t].value
            if t == "step_started":
                self._current_step_id = sid
            elif t in ("step_done", "step_skipped"):
                if self._current_step_id == sid:
                    self._current_step_id = None
        kind = self._PARSED_EVENT_TYPES.get(t)
        if kind is None:
            return
        payload = {k: v for k, v in ev.items() if k != "type"}
        self._emit(kind, payload)

    def _run_container(
        self,
        flow_factory: Any,
        config_files: Sequence[str],
        design_dir: Path,
        *,
        pdk_root: Optional[str],
        pdk: Optional[str],
        scl: Optional[str],
        pad: Optional[str],
        tag: Optional[str],
        frm: Optional[str],
        to: Optional[str],
        skip: Optional[List[str]],
        overwrite: bool,
        reproducible_step: Optional[str],
        config_overrides: Dict[str, Any],
        extra_sources: Optional[List[str]],
        extra_extras: Optional[List[str]],
        extra_config_files: Optional[List[str]] = None,
        last_run: bool = False,  # container resumes via --run-tag; accepted for signature parity
    ) -> None:
        """Shell out to ``librelane --dockerized`` and stream/parse its stdout."""
        try:
            if not config_files:
                raise ValueError("no config file to run")
            # We set --run-tag ourselves so the run dir is known up front.
            if not tag:
                tag = time.strftime("glui-%Y%m%d-%H%M%S")
            self._run_dir = str(design_dir / "runs" / tag)

            step_ids: List[str] = []
            try:
                for cls in getattr(flow_factory, "Steps", []) or []:
                    step_ids.append(cls.id)
            except Exception:
                pass
            self._seed_step_graph(flow_factory)
            parser = ContainerLogParser(step_ids)

            argv = build_dockerized_argv(
                config_file=config_files[0],
                extra_config_files=extra_config_files,
                design_dir=design_dir,
                flow=self._flow_name,
                pdk=pdk,
                scl=scl,
                pdk_root=pdk_root,
                tag=tag,
                frm=frm,
                to=to,
                skip=skip,
                overrides=config_overrides,
                extra_sources=extra_sources,
                extra_extras=extra_extras,
                overwrite=overwrite,
            )
            # Force LibreLane to the engine the GUI determined is usable (so a
            # present-but-unusable Docker can't shadow a working Podman), and
            # activate the docker group via `sg` when that's how we made Docker
            # usable without a re-login.
            run_env = os.environ.copy()
            try:
                from . import tools

                resolved = tools.resolve_engine()
                run_env.update(resolved.get("env") or {})
                if resolved.get("sg_wrap"):
                    argv = tools.sg_wrap_argv(argv)
            except Exception:
                pass

            self._emit(
                EventType.INFO,
                {"message": "Container mode — running: " + " ".join(argv)},
            )
            # Seed an immediate phase so the pipeline shows "preparing" the
            # instant the run starts, before any container stdout arrives.
            self._emit(
                EventType.PHASE,
                {"label": "Starting the LibreLane container…"},
            )

            proc = subprocess.Popen(
                argv,
                cwd=str(design_dir),
                stdin=subprocess.DEVNULL,  # no controlling TTY → engine won't want -t
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=run_env,
            )
            self._container_proc = proc
            assert proc.stdout is not None
            for raw in proc.stdout:
                # Strip ANSI/control bytes first so both the parser and the log
                # see clean text. Feed the parser every line (it keys off
                # `Running '<id>'` / `--name <uuid>` / failure markers).
                line = strip_ansi(raw).rstrip()
                for parsed in parser.feed(line):
                    self._dispatch_parsed(parsed)
                # Emit real output only — drop the Rich progress-bar redraws that
                # otherwise flood the log (progress is shown on the timeline).
                if line and not is_progress_bar(line):
                    self._emit(EventType.LOG, {"message": line})
                if self._cancel.is_set():
                    break
            proc.wait()
            # The container has created the run dir by now — persist GUI settings.
            self._persist_gui_meta()

            if self._cancel.is_set():
                # Second removal sweep: the container may have come up after (or
                # raced with) cancel()'s first attempt; the flow must not keep
                # running behind a "cancelled" status.
                self._kill_container()
                self._mark_current_failed("cancelled")
                self._emit(EventType.INFO, {"message": "flow cancelled by user"})
                self._emit(EventType.FLOW_DONE, {"tag": self._run_dir or "", "cancelled": True})
            else:
                for parsed in parser.finish(proc.returncode):
                    if parsed.get("type") == "flow_done":
                        parsed.setdefault("tag", self._run_dir or "")
                    self._dispatch_parsed(parsed)
        except FileNotFoundError as ex:
            self._error = f"{type(ex).__name__}: {ex}"
            self._emit(
                EventType.STEP_FAILED,
                {"step_id": self._current_step_id, "message": str(ex)},
            )
            self._emit(EventType.FLOW_DONE, {"tag": self._run_dir or "", "error": self._error})
        except Exception as ex:
            tb = traceback.format_exc()
            self._error = f"{type(ex).__name__}: {ex}"
            self._mark_current_failed(str(ex))
            self._emit(
                EventType.STEP_FAILED,
                {
                    "step_id": self._current_step_id,
                    "message": str(ex),
                    "traceback": tb[-4000:],
                    "cancelled": self._cancel.is_set(),
                },
            )
            self._emit(EventType.FLOW_DONE, {"tag": self._run_dir or "", "error": self._error})
        finally:
            self._running = False
            self._container_proc = None

    # ---- container step-by-step execution ----

    def _run_container_stepwise(
        self,
        flow_factory: Any,
        config_files: Sequence[str],
        design_dir: Path,
        *,
        pdk_root: Optional[str],
        pdk: Optional[str],
        scl: Optional[str],
        pad: Optional[str],
        tag: Optional[str],
        frm: Optional[str],
        to: Optional[str],
        skip: Optional[List[str]],
        overwrite: bool,
        reproducible_step: Optional[str],
        config_overrides: Dict[str, Any],
        extra_sources: Optional[List[str]],
        extra_extras: Optional[List[str]],
        extra_config_files: Optional[List[str]] = None,
        last_run: bool = False,
    ) -> None:
        """Set up container step-by-step: seed the step graph, save the
        invocation args, and run the first step. Each subsequent step is launched
        by :meth:`resume` (the "Next"/Resume button) via
        :meth:`_advance_container_step`."""
        try:
            if not config_files:
                raise ValueError("no config file to run")
            if not tag:
                tag = time.strftime("glui-%Y%m%d-%H%M%S")
            self._run_dir = str(design_dir / "runs" / tag)

            step_ids: List[str] = []
            try:
                for cls in getattr(flow_factory, "Steps", []) or []:
                    step_ids.append(cls.id)
            except Exception:
                pass
            # Honour a From/To window if the user set one, so step-by-step can
            # also walk just a slice of the flow.
            sub = self._slice_steps(step_ids, frm, to, skip or [])
            if not sub:
                raise ValueError("no steps to run (check From/To/Skip)")
            self._seed_step_graph(flow_factory)

            self._cstep = {
                "steps": sub,
                "idx": 0,
                "tag": tag,
                "design_dir": design_dir,
                "config_file": config_files[0],
                "extra_config_files": list(extra_config_files or []),
                "pdk": pdk,
                "scl": scl,
                "pdk_root": pdk_root,
                "overrides": dict(config_overrides or {}),
                "extra_sources": list(extra_sources or []),
                "extra_extras": list(extra_extras or []),
                "overwrite": bool(overwrite),
            }
            self._emit(
                EventType.INFO,
                {"message": f"Container step-by-step — {len(sub)} steps; running one at a time."},
            )
            self._run_container_step(0)
        except Exception as ex:
            self._error = f"{type(ex).__name__}: {ex}"
            self._emit(EventType.STEP_FAILED, {"step_id": self._current_step_id, "message": str(ex)})
            self._emit(EventType.FLOW_DONE, {"tag": self._run_dir or "", "error": self._error})
            self._running = False

    @staticmethod
    def _slice_steps(step_ids: List[str], frm: Optional[str], to: Optional[str], skip: Sequence[str]) -> List[str]:
        """Return the ordered sub-list of step ids honoring From/To/Skip."""
        if not step_ids:
            return []
        lo = step_ids.index(frm) if (frm and frm in step_ids) else 0
        hi = step_ids.index(to) if (to and to in step_ids) else len(step_ids) - 1
        if hi < lo:
            # An inverted range is a user mistake — running the FULL flow instead
            # (the old behaviour) silently ignores their intent. Return no steps
            # so the caller raises "no steps to run (check From/To/Skip)".
            return []
        skipset = set(skip or [])
        return [s for s in step_ids[lo:hi + 1] if s not in skipset]

    def _advance_container_step(self) -> None:
        """Launch the next single-step container invocation in a worker thread."""
        if not self._cstep:
            return
        idx = self._cstep.get("idx", 0)
        self._awaiting_next = False
        self._worker = threading.Thread(
            target=self._run_container_step,
            args=(idx,),
            daemon=True,
            name="librelane.gui.FlowRunner.cstep",
        )
        self._worker.start()

    def _run_container_step(self, idx: int) -> None:
        """Run exactly one flow step inside the container via ``--only <step>``,
        resuming the shared run tag. Pauses (awaiting Next) afterwards unless it
        was the last step or the run failed."""
        c = self._cstep
        steps: List[str] = c["steps"]
        sid = steps[idx]
        design_dir: Path = c["design_dir"]
        try:
            parser = ContainerLogParser([sid])
            argv = build_dockerized_argv(
                config_file=c["config_file"],
                extra_config_files=c.get("extra_config_files"),
                design_dir=design_dir,
                flow=self._flow_name,
                pdk=c["pdk"],
                scl=c["scl"],
                pdk_root=c["pdk_root"],
                tag=c["tag"],
                frm=sid,
                to=sid,
                overrides=c["overrides"],
                extra_sources=c["extra_sources"],
                extra_extras=c["extra_extras"],
                # Only the FIRST step may overwrite an existing tag; later steps
                # MUST reuse the run dir (overwrite would wipe prior step state).
                overwrite=bool(c["overwrite"]) and idx == 0,
            )
            run_env = os.environ.copy()
            try:
                from . import tools

                resolved = tools.resolve_engine()
                run_env.update(resolved.get("env") or {})
                if resolved.get("sg_wrap"):
                    argv = tools.sg_wrap_argv(argv)
            except Exception:
                pass

            self._emit(
                EventType.INFO,
                {"message": f"Step {idx + 1}/{len(steps)} ({sid}) — running: " + " ".join(argv)},
            )
            self._emit(EventType.PHASE, {"label": f"Starting the container for step '{sid}'…"})

            proc = subprocess.Popen(
                argv, cwd=str(design_dir), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                bufsize=1, env=run_env,
            )
            self._container_proc = proc
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = strip_ansi(raw).rstrip()
                for parsed in parser.feed(line):
                    # Suppress the parser's auto-progress; we drive global
                    # progress ourselves below to reflect the whole flow.
                    if parsed.get("type") != "progress":
                        self._dispatch_parsed(parsed)
                if line and not is_progress_bar(line):
                    self._emit(EventType.LOG, {"message": line})
                if self._cancel.is_set():
                    break
            proc.wait()
            self._container_proc = None
            self._persist_gui_meta()  # run dir exists once the first step ran

            if self._cancel.is_set():
                # Second removal sweep — same reasoning as the full-run worker.
                self._kill_container()
                self._mark_current_failed("cancelled")
                self._emit(EventType.INFO, {"message": "flow cancelled by user"})
                self._emit(EventType.FLOW_DONE, {"tag": self._run_dir or "", "cancelled": True})
                self._running = False
                return

            if proc.returncode == 0:
                self._step_statuses[sid] = StepStatus.DONE.value
                self._emit(EventType.STEP_DONE, {"step_id": sid, "index": idx})
                completed = idx + 1
                self._emit(EventType.PROGRESS, {"done": completed, "total": len(steps), "current": ""})
                if completed >= len(steps):
                    self._emit(EventType.FLOW_DONE, {"tag": self._run_dir or "", "ok": True})
                    self._running = False
                else:
                    self._cstep["idx"] = completed
                    self._awaiting_next = True
                    nxt = steps[completed]
                    self._emit(
                        EventType.INFO,
                        {"message": f"step '{sid}' complete — click Resume for the next step ('{nxt}')",
                         "paused": True},
                    )
            else:
                self._step_statuses[sid] = StepStatus.FAILED.value
                if not parser.failed:
                    msg = (parser.pdk_download_issue and
                           "PDK download/resolve failed (offline?)") or \
                          f"step '{sid}' exited with code {proc.returncode}"
                    self._emit(EventType.STEP_FAILED, {"step_id": sid, "message": msg})
                self._emit(EventType.FLOW_DONE,
                           {"tag": self._run_dir or "", "error": f"step '{sid}' failed"})
                self._running = False
        except Exception as ex:
            tb = traceback.format_exc()
            self._error = f"{type(ex).__name__}: {ex}"
            self._step_statuses[sid] = StepStatus.FAILED.value
            self._emit(EventType.STEP_FAILED,
                       {"step_id": sid, "message": str(ex), "traceback": tb[-4000:]})
            self._emit(EventType.FLOW_DONE, {"tag": self._run_dir or "", "error": self._error})
            self._running = False
            self._container_proc = None

    def _mark_current_failed(self, _why: str) -> None:
        sid = self._current_step_id
        if sid:
            self._step_statuses[sid] = StepStatus.FAILED.value

    def _mark_remaining_aborted(self) -> None:
        """After a flow aborts (cancel or mid-flow error), every step that never
        reached a terminal state stays PENDING/RUNNING forever — the timeline
        then shows a tail of grey "pending" rows that look like they might still
        run, even though the run is over (audit A5). Emit ``step_skipped``
        (reason: flow aborted) for each so the timeline is honest. The current
        step is already marked FAILED by :meth:`_mark_current_failed` and is left
        untouched here."""
        for sid, st in list(self._step_statuses.items()):
            if sid == self._current_step_id:
                continue
            if st in (StepStatus.PENDING.value, StepStatus.RUNNING.value):
                self._step_statuses[sid] = StepStatus.SKIPPED.value
                self._emit(EventType.STEP_SKIPPED, {"step_id": sid, "reason": "flow aborted"})

    def _seed_step_graph(self, flow: Any) -> None:
        """Tell the SPA which steps exist before any run begins."""
        try:
            graph = []
            for cls in getattr(flow, "Steps", []) or []:
                self._step_statuses.setdefault(cls.id, StepStatus.PENDING.value)
                graph.append({"id": cls.id, "status": StepStatus.PENDING.value})
            self._stage_total = len(graph)
            self._emit(EventType.INFO, {"step_graph": graph})
        except Exception:
            pass

    # ---- log bridge ----

    def _setup_log_bridge(self) -> None:
        """Forward LibreLane's logs to the SSE stream as ``log`` events.

        Two things matter here, and getting either wrong makes the in-image
        (native-toolchain) run look far less detailed than a container run:

        * **Bind to the right logger.** LibreLane logs to a named logger,
          ``__librelane__`` (not the root logger). The old
          ``from librelane.logging import getLogger`` import silently failed
          (that name isn't exported) and we fell back to the root logger,
          catching LibreLane's records only by propagation.
        * **Accept the SUBPROCESS level.** LibreLane streams every EDA tool's
          stdout through that logger at its custom ``SUBPROCESS`` level (=12,
          *below* ``INFO``). Our handler sat at ``INFO`` (20) and so dropped
          exactly that per-tool detail — the polygon dumps / per-cell / LVS
          output a verbose container run shows live. Capturing SUBPROCESS makes
          the local/in-image stream as detailed as container mode.
        """
        try:
            from librelane.logging.logger import LogLevels  # type: ignore

            sub_level = int(LogLevels.SUBPROCESS)
        except Exception:
            sub_level = 12  # SUBPROCESS — stable, documented CLI log-level value
        root = logging.getLogger("__librelane__")
        handler = _SSEHandler(self)
        handler.setLevel(sub_level)
        root.addHandler(handler)
        # __librelane__ defaults to SUBPROCESS, but be explicit so a global/parent
        # level set elsewhere can't filter the tool detail before we see it.
        try:
            if root.level == 0 or root.level > sub_level:
                root.setLevel(sub_level)
        except Exception:
            pass
        self._log_handler = handler
        self._log_root = root

    def _teardown_log_bridge(self) -> None:
        h = getattr(self, "_log_handler", None)
        root = getattr(self, "_log_root", None)
        if h is not None and root is not None:
            try:
                root.removeHandler(h)
            except Exception:
                pass
        self._log_handler = None


class _SSEHandler(logging.Handler):
    """Forward log records to the SSE event stream (no control flow)."""

    def __init__(self, runner: FlowRunner) -> None:
        super().__init__()
        self._runner = runner

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - threading-sensitive
        try:
            msg = self.format(record).rstrip()
        except Exception:
            return
        kind = EventType.LOG
        if record.levelno >= logging.ERROR:
            kind = EventType.LOG  # keep as log; failures are emitted by the runner itself
        try:
            self._runner._emit(kind, {"level": record.levelname, "message": msg})
        except Exception:
            pass
