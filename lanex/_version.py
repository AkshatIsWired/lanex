# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""LanEx package version.

The version is the installed distribution's (``pyproject.toml``'s
``version``), read from the package metadata. A source tree that was never
installed (vendored, or run from a checkout without ``pip install -e``) has no
metadata and reports the fallback below.

Importing :mod:`lanex._version` is cheap; :func:`get_version` reads metadata
and never imports librelane. :func:`get_version_line` adds the librelane
version for ``lanex --version`` and does import it.
"""
from __future__ import annotations

__version__ = "0.0.0+unknown"


def get_version() -> str:
    """Return the installed LanEx version, e.g. ``"1.0.0"``."""
    try:
        from importlib.metadata import version

        return version("lanex")
    except Exception:  # not installed: a vendored copy or a bare checkout
        return __version__


def get_version_line() -> str:
    """Return ``"1.0.0 (librelane 3.0.4)"`` for ``lanex --version``."""
    ver = get_version()
    try:
        from librelane.__version__ import __version__ as librelane_version
    except Exception:  # librelane missing or broken: still say who we are
        return ver
    return f"{ver} (librelane {librelane_version})"
