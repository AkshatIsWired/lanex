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

    Three-state (mirrors :func:`parse_lvs`): the payload carries ``status`` =
    ``"parsed"`` (the parser really read the report — 0 violations then means
    *clean*), ``"missing"`` (no such file), or ``"error"`` (unreadable/empty).
    A missing or empty report must never be indistinguishable from a clean one
    — the old behaviour returned a bare 0-violation report for a missing file,
    which the UI rendered as a green "Clean DRC report".
    """
    path = Path(path)
    if not path.is_file():
        out = to_json(DRCReport(module="UNKNOWN", bbox_count=0, violations=[]))
        out["status"] = "missing"
        out["error"] = f"report file not found: {path}"
        return out
    name = path.name.lower()
    try:
        empty = path.stat().st_size == 0 or not path.read_text(
            encoding="utf-8", errors="replace").strip()
    except Exception:
        empty = False
    if empty:
        # A real Magic/OpenROAD DRC report always has content (header/counts);
        # an empty file is a truncated or failed write, not a clean result.
        out = to_json(DRCReport(module="UNKNOWN", bbox_count=0, violations=[]))
        out["status"] = "error"
        out["error"] = "report file is empty — the DRC step may not have finished writing it"
        return out
    with path.open("r", encoding="utf-8", errors="replace") as f:
        try:
            from librelane.common.drc import DRC  # type: ignore

            if name.endswith(".drc") or "openroad" in name or "or_" in name:
                drc, count = DRC.from_openroad(f, module="UNKNOWN")
            else:
                drc, count = DRC.from_magic(f)
        except Exception as ex:
            out = to_json(
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
            out["status"] = "error"
            out["error"] = str(ex)
            return out
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
    out = to_json(DRCReport(module=drc.module, bbox_count=count, violations=violations))
    out["status"] = "parsed"
    return out


def parse_lvs(path: str | Path) -> Dict[str, Any]:
    """Three-state LVS parser for Netgen reports: clean / mismatch / unknown.

    The verdict comes ONLY from Netgen's own final-verdict line (``Final
    result: Circuits match uniquely.`` / ``Netlists do not match.``) — the rest
    of the report is free-form comparison tables whose numbers are NOT error
    counts. In particular the two-column inventory (``Number of devices: 362
    |Number of devices: 362``) shows both circuits' totals side by side; a
    loose ``devices: (\\d+)`` match read that as 362 *unmatched* devices on a
    perfectly clean run. Counts are therefore only extracted when explicitly
    labelled ``unmatched …``, and a missing verdict is reported as
    ``status: "unknown"`` — never silently as clean or dirty.
    """
    path = Path(path)
    text = Path(path).read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    import re as _re

    counts: Dict[str, int] = {}
    for label in ("devices", "nets", "pins"):
        m = _re.search(rf"unmatched\s+{label}\s*[:=]\s*(\d+)", text, _re.IGNORECASE)
        if m:
            counts[f"unmatched_{label}"] = int(m.group(1))

    verdict: Optional[str] = None
    for line in reversed(text.splitlines()):
        if _re.match(r"\s*Final result\s*:", line, _re.IGNORECASE):
            verdict = line.strip()
            break

    def _classify(s: str) -> Optional[str]:
        low = s.lower()
        if "do not match" in low or "mismatch" in low:
            return "mismatch"
        if "match uniquely" in low or "circuits match" in low or "netlists match" in low:
            # "match uniquely with port errors" is still an LVS failure.
            return "mismatch" if "error" in low else "clean"
        return None

    status = _classify(verdict) if verdict else None
    if status is None:
        # No verdict line — fall back to unambiguous whole-text markers only.
        if _re.search(r"netlists do not match|circuits do not match", text, _re.IGNORECASE):
            status = "mismatch"
        elif _re.search(r"circuits match uniquely", text, _re.IGNORECASE):
            status = "clean"
        else:
            status = "unknown"
    if status == "clean" and any(counts.values()):
        # Verdict and explicit unmatched counts disagree — surface, don't pick.
        status = "mismatch"
    return {
        "path": str(path),
        "raw_chars": len(text),
        "status": status,
        "verdict": verdict,
        "counts": counts,
    }
