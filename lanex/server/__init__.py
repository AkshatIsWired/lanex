# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""The :mod:`lanex.server` package provides the stdlib :mod:`http.server`-backed
HTTP layer. It is the *face* of the application: replaceable, throwaway,
zero domain knowledge. All real work happens in :mod:`lanex.controller`.
"""
from __future__ import annotations

from . import app
from . import routes
from . import sse

from .app import (
    LibreLaneGUIRequestHandler,
    find_free_port,
    make_server,
    open_browser,
    serve_forever,
)
from .routes import ROUTES, serve_view, static_root
from .sse import ISSEHandler, attach_sse_handler, detach_sse_handler

__all__ = [
    "app",
    "routes",
    "sse",
    "LibreLaneGUIRequestHandler",
    "find_free_port",
    "make_server",
    "open_browser",
    "serve_forever",
    "ROUTES",
    "serve_view",
    "static_root",
    "ISSEHandler",
    "attach_sse_handler",
    "detach_sse_handler",
]
