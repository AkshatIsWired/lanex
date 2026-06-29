"""LibreLane version detection and API compatibility layer."""

import importlib.metadata
from typing import Optional

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
