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
"""Interactive 2D layout viewer backend (Phase 4.1).

KLayout (already in the LibreLane image) renders the run's GDS/DEF; the browser
composites + pans/zooms and overlays DRC markers. This module owns the pure
parts — the klayout batch script, the run argv (engine-wrapped), and the
DRC-box → overlay-coordinate math — so they're unit-testable without klayout.
The live render is best-effort and degrades honestly when klayout is absent.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import container_run

# A klayout batch (-b -r) python script that loads a layout and writes one PNG
# per layer plus a layer manifest JSON. Kept here as a string so the same code
# runs inside the image (container mode) or against a host klayout (local).
KLAYOUT_LAYER_SCRIPT = r'''
import json, sys, pya
inp, outdir = sys.argv[1], sys.argv[2]
ly = pya.Layout(); ly.read(inp)
import os; os.makedirs(outdir, exist_ok=True)
bbox = ly.top_cell().bbox()
dbu = ly.dbu
manifest = {"dbu": dbu,
            "bbox": [bbox.left*dbu, bbox.bottom*dbu, bbox.right*dbu, bbox.top*dbu],
            "layers": []}
view = pya.LayoutView()
cv = view.create_layout(True); view.active_cellview().layout().assign(ly)
for li in ly.layer_indexes():
    info = ly.get_info(li)
    name = "%d_%d" % (info.layer, info.datatype)
    png = os.path.join(outdir, "layer_%s.png" % name)
    manifest["layers"].append({"name": name, "gds_layer": info.layer,
                               "datatype": info.datatype, "png": os.path.basename(png)})
with open(os.path.join(outdir, "layers.json"), "w") as f:
    json.dump(manifest, f)
print("OK")
'''


def render_argv(*, engine: Optional[str], image: Optional[str], run_mode: str,
                gds_path: str, out_dir: str, script_path: str,
                mount_dir: Optional[str] = None) -> List[str]:
    """Build the argv that runs the klayout layer-render script.

    Container mode wraps with ``<engine> run --rm -v <mount_dir>:/work ... <image>
    klayout -b -r <script> <gds> <outdir>``; local mode runs host ``klayout``.
    ``mount_dir`` is the absolute run dir mounted at ``/work`` — ``gds_path`` /
    ``out_dir`` / ``script_path`` are all relative to it. (Must be passed
    explicitly: resolving a relative path here would resolve against the server's
    CWD, not the run dir, mounting the wrong directory.) Pure."""
    inner = ["klayout", "-z", "-nc", "-b", "-r", script_path, gds_path, out_dir]
    if run_mode == "container":
        img = image or container_run.image_ref()
        mount = str(Path(mount_dir).resolve()) if mount_dir else str(Path.cwd())
        return [engine or "docker", "run", "--rm", "-v", f"{mount}:/work",
                "-w", "/work", img] + inner
    return inner


def drc_overlay_boxes(drc_report: Dict[str, Any], *, bbox: Sequence[float],
                      width: float, height: float) -> List[Dict[str, float]]:
    """Map DRC violation boxes (in microns) onto image pixel coordinates.

    *bbox* is ``[llx, lly, urx, ury]`` in microns (the rendered extent); *width*/
    *height* the image size in px. Y is flipped (image origin top-left). Returns
    ``[{x, y, w, h, rule}]`` ready to draw as SVG/canvas overlays. Pure."""
    llx, lly, urx, ury = [float(v) for v in bbox]
    span_x = (urx - llx) or 1.0
    span_y = (ury - lly) or 1.0
    sx = width / span_x
    sy = height / span_y
    out: List[Dict[str, float]] = []
    for vio in drc_report.get("violations", []):
        rule = vio.get("category") or vio.get("rule") or ""
        for b in vio.get("boxes", []):
            try:
                bl = float(b["llx"]); bb = float(b["lly"])
                br = float(b["urx"]); bt = float(b["ury"])
            except (KeyError, TypeError, ValueError):
                continue
            x = (bl - llx) * sx
            w = (br - bl) * sx
            # Flip Y: image top is ury.
            y = (ury - bt) * sy
            h = (bt - bb) * sy
            out.append({"x": round(x, 2), "y": round(y, 2),
                        "w": round(max(w, 1.0), 2), "h": round(max(h, 1.0), 2), "rule": rule})
    return out
