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
"""Functional simulation (Phase 3.5) — Verilator or Icarus Verilog.

Two engines, picked to fit the testbench:

* **Icarus Verilog** (``iverilog`` + ``vvp``) — event-driven, full 4-state,
  honours ``#delay`` timing controls and classic ``initial`` testbenches. The
  better fit for hand-written RTL testbenches (and beginners), but it is **not**
  in the LibreLane container image, so it only runs in **Local-tools** mode when
  the host has it.
* **Verilator** (``--binary``) — fast, cycle-based, SV-leaning. It ships in the
  LibreLane image, so it is the default for **container** mode (and a host
  fallback when iverilog is absent).

Either way this is our own subprocess wrapping a binary (image or host) via the
public image + ``tools.resolve_engine`` only — no new dependency and no new
LibreLane API. LibreLane itself only *lints* with Verilator; this does not change
that. The build is pure/unit-testable; :class:`SimJob` does the subprocess + SSE.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import container_run, events, lint

# Wall-clock ceiling for a single simulation. A hand-written testbench with a
# free-running clock (``always #5 clk = ~clk``) and no ``$finish`` never
# terminates — the event queue never empties — so the sim process would run
# forever, the SimJob thread would stay alive, and ``job.running`` would stay
# True, blocking every later "Build & run" with "a simulation is already
# running". The timeout kills a runaway sim so the job always frees itself; the
# (partial) VCD it already wrote is still loaded. Cancel/Stop bypasses it.
DEFAULT_SIM_TIMEOUT = 120


def _verilator_shell(*, top: str, sources: Sequence[str], testbench: str,
                     defines: Optional[Dict[str, Any]], include_dirs: Optional[Sequence[str]],
                     trace: str, out_name: str = "sim_top") -> str:
    """The ``bash -lc`` command that builds + runs the testbench with Verilator 5.

    Uses ``--binary`` (Verilator 5 standalone executable) and ``--trace`` (VCD) /
    ``--trace-fst`` (FST). All paths are relative to the working dir (= design
    dir / container mount)."""
    trace_flag = "--trace-fst" if trace == "fst" else "--trace"
    parts: List[str] = ["verilator", "--binary", trace_flag, "--trace-structs",
                        "-Wno-fatal", "--Mdir", "obj_dir", "-o", out_name, "--top-module", top]
    for k, v in (defines or {}).items():
        parts.append(f"-D{k}={v}" if v not in (None, "") else f"-D{k}")
    for inc in (include_dirs or []):
        parts.append(f"-I{inc}")
    parts.extend(str(s) for s in sources)
    parts.append(str(testbench))
    build = " ".join(_shquote(p) for p in parts)
    # Build, then run the produced simulator (which dumps the VCD/FST).
    return f"set -e; {build}; ./obj_dir/{out_name}"


def _iverilog_shell(*, top: str, sources: Sequence[str], testbench: str,
                    defines: Optional[Dict[str, Any]], include_dirs: Optional[Sequence[str]],
                    out_name: str = "sim.vvp") -> str:
    """The ``bash -lc`` command that compiles + runs the testbench with Icarus.

    ``iverilog -g2012`` (Verilog-2005 + SV subset) compiles to a ``.vvp`` that
    ``vvp`` then executes; the testbench's ``$dumpfile``/``$dumpvars`` writes the
    VCD (whatever name it chooses — :class:`SimJob` detects the produced file).
    The TB module is the elaboration top (``-s``)."""
    parts: List[str] = ["iverilog", "-g2012", "-s", top, "-o", out_name]
    for k, v in (defines or {}).items():
        parts.append(f"-D{k}={v}" if v not in (None, "") else f"-D{k}")
    for inc in (include_dirs or []):
        parts.append(f"-I{inc}")
    parts.extend(str(s) for s in sources)
    parts.append(str(testbench))
    build = " ".join(_shquote(p) for p in parts)
    return f"set -e; {build}; vvp {out_name}"


def _shquote(s: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./=:+-]+", s or ""):
        return s
    return "'" + str(s).replace("'", "'\\''") + "'"


def build_sim_command(
    design_dir: str | Path,
    *,
    top: str,
    sources: Sequence[str],
    testbench: str,
    defines: Optional[Dict[str, Any]] = None,
    include_dirs: Optional[Sequence[str]] = None,
    trace: str = "vcd",
    run_mode: str = "container",
    engine: str = "docker",
    image: Optional[str] = None,
    container_name: Optional[str] = None,
    sim_engine: str = "verilator",
) -> List[str]:
    """Build the full argv to simulate the testbench.

    ``sim_engine`` selects ``"iverilog"`` or ``"verilator"``. Container mode
    wraps the build+run in ``<engine> run --rm -v <design>:/work -w /work <image>
    bash -lc '…'`` (mount only the design dir); local mode is a bare
    ``bash -lc '…'`` (the caller sets ``cwd=design_dir``). iverilog is local-only
    (not in the image); the caller enforces that. Pure — no system probing."""
    if sim_engine == "iverilog":
        shell = _iverilog_shell(top=top, sources=sources, testbench=testbench,
                                defines=defines, include_dirs=include_dirs)
    else:
        shell = _verilator_shell(top=top, sources=sources, testbench=testbench,
                                 defines=defines, include_dirs=include_dirs, trace=trace)
    if run_mode == "container":
        img = image or container_run.image_ref()
        name = container_name or ("ll-sim-" + uuid.uuid4().hex[:12])
        abs_design = str(Path(design_dir).resolve())
        return [engine, "run", "--rm", "--name", name, "-v", f"{abs_design}:/work",
                "-w", "/work", img, "bash", "-lc", shell]
    return ["bash", "-lc", shell]


_TB_PATTERNS = ("*_tb.v", "*_tb.sv", "tb_*.v", "tb_*.sv", "*testbench*.v", "*testbench*.sv")

# `module <name>` — used to auto-derive the testbench's top module so the user
# doesn't have to type it (typing the DUT name instead is the #1 reason iverilog
# elaborates the wrong top, runs no $dumpvars, and produces no VCD).
_MODULE_RX = re.compile(r"^\s*module\s+([A-Za-z_]\w*)", re.MULTILINE)


def top_module_of(design_dir: str | Path, testbench: str) -> Optional[str]:
    """Best-effort: the testbench's top module name (the module that has no
    ports — i.e. the bench — else the last module declared). Returns ``None`` if
    the file can't be read. Pure / stdlib."""
    try:
        text = (Path(design_dir) / testbench).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    names = _MODULE_RX.findall(text)
    if not names:
        return None
    # A classic testbench module declares no ports: ``module foo_tb;``. Prefer
    # the first such; otherwise fall back to the last module in the file.
    for m in re.finditer(r"^\s*module\s+([A-Za-z_]\w*)\s*([;(])", text, re.MULTILINE):
        if m.group(2) == ";":
            return m.group(1)
    return names[-1]


