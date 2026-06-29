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
"""Remember the design directories the user has opened, server-side.

The browser already keeps a ``ll.recentDesigns`` list in localStorage, but that
is per-profile and lost when storage is cleared — so a cross-design view (e.g.
Compare) could miss a design the user genuinely worked on. Persisting the list in
the GUI home (``~/.librelane-gui/known-designs.json``) makes the set of known
designs robust across browsers/profiles and server restarts.

Pure stdlib (``json`` + ``pathlib``); no new dependency; never raises.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

_MAX = 50


def _home() -> Path:
    return Path(os.environ.get("LIBRELANE_GUI_HOME", str(Path.home() / ".librelane-gui")))


def _store() -> Path:
    return _home() / "known-designs.json"


def list_designs() -> List[str]:
    """Known design dirs that still exist on disk, most-recent first."""
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: List[str] = []
    for d in data:
        try:
            if isinstance(d, str) and Path(d).is_dir():
                out.append(d)
        except OSError:
            continue
    return out


def remember(design_dir: str) -> None:
    """Record *design_dir* as known (de-duped, most-recent first). Best-effort."""
    if not design_dir:
        return
    try:
        p = str(Path(design_dir).resolve())
    except Exception:
        return
    existing = []
    try:
        cur = json.loads(_store().read_text(encoding="utf-8"))
        if isinstance(cur, list):
            existing = [x for x in cur if isinstance(x, str)]
    except Exception:
        existing = []
    ordered = [p] + [x for x in existing if x != p]
    ordered = ordered[:_MAX]
    try:
        home = _home()
        home.mkdir(parents=True, exist_ok=True)
        _store().write_text(json.dumps(ordered, indent=2), encoding="utf-8")
    except Exception:
        pass
