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
"""RTL lint (Phase 3.4) — a standalone Verilator ``--lint-only`` job.

"Check syntax" in the RTL IDE must be a *lint*, not a hardening run. Earlier it
drove the whole ``Classic`` flow through the shared FlowRunner, so it wrote a
``runs/`` directory, needed a PDK, and showed up in the Runs tab / pipeline /
logs as a full RTL→GDS run. This module instead runs ``verilator --lint-only``
directly on the design sources — no FlowRunner, no ``runs/`` dir, no PDK — and
emits dedicated ``lint_started`` / ``lint_done`` events so the IDE can react
without touching the cockpit's run UI.

Verilator emits diagnostics like::

    %Error: foo.v:12:7: syntax error, unexpected ...
    %Warning-WIDTH: bar.sv:30:14: Operator ... expects 8 bits ...

We turn each into ``{file, line, col, severity, code, msg}`` for editor-gutter
markers. Pure regex + stdlib subprocess; no new dependency. Verilator runs on
the host when present, else inside the LibreLane image (container mode).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Wall-clock ceiling for a single lint. ``verilator --lint-only`` returns almost
# instantly on healthy input, but a wedged tool (e.g. the *Windows* verilator
# resolved off the WSL ``/mnt/c`` PATH, which can hang under interop) would keep
# the worker thread alive forever, leaving ``job.running`` stuck True and
# refusing every later "Check syntax" with "a lint is already running" — the
# classic "works only once" bug. The watchdog kills a runaway lint so the job
# ALWAYS frees itself.
DEFAULT_LINT_TIMEOUT = 90

# %Error / %Warning-CODE: file:line:col: message
_RX = re.compile(
    r"^%(?P<sev>Error|Warning)(?:-(?P<code>[A-Z0-9_]+))?:\s*"
    r"(?P<file>[^:\s][^:]*):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<msg>.*)$"
)


def parse_verilator(log_text: str) -> List[Dict[str, Any]]:
    """Extract structured diagnostics from Verilator stdout/stderr."""
    out: List[Dict[str, Any]] = []
    for raw in (log_text or "").splitlines():
        line = raw.rstrip()
        m = _RX.match(line)
        if not m:
            continue
        out.append({
            "file": m.group("file").strip(),
            "line": int(m.group("line")),
            "col": int(m.group("col")) if m.group("col") else 1,
            "severity": m.group("sev").lower(),  # "error" | "warning"
            "code": m.group("code") or "",
            "msg": m.group("msg").strip(),
        })
    return out


def summarize(diags: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count errors/warnings for a status line."""
    errors = sum(1 for d in diags if d["severity"] == "error")
    warnings = sum(1 for d in diags if d["severity"] == "warning")
    return {"errors": errors, "warnings": warnings, "total": len(diags)}


# ---------------------------------------------------------------------------
# Standalone lint job (NOT the hardening flow)
# ---------------------------------------------------------------------------

def _shquote(s: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./=:+-]+", s or ""):
        return s
    return "'" + str(s).replace("'", "'\\''") + "'"


def build_lint_command(
    design_dir: str | Path,
    *,
    sources: Sequence[str],
    top: Optional[str] = None,
    include_dirs: Optional[Sequence[str]] = None,
    defines: Optional[Dict[str, Any]] = None,
    run_mode: str = "local",
    engine: str = "docker",
    image: Optional[str] = None,
) -> List[str]:
    """Build the argv for ``verilator --lint-only`` over *sources*.

    Local mode returns a bare ``verilator …`` argv (caller sets
    ``cwd=design_dir``); container mode mounts the design dir at ``/work`` and
    runs the image's verilator. Pure / no system probing. All source paths are
    relative to the design dir (the cwd / mount), so they're portable."""
    flags: List[str] = ["verilator", "--lint-only", "-Wall", "-Wno-fatal"]
    if top:
        flags += ["--top-module", str(top)]
    for inc in (include_dirs or []):
        flags.append("-I" + str(inc))
    for k, v in (defines or {}).items():
        flags.append(f"-D{k}={v}" if v not in (None, "") else f"-D{k}")
    flags.extend(str(s) for s in sources)
    if run_mode == "container":
        from . import container_run

        img = image or container_run.image_ref()
        abs_design = str(Path(design_dir).resolve())
        shell = " ".join(_shquote(p) for p in flags)
        return [engine, "run", "--rm", "-v", f"{abs_design}:/work", "-w", "/work",
                img, "bash", "-lc", shell]
    return flags


