# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Non-finite-float JSON sanitiser shared by both transports.

Python's ``json.dumps`` emits bare ``Infinity``/``-Infinity``/``NaN`` for
non-finite floats. ``json.loads`` tolerates them, but the browser's
``JSON.parse`` (and any strict parser) rejects them, which silently breaks
every payload that carries such a value — e.g. LibreLane metrics like
``timing__setup_r2r__ws`` are ``inf`` when a design has no register-to-register
paths.

Both the REST path (``app.py`` → ``_send_json`` with ``allow_nan=False``) and
the SSE path (``sse.py`` → ``_write``) run every payload through :func:`json_safe`
so the wire is standards-compliant JSON everywhere. Keeping the function in this
neutral module avoids the ``app`` ⇄ ``sse`` import cycle (``app`` imports
``sse`` at module load, so ``sse`` cannot import back from ``app``).

Token convention (API contract): a non-finite metric value appears on the wire
as the JSON *string* ``"Infinity"`` / ``"-Infinity"`` / ``"NaN"`` — by design,
not a bug. API consumers must treat those three strings as the numeric
non-finite values; the bundled frontend does (``fmt.metric``), and the text
exports use the same spellings (CSV passes LibreLane's own ``Infinity``
through; the MD/HTML exports normalise to it) so every surface agrees.
"""
from __future__ import annotations

import math
import numbers
from typing import Any


def json_safe(obj: Any) -> Any:
    """Recursively replace non-finite floats with JSON-standard-safe strings.

    Maps ``NaN`` → ``"NaN"``, ``+inf`` → ``"Infinity"``, ``-inf`` →
    ``"-Infinity"`` (the exact tokens the frontend's ``fmt.metric`` already
    understands). Every other value passes through unchanged. Handles numpy
    floats too (all subclasses of ``numbers.Real``).
    """
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    # bool is an Integral subclass; ints/numpy ints are always finite — pass through.
    if isinstance(obj, numbers.Integral) or isinstance(obj, bool):
        return obj
    if isinstance(obj, numbers.Real):
        f = float(obj)
        if math.isnan(f):
            return "NaN"
        if math.isinf(f):
            return "Infinity" if f > 0 else "-Infinity"
        return f
    return obj
