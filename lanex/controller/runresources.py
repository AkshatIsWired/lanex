"""Size LibreLane's thread counts to the PC a run starts on.

LibreLane 3.0.4 gives every multi-threaded step ``os.cpu_count()`` threads
unless a variable says otherwise (``common/misc.py`` ``_get_process_limit``):

* ``DRT_THREADS`` (OpenROAD.DetailedRouting): TritonRoute threads. Memory grows
  with threads (mac_array: 2.3 GB at 32 threads, 1.1 GB at 4) and OpenROAD has
  segfaulted with 32; routing gets no faster past ~16 (OpenROAD issue #7159).
* ``KLAYOUT_DRC_THREADS`` (KLayout.DRC), ``KLAYOUT_XOR_THREADS`` (KLayout.XOR),
  ``KLAYOUT_DENSITY_THREADS`` (KLayout.Density, Chip flow): KLayout tiles.
* ``STA_THREADS`` (OpenROAD.STAPrePNR / STAMidPNR / STAPostPNR / RCX): how many
  timing corners run at once, each its own OpenROAD process with its own copy
  of the design, so memory multiplies.

``_OPENLANE_MAX_CORES`` would cap them all, but LibreLane does not forward it
into the container, so LanEx sets the variables themselves as ``-c`` overrides,
only for the ones the user's config and this run's overrides leave unset (the
user's value always wins), and only for variables a step of the chosen flow
reads. Thread counts change how fast a step runs, never what it computes: the
router and KLayout split the same work into more or fewer pieces, and STA runs
the same corners in a different order (checked on spm and mac_array: identical
final metrics). Each run records what was chosen, and why, in ``gui-run.json``
(``resources``) and the values ride the run's recorded command, so Reproduce
runs with the same numbers.

Turn sizing off with ``{"thread_sizing": false}`` in ``$LANEX_HOME/settings.json``
or ``LANEX_THREAD_SIZING=0`` in the environment.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set

_log = logging.getLogger(__name__)

SOURCE = "LanEx (sized to this PC)"

# The variables LanEx may size, in display order.
THREAD_VARS = ("DRT_THREADS", "KLAYOUT_DRC_THREADS", "KLAYOUT_XOR_THREADS",
               "KLAYOUT_DENSITY_THREADS", "STA_THREADS")
# Older names LibreLane still accepts for the same variable: a config that uses
# one of them has set the variable.
_DEPRECATED = {"ROUTING_CORES": "DRT_THREADS"}

DRT_MAX = 16             # past this TritonRoute gets no faster and has crashed
DRT_BASE_GB = 2.0        # the rest of the flow, the container and LibreLane
DRT_GB_PER_THREAD = 0.25
KLAYOUT_MAX = 8
KLAYOUT_LOW_MEM = 2      # threads when less than KLAYOUT_LOW_MEM_GB is free
KLAYOUT_LOW_MEM_GB = 4.0
STA_GB_PER_CORNER = 1.0


# --------------------------------------------------------------------- pure

def size_threads(cores: Optional[int], avail_gb: Optional[float], *,
                 flow_vars: Optional[Iterable[str]] = None,
                 taken: Optional[Iterable[str]] = None,
                 corners: Optional[int] = None) -> Dict[str, Any]:
    """The thread overrides for a PC with *cores* usable CPUs and *avail_gb*
    of free memory. Pure.

    *flow_vars*: the thread variables a step of the chosen flow reads (None:
    all of :data:`THREAD_VARS`). *taken*: variables the user's config or this
    run already sets; those are left alone and listed in ``kept``.
    *corners*: how many STA corners the PDK has, when known.

    Returns ``{"values": {VAR: int}, "why": {VAR: text}, "kept": [VAR]}``;
    ``values`` is empty when the PC can't be read.
    """
    out: Dict[str, Any] = {"values": {}, "why": {}, "kept": []}
    fv = set(THREAD_VARS if flow_vars is None else flow_vars) & set(THREAD_VARS)
    tk = {_DEPRECATED.get(t, t) for t in (taken or [])}
    out["kept"] = [v for v in THREAD_VARS if v in fv and v in tk]
    if not cores or cores < 1 or avail_gb is None:
        return out
    cores = int(cores)
    avail = max(0.0, float(avail_gb))
    want = [v for v in THREAD_VARS if v in fv and v not in tk]

    for var in want:
        if var == "DRT_THREADS":
            by_mem = math.floor((avail - DRT_BASE_GB) / DRT_GB_PER_THREAD)
            n = max(1, min(cores, DRT_MAX, by_mem))
            if n == cores and cores <= DRT_MAX:
                why = "one per core"
            elif n == DRT_MAX and by_mem >= DRT_MAX:
                why = f"{DRT_MAX} at most: more threads don't route faster and have crashed OpenROAD"
            else:
                why = (f"about {DRT_GB_PER_THREAD:g} GB each, keeping {DRT_BASE_GB:g} GB "
                       f"for the rest of the flow")
        elif var.startswith("KLAYOUT_"):
            if avail < KLAYOUT_LOW_MEM_GB:
                n = max(1, min(cores, KLAYOUT_LOW_MEM))
                why = f"{KLAYOUT_LOW_MEM} while less than {KLAYOUT_LOW_MEM_GB:g} GB is free"
            else:
                n = max(1, min(cores, KLAYOUT_MAX))
                why = "one per core" if n == cores else f"{KLAYOUT_MAX} at most"
        else:  # STA_THREADS
            by_mem = math.floor(avail / STA_GB_PER_CORNER)
            caps = [cores, by_mem] + ([int(corners)] if corners and corners > 0 else [])
            n = max(1, min(caps))
            if corners and n == int(corners):
                why = f"every corner at once ({int(corners)} corners)"
            elif n == by_mem and by_mem < cores:
                why = f"about {STA_GB_PER_CORNER:g} GB per corner running at once"
            else:
                why = "one corner per core"
        out["values"][var] = int(n)
        out["why"][var] = why
    return out


def reason_text(cores: Optional[int], avail_gb: Optional[float]) -> str:
    """'8 cores, 5.1 GB free' — the PC facts a sizing was based on."""
    parts = []
    if cores:
        parts.append(f"{int(cores)} core{'s' if int(cores) != 1 else ''}")
    if avail_gb is not None:
        parts.append(f"{float(avail_gb):.1f} GB free")
    return ", ".join(parts)


# ------------------------------------------------------------ machine facts

def _cgroup_cpu_limit() -> Optional[int]:
    """CPUs allowed by this process's cgroup v2 ``cpu.max`` (None: no limit)."""
    try:
        rel = ""
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            if line.startswith("0::"):
                rel = line[3:].strip()
        p = Path("/sys/fs/cgroup") / rel.lstrip("/") / "cpu.max"
        if not p.is_file():
            return None
        quota, period = p.read_text().split()[:2]
        if quota == "max":
            return None
        return max(1, math.floor(int(quota) / int(period)))
    except Exception:
        return None


