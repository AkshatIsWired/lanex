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
"""3D GDS geometry extraction (Phase 4.2, shipped as a plugin).

A klayout ``pya`` script (klayout is in the LibreLane image) reads polygons +
the PDK layer z-stack and emits a compact JSON the browser extrudes with
three.js. This module owns the script + the run argv + the geometry-JSON schema
validator (the testable parts). Zero new Python dependency — three.js is vendored
front-end only; the extraction reuses klayout from the image.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import container_run

# klayout pya script: for each layer, read polygons and emit
# {units, layers:[{name,color,zmin,zmax,polys:[[ [x,y], ... ], ...]}]}.
# Z-heights come from a layer-stack map passed as JSON (PDK-specific); when none
# is supplied each layer gets a unit thickness stacked in layer order so the
# model is still meaningful.
KLAYOUT_EXTRACT_SCRIPT = r'''
import json, sys, pya
inp, outp = sys.argv[1], sys.argv[2]
stack = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
ly = pya.Layout(); ly.read(inp); dbu = ly.dbu
top = ly.top_cell()
out = {"units": dbu, "layers": []}
z = 0.0
for li in ly.layer_indexes():
    info = ly.get_info(li)
    key = "%d/%d" % (info.layer, info.datatype)
    zinfo = stack.get(key, {})
    zmin = zinfo.get("zmin", z); zmax = zinfo.get("zmax", z + 1.0)
    polys = []
    it = top.begin_shapes_rec(li)
    n = 0
    while not it.at_end() and n < 20000:
        sh = it.shape()
        if sh.is_polygon() or sh.is_box() or sh.is_path():
            poly = sh.polygon if sh.is_polygon() else sh.bbox().to_p()
            pts = [[p.x*dbu, p.y*dbu] for p in poly.each_point_hull()]
            if pts:
                polys.append(pts); n += 1
        it.next()
    if polys:
        out["layers"].append({"name": key, "gds_layer": info.layer, "datatype": info.datatype,
                              "color": zinfo.get("color", "#888888"), "zmin": zmin, "zmax": zmax,
                              "polys": polys})
    z += 1.0
with open(outp, "w") as f:
    json.dump(out, f)
print("OK")
'''


def extract_argv(*, engine: Optional[str], image: Optional[str], run_mode: str,
                 gds_path: str, out_json: str, script_path: str,
                 stack_json: str = "{}", mount_dir: Optional[str] = None) -> List[str]:
    """argv to run the geometry extractor (engine-wrapped in container mode).

    ``mount_dir`` (absolute run dir) is mounted at ``/work``; the gds/out/script
    paths are relative to it. Must be explicit — a relative path would resolve
    against the server CWD, mounting the wrong dir (errno=2 on the GDS)."""
    inner = ["klayout", "-z", "-nc", "-b", "-r", script_path, gds_path, out_json, stack_json]
    if run_mode == "container":
        img = image or container_run.image_ref()
        mount = str(Path(mount_dir).resolve()) if mount_dir else str(Path.cwd())
        return [engine or "docker", "run", "--rm", "-v",
                f"{mount}:/work", "-w", "/work", img] + inner
    return inner


def validate_geometry(doc: Any) -> Dict[str, Any]:
    """Validate the extractor's JSON shape before the browser consumes it.

    Returns ``{ok, layers, polygons}`` summary or ``{ok: False, error}``. Pure —
    used both by the endpoint and by tests against a fixture (no klayout needed)."""
    if not isinstance(doc, dict):
        return {"ok": False, "error": "geometry must be an object"}
    layers = doc.get("layers")
    if not isinstance(layers, list):
        return {"ok": False, "error": "missing 'layers' array"}
    poly_count = 0
    for layer in layers:
        if not isinstance(layer, dict):
            return {"ok": False, "error": "a layer is not an object"}
        for k in ("name", "zmin", "zmax", "polys"):
            if k not in layer:
                return {"ok": False, "error": f"layer missing '{k}'"}
        if not isinstance(layer["polys"], list):
            return {"ok": False, "error": "layer.polys must be a list"}
        poly_count += len(layer["polys"])
    return {"ok": True, "layers": len(layers), "polygons": poly_count}
