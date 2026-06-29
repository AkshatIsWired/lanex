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
"""Wrap LibreLane's DRC/LVS report parsers for the GUI."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import DRCReport, Violation, to_json


def _box_to_dict(box: Any) -> Dict[str, str]:
    return {
        "llx": str(getattr(box, "llx", "")),
        "lly": str(getattr(box, "lly", "")),
        "urx": str(getattr(box, "urx", "")),
        "ury": str(getattr(box, "ury", "")),
    }


def parse_drc(path: str | Path) -> Dict[str, Any]:
    """Run LibreLane's DRC parser and yield a JSON-safe DRC report.

    Decides parser based on file extension or magic byte sniffing.
    """
    path = Path(path)
    if not path.is_file():
        return to_json(DRCReport(module="UNKNOWN", bbox_count=0, violations=[]))
    name = path.name.lower()
    with path.open("r", encoding="utf-8", errors="replace") as f:
        try:
            from librelane.common.drc import DRC  # type: ignore

            if name.endswith(".drc") or "openroad" in name or "or_" in name:
                drc, count = DRC.from_openroad(f, module="UNKNOWN")
            else:
                drc, count = DRC.from_magic(f)
        except Exception as ex:
            return to_json(
                DRCReport(
                    module="UNKNOWN",
                    bbox_count=0,
                    violations=[Violation(
                        category="PARSE_ERROR",
                        layer="UNKNOWN",
                        rule="PARSE",
                        description=str(ex),
                        boxes=[],
                    )],
                )
            )
    violations: List[Violation] = []
    for vio in drc.violations.values():
        try:
            cat = vio.category_name
            layer, rule = cat.split(".", 1)
        except Exception:
            cat = "UNKNOWN.UNKNOWN"
            layer, rule = "UNKNOWN", "UNKNOWN"
        violations.append(
            Violation(
                category=cat,
                layer=layer,
                rule=rule,
                description=vio.description,
                boxes=[_box_to_dict(b) for b in vio.bounding_boxes],
            )
        )
    return to_json(DRCReport(module=drc.module, bbox_count=count, violations=violations))


def parse_lvs(path: str | Path) -> Dict[str, Any]:
    """Best-effort LVS-bytes parser for Netgen reports.

    Netgen output is mostly free-form text; we don't try to pull geometry,
    just pull out the unmatched counts if they look like ``unmatched nets = N``.
    """
    path = Path(path)
    text = Path(path).read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    import re as _re

    matches: Dict[str, int] = {}
    for label in ("devices", "nets", "pins"):
        m = _re.search(rf"(?:unmatched\s+)?{label}\s*[:=]\s*(\d+)", text, _re.IGNORECASE)
        if m:
            matches[f"unmatched_{label}"] = int(m.group(1))
    return {
        "path": str(path),
        "raw_chars": len(text),
        "counts": matches,
    }