def usable_cores() -> Optional[int]:
    """CPUs this process may use: the affinity mask (``nproc``), capped by a
    cgroup CPU limit and by ``_OPENLANE_MAX_CORES`` when either is set."""
    try:
        n: Optional[int] = len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except Exception:
        n = os.cpu_count()
    lim = _cgroup_cpu_limit()
    if lim and n:
        n = min(n, lim)
    try:
        env = int(os.environ.get("_OPENLANE_MAX_CORES") or 0)
        if env > 0 and n:
            n = min(n, env)
    except ValueError:
        pass
    return n


_MACHINE_TTL_S = 2.0
_machine_cache: Dict[str, Any] = {}


def machine() -> Dict[str, Any]:
    """Cores and free memory now, read in the distro the flow runs in. Kept
    for two seconds, so the command preview and the run started right after
    it (or a sweep point's record and its start) agree."""
    import time
    now = time.monotonic()
    if _machine_cache and now - _machine_cache.get("_t", 0) < _MACHINE_TTL_S:
        return {k: v for k, v in _machine_cache.items() if k != "_t"}
    from . import dse
    res = dse.system_resources()
    out = {"cores": usable_cores() or res.get("cores"),
           "available_gb": res.get("available_gb"),
           "total_gb": res.get("total_gb")}
    _machine_cache.clear()
    _machine_cache.update(out, _t=now)
    return out


def enabled() -> bool:
    """False when the user turned sizing off (settings file or environment)."""
    env = (os.environ.get("LANEX_THREAD_SIZING") or "").strip().lower()
    if env in ("0", "off", "false", "no"):
        return False
    try:
        from . import platform_env
        p = platform_env.home() / "settings.json"
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("thread_sizing") is False:
                return False
    except Exception:
        pass
    return True


# -------------------------------------------------------- what the run sets

def _keys_in(obj: Any, into: Set[str]) -> None:
    """Every variable a JSON config sets: the top level and pdk::/scl:: sections."""
    if not isinstance(obj, dict):
        return
    for k, v in obj.items():
        if not isinstance(k, str):
            continue
        if k.startswith(("pdk::", "scl::")):
            _keys_in(v, into)
        else:
            into.add(k)


