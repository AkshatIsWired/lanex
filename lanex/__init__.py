# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""The :mod:`lanex` package.

Thin wrapper that re-exports :mod:`lanex.controller` and :mod:`lanex.server`.
Importing this package MUST be side-effect-free for the rest of LibreLane:
the GUI's CLI is registered as a separate console script, not bolted onto
``librelane`` itself.
"""
from __future__ import annotations

from . import _version as _version_mod
from . import controller as controller
from . import server as server


def __getattr__(name: str):
    # Lazy attribute: ``__version__`` only resolves librelane when somebody
    # actually asks for it. Keeps the package import sec-zero.
    if name == "__version__":
        return _version_mod.get_version()
    raise AttributeError(name)


__all__ = [
    "_version",
    "controller",
    "server",
    "__version__",
]