class LintJob:
    """Run ``verilator --lint-only`` in a worker thread, streaming output to the
    event bus and emitting ``lint_started`` / ``lint_done`` (with parsed
    diagnostics). Independent of the hardening FlowRunner."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None
        self._timed_out = threading.Event()
        self.last_result: Dict[str, Any] = {"diagnostics": [], "summary": summarize([])}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, argv: Sequence[str], *, design_dir: str | Path,
              env: Optional[Dict[str, str]] = None,
              timeout: int = DEFAULT_LINT_TIMEOUT) -> Dict[str, Any]:
        with self._lock:
            if self.running:
                return {"ok": False, "error": "a lint is already running"}
            self._timed_out.clear()
            self._thread = threading.Thread(
                target=self._run, args=(list(argv), str(design_dir), env or {}, int(timeout)),
                daemon=True, name="librelane.gui.LintJob",
            )
            self._thread.start()
        return {"ok": True}

    def _kill(self) -> None:
        """Terminate the lint process and its children (whole group on POSIX)."""
        proc = self._proc
        if not proc or proc.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(proc.pid), __import__("signal").SIGTERM)
            else:
                proc.terminate()
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass

    def _run(self, argv, design_dir, env, timeout) -> None:
        from . import container_run, events, platform_env

        events.publish("lint_started", {"argv": argv})
        # PATH must be Linux-only on WSL so a bare ``verilator`` argv resolves to
        # the real Linux build, never the Windows one on /mnt/c (which hangs /
        # fails and would wedge this job).
        full_env = {**os.environ, **env}
        full_env["PATH"] = platform_env.linux_only_path(full_env.get("PATH"))
        out_lines: List[str] = []
        rc = -1
        watchdog: Optional[threading.Timer] = None
        try:
            # Own session so the watchdog can kill the whole group on POSIX.
            popen_kw: Dict[str, Any] = {}
            if os.name == "posix":
                popen_kw["start_new_session"] = True
            self._proc = subprocess.Popen(
                argv, cwd=design_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env=full_env, **popen_kw,
            )
            if timeout and timeout > 0:
                def _on_timeout() -> None:
                    self._timed_out.set()
                    events.publish("log", {"message":
                        f"lint exceeded {timeout}s and was stopped (the linter wedged — on WSL a "
                        "Windows verilator on the PATH can hang; install the Linux build)."})
                    self._kill()
                watchdog = threading.Timer(timeout, _on_timeout)
                watchdog.daemon = True
                watchdog.start()
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                clean = container_run.strip_ansi(line.rstrip("\n"))
                out_lines.append(clean)
                if clean:
                    events.publish("log", {"message": clean})
            rc = self._proc.wait()
        except FileNotFoundError as ex:
            events.publish("log", {"message": f"lint failed to launch: {ex}"})
            rc = 127
        except Exception as ex:  # pragma: no cover - environment dependent
            events.publish("log", {"message": f"lint error: {ex}"})
            rc = 1
        finally:
            if watchdog is not None:
                watchdog.cancel()
            self._proc = None
        diags = parse_verilator("\n".join(out_lines))
        summary = summarize(diags)
        self.last_result = {"diagnostics": diags, "summary": summary}
        # rc==0 means verilator ran and found no *errors* (warnings don't fail
        # --lint-only). A non-zero rc with parsed errors is a real lint failure;
        # rc 127 means verilator wasn't found.
        events.publish("lint_done", {
            "ok": (rc == 0 or summary["errors"] == 0) and not self._timed_out.is_set(),
            "returncode": rc,
            "diagnostics": diags,
            "summary": summary,
            "timed_out": self._timed_out.is_set(),
        })


# Process-wide singleton.
job = LintJob()
