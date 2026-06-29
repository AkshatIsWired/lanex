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
"""Pure helpers for the **container** run mode.

LibreLane ships a version-matched container image with every EDA tool
(``openroad``, ``yosys``, ``magic``, ``netgen``, ``klayout``, ``verilator``)
and a built-in ``--dockerized`` CLI flag that runs the flow inside it. The host
needs exactly one thing — Docker or Podman — instead of six native tools.

``run_in_container`` replaces the current process via ``os.execlp``, so the GUI
cannot call it in-process; it must **shell out** to ``librelane --dockerized``,
stream stdout, and parse the step lines. Everything in this module is pure and
unit-testable:

* :func:`build_dockerized_argv` constructs the exact command line.
* :func:`image_ref` / :func:`pull_argv` mirror what LibreLane's own CLI uses.
* :class:`ContainerLogParser` turns the deterministic stdout into the same
  ``step_started`` / ``step_done`` / ``step_skipped`` / ``step_failed`` /
  ``progress`` / ``flow_done`` events the in-process runner emits.

No new third-party dependencies and no private LibreLane APIs are used — only
the documented ``--dockerized`` CLI flag (plus ``librelane.__version__`` for the
image tag, which is already importable).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Log-line cleanup.
# ---------------------------------------------------------------------------

# CSI / OSC escape sequences (colours, cursor moves, hyperlinks). Stripped for
# display so the GUI log shows plain text instead of raw control bytes.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|[\x00-\x08\x0b\x0c\x0e-\x1f]")
# Rich progress-bar block glyphs. LibreLane renders a live progress bar to
# stdout; over a pipe every redraw arrives as its own line
# (``Classic - Stage 68 - … ━━━ 67/80 0:01:48``) — thousands of them. Those
# glyphs never appear in real tool output, so their presence cleanly identifies
# a progress-bar redraw to drop (we already surface progress via the timeline).
_BAR_GLYPHS = "━╸╺╶╴"


def strip_ansi(s: str) -> str:
    """Remove ANSI escape sequences + stray control bytes from *s*."""
    return _ANSI_RE.sub("", s)


def is_progress_bar(line: str) -> bool:
    """True if *line* (already ANSI-stripped) is a Rich progress-bar redraw."""
    return any(g in line for g in _BAR_GLYPHS)


# ---------------------------------------------------------------------------
# Image reference (matches librelane/__main__.py exactly).
# ---------------------------------------------------------------------------

def image_ref() -> str:
    """The image LibreLane's own ``--dockerized`` path would use.

    Honours ``LIBRELANE_IMAGE_OVERRIDE`` and otherwise pins the tag to the
    installed ``librelane.__version__`` so tool versions always match the host
    package.
    """
    override = os.environ.get("LIBRELANE_IMAGE_OVERRIDE")
    if override:
        return override
    ver = "latest"
    try:
        import librelane  # type: ignore

        ver = getattr(librelane, "__version__", "") or "latest"
    except Exception:  # pragma: no cover - librelane missing
        ver = "latest"
    return f"ghcr.io/librelane/librelane:{ver}"


def pull_argv(engine: str) -> List[str]:
    """``<engine> pull <image>`` — pre-warm the image."""
    return [engine, "pull", image_ref()]


# ---------------------------------------------------------------------------
# Command-line construction.
# ---------------------------------------------------------------------------

def build_dockerized_argv(
    *,
    config_file: str | Path,
    extra_config_files: Optional[Sequence[str]] = None,
    design_dir: str | Path,
    flow: Optional[str] = None,
    pdk: Optional[str] = None,
    scl: Optional[str] = None,
    pdk_root: Optional[str] = None,
    tag: Optional[str] = None,
    frm: Optional[str] = None,
    to: Optional[str] = None,
    skip: Optional[Sequence[str]] = None,
    overrides: Optional[Dict[str, Any]] = None,
    extra_sources: Optional[Sequence[str]] = None,
    extra_extras: Optional[Sequence[str]] = None,
    overwrite: bool = False,
    python_exe: Optional[str] = None,
) -> List[str]:
    """Build ``python -m librelane [--pdk-root R] --dockerized CONFIG …``.

    Flag ordering matters: LibreLane's CLI consumes everything **before**
    ``--dockerized`` itself (``--pdk-root`` decides which PDK store to mount and
    export), and treats everything **after** it as the literal command to run
    inside the container (``python3 -m librelane <those args>``). See
    ``librelane/__main__.py``.

    The container's working directory is the host CWD (the design dir), so we
    pass the config as a path **relative** to the design dir when possible —
    that is mount-safe on Linux/macOS/Windows alike.
    """
    python_exe = python_exe or sys.executable or "python3"
    design_dir = Path(design_dir)
    cfg = Path(config_file)
    try:
        cfg_arg = str(cfg.resolve().relative_to(design_dir.resolve()))
    except Exception:
        cfg_arg = str(cfg)

    # Host-side options — must precede --dockerized.
    host: List[str] = [python_exe, "-m", "librelane"]
    if pdk_root:
        host += ["--pdk-root", str(pdk_root)]
    # The GUI streams the container over a pipe (no controlling terminal), so the
    # engine must NOT allocate a pseudo-TTY (`docker -t`) — otherwise it aborts
    # with "the input device is not a TTY". LibreLane defaults to --docker-tty;
    # force it off. (Host-side flag → before --dockerized.)
    host += ["--docker-no-tty"]
    host += ["--dockerized"]

    # Inner options — run by `python3 -m librelane …` inside the container.
    # LibreLane's CLI takes CONFIG_FILES as nargs=-1 and Config.load merges them,
    # so GUI overlay configs (e.g. the custom-macro MACROS overlay) ride along as
    # extra leading positionals. Each is passed relative to the design dir (the
    # container cwd / mount) so it resolves the same on every platform.
    inner: List[str] = [cfg_arg]
    for ecf in (extra_config_files or []):
        if not ecf:
            continue
        try:
            inner.append(str(Path(ecf).resolve().relative_to(design_dir.resolve())))
        except Exception:
            inner.append(str(ecf))
    if flow:
        inner += ["-f", str(flow)]
    if pdk:
        inner += ["-p", str(pdk)]
    if scl:
        inner += ["-s", str(scl)]
    if tag:
        inner += ["--run-tag", str(tag)]
    if overwrite:
        inner += ["--overwrite"]
    if frm:
        inner += ["-F", str(frm)]
    if to:
        inner += ["-T", str(to)]
    for s in (skip or []):
        if s:
            inner += ["-S", str(s)]

    ov: Dict[str, Any] = dict(overrides or {})
    # LibreLane parses list overrides as whitespace-separated values.
    if extra_sources:
        ov["VERILOG_FILES"] = " ".join(str(s) for s in extra_sources)
    if extra_extras:
        ov["EXTRA_FILES"] = " ".join(str(s) for s in extra_extras)
    for k, v in ov.items():
        inner += ["-c", f"{k}={v}"]

    return host + inner


# ---------------------------------------------------------------------------
# Stdout step parser.
# ---------------------------------------------------------------------------

# LibreLane logs one line per step start (steps/step.py): ``Running '<id>' at
# '<relpath>'…``. Skips log ``Skipping step '<name>'…``. The container engine
# echoes its own ``… run --rm --name <uuid> …`` line first (container.py).
_RUNNING_RX = re.compile(r"Running '(?P<id>[A-Za-z0-9_.\-:+]+)' at\b")
_SKIP_RX = re.compile(r"Skipping step '(?P<name>[^']+)'")
_NAME_RX = re.compile(r"--name\s+(?P<name>[A-Za-z0-9][A-Za-z0-9._\-]*)")
_FAIL_RX = re.compile(
    r"(Subprocess had a non-zero exit"
    r"|FlowException"
    r"|FlowError"
    r"|StepException"
    r"|StepError"
    r"|Traceback \(most recent call last\))"
)
# A PDK (re)download that the container's ciel attempts when the pinned version
# isn't present locally — fails hard when the host/container is offline. We turn
# the raw httpx/ciel traceback into one actionable line.
_PDK_DL_RX = re.compile(
    r"(attempting to download"
    r"|Failed to download PDK"
    r"|Could not resolve the PDK"
    r"|httpx\.(ReadTimeout|ConnectError|ConnectTimeout|RemoteProtocolError)"
    r"|ConnectionError"
    r"|Max retries exceeded"
    r"|Temporary failure in name resolution)"
)
_PDK_DL_MSG = (
    "PDK download/resolve failed — the version LibreLane pins isn't installed "
    "locally and the PDK release host couldn't be reached. Install the matching "
    "PDK first (Tools ▸ PDK) or connect to the internet, then retry."
)

# Pre-step preparation milestones. The container does a lot before the first
# ``Running '<id>'`` line — pull/extract the image, start the container, let the
# inner ciel verify the pinned PDK, then load + resolve the configuration. The
# inner process block-buffers stdout over a pipe, so that work looks like a
# frozen pipeline. We anchor on the few lines that DO arrive and surface a phase
# label (with a live timer, UI-side) so the user knows it is alive and on what.
# Ordered: first match wins.
_PHASE_RX = [
    (re.compile(r"Running containerized command|Updating to use container|Using (Docker|Podman)|--dockerized"),
     "Starting the LibreLane container…"),
    (re.compile(r"\brun --rm\b|--name\s+[A-Za-z0-9]"),
     "Launching container — first start can take a while…"),
    (re.compile(r"Pulling|Downloading|Extracting|Pull complete|layer|manifest"),
     "Pulling the container image (one-time, large download)…"),
    (re.compile(r"ciel|PDK|pdk|sky130|gf180|ihp|libs\.(ref|tech)|enabling|Resolving the"),
     "Resolving the PDK inside the container…"),
    (re.compile(r"Starting a new run|Using existing run|Loading the configuration|Initializing|Reading config|Resolved"),
     "Loading the configuration and building the flow…"),
]


class ContainerLogParser:
    """Turn LibreLane container stdout into structured flow events.

    Seed it with the flow's ordered step ids (known up front from
    ``flow.Steps`` without running anything) so each ``Running '<id>'`` line
    correlates directly and intermediate skipped steps can be inferred. The
    parser never raises and never loses output — the caller streams every line
    verbatim as a ``log`` event regardless.
    """

    def __init__(self, step_ids: Optional[Sequence[str]] = None) -> None:
        self.step_ids: List[str] = list(step_ids or [])
        self._index: Dict[str, int] = {sid: i for i, sid in enumerate(self.step_ids)}
        self.total: int = len(self.step_ids)
        self.current_id: Optional[str] = None
        self.current_idx: int = -1
        self.done_ids: set = set()
        self.failed: bool = False
        self.pdk_download_issue: bool = False
        self.container_name: Optional[str] = None
        self.phase: Optional[str] = None
        self._first_step_seen: bool = False

    def feed(self, line: str) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []

        # Capture the container name (for force-removal on cancel) from the
        # engine's echoed run command.
        if self.container_name is None and " run " in f" {line} " and "--name" in line:
            m = _NAME_RX.search(line)
            if m:
                self.container_name = m.group("name")
                events.append({"type": "container", "name": self.container_name})

        m = _RUNNING_RX.search(line)
        if m:
            self._first_step_seen = True
            events.extend(self._advance_to(m.group("id")))
            return events

        # Before the first step, surface what the container is busy with so the
        # pipeline doesn't look frozen. Emit only on a phase *change*.
        if not self._first_step_seen:
            for rx, label in _PHASE_RX:
                if rx.search(line):
                    if label != self.phase:
                        self.phase = label
                        events.append({"type": "phase", "label": label})
                    break

        # Note a PDK download/network problem so the eventual failure reads
        # clearly rather than dumping the raw httpx traceback.
        if _PDK_DL_RX.search(line):
            self.pdk_download_issue = True

        if not self.failed and _FAIL_RX.search(line):
            self.failed = True
            msg = _PDK_DL_MSG if self.pdk_download_issue else line.strip()[:400]
            events.append(
                {"type": "step_failed", "step_id": self.current_id, "message": msg}
            )
        return events

    def _advance_to(self, sid: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        # Close the previously-running step.
        if self.current_id and self.current_id not in self.done_ids:
            self.done_ids.add(self.current_id)
            out.append({"type": "step_done", "step_id": self.current_id})
        # Any seeded steps strictly between the last and this one were skipped.
        idx = self._index.get(sid)
        if idx is not None:
            for j in range(self.current_idx + 1, idx):
                skipped = self.step_ids[j]
                if skipped not in self.done_ids:
                    self.done_ids.add(skipped)
                    out.append({"type": "step_skipped", "step_id": skipped})
            self.current_idx = idx
        self.current_id = sid
        out.append(
            {
                "type": "step_started",
                "step_id": sid,
                "index": max(self.current_idx, 0),
                "total": self.total,
            }
        )
        out.append(
            {"type": "progress", "done": len(self.done_ids), "total": self.total, "current": sid}
        )
        return out

    def finish(self, returncode: int) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if returncode == 0:
            # A clean exit means every step ran (or was intentionally skipped).
            # Close out any seeded step we never saw a `Running '<id>'` for —
            # otherwise the final step(s) linger as "running" and the progress
            # bar sticks at 99%.
            for sid in self.step_ids:
                if sid not in self.done_ids:
                    self.done_ids.add(sid)
                    out.append({"type": "step_done", "step_id": sid})
            if not self.step_ids and self.current_id and self.current_id not in self.done_ids:
                self.done_ids.add(self.current_id)
                out.append({"type": "step_done", "step_id": self.current_id})
            total = self.total or len(self.done_ids)
            out.append(
                {"type": "progress", "done": len(self.done_ids), "total": total, "current": ""}
            )
            out.append({"type": "flow_done", "ok": True})
        else:
            if not self.failed:
                msg = (
                    _PDK_DL_MSG
                    if self.pdk_download_issue
                    else f"librelane exited with code {returncode}"
                )
                out.append(
                    {
                        "type": "step_failed",
                        "step_id": self.current_id,
                        "message": msg,
                    }
                )
            err = "PDK download failed (offline?)" if self.pdk_download_issue else f"exit code {returncode}"
            out.append({"type": "flow_done", "error": err})
        return out
