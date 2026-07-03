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
"""Manual / advanced mode: run LibreLane + EDA commands from the GUI, and reveal
the exact CLI for the current configuration.

Advanced users want to drive LibreLane themselves while keeping the cockpit's
views. This module supports that two ways, both safe to ship upstream:

1. :func:`cli_command_for` returns the **exact** ``librelane`` / ``--dockerized``
   command equivalent to a GUI run config, so the user can copy it and run it in
   their own terminal. The GUI keeps watching ``runs/`` and reflects whatever
   appears there, regardless of who launched it.
2. :class:`ManualJob` runs a command **from an allow-list** (LibreLane, the EDA
   tools, ciel, and the container engines) and streams its output over SSE. It
   is NOT an arbitrary shell: the program (argv[0]) must be allow-listed, the
   command is never run through a shell (no ``shell=True``), and shell
   operators / ``sudo`` are rejected. This keeps the localhost web server from
   becoming a remote-code path while still giving real manual control.

Pure stdlib; psutil (already a LibreLane dependency) is used only to terminate a
process tree on cancel. Cross-platform via ``shlex`` / ``subprocess``.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .events import bus

# Programs the manual console may run. argv[0]'s basename must be one of these.
# ``python``/``python3`` is allowed ONLY as ``python -m librelane …`` (checked
# below) so it can't become an arbitrary code path.
_ALLOWED = {
    "librelane", "openroad", "yosys", "abc",
    "magic", "klayout", "netgen", "iverilog", "vvp", "verilator", "verilator_bin",
    "ciel", "volare", "docker", "podman", "dot",
}
_PYTHON = {"python", "python3"}
# Container engines are allow-listed, but only for **read-only / status**
# subcommands. A bare ``docker``/``podman`` allow would let the localhost console
# do ``docker run -v /:/host …`` — full host read/write through the daemon, which
# defeats the whole point of an allow-list. The GUI's own container work
# (pull_image, the flow runner) builds argv directly and never goes through this
# validator, so narrowing here costs no functionality.
_CONTAINER_RO = {"version", "info", "images", "ps", "pull", "logs", "inspect"}
# ``docker image <sub>`` — only the read-only sub-subcommands.
_CONTAINER_IMAGE_RO = {"inspect", "ls", "history"}
# Never allow these even if someone adds them above — privilege escalation /
# shell escapes that defeat the allow-list.
_DENY = {"sudo", "su", "doas", "pkexec", "bash", "sh", "zsh", "fish", "env",
         "eval", "exec", "nohup", "xargs", "find", "perl", "ruby", "node"}
# Tokens that only make sense with a shell (we don't use one) — reject so the
# user gets a clear message instead of confusing literal-arg behaviour.
_SHELL_BITS = {"|", "||", "&", "&&", ";", ">", ">>", "<", "`"}

_OUTPUT_CAP = 20000  # lines retained for `last_result`; the SSE stream is live.


def validate(command: str) -> Dict[str, Any]:
    """Parse *command* and decide whether the manual console may run it.

    Returns ``{ok, argv, base}`` or ``{ok: False, error}``."""
    command = (command or "").strip()
    if not command:
        return {"ok": False, "error": "empty command"}
    try:
        argv = shlex.split(command, posix=(os.name != "nt"))
    except ValueError as ex:
        return {"ok": False, "error": f"could not parse command: {ex}"}
    if not argv:
        return {"ok": False, "error": "empty command"}
    for tok in argv:
        if (tok in _SHELL_BITS or "`" in tok or "$(" in tok
                or any(ch in tok for ch in (";", "|"))):
            return {"ok": False, "error": "shell operators (pipes, redirects, sub-shells) "
                    "aren't allowed here — run those in your own terminal. Copy the command "
                    "with the button if you need the full shell."}
    prog = Path(argv[0]).name.lower()
    if prog.endswith(".exe"):
        prog = prog[:-4]
    if prog in _DENY:
        return {"ok": False, "error": f"'{prog}' is not allowed from the GUI console "
                "(it would bypass the allow-list). Run it in your own terminal if you need it."}
    if prog in _PYTHON:
        # Only `python -m librelane …`.
        if len(argv) >= 3 and argv[1] == "-m" and argv[2] == "librelane":
            return {"ok": True, "argv": argv, "base": "librelane"}
        return {"ok": False, "error": "python is only allowed as `python -m librelane …` here."}
    if prog not in _ALLOWED:
        return {"ok": False, "error": f"'{prog}' isn't in the allow-list. Allowed: "
                + ", ".join(sorted(_ALLOWED | {"python -m librelane"})) + "."}
    if prog in ("docker", "podman"):
        sub = argv[1].lower() if len(argv) >= 2 else ""
        ok_sub = False
        if sub == "image":
            sub2 = argv[2].lower() if len(argv) >= 3 else ""
            ok_sub = sub2 in _CONTAINER_IMAGE_RO
        else:
            ok_sub = sub in _CONTAINER_RO
        if not ok_sub:
            return {"ok": False, "error": f"'{prog} {sub}' isn't allowed from the GUI console — "
                    "only read-only/status commands are (version, info, images, ps, pull, logs, "
                    "inspect). Run other container commands in your own terminal."}
    return {"ok": True, "argv": argv, "base": prog}


class ManualJob:
    """Run one allow-listed command at a time, streaming output over SSE."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lines: List[str] = []
        self.last_result: Dict[str, Any] = {}

    @property
    def running(self) -> bool:
        return self._running

    def start(self, command: str, *, cwd: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if self._running:
                return {"ok": False, "error": "a command is already running — cancel it first"}
            v = validate(command)
            if not v.get("ok"):
                return v
            argv = v["argv"]
            base = v["base"]
            run_env = os.environ.copy()
            # Container engine activation (sg-wrap / env) so `docker …` works the
            # same way the flow runner makes it work.
            if base in ("docker", "podman"):
                try:
                    from . import tools
                    resolved = tools.resolve_engine()
                    run_env.update(resolved.get("env") or {})
                    if resolved.get("sg_wrap"):
                        argv = tools.sg_wrap_argv(argv)
                except Exception:
                    pass
            self._running = True
            self._lines = []
            self._thread = threading.Thread(
                target=self._run, args=(argv, cwd, run_env, command),
                daemon=True, name="librelane.gui.ManualJob",
            )
            self._thread.start()
        return {"ok": True, "argv": argv}

    def _run(self, argv: Sequence[str], cwd: Optional[str], env: Dict[str, str], shown: str) -> None:
        bus.emit("manual_started", {"command": shown, "argv": list(argv)})
        try:
            kwargs: Dict[str, Any] = {
                "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                "text": True, "bufsize": 1, "env": env,
            }
            if cwd and Path(cwd).is_dir():
                kwargs["cwd"] = cwd
            if os.name != "nt":
                kwargs["start_new_session"] = True
            proc = subprocess.Popen(list(argv), **kwargs)  # noqa: S603 - allow-listed program only
            self._proc = proc
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\n")
                if len(self._lines) < _OUTPUT_CAP:
                    self._lines.append(line)
                bus.emit("manual_line", {"line": line})
            proc.wait()
            rc = proc.returncode
            self.last_result = {"command": shown, "rc": rc, "lines": list(self._lines)}
            bus.emit("manual_done", {"command": shown, "rc": rc})
        except FileNotFoundError:
            msg = f"{Path(argv[0]).name}: not found on PATH (is the tool installed?)"
            self.last_result = {"command": shown, "rc": 127, "error": msg}
            bus.emit("manual_done", {"command": shown, "rc": 127, "error": msg})
        except Exception as ex:  # pragma: no cover - platform dependent
            self.last_result = {"command": shown, "rc": 1, "error": str(ex)}
            bus.emit("manual_done", {"command": shown, "rc": 1, "error": str(ex)})
        finally:
            self._running = False
            self._proc = None

    def cancel(self) -> Dict[str, Any]:
        proc = self._proc
        if proc is None:
            return {"ok": True, "note": "nothing running"}
        try:
            import psutil
            p = psutil.Process(proc.pid)
            for child in p.children(recursive=True):
                try:
                    child.terminate()
                except Exception:
                    pass
            p.terminate()
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
        bus.emit("manual_line", {"line": "⏹ cancelled by user"})
        return {"ok": True}


_JOB: Optional[ManualJob] = None


def get_job() -> ManualJob:
    global _JOB
    if _JOB is None:
        _JOB = ManualJob()
    return _JOB


# ---------------------------------------------------------------------------
# CLI reveal — the exact command equivalent to a GUI run config.
# ---------------------------------------------------------------------------

def cli_command_for(
    *,
    design_dir: str,
    config_file: str,
    flow: Optional[str] = None,
    pdk: Optional[str] = None,
    scl: Optional[str] = None,
    pdk_root: Optional[str] = None,
    run_mode: str = "container",
    tag: Optional[str] = None,
    frm: Optional[str] = None,
    to: Optional[str] = None,
    skip: Optional[Sequence[str]] = None,
    overrides: Optional[Dict[str, Any]] = None,
    extra_sources: Optional[Sequence[str]] = None,
    extra_extras: Optional[Sequence[str]] = None,
    extra_config_files: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Return the copy-pasteable CLI for a run, for both engines.

    ``container`` mirrors :func:`container_run.build_dockerized_argv` exactly;
    ``local`` is the native ``librelane`` invocation. Returns
    ``{container, local, recommended}`` as shell-quoted strings.

    A faithful reproduction MUST include everything the runner synthesises that
    is NOT already in the config file (audit A3): the Setup file-picker sources
    become a ``VERILOG_FILES=`` / ``EXTRA_FILES=`` override (LibreLane parses
    list variables as whitespace-separated), and the Cells & Macros overlay
    config rides along as an extra leading CONFIG_FILE positional (LibreLane's
    CLI takes ``CONFIG_FILES`` as ``nargs=-1`` and ``Config.load`` merges them).
    Omitting these produced a command that ran *different RTL* (or dropped
    macros) for any design using the pickers — the exact reproduce-metadata bug."""
    cfg_rel = config_file
    try:
        cfg_rel = str(Path(config_file).resolve().relative_to(Path(design_dir).resolve()))
    except Exception:
        pass

    # Overlay configs ride as extra leading positionals. Container form is
    # relativised to the design dir (the container cwd / mount) exactly like
    # build_dockerized_argv; local form keeps the absolute path the runner uses.
    container_extra_cfgs: List[str] = []
    local_extra_cfgs: List[str] = []
    for ecf in (extra_config_files or []):
        if not ecf:
            continue
        local_extra_cfgs.append(str(ecf))
        try:
            container_extra_cfgs.append(
                str(Path(ecf).resolve().relative_to(Path(design_dir).resolve())))
        except Exception:
            container_extra_cfgs.append(str(ecf))

    def _inner(prefix: List[str], cfg: str, extra_cfgs: List[str]) -> List[str]:
        argv = list(prefix) + [cfg] + list(extra_cfgs)
        if flow:
            argv += ["-f", flow]
        if pdk:
            argv += ["-p", pdk]
        if scl:
            argv += ["-s", scl]
        if tag:
            argv += ["--run-tag", tag]
        if frm:
            argv += ["-F", frm]
        if to:
            argv += ["-T", to]
        for s in (skip or []):
            if s:
                argv += ["-S", str(s)]
        # Overrides + the picker-synthesised list variables, exactly as the
        # runner / build_dockerized_argv assemble them.
        ov: Dict[str, Any] = dict(overrides or {})
        if extra_sources:
            ov["VERILOG_FILES"] = " ".join(str(s) for s in extra_sources)
        if extra_extras:
            ov["EXTRA_FILES"] = " ".join(str(s) for s in extra_extras)
        for k, v in ov.items():
            argv += ["-c", f"{k}={v}"]
        return argv

    # Container: host options (--pdk-root) precede --dockerized. ``--docker-no-tty``
    # must be present so the revealed command also runs non-interactively (in a
    # pipe / script) — exactly mirroring container_run.build_dockerized_argv. Its
    # absence here meant a copied command aborted "the input device is not a TTY".
    host: List[str] = ["librelane"]
    if pdk_root:
        host += ["--pdk-root", pdk_root]
    host += ["--docker-no-tty", "--dockerized"]
    container = _inner(host, cfg_rel, container_extra_cfgs)

    local_prefix: List[str] = ["librelane"]
    if pdk_root:
        local_prefix += ["--pdk-root", pdk_root]
    local = _inner(local_prefix, config_file, local_extra_cfgs)

    quote = (lambda a: " ".join(shlex.quote(x) for x in a))
    return {
        "container": quote(container),
        "local": quote(local),
        "recommended": "container" if run_mode == "container" else "local",
        "cwd": design_dir,
    }