def config_sets(config_files: Iterable[Any]) -> Set[str]:
    """The thread variables (or their old names) any of *config_files* sets,
    anywhere, scoped sections included: a value the user wrote for some PDK
    is theirs, so LanEx leaves the variable alone for every PDK."""
    names = set(THREAD_VARS) | set(_DEPRECATED)
    found: Set[str] = set()
    for cf in config_files or []:
        try:
            p = Path(cf)
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if p.suffix.lower() == ".json":
            try:
                keys: Set[str] = set()
                _keys_in(json.loads(text), keys)
                found |= keys & names
                continue
            except Exception:
                pass  # fall through to the line scan
        for name in names:
            if p.suffix.lower() == ".tcl":
                rx = r"^\s*set\s+::env\(\s*" + name + r"\s*\)"
            else:  # yaml (and unparseable json): a key at any indent
                rx = r"""^\s*["']?""" + name + r"""["']?\s*:"""
            if re.search(rx, text, re.M):
                found.add(name)
    return {_DEPRECATED.get(n, n) for n in found}


def flow_thread_vars(flow_factory: Any) -> Optional[Set[str]]:
    """The thread variables a step of *flow_factory* reads (None: unknown)."""
    steps = getattr(flow_factory, "Steps", None)
    if not steps:
        return None
    out: Set[str] = set()
    try:
        for step in steps:
            for v in getattr(step, "config_vars", []) or []:
                if getattr(v, "name", None) in THREAD_VARS:
                    out.add(v.name)
    except Exception:
        return None
    return out


