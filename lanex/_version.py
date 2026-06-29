# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""LanEx package version.

Tied to the upstream ``librelane.__version__`` when in-tree, otherwise a
fallback ``0.1.0.dev0`` so the GUI can be vendored without importing
librelane at module-import time.

Importing :mod:`lanex._version` is cheap; it does NOT import librelane
unless somebody actually reads ``__version__``.
"""
from __future__ import annotations

__version__ = "0.1.0.dev0"


def get_version() -> str:
    """Return ``"0.1.0+<librelane_version>"`` when librelane is available."""
    try:
        from librelane.__version__ import __version__ as _LIBRELANE_VERSION

        return "0.1.0+" + _LIBRELANE_VERSION
    except Exception:  # pragma: no cover - upstream not installed
        return __version__
