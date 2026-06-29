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
"""Guarded file writes for the RTL IDE (Phase 3.3).

Until now the GUI is **read-only**. This is the *only* module that grants write
power, so the guard is the whole point: every path is resolved strictly inside
the design dir (no ``..``, no absolute escape, no symlink escape), only an
allowlisted set of source extensions is writable, and writes are atomic
(temp + ``os.replace``). Pure / stdlib only.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

# Only these extensions may be created/edited through the IDE.
EDITABLE_EXTS = {
    ".v", ".sv", ".vh", ".svh", ".vhd", ".vhdl", ".sdc", ".tcl", ".xdc",
    ".yaml", ".yml", ".json", ".cfg", ".md", ".txt", ".mem", ".hex",
}
MAX_WRITE_BYTES = 4 * 1024 * 1024  # 4 MiB — RTL/config files are tiny.


def _resolve_inside(design_dir: str | Path, rel_path: str) -> Optional[Path]:
    """Resolve *rel_path* strictly inside *design_dir*; None if it escapes.

    Rejects absolute paths and any ``..`` traversal, and verifies the resolved
    target (following symlinks) is still within the resolved design dir — so a
    symlink inside the design dir can't be used to escape it.
    """
    if not rel_path or os.path.isabs(rel_path):
        return None
    # Reject explicit parent traversal up front (defence in depth).
    parts = Path(rel_path).parts
    if ".." in parts:
        return None
    base = Path(design_dir).resolve()
    target = (base / rel_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target


def write_text(design_dir: str | Path, rel_path: str, content: str) -> Dict[str, Any]:
    """Atomically write *content* to *rel_path* inside *design_dir*.

    Returns ``{ok, path, bytes}`` or ``{ok: False, error}``. Refuses paths that
    escape the design dir or carry a non-allowlisted extension."""
    target = _resolve_inside(design_dir, rel_path)
    if target is None:
        return {"ok": False, "error": "path escapes the design directory"}
    if target.suffix.lower() not in EDITABLE_EXTS:
        return {"ok": False, "error": f"extension '{target.suffix}' is not editable"}
    data = content.encode("utf-8")
    if len(data) > MAX_WRITE_BYTES:
        return {"ok": False, "error": "file too large to save"}
    target.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: write to a temp file in the same dir, then replace.
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".ll-edit-", suffix=target.suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, target)
    except Exception as ex:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return {"ok": False, "error": str(ex)}
    return {"ok": True, "path": rel_path, "bytes": len(data)}


def create_file(design_dir: str | Path, rel_path: str) -> Dict[str, Any]:
    """Create an empty editable file (refuses to clobber an existing one)."""
    target = _resolve_inside(design_dir, rel_path)
    if target is None:
        return {"ok": False, "error": "path escapes the design directory"}
    if target.suffix.lower() not in EDITABLE_EXTS:
        return {"ok": False, "error": f"extension '{target.suffix}' is not editable"}
    if target.exists():
        return {"ok": False, "error": "file already exists"}
    return write_text(design_dir, rel_path, "")


def delete_file(design_dir: str | Path, rel_path: str) -> Dict[str, Any]:
    """Delete a file inside the design dir (never recursive, never outside)."""
    target = _resolve_inside(design_dir, rel_path)
    if target is None:
        return {"ok": False, "error": "path escapes the design directory"}
    if not target.is_file():
        return {"ok": False, "error": "not a file"}
    try:
        target.unlink()
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
    return {"ok": True, "deleted": rel_path}