def sta_corners(design_dir: Any, pdk: Optional[str] = None) -> Optional[int]:
    """How many STA corners this design's PDK has, from the newest run that
    resolved its config for the same PDK (None: no such run)."""
    runs = Path(design_dir) / "runs"
    try:
        dirs = sorted((e for e in os.scandir(runs) if e.is_dir()),
                      key=lambda e: e.stat().st_mtime, reverse=True)
    except Exception:
        return None
    for e in dirs[:8]:
        rp = Path(e.path) / "resolved.json"
        if not rp.is_file():
            continue
        try:
            data = json.loads(rp.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if pdk and data.get("PDK") and data.get("PDK") != pdk:
            continue
        c = data.get("STA_CORNERS")
        if isinstance(c, list) and c:
            return len(c)
    return None


def plan(*, design_dir: Any, config_files: Iterable[Any], flow_factory: Any = None,
         overrides: Optional[Dict[str, Any]] = None, pdk: Optional[str] = None,
         facts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The thread overrides for one run and the record ``gui-run.json`` keeps.

    Returns ``{"overrides": {VAR: int}, "record": {...}}``. The record says
    what was chosen and from what: ``source``, ``cores``, ``available_gb``,
    ``total_gb``, ``reason`` ("8 cores, 5.1 GB free"), ``values``, ``why`` and
    ``kept`` (with where each kept value comes from). Never raises.
    """
    try:
        if not enabled():
            return {"overrides": {}, "record": {"source": SOURCE, "enabled": False,
                                                "values": {}, "kept": {},
                                                "reason": "thread sizing is turned off"}}
        m = dict(facts) if facts else machine()
        cfg_set = config_sets(config_files)
        run_set = {_DEPRECATED.get(k, k) for k in (overrides or {})}
        sized = size_threads(m.get("cores"), m.get("available_gb"),
                             flow_vars=flow_thread_vars(flow_factory) if flow_factory is not None else None,
                             taken=cfg_set | run_set,
                             corners=sta_corners(design_dir, pdk))
        kept = {v: ("this run's settings" if v in run_set else "your config")
                for v in sized["kept"]}
        record = {
            "source": SOURCE,
            "enabled": True,
            "cores": m.get("cores"),
            "available_gb": m.get("available_gb"),
            "total_gb": m.get("total_gb"),
            "reason": reason_text(m.get("cores"), m.get("available_gb")),
            "values": dict(sized["values"]),
            "why": dict(sized["why"]),
            "kept": kept,
        }
        return {"overrides": dict(sized["values"]), "record": record}
    except Exception:
        _log.debug("thread sizing failed; LibreLane's defaults apply", exc_info=True)
        return {"overrides": {}, "record": {}}


# ------------------------------------------------------- memory heads-up

_SIZE_RE = re.compile(r"^\s*([0-9.]+)\s*([KMGT]?)i?B?\s*$", re.I)
_UNIT = {"": 1 / 2 ** 30, "K": 1 / 2 ** 20, "M": 1 / 2 ** 10, "G": 1.0, "T": 2 ** 10}


def _gb(text: Any) -> Optional[float]:
    m = _SIZE_RE.match(str(text or ""))
    if not m:
        return None
    return float(m.group(1)) * _UNIT[m.group(2).upper()]


# Each run's peak, by run folder and what says it changed: a run's step folders
# are only read again when one was added or its newest one changed. Preflight
# asks on every design load and PDK pick; reading ~80 step folders each time
# cost ~0.3 s on a /mnt/c project.
_PEAK_CACHE: Dict[str, Any] = {}
_PEAK_CACHE_MAX = 64


def _step_no(entry: Any) -> int:
    """LibreLane numbers its step folders ('44-openroad-detailedrouting')."""
    m = re.match(r"(\d+)-", entry.name)
    return int(m.group(1)) if m else -1


def _run_peak(path: str, name: str) -> Optional[Dict[str, Any]]:
    try:
        steps = [s for s in os.scandir(path) if s.is_dir()]
        newest = max(steps, key=_step_no) if steps else None
        key = (os.stat(path).st_mtime_ns, len(steps), newest.stat().st_mtime_ns if newest else 0)
    except Exception:
        return None
    hit = _PEAK_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    best: Optional[Dict[str, Any]] = None
    for s in steps:
        try:
            files = [f for f in os.scandir(s.path) if f.name.endswith(".process_stats.json")]
        except Exception:
            continue
        for f in files:
            try:
                d = json.loads(Path(f.path).read_text(encoding="utf-8"))
                gb = _gb((d.get("peak_resources") or {}).get("memory_rss"))
            except Exception:
                gb = None
            if gb is not None and (best is None or gb > best["gb"]):
                best = {"gb": round(gb, 2), "tag": name, "step": s.name}
    if len(_PEAK_CACHE) >= _PEAK_CACHE_MAX:
        _PEAK_CACHE.clear()
    _PEAK_CACHE[path] = (key, best)
    return best


def last_run_peak_gb(design_dir: Any) -> Optional[Dict[str, Any]]:
    """The biggest memory any step of this design's newest finished run used
    (LibreLane's ``*.process_stats.json``): ``{gb, tag, step}`` or None."""
    runs = Path(design_dir) / "runs"
    try:
        dirs = sorted((e for e in os.scandir(runs) if e.is_dir()),
                      key=lambda e: e.stat().st_mtime, reverse=True)
    except Exception:
        return None
    for e in dirs[:6]:
        best = _run_peak(e.path, e.name)
        if best:
            return best
    return None


SMALL_DESIGN_GB = 2.0    # free memory a small design's full run needs
OVERHEAD_GB = 0.5        # the container, LibreLane itself and the OS cache it wants
WSL_CONFIG_URL = "https://learn.microsoft.com/windows/wsl/wsl-config"


def memory_check(available_gb: Optional[float], total_gb: Optional[float],
                 peak: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Whether free memory looks too small for this design. Pure.

    With a previous run, the need is its biggest step plus some room; without,
    a small design's ~2 GB. Returns ``{warn, need_gb, available_gb, basis,
    message, next_step, link}``; ``warn`` False means nothing to say."""
    out: Dict[str, Any] = {"warn": False, "available_gb": available_gb, "total_gb": total_gb,
                           "need_gb": None, "basis": None, "message": "", "next_step": "",
                           "link": WSL_CONFIG_URL}
    if peak and peak.get("gb"):
        need = round(float(peak["gb"]) + OVERHEAD_GB, 1)
        out["basis"] = "last-run"
    else:
        need = SMALL_DESIGN_GB
        out["basis"] = "rule"
    out["need_gb"] = need
    if available_gb is None or available_gb >= need:
        return out
    out["warn"] = True
    if out["basis"] == "last-run":
        why = (f"the last run of this design ({peak.get('tag')}) used up to {peak['gb']:.1f} GB "
               f"in one step")
    else:
        why = f"even a small design needs about {SMALL_DESIGN_GB:g} GB"
    out["message"] = (f"Only {available_gb:.1f} GB of memory is free for LanEx's Linux, and {why}. "
                      "The run may slow to a crawl or stop part-way.")
    out["next_step"] = ("Close other apps you don't need (browsers, editors, other runs), then check "
                        "again. LanEx doesn't change your WSL settings; to give WSL more memory "
                        "yourself, set memory= in the [wsl2] section of .wslconfig in your Windows "
                        "user folder, then run wsl --shutdown.")
    return out