def find_testbenches(design_dir: str | Path) -> List[str]:
    """Heuristically locate testbench files (rel paths), searching ``verify/``
    first then the whole design dir. De-duplicated, ``runs/`` excluded."""
    base = Path(design_dir)
    found: List[str] = []
    seen = set()

    def add(p: Path) -> None:
        try:
            rel = str(p.relative_to(base))
        except ValueError:
            return
        if "runs/" in rel or rel.startswith("runs"):
            return
        if rel not in seen:
            seen.add(rel)
            found.append(rel)

    for pat in _TB_PATTERNS:
        for p in sorted(base.glob("verify/" + pat)):
            add(p)
    for pat in _TB_PATTERNS:
        for p in sorted(base.rglob(pat)):
            add(p)
    return found


def sim_verdict(rc: int, timed_out: bool, wave: Any, cancelled: bool) -> Dict[str, bool]:
    """Pure sim outcome → ``{ok, partial}``.

    A timed-out runaway bench (free-running clock / no ``$finish``) that still
    wrote a waveform is a soft SUCCESS — the button re-enables and the dump
    loads — but that dump is INCOMPLETE, so ``partial`` is set so the UI can
    carry a durable badge and no downstream consumer mistakes a truncated dump
    for a completed simulation (Fear #5 / N2). ``partial`` is never true without
    a waveform, and a cancelled run is neither ok-by-timeout nor partial.
    """
    has_wave = bool(wave)
    ok = (rc == 0) or (bool(timed_out) and has_wave)
    partial = bool(timed_out) and has_wave and not bool(cancelled)
    return {"ok": ok, "partial": partial}


