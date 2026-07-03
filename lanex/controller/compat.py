"""LibreLane version detection and API compatibility layer."""

import functools
import importlib.metadata
from typing import Any, Dict

# The librelane range LanEx has actually been validated against. LanEx reaches
# past librelane's public CLI (it patches FlowProgressBar for per-step status,
# introspects config.variable internals, and assumes the metrics vocabulary), so
# a future minor/major bump can break it at runtime. The probe below turns that
# silent breakage into an explicit, actionable banner (I2).
KNOWN_GOOD_MIN = "3.0.4"
KNOWN_GOOD_MAX_EXCL = "3.1"

_LIBRELANE_VERSION = "unknown"
try:
    _LIBRELANE_VERSION = importlib.metadata.version("librelane")
except importlib.metadata.PackageNotFoundError:
    try:
        _LIBRELANE_VERSION = importlib.metadata.version("openlane")
    except importlib.metadata.PackageNotFoundError:
        pass

def get_version() -> str:
    """Return the detected LibreLane or OpenLane version, or 'unknown'."""
    return _LIBRELANE_VERSION

def is_available() -> bool:
    """Return True if LibreLane/OpenLane is installed in the current environment."""
    return _LIBRELANE_VERSION != "unknown"


def _version_in_range(v: str) -> bool:
    try:
        from packaging.version import Version
        return Version(KNOWN_GOOD_MIN) <= Version(v) < Version(KNOWN_GOOD_MAX_EXCL)
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def probe_compat() -> Dict[str, Any]:
    """Fast, one-shot self-check of every librelane private-API touchpoint LanEx
    relies on. Cached (runs once per process). Never raises. Returns
    ``{ok, version, known_good, range, issues}`` — the server exposes this via
    ``/api/health`` so the GUI can warn when running against an unvalidated
    librelane instead of failing cryptically mid-run."""
    version = get_version()
    if not is_available():
        return {"ok": False, "version": version, "known_good": False,
                "range": f">={KNOWN_GOOD_MIN},<{KNOWN_GOOD_MAX_EXCL}",
                "issues": ["librelane is not installed in this environment"]}
    issues = []
    # 1. Flow factory (flow discovery).
    try:
        from librelane.flows import Flow
        if not hasattr(Flow, "factory"):
            issues.append("librelane.flows.Flow.factory is missing")
    except Exception as ex:  # pragma: no cover - import-shape dependent
        issues.append(f"cannot import librelane.flows.Flow ({ex})")
    # 2. FlowProgressBar methods the runner patches for live per-step status.
    try:
        from librelane.flows.flow import FlowProgressBar
        for attr in ("set_max_stage_count", "start_stage", "end_stage"):
            if not hasattr(FlowProgressBar, attr):
                issues.append(f"FlowProgressBar.{attr} is missing — per-step status will be coarse")
    except Exception as ex:  # pragma: no cover
        issues.append(f"cannot import FlowProgressBar ({ex})")
    # 3. Variable introspection (drives the whole Config tab).
    try:
        from . import introspect
        if not introspect.list_variables():
            issues.append("introspect.list_variables() returned nothing")
    except Exception as ex:  # pragma: no cover
        issues.append(f"introspect.list_variables() failed ({ex})")
    return {"ok": not issues, "version": version,
            "known_good": _version_in_range(version),
            "range": f">={KNOWN_GOOD_MIN},<{KNOWN_GOOD_MAX_EXCL}",
            "issues": issues}