class SimJob:
    """Run a built sim command, streaming stdout→``log`` events and emitting
    ``sim_started`` / ``sim_done``. Cancel kills the process (and force-removes
    the container in container mode)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._timed_out = threading.Event()
        self._container_name: Optional[str] = None
        self._engine: Optional[str] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, argv: Sequence[str], *, design_dir: str | Path, run_mode: str,
              env: Optional[Dict[str, str]] = None, vcd_name: str = "dump.vcd",
              container_name: Optional[str] = None, engine: Optional[str] = None,
              timeout: int = DEFAULT_SIM_TIMEOUT) -> Dict[str, Any]:
        with self._lock:
            if self.running:
                return {"ok": False, "error": "a simulation is already running"}
            self._cancel.clear()
            self._timed_out.clear()
            self._container_name = container_name
            self._engine = engine
            self._thread = threading.Thread(
                target=self._run,
                args=(list(argv), str(design_dir), run_mode, env or {}, vcd_name, int(timeout)),
                daemon=True, name="librelane.gui.SimJob",
            )
            self._thread.start()
        return {"ok": True}

    def cancel(self) -> None:
        self._cancel.set()
        self._kill()

    def _kill(self) -> None:
        """Terminate the sim process (and its children / its container)."""
        proc = self._proc
        if proc and proc.poll() is None:
            # Local sims are `bash -lc '… ; vvp …'`: terminating bash can orphan
            # vvp/verilator. On POSIX the process is its own session leader (see
            # _run), so signal the whole group; elsewhere fall back to terminate.
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
        if self._container_name and self._engine:
            try:
                subprocess.run([self._engine, "rm", "-f", self._container_name],
                               capture_output=True, timeout=10)
            except Exception:
                pass

    def _run(self, argv, design_dir, run_mode, env, vcd_name, timeout) -> None:
        from . import platform_env

        events.publish("sim_started", {"argv": argv, "timeout": timeout})
        # Linux-only PATH on WSL: a local `bash -lc 'verilator …'` / `iverilog …`
        # must use the Linux build, never a Windows tool on /mnt/c (which fails
        # with "verilator_bin: No such file or directory").
        full_env = {**os.environ, **env}
        full_env["PATH"] = platform_env.linux_only_path(full_env.get("PATH"))
        import time as _time
        started_at = _time.time()
        rc = -1
        watchdog: Optional[threading.Timer] = None
        try:
            # Own session so a runaway local sim can be killed as a group (POSIX).
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
                        f"simulation exceeded {timeout}s and was stopped — a free-running "
                        "testbench clock with no $finish runs forever. Add $finish to the bench."})
                    self._kill()
                watchdog = threading.Timer(timeout, _on_timeout)
                watchdog.daemon = True
                watchdog.start()
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                clean = container_run.strip_ansi(line.rstrip("\n"))
                if clean:
                    events.publish("log", {"message": clean})
            rc = self._proc.wait()
        except FileNotFoundError as ex:
            events.publish("log", {"message": f"simulation failed to launch: {ex}"})
            rc = 127
        except Exception as ex:  # pragma: no cover - environment dependent
            events.publish("log", {"message": f"simulation error: {ex}"})
            rc = 1
        finally:
            if watchdog is not None:
                watchdog.cancel()
            self._proc = None
        # Find the waveform the run produced. Verilator's --binary writes the name
        # we hinted, but iverilog testbenches name their own $dumpfile — so prefer
        # the expected name, else the newest *.vcd/*.fst created during this run.
        wave = self._find_waveform(Path(design_dir), vcd_name, started_at)
        timed_out = self._timed_out.is_set()
        cancelled = self._cancel.is_set()
        verdict = sim_verdict(rc, timed_out, wave, cancelled)
        events.publish("sim_done", {
            "ok": verdict["ok"],
            "partial": verdict["partial"],
            "returncode": rc,
            "vcd": wave,
            "cancelled": cancelled,
            "timed_out": timed_out,
        })

    @staticmethod
    def _find_waveform(design_dir: Path, hint: str, started_at: float) -> Optional[str]:
        # Only accept the hinted file if THIS run wrote it — otherwise a stale
        # dump.vcd from a previous sim would be falsely reported as the result.
        hinted = design_dir / hint
        try:
            if hinted.is_file() and hinted.stat().st_mtime >= started_at - 1.0:
                return hint
        except OSError:
            pass
        best: Optional[Path] = None
        best_mtime = started_at - 1.0
        try:
            for pat in ("*.vcd", "*.fst", "**/*.vcd", "**/*.fst"):
                for p in design_dir.glob(pat):
                    if "runs/" in str(p.relative_to(design_dir)).replace(os.sep, "/"):
                        continue
                    try:
                        mt = p.stat().st_mtime
                    except OSError:
                        continue
                    if mt >= best_mtime:
                        best_mtime = mt
                        best = p
        except Exception:
            return None
        if best is not None:
            try:
                return str(best.relative_to(design_dir))
            except ValueError:
                return None
        return None


# Process-wide singleton.
job = SimJob()
