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
"""Live layout viewing for the Layout tab, drawn by KLayout itself.

LibreLane already depends on the ``klayout`` Python package, and from 0.28 on
that package carries KLayout's own renderer (``klayout.lay.LayoutView``)
without Qt. So the app can show a run's layout exactly as KLayout draws it,
with the PDK's layer properties (.lyp), at any zoom, without opening a window.
This is the approach of gdsfactory's kweb and OpenROAD's web viewer: the
server draws the requested viewport, the browser shows the picture and does
the interaction.

What a run offers (:func:`sources`):

* ``final``: the signoff GDS (``final/gds``), full transistor-level detail;
* one snapshot per flow stage (floorplan, power grid, placement, clock tree,
  routing), read from the DEF that stage's step wrote, with the standard cells
  as their LEF abstracts (outline + pins), the way LibreLane's own
  ``OpenInKLayout`` flow opens a DEF;
* every other step that wrote a DEF, for anyone who wants a particular step.

Nothing here computes silicon numbers: geometry, layer names and colours come
straight from KLayout and the PDK files the run itself used (``resolved.json``).
KLayout objects are not thread-safe, so every call holds one lock.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import flowstages

_log = logging.getLogger(__name__)

_LOCK = threading.RLock()
_SESSIONS: "OrderedDict[str, _Session]" = OrderedDict()
_MAX_SESSIONS = 4
_THUMBS: "OrderedDict[Tuple, bytes]" = OrderedDict()
_MAX_THUMBS = 48

# Render limits: a 4K export with 2x oversampling is the biggest legitimate ask.
_MAX_PX = 8192
_MAX_MARKERS = 4000
_MAX_INSTANCES = 30000
_MAX_LABELS = 6000

# Flow stages that leave a picture, in flow order, named as on every other page
# (flowstages.py). Each is shown from the LAST step (by ordinal) whose name
# matches one of its patterns and that wrote a DEF. Patterns match the step dir
# name after "NN-".
_SNAPSHOT_STEPS = {
    "floorplan": ["openroad-floorplan", "openroad-cutrows", "openroad-tapendcapinsertion"],
    "pdn": ["openroad-generatepdn"],
    "placement": ["openroad-globalplacement", "openroad-repairdesignpostgpl", "openroad-detailedplacement"],
    "cts": ["openroad-cts", "openroad-resizertimingpostcts"],
    "routing": ["openroad-globalrouting", "openroad-detailedrouting"],
}
STAGES: List[Dict[str, Any]] = [
    {"id": sid, "label": flowstages.stage(sid)["label"], "blurb": flowstages.stage(sid)["blurb"], "match": m}
    for sid, m in _SNAPSHOT_STEPS.items()
]
_FINAL_BLURB = ("The signoff GDS: every cell with its real transistor-level shapes, plus fill. "
                "This is the file that goes to the foundry.")

# Report databases that carry marker geometry, newest step of each wins.
_MARKER_SOURCES = [
    {"id": "klayout-drc", "label": "KLayout DRC", "step": "klayout-drc", "glob": "reports/*.lyrdb"},
    {"id": "magic-drc", "label": "Magic DRC", "step": "magic-drc", "glob": "reports/*.lyrdb"},
    {"id": "route-drc", "label": "Routing DRC", "step": "openroad-detailedrouting", "glob": "*.drc.xml"},
    {"id": "xor", "label": "Magic vs KLayout XOR", "step": "klayout-xor", "glob": "*.xml"},
]


# --------------------------------------------------------------------------- availability
def available() -> Dict[str, Any]:
    """Is KLayout's renderer importable here? (It ships with LibreLane.)"""
    try:
        import klayout.db as kdb  # noqa: F401
        import klayout.lay as klay
        ok = hasattr(klay, "LayoutView")
        ver = ""
        try:
            import klayout
            ver = getattr(klayout, "__version__", "") or ""
        except Exception:
            pass
        if not ver:
            try:
                from importlib.metadata import version
                ver = version("klayout")
            except Exception:
                ver = ""
        return {"ok": ok, "version": ver,
                "reason": "" if ok else "this klayout package has no LayoutView (needs 0.28 or newer)"}
    except Exception as ex:
        return {"ok": False, "version": "", "reason": "the klayout Python package is not installed (" + str(ex) + ")"}


# --------------------------------------------------------------------------- run helpers
def _ordinal(name: str) -> int:
    head = name.split("-", 1)[0]
    return int(head) if head.isdigit() else -1


def _step_dirs(run_dir: Path) -> List[Path]:
    try:
        dirs = [d for d in run_dir.iterdir() if d.is_dir() and _ordinal(d.name) >= 0 and "-" in d.name]
    except Exception:
        return []
    return sorted(dirs, key=lambda d: _ordinal(d.name))


def _step_key(name: str) -> str:
    """``35-openroad-cts`` / ``36-openroad-stamidpnr-1`` -> ``openroad-cts`` / ``openroad-stamidpnr``."""
    rest = name.split("-", 1)[1] if "-" in name else name
    return re.sub(r"-\d+$", "", rest)


def _def_in(step_dir: Path) -> Optional[Path]:
    try:
        hits = sorted(step_dir.glob("*.def"))
    except Exception:
        return None
    return hits[0] if hits else None


def _final_gds(run_dir: Path) -> Optional[Path]:
    for sub in ("gds", "klayout_gds", "mag_gds"):
        d = run_dir / "final" / sub
        if d.is_dir():
            hits = sorted(d.glob("*.gds")) + sorted(d.glob("*.gds.gz"))
            if hits:
                return hits[0]
    return None


def _resolved(run_dir: Path) -> Dict[str, Any]:
    for name in ("resolved.json", "config.json"):
        f = run_dir / name
        if f.is_file():
            try:
                return json.loads(f.read_text(encoding="utf-8", errors="replace")) or {}
            except Exception:
                continue
    return {}


def _pdk_tech_dir(cfg: Dict[str, Any]) -> Optional[Path]:
    """``<PDK_ROOT>/<PDK>/libs.tech/klayout/tech`` when the run's own paths moved."""
    pdk = cfg.get("PDK")
    if not pdk:
        return None
    roots: List[Path] = []
    if cfg.get("PDK_ROOT"):
        roots.append(Path(str(cfg["PDK_ROOT"])))
    try:
        from . import pdk as pdk_mod
        roots.extend(pdk_mod._candidate_pdk_roots())
    except Exception:
        pass
    for r in roots:
        d = r / str(pdk) / "libs.tech" / "klayout" / "tech"
        if d.is_dir():
            return d
    return None


def _existing(p: Any) -> Optional[str]:
    if not p:
        return None
    try:
        return str(p) if Path(str(p)).is_file() else None
    except Exception:
        return None


def _tech_files(cfg: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """The run's KLayout .lyp / .map (falling back to the PDK's klayout/tech dir)."""
    lyp = _existing(cfg.get("KLAYOUT_PROPERTIES"))
    lym = _existing(cfg.get("KLAYOUT_DEF_LAYER_MAP"))
    if not (lyp and lym):
        d = _pdk_tech_dir(cfg)
        if d is not None:
            lyp = lyp or next((str(p) for p in sorted(d.glob("*.lyp"))), None)
            lym = lym or next((str(p) for p in sorted(d.glob("*.map"))), None)
    return {"lyp": lyp, "lym": lym}


def _lef_list(cfg: Dict[str, Any]) -> List[str]:
    """Tech LEF first, then cell LEFs and any macro LEFs (as LibreLane passes them)."""
    out: List[str] = []
    tl = cfg.get("TECH_LEFS")
    if isinstance(tl, dict):
        pick = tl.get("nom_*") or next(iter(tl.values()), None)
        if pick:
            out.append(str(pick))
    elif isinstance(tl, (list, tuple)) and tl:
        out.append(str(tl[0]))
    elif isinstance(tl, str):
        out.append(tl)
    for key in ("CELL_LEFS", "EXTRA_LEFS"):
        v = cfg.get(key)
        if isinstance(v, str):
            out.extend(v.split())
        elif isinstance(v, (list, tuple)):
            out.extend(str(x) for x in v)
    macros = cfg.get("MACROS")
    if isinstance(macros, dict):
        for m in macros.values():
            if isinstance(m, dict):
                for lef in m.get("lef") or []:
                    out.append(str(lef))
    return [p for p in out if Path(p).is_file()]


def _odb_in(step_dir: Path, run_dir: Path) -> Optional[str]:
    """The step's own OpenROAD database, when the run kept it on disk."""
    try:
        hits = sorted(step_dir.glob("*.odb"))
    except Exception:
        return None
    return hits[0].relative_to(run_dir).as_posix() if hits else None


def sources(run_dir: Path) -> Dict[str, Any]:
    """What can be viewed for a run: the final GDS and one snapshot per stage."""
    run_dir = Path(run_dir)
    steps = _step_dirs(run_dir)
    with_def = [(d, _def_in(d)) for d in steps]
    with_def = [(d, p) for d, p in with_def if p is not None]
    stages: List[Dict[str, Any]] = []
    for st in STAGES:
        pick = None
        for d, p in with_def:
            if _step_key(d.name) in st["match"]:
                pick = (d, p)
        if pick is not None:
            d, p = pick
            stages.append({"id": st["id"], "label": st["label"], "blurb": st["blurb"], "kind": "def",
                           "source": d.name, "step": d.name, "path": p.relative_to(run_dir).as_posix(),
                           "odb": _odb_in(d, run_dir)})
    gds = _final_gds(run_dir)
    if gds is not None:
        stages.append({"id": "final", "label": "Final GDS", "blurb": _FINAL_BLURB, "kind": "gds",
                       "source": "final", "step": "final", "path": gds.relative_to(run_dir).as_posix()})
    all_steps = [{"source": d.name, "step": d.name, "path": p.relative_to(run_dir).as_posix(), "kind": "def",
                  "odb": _odb_in(d, run_dir)} for d, p in with_def]
    variants = []
    for sub, label in (("gds", "Signoff GDS"), ("klayout_gds", "KLayout stream-out"), ("mag_gds", "Magic stream-out")):
        dd = run_dir / "final" / sub
        if dd.is_dir():
            for f in sorted(dd.glob("*.gds")):
                variants.append({"source": "final:" + sub, "label": label, "path": f.relative_to(run_dir).as_posix(), "kind": "gds"})
    render = next((p.relative_to(run_dir).as_posix() for p in sorted((run_dir / "final" / "render").glob("*.png"))), None) \
        if (run_dir / "final" / "render").is_dir() else None
    cfg = _resolved(run_dir)
    return {"stages": stages, "steps": all_steps, "variants": variants, "render": render,
            "pdk": cfg.get("PDK"), "scl": cfg.get("STD_CELL_LIBRARY"), "design": cfg.get("DESIGN_NAME")}


def _source_path(run_dir: Path, source: str) -> Tuple[Optional[Path], str]:
    """(file, kind) for a source id from :func:`sources`."""
    if source in ("", "final"):
        return _final_gds(run_dir), "gds"
    if source.startswith("final:"):
        sub = source.split(":", 1)[1]
        if sub not in ("gds", "klayout_gds", "mag_gds"):
            return None, ""
        d = run_dir / "final" / sub
        hits = sorted(d.glob("*.gds")) if d.is_dir() else []
        return (hits[0] if hits else None), "gds"
    # A step dir: must be a direct child of the run dir.
    d = (run_dir / source).resolve()
    if d.parent != run_dir.resolve() or not d.is_dir():
        return None, ""
    return _def_in(d), "def"


# --------------------------------------------------------------------------- layer naming
_GROUPS = [
    ("metal", "Metal and vias"),
    # gf180 (Contact) and IHP (Cont) have contacts here but no local interconnect.
    ("local", "Contacts and local interconnect"),
    ("device", "Transistor layers"),
    ("well", "Wells and implants"),
    ("pin", "Pins and labels"),
    ("misc", "Boundaries and markers"),
]

# Layer base names across the PDKs LanEx supports: sky130 (met1, via, li1,
# licon1, mcon, diff, poly), gf180mcu (Metal1..Metal5, MetalTop, Via1..Via5,
# Contact, Poly2, COMP, Nplus/Pplus) and ihp-sg13g2 (Metal1..Metal5,
# TopMetal1/2, TopVia1/2, Cont, GatPoly, Activ, nSD/pSD).
_RX_METAL = re.compile(r"^(met\d|metal\d|m\d|topmetal\d?|metaltop|tm\d|rdl)$", re.I)
_RX_VIA = re.compile(r"^(via\d*|v\d|topvia\d?|tv\d|pad)$", re.I)
_RX_LOCAL = re.compile(r"^(li1?|licon\d?|mcon|cont|contact|co)$", re.I)
_RX_DEVICE = re.compile(r"^(diff|tap|poly|poly2|gatpoly|activ|comp|active|od|npc|hvi|hvntm)$", re.I)
_RX_WELL = re.compile(r"(well|implant|^nsdm$|^psdm$|^nsd$|^psd$|^nplus$|^pplus$|^hvtp$|^hvtr$|^lvtn$|^nimp$|^pimp$|^dnwell$|^nwell$|^pwell$|^dualgate$|^thkox$|^sab$)", re.I)
# Purposes that mark a region rather than draw silicon (gf180's metal slots and
# routing blockages), listed with the boundaries and markers.
_MARKER_PURPOSES = ("slot", "blk")

# One plain-English line per common layer, shown in the layer list's tooltip.
_LAYER_WORDS = {
    "met": "metal wiring layer {n}; higher numbers sit higher in the stack and carry longer wires",
    "metal": "metal wiring layer {n}",
    "via": "via: a vertical plug that joins the metal layer below to the one above",
    "mcon": "contact from local interconnect (li1) up to metal 1",
    "licon": "contact from diffusion or poly up to local interconnect (li1)",
    "li": "local interconnect: a thin wiring layer right above the transistors",
    "poly": "polysilicon: where poly crosses diffusion, a transistor gate is formed",
    "diff": "diffusion: the active silicon where transistors are made",
    "tap": "well tap: ties the wells to the power rails",
    "nwell": "n-well: the region where PMOS transistors are built",
    "pwell": "p-well: the region where NMOS transistors are built",
    "dnwell": "deep n-well: isolates a region from the substrate",
    "nsdm": "n+ implant: marks n-type source/drain regions",
    "psdm": "p+ implant: marks p-type source/drain regions",
    "npc": "nitride poly cut: opening for poly contacts",
    "hvtp": "high-Vt PMOS implant",
    "areaid": "area ID: a marker layer that tells rule decks what a region is",
    "prboundary": "placement boundary: the outline each cell or block reserves",
    "boundary": "design boundary",
    "contact": "contact: a plug from diffusion or poly up to metal 1",
    "topmetal": "thick top metal: carries power and long wires",
    "nplus": "n+ implant: marks n-type source/drain regions",
    "pplus": "p+ implant: marks p-type source/drain regions",
}
# Other PDKs' names for the same layers.
_WORD_ALIAS = {"poly2": "poly", "gatpoly": "poly", "comp": "diff", "activ": "diff", "active": "diff",
               "cont": "contact", "metaltop": "topmetal", "lvpwell": "pwell",
               "nsd": "nplus", "psd": "pplus"}

_RX_LD = re.compile(r"(\d+)/(\d+)")
# gf180mcu marks the purpose with a suffix ("Metal1_Label") where sky130 uses
# ".label"; a .lyp that names a layer only in its source carries it there.
_RX_SUFFIX_PURPOSE = re.compile(r"^(.+?)_(label|dummy|slot|blk|res|text|pin)$", re.I)


def _split_name(name: str) -> Tuple[str, str, str]:
    """``met1.drawing - 68/20`` -> (``met1``, ``drawing``, ``68/20``)."""
    src = ""
    m = re.search(r"\s-\s*(\d+/\d+)\s*$", name or "")
    if m:
        src = m.group(1)
        name = name[:m.start()]
    base, _, purpose = (name or "").strip().partition(".")
    return base.strip(), purpose.strip(), src


def _layer_ident(name: str, source: str) -> Tuple[str, str, str, str]:
    """(base, purpose, ``"l/d"``, label) of one layer-properties entry.

    sky130's .lyp names layers ``met1.drawing - 68/20`` (source ``68/20@1``);
    ihp-sg13g2's ``Activ.drawing`` (source ``1/0``); gf180mcu's leaves the name
    empty and puts it in the source (``Metal1_Label 34/10@1``). ``"l/d"`` is
    what the 3D stack is keyed by, so it must never keep the name text; the
    label is what the layer list shows, in the PDK's own spelling."""
    base, purpose, src = _split_name(name or "")
    if not base:
        spec = (source or "").split("@", 1)[0].strip()
        m = _RX_LD.search(spec)
        if m:
            src = src or m.group(0)
            spec = (spec[:m.start()] + spec[m.end():]).strip()
        base, _, purpose = spec.partition(".")
        base, purpose = base.strip(), purpose.strip()
        if not base:
            base = src
    if not src:
        m = _RX_LD.search(source or "")
        src = m.group(0) if m else ""
    label = (base + ("." + purpose if purpose else "")) or src
    if not purpose:
        m = _RX_SUFFIX_PURPOSE.match(base)
        if m:
            base, purpose = m.group(1), m.group(2).lower()
    return base, purpose, src, label


def _group_of(base: str, purpose: str) -> str:
    p = purpose.lower()
    if p in ("pin", "label", "text", "net", "port"):
        return "pin"
    if p in _MARKER_PURPOSES:
        return "misc"
    b = base.lower()
    if _RX_LOCAL.match(b):
        return "local"
    if _RX_METAL.match(b) or _RX_VIA.match(b):
        return "metal"
    if _RX_WELL.search(b):
        return "well"
    if _RX_DEVICE.match(b):
        return "device"
    if b.startswith(("met", "metal", "via")):
        return "metal"
    return "misc"


def _layer_words(base: str) -> str:
    b = base.lower()
    m = re.match(r"^(met|metal)(\d)$", b)
    if m:
        return _LAYER_WORDS[m.group(1)].format(n=m.group(2))
    if re.match(r"^(?:top)?via(\d*)$", b):
        return _LAYER_WORDS["via"]
    if re.match(r"^topmetal\d?$", b):
        return _LAYER_WORDS["topmetal"]
    b = _WORD_ALIAS.get(b, b)
    for k, v in _LAYER_WORDS.items():
        if b == k or (k in ("licon", "li") and b.startswith(k)):
            return v
    return ""


_RX_Z_METAL = re.compile(r"^(?:met|metal|m)(\d)$")
_RX_Z_VIA = re.compile(r"^(?:via|v)(\d*)$")
_RX_Z_TOPMETAL = re.compile(r"^(?:topmetal|tm)(\d?)$")
_RX_Z_TOPVIA = re.compile(r"^(?:topvia|tv)(\d?)$")


def _z_rank(base: str, purpose: str) -> float:
    """Rough stacking order, top first, so a click reports the top shape first.

    Metal n sits at 10 + 2n with via n just above it (via1 between metal1 and
    metal2); IHP's TopVia1 < TopMetal1 < TopVia2 < TopMetal2 above the thin
    metals; contacts (licon, Cont, Contact) under li/metal1, poly above
    diffusion, wells at the bottom."""
    b = base.lower()
    m = _RX_Z_METAL.match(b)
    mv = _RX_Z_VIA.match(b)
    mt = _RX_Z_TOPMETAL.match(b)
    mtv = _RX_Z_TOPVIA.match(b)
    if m:
        z = 10 + 2 * int(m.group(1))
    elif mv:
        z = 11 + 2 * int(mv.group(1) or 1)
    elif mt:
        z = 28 + 2 * int(mt.group(1) or 1)      # TopMetal1 30, TopMetal2 32
    elif mtv:
        z = 27 + 2 * int(mtv.group(1) or 1)     # TopVia1 29, TopVia2 31
    elif b == "metaltop":
        z = 30
    elif b == "rdl":
        z = 34
    elif b == "pad":
        z = 36
    elif b == "mcon":
        z = 9
    elif b.startswith("licon") or b in ("cont", "contact", "co"):
        z = 7
    elif b.startswith("li"):
        z = 8
    elif b in ("poly", "poly2", "gatpoly"):
        z = 5
    elif b in ("diff", "tap", "activ", "active", "comp", "od"):
        z = 4
    elif _RX_WELL.search(b):
        z = 1
    else:
        z = 0
    if purpose.lower() in ("pin", "label", "text"):
        z += 0.5
    return z


def _hex(c: int) -> str:
    return "#%06x" % (int(c) & 0xFFFFFF)


# --------------------------------------------------------------------------- sessions
class _Session:
    """One loaded layout (a run's GDS or a stage DEF) in a headless LayoutView."""

    def __init__(self, sid: str, path: Path, kind: str, cfg: Dict[str, Any]):
        import klayout.db as kdb
        import klayout.lay as klay

        self.sid = sid
        self.path = path
        self.kind = kind
        self.mtime = path.stat().st_mtime
        self.used = time.time()
        self.notes: List[str] = []
        tech = _tech_files(cfg)
        v = klay.LayoutView()
        if kind == "def":
            lefs = _lef_list(cfg)
            if not lefs:
                raise RuntimeError("the run's tech and cell LEF files are missing, so this DEF can't be drawn")
            opt = kdb.LoadLayoutOptions()
            c = opt.lefdef_config
            c.macro_resolution_mode = 1          # LEF abstracts for cells (as OpenInKLayout)
            c.read_lef_with_def = False
            c.lef_files = lefs
            if tech["lym"]:
                c.map_file = tech["lym"]
            else:
                self.notes.append("No LEF/DEF layer map found, so layers keep KLayout's generic names.")
            c.produce_cell_outlines = True
            v.load_layout(str(path), opt, True)
        else:
            v.load_layout(str(path), True)
        if tech["lyp"]:
            try:
                v.load_layer_props(tech["lyp"])
            except Exception:
                self.notes.append("The PDK layer properties could not be loaded; showing KLayout's default colours.")
        else:
            self.notes.append("No PDK layer properties (.lyp) found; showing KLayout's default colours.")
        for k, val in (("grid-visible", "false"), ("grid-show-ruler", "false"),
                       ("background-color", "#06080d"), ("text-visible", "true"),
                       ("cell-box-text-transform", "true"), ("min-inst-label-size", "120"),
                       ("cell-box-color", "#8ea6c4"),
                       # A vector font scales with the zoom: labels stay out of
                       # the way at fit and become readable as you zoom in (the
                       # page draws the chip's I/O names itself, at a fixed size).
                       ("text-font", "2"),
                       ("draw-array-border-instances", "false")):
            try:
                v.set_config(k, val)
            except Exception:
                pass
        v.max_hier()
        v.zoom_fit()
        self.view = v
        self.cv = v.cellview(0)
        self.layout = self.cv.layout()
        self.top = self.cv.cell
        self.dbu = self.layout.dbu
        self.applied: Dict[str, Any] = {}
        self._layers = self._scan_layers()

    # -- layers
    def _scan_layers(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        it = self.view.begin_layers()
        pos = 0
        while not it.at_end():
            lp = it.current()
            li = lp.layer_index()
            empty = True
            if li >= 0:
                try:
                    empty = self.top.dbbox_per_layer(li).empty()
                except Exception:
                    empty = True
            if not empty:
                base, purpose, src, label = _layer_ident(lp.name or "", lp.source or "")
                out.append({
                    "id": pos, "name": base, "purpose": purpose, "src": src,
                    "label": label,
                    "fill": _hex(lp.fill_color), "frame": _hex(lp.frame_color),
                    "dither": int(lp.dither_pattern), "visible": bool(lp.visible),
                    "group": _group_of(base, purpose), "z": _z_rank(base, purpose),
                    "about": _layer_words(base), "li": li,
                })
            it.next()
            pos += 1
        return out

    def info(self) -> Dict[str, Any]:
        bb = self.top.dbbox()
        groups = [{"id": g, "label": lbl} for g, lbl in _GROUPS]
        return {
            "sid": self.sid, "kind": self.kind, "file": self.path.name,
            "top": self.top.name, "dbu": self.dbu,
            "bbox": [bb.left, bb.bottom, bb.right, bb.top],
            "layers": [{k: v for k, v in L.items() if k != "li"} for L in self._layers],
            "groups": groups, "notes": self.notes,
            "cells": self.cell_stats(), "labels": self.labels(),
        }

    def _apply(self, visible: Optional[List[int]], depth: Optional[int], labels: bool,
               bg: str, boxes: bool) -> None:
        v = self.view
        # None keeps what is there (the .lyp defaults until a client sets it).
        want_vis = None if visible is None else set(visible)
        if want_vis is not None and want_vis != self.applied.get("visible", "unset"):
            ids = {L["id"] for L in self._layers}
            it = v.begin_layers()
            pos = 0
            while not it.at_end():
                if pos in ids:
                    on = pos in want_vis
                    node = it.current()
                    if node.visible != on:
                        node.visible = on
                it.next()
                pos += 1
            self.applied["visible"] = want_vis
        if depth != self.applied.get("depth", "unset"):
            v.min_hier_levels = 0
            if depth is None or depth < 0:
                v.max_hier()
            else:
                v.max_hier_levels = int(depth)
            self.applied["depth"] = depth
        if labels != self.applied.get("labels"):
            v.set_config("text-visible", "true" if labels else "false")
            self.applied["labels"] = labels
        if bg != self.applied.get("bg"):
            v.set_config("background-color", bg)
            self.applied["bg"] = bg
        if boxes != self.applied.get("boxes"):
            try:
                v.set_config("cell-box-visible", "true" if boxes else "false")
            except Exception:
                pass
            self.applied["boxes"] = boxes

    def render(self, box: Optional[List[float]], w: int, h: int, *, visible: Optional[List[int]] = None,
               depth: Optional[int] = None, labels: bool = True, bg: str = "#06080d",
               boxes: bool = True, oversampling: int = 1, resolution: float = 0.0) -> bytes:
        import klayout.db as kdb

        self.used = time.time()
        w = max(16, min(_MAX_PX, int(w)))
        h = max(16, min(_MAX_PX, int(h)))
        self._apply(visible, depth, labels, bg, boxes)
        target = kdb.DBox(box[0], box[1], box[2], box[3]) if box else self.top.dbbox()
        os_ = max(1, min(3, int(oversampling)))
        pb = self.view.get_pixels_with_options(w, h, 1, os_, float(resolution or 0.0), target)
        return bytes(pb.to_png_data())

    # -- content
    def cell_stats(self) -> List[Dict[str, Any]]:
        """Cells placed directly in the top cell, with counts (most used first)."""
        counts: Dict[int, int] = {}
        for inst in self.top.each_inst():
            n = inst.size() if inst.is_regular_array() else 1
            counts[inst.cell_index] = counts.get(inst.cell_index, 0) + n
        try:
            from .cells import classify_cell
        except Exception:  # pragma: no cover - cells module always ships
            def classify_cell(_n: str) -> str:
                return "other"
        out = []
        for ci, n in counts.items():
            c = self.layout.cell(ci)
            bb = c.dbbox()
            out.append({"name": c.name, "count": n, "kind": classify_cell(c.name),
                        "w": round(bb.width(), 4), "h": round(bb.height(), 4),
                        "area": round(bb.width() * bb.height() * n, 3),
                        "children": c.child_cells()})
        out.sort(key=lambda r: (-r["count"], r["name"]))
        return out

    def instances(self, cell_name: str) -> Dict[str, Any]:
        """Bounding boxes (top-cell µm) of every placement of one cell type."""
        ci = self.layout.cell_by_name(cell_name) if self.layout.has_cell(cell_name) else None
        boxes: List[List[float]] = []
        total = 0
        if ci is not None:
            for inst in self.top.each_inst():
                if inst.cell_index != ci:
                    continue
                total += 1
                if len(boxes) < _MAX_INSTANCES:
                    bb = inst.dbbox()
                    boxes.append([round(bb.left, 4), round(bb.bottom, 4), round(bb.right, 4), round(bb.top, 4)])
        return {"cell": cell_name, "total": total, "boxes": boxes, "truncated": total > len(boxes)}

    def labels(self) -> List[Dict[str, Any]]:
        """Text labels in the top cell (pin names), for the search box."""
        import klayout.db as kdb

        out: List[Dict[str, Any]] = []
        by_li = {L["li"]: L for L in self._layers}
        for li in self.layout.layer_indexes():
            L = by_li.get(li)
            for s in self.top.shapes(li).each(kdb.Shapes.STexts):
                t = s.dtext
                out.append({"text": t.string, "x": round(t.x, 4), "y": round(t.y, 4),
                            "layer": (L or {}).get("label") or self.layout.get_info(li).to_s()})
                if len(out) >= _MAX_LABELS:
                    return out
        return out

    def probe(self, x: float, y: float, r: float) -> List[Dict[str, Any]]:
        """Shapes under a click on the visible layers, top of the stack first."""
        import klayout.db as kdb

        box = kdb.DBox(x - r, y - r, x + r, y + r)
        vis = self.applied.get("visible")
        hits: List[Dict[str, Any]] = []
        for L in self._layers:
            if vis is not None and L["id"] not in vis:
                continue
            it = self.top.begin_shapes_rec_touching(L["li"], box)
            n = 0
            while not it.at_end() and n < 6:
                shape = it.shape()
                path = it.path()
                inst_cell = None
                inst_box = None
                if path:
                    inst = path[0].inst()
                    inst_cell = self.layout.cell(inst.cell_index).name
                    ib = inst.dbbox()
                    inst_box = [ib.left, ib.bottom, ib.right, ib.top]
                sb = shape.dbbox().transformed(it.dtrans())
                text = shape.text_string if shape.is_text() else None
                hits.append({"layer": L["label"], "src": L["src"], "fill": L["fill"], "z": L["z"],
                             "about": L["about"], "cell": inst_cell, "cell_box": inst_box,
                             "box": [sb.left, sb.bottom, sb.right, sb.top], "text": text,
                             "area": sb.width() * sb.height()})
                n += 1
                it.next()
        hits.sort(key=lambda h: (-h["z"], h["area"]))
        return hits[:40]


def _sid(run_dir: Path, source: str) -> str:
    return str(Path(run_dir).resolve()) + "::" + (source or "final")


def open_session(run_dir: Path, source: str) -> Dict[str, Any]:
    """Load (or reuse) a source of a run and return what the viewer needs."""
    av = available()
    if not av["ok"]:
        return {"ok": False, "error": av["reason"], "need": "klayout"}
    run_dir = Path(run_dir)
    path, kind = _source_path(run_dir, source)
    if path is None or not path.is_file():
        return {"ok": False, "error": "this run has no layout for '" + (source or "final") + "'"}
    sid = _sid(run_dir, source)
    with _LOCK:
        s = _SESSIONS.get(sid)
        if s is not None and s.mtime != path.stat().st_mtime:
            _SESSIONS.pop(sid, None)
            s = None
        if s is None:
            t0 = time.time()
            try:
                s = _Session(sid, path, kind, _resolved(run_dir))
            except Exception as ex:
                _log.exception("layout session open failed")
                return {"ok": False, "error": "KLayout could not read " + path.name + ": " + str(ex)}
            _log.info("layout session %s opened in %.2fs", sid, time.time() - t0)
            _SESSIONS[sid] = s
            while len(_SESSIONS) > _MAX_SESSIONS:
                _SESSIONS.popitem(last=False)
        else:
            _SESSIONS.move_to_end(sid)
        info = s.info()
    info["ok"] = True
    info["klayout"] = av.get("version")
    return info


def session(sid: str) -> Optional[_Session]:
    with _LOCK:
        s = _SESSIONS.get(sid)
        if s is not None:
            _SESSIONS.move_to_end(sid)
        return s


def render(sid: str, **kw: Any) -> Optional[bytes]:
    with _LOCK:
        s = _SESSIONS.get(sid)
        if s is None:
            return None
        return s.render(**kw)


def probe(sid: str, x: float, y: float, r: float) -> Optional[List[Dict[str, Any]]]:
    with _LOCK:
        s = _SESSIONS.get(sid)
        return None if s is None else s.probe(x, y, r)


def instances(sid: str, cell: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        s = _SESSIONS.get(sid)
        return None if s is None else s.instances(cell)


def thumbnail(run_dir: Path, source: str, w: int, h: int, bg: str) -> Optional[bytes]:
    """A small fit-to-window picture of one stage, cached by file mtime."""
    run_dir = Path(run_dir)
    path, kind = _source_path(run_dir, source)
    if path is None or not path.is_file():
        return None
    key = (str(path), path.stat().st_mtime, int(w), int(h), bg)
    with _LOCK:
        if key in _THUMBS:
            _THUMBS.move_to_end(key)
            return _THUMBS[key]
    if not available()["ok"]:
        return None
    with _LOCK:
        # A throwaway view: thumbnails must never push the viewer's own
        # sessions out of the cache (that made the main view expire).
        try:
            s = _Session("thumb", path, kind, _resolved(run_dir))
        except Exception:
            _log.exception("layout thumbnail open failed")
            return None
        png = s.render(None, w, h, visible=None, depth=None, labels=False, bg=bg, boxes=False, oversampling=3)
        _THUMBS[key] = png
        while len(_THUMBS) > _MAX_THUMBS:
            _THUMBS.popitem(last=False)
    return png


# --------------------------------------------------------------------------- markers
_NUM = r"-?\d+(?:\.\d+)?(?:e-?\d+)?"
_RX_PT = re.compile(r"(" + _NUM + r"),(" + _NUM + r")")


def _marker_geom(text: str) -> Optional[Dict[str, Any]]:
    """A report-database ``<value>`` -> {kind, pts (list of rings), bbox} in µm."""
    t = (text or "").strip()
    kind = t.split(":", 1)[0].strip().lower() if ":" in t else ""
    if kind not in ("polygon", "box", "edge", "edge-pair", "path", "point", "text"):
        return None
    rings: List[List[List[float]]] = []
    for chunk in re.split(r"[|/]", t.split(":", 1)[1]):
        pts = [[float(a), float(b)] for a, b in _RX_PT.findall(chunk)]
        if pts:
            rings.append(pts)
    if not rings:
        return None
    if kind == "box" and len(rings[0]) == 2:
        (x1, y1), (x2, y2) = rings[0]
        rings = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return {"kind": kind, "rings": rings, "bbox": [min(xs), min(ys), max(xs), max(ys)]}


def parse_rdb(path: Path) -> Dict[str, Any]:
    """Every category and item of a KLayout report database (streamed)."""
    cats: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    items: List[Dict[str, Any]] = []
    total = 0
    stack: List[str] = []
    cat_names: List[Optional[str]] = []
    try:
        for ev, el in ET.iterparse(str(path), events=("start", "end")):
            tag = el.tag
            if ev == "start":
                if tag == "category" and (stack[-1] if stack else "") != "item":
                    cat_names.append(None)
                stack.append(tag)
                continue
            stack.pop()
            parent = stack[-1] if stack else ""
            if tag == "name" and parent == "category" and cat_names:
                nm = (el.text or "").strip()
                outer = [c for c in cat_names[:-1] if c]
                full = ".".join(outer + [nm]) if outer else nm
                cat_names[-1] = full
                cats.setdefault(full, {"name": full, "description": "", "count": 0})
            elif tag == "description" and parent == "category" and cat_names and cat_names[-1]:
                cats[cat_names[-1]]["description"] = (el.text or "").strip()
            elif tag == "category" and parent != "item":
                if cat_names:
                    cat_names.pop()
            elif tag == "item":
                total += 1
                cat = (el.findtext("category") or "").strip().strip("'").replace("'.'", ".")
                entry = cats.setdefault(cat, {"name": cat, "description": "", "count": 0})
                entry["count"] += 1
                if len(items) < _MAX_MARKERS:
                    geoms = []
                    for val in el.iter("value"):
                        g = _marker_geom(val.text or "")
                        if g:
                            geoms.append(g)
                    if geoms:
                        xs = [g["bbox"][0] for g in geoms] + [g["bbox"][2] for g in geoms]
                        ys = [g["bbox"][1] for g in geoms] + [g["bbox"][3] for g in geoms]
                        items.append({"cat": cat, "geoms": geoms,
                                      "bbox": [min(xs), min(ys), max(xs), max(ys)]})
                el.clear()
    except Exception as ex:
        return {"ok": False, "error": "could not read " + path.name + ": " + str(ex),
                "total": 0, "categories": [], "items": []}
    cl = [c for c in cats.values() if c["count"]]
    cl.sort(key=lambda c: -c["count"])
    return {"ok": True, "total": total, "categories": cl, "items": items,
            "truncated": total > len(items)}


def markers(run_dir: Path) -> Dict[str, Any]:
    """Marker databases the run wrote (DRC, routing DRC, XOR), parsed."""
    run_dir = Path(run_dir)
    steps = _step_dirs(run_dir)
    out = []
    try:
        from . import history
        metrics = history._load_metrics(run_dir)
    except Exception:
        metrics = {}
    metrics_rel = "final/metrics.json" if (run_dir / "final" / "metrics.json").is_file() else "metrics.json"
    for src in _MARKER_SOURCES:
        hit = None
        for d in steps:
            if _step_key(d.name) == src["step"]:
                files = sorted(p for p in d.glob(src["glob"]) if p.is_file())
                if files:
                    hit = files[0]
        if hit is None:
            continue
        res = parse_rdb(hit)
        res.update({"id": src["id"], "label": src["label"], "path": hit.relative_to(run_dir).as_posix()})
        # The metric LibreLane judged the run on (what Verify uses). A report
        # file that disagrees with it (edited, or left over from an earlier
        # run) is shown, and the disagreement said, never silently trusted.
        mkey = _MARKER_METRIC.get(src["id"])
        mval = metrics.get(mkey) if mkey else None
        if isinstance(mval, (int, float)) and not isinstance(mval, bool):
            res["metric"] = {"key": mkey, "value": mval, "file": metrics_rel}
            # Counted as a disagreement only when one side is zero: the tools
            # may count a multi-box error differently, but "no errors" next
            # to markers (or the reverse) is a real contradiction.
            res["disagree"] = bool(res.get("ok")) and (int(mval) == 0) != (int(res.get("total") or 0) == 0)
        out.append(res)
    return {"sources": out}


_MARKER_METRIC = {
    "klayout-drc": "klayout__drc_error__count",
    "magic-drc": "magic__drc_error__count",
}


def viewer_commands(run_dir: Path, tag: str) -> Dict[str, str]:
    """Terminal commands that open this run the way LibreLane users do it."""
    run_dir = Path(run_dir)
    out: Dict[str, str] = {}
    gui: Dict[str, Any] = {}
    try:
        gui = json.loads((run_dir / "gui-run.json").read_text(encoding="utf-8")) or {}
    except Exception:
        gui = {}
    cli = gui.get("cli_command") or {}
    base = cli.get(gui.get("run_mode") or "container") or cli.get("local") or ""
    # Drop any "-f <flow>" / "--flow <flow>" and the -c overrides; the viewer flow
    # reads the run's own state, so only the config, PDK and run tag matter.
    if base:
        base = re.sub(r"\s(?:-f|--flow)\s+\S+", "", base)
        base = re.sub(r"\s-c\s+'[^']*'", "", base)
        base = re.sub(r"\s-c\s+\S+", "", base)
        out["klayout_flow"] = base + " --run-tag " + tag + " --flow OpenInKLayout"
        out["openroad_flow"] = base + " --run-tag " + tag + " --flow OpenInOpenROAD"
    cfg = _resolved(run_dir)
    tech = _tech_files(cfg)
    gds = _final_gds(run_dir)
    if gds is not None:
        parts = ["klayout"]
        lyt = _existing(cfg.get("KLAYOUT_TECH"))
        if lyt:
            parts += ["-nn", lyt]
        if tech["lyp"]:
            parts += ["-l", tech["lyp"]]
        parts.append(str(gds))
        out["klayout"] = " ".join(parts)
    out["cwd"] = str(run_dir.parent.parent)
    return out


# --------------------------------------------------------------------------- 3D
# The in-app 3D view: each layer's merged shapes as flat triangles (the top
# face) plus their outline edges (the browser extrudes the walls), stacked at
# real heights: the PDK's GDS3D process file (LanEx bundles one per supported
# PDK, desktop.gds3d_process_file), else the PDK's own KLayout 2.5D stack
# (libs.tech/klayout/tech/d25/*.lyd25), else an even, honest-looking generic
# spacing (said so in the reply).
_MAX_3D_PRIMS = 2_600_000


def _gds3d_stack(pdk: Optional[str]) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    """``"l/d" -> {name, z0, z1 (µm), color}`` from the PDK's GDS3D process file."""
    try:
        from .desktop import gds3d_process_file
        path = gds3d_process_file(pdk)
    except Exception:
        path = None
    if not path:
        return {}, None
    return _parse_gds3d(path)


def _parse_gds3d(path: str) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    out: Dict[str, Dict[str, Any]] = {}
    cur: Dict[str, str] = {}
    try:
        for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line != "LayerEnd" and ":" not in line:
                continue
            if line == "LayerEnd":
                try:
                    key = cur["Layer"].strip() + "/" + cur.get("Datatype", "0").strip()
                    h = float(cur.get("Height", "0")) / 1000.0
                    t = float(cur.get("Thickness", "0")) / 1000.0
                    rgb = [float(cur.get(c, "0.5")) for c in ("Red", "Green", "Blue")]
                    if cur.get("Show", "1").strip() != "0" and t > 0 and key != "255/0":
                        out[key] = {"name": cur.get("LayerStart", key).strip(), "z0": h, "z1": h + t,
                                    "color": "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c * 255)))) for c in rgb),
                                    "metal": cur.get("Metal", "0").strip() == "1"}
                except Exception:
                    pass
                cur = {}
                continue
            k, _, v = line.partition(":")
            cur[k.strip()] = v.strip()
    except Exception:
        return {}, None
    return out, path


_RX_D25_INPUT = re.compile(r"^\s*(\w+)\s*=\s*input\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*$", re.M)
_RX_D25_Z = re.compile(r"^\s*z\(\s*(?:input\(\s*(\d+)\s*,\s*(\d+)\s*\)|(\w+))\s*,(.*)\)\s*$", re.M)


def _d25_stack(cfg: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    """``"l/d" -> {name, z0, z1, color}`` from the PDK's KLayout 2.5D stack.

    A ``.lyd25`` script declares ``Metal1 = input(8, 0)`` and then
    ``z(Metal1, zstart: 1.04, height: 0.42, color: 0x39bfff)`` in µm. Only
    layers drawn straight from one GDS layer are used; derived ones (boolean
    expressions such as resistor regions) have no single ``l/d`` to key by."""
    d = _pdk_tech_dir(cfg)
    files = sorted((d / "d25").glob("*.lyd25")) if d is not None and (d / "d25").is_dir() else []
    for f in files:
        try:
            raw = f.read_text(encoding="utf-8", errors="replace")
            try:
                text = ET.fromstring(raw).findtext("text") or raw
            except ET.ParseError:
                text = raw
            inputs = {m.group(1): m.group(2) + "/" + m.group(3) for m in _RX_D25_INPUT.finditer(text)}
            out: Dict[str, Dict[str, Any]] = {}
            for m in _RX_D25_Z.finditer(text):
                key = (m.group(1) + "/" + m.group(2)) if m.group(1) else inputs.get(m.group(3) or "")
                if not key or key in out:
                    continue
                args = m.group(4)
                z0 = re.search(r"zstart\s*:\s*(" + _NUM + r")", args)
                h = re.search(r"height\s*:\s*(" + _NUM + r")", args)
                if not (z0 and h) or float(h.group(1)) <= 0:
                    continue
                nm = re.search(r'name\s*:\s*"([^"]*)"', args)
                col = re.search(r"color\s*:\s*0x([0-9a-fA-F]{6})", args)
                out[key] = {"name": nm.group(1) if nm else (m.group(3) or key),
                            "z0": float(z0.group(1)), "z1": float(z0.group(1)) + float(h.group(1)),
                            "color": "#" + (col.group(1).lower() if col else "8ea6c4"), "metal": True}
            if out:
                return out, str(f)
        except Exception:
            continue
    return {}, None


def _generic_stack(layers: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Even spacing by stacking order when no process file is known."""
    out: Dict[int, Dict[str, Any]] = {}
    for L in layers:
        unnamed = re.match(r"^\d+/\d+$", L["name"] or "") is not None   # no .lyp: KLayout's own names
        if L["purpose"].lower() not in ("drawing", "") or (L["group"] not in ("metal", "local", "device") and not unnamed):
            continue
        z = L["z"]
        out[L["id"]] = {"name": L["label"], "z0": z * 0.32, "z1": z * 0.32 + 0.24, "color": L["fill"], "metal": True}
    return out


def mesh(sid: str, box: Optional[List[float]], visible: Optional[List[int]]) -> Optional[bytes]:
    """Binary 3D mesh of a session's layout: ``u32 header length | JSON header |
    float32 data`` (triangles as x,y triples, edges as x1,y1,x2,y2, in µm
    relative to ``origin``)."""
    import struct
    from array import array
    import klayout.db as kdb

    with _LOCK:
        s = _SESSIONS.get(sid)
        if s is None:
            return None
        run_dir = s.path.parent
        while run_dir.parent != run_dir and not (run_dir / "resolved.json").is_file():
            run_dir = run_dir.parent
        cfg = _resolved(run_dir)
        stack, techfile = _gds3d_stack(cfg.get("PDK"))
        kind = "gds3d"
        if not stack:
            stack, techfile = _d25_stack(cfg)
            kind = "d25"
        generic = _generic_stack(s._layers) if not stack else {}
        vis = set(visible) if visible is not None else None
        dbu = s.dbu
        bb = s.top.dbbox()
        clip = None
        if box:
            cb = kdb.DBox(box[0], box[1], box[2], box[3]) & bb
            if not cb.empty() and (cb.width() < bb.width() * 0.98 or cb.height() < bb.height() * 0.98):
                clip = kdb.Region(cb.to_itype(dbu))
        extent = clip.bbox().to_dtype(dbu) if clip is not None else bb
        ox, oy = extent.left, extent.bottom
        layers_out: List[Dict[str, Any]] = []
        dropped: List[str] = []
        tri = array("f")
        edg = array("f")
        prims = 0
        # Top of the stack first: when a whole big chip has more geometry than
        # a browser can hold, the wiring is kept and the dense transistor-level
        # layers below it are left out (and named in the reply), instead of
        # drawing nothing. Nothing at all fitting is still "too_big".
        todo = []
        for L in s._layers:
            if vis is not None and L["id"] not in vis:
                continue
            spec = stack.get(L["src"]) if stack else generic.get(L["id"])
            if spec:
                todo.append((L, spec))
        todo.sort(key=lambda t: (-t[1]["z0"], -t[1]["z1"]))
        for L, spec in todo:
            if dropped:
                dropped.append(spec["name"])
                continue
            r = kdb.Region(s.top.begin_shapes_rec(L["li"]))
            if clip is not None:
                r = r & clip
            r.merge()
            if r.is_empty():
                continue
            # A cheap size check (in KLayout's C++) before the slow Python
            # triangulation: every edge becomes a wall of two triangles.
            if prims + 2 * r.edges().count() > _MAX_3D_PRIMS:
                dropped.append(spec["name"])
                continue
            t0 = len(tri)
            e0 = len(edg)
            for p in r.decompose_trapezoids_to_region().each():
                pts = [(pt.x * dbu - ox, pt.y * dbu - oy) for pt in p.each_point_hull()]
                for i in range(1, len(pts) - 1):
                    tri.extend((pts[0][0], pts[0][1], pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]))
            for e in r.edges().each():
                edg.extend((e.p1.x * dbu - ox, e.p1.y * dbu - oy, e.p2.x * dbu - ox, e.p2.y * dbu - oy))
            nt = (len(tri) - t0) // 6
            ne = (len(edg) - e0) // 4
            if prims + nt + 2 * ne > _MAX_3D_PRIMS:
                del tri[t0:]
                del edg[e0:]
                dropped.append(spec["name"])
                continue
            prims += nt + 2 * ne
            layers_out.append({"id": L["id"], "label": L["label"], "name": spec["name"], "z0": spec["z0"],
                               "z1": spec["z1"], "color": spec["color"], "metal": spec.get("metal", True),
                               "tris": nt, "edges": ne, "triOff": t0, "edgeOff": e0})
        if dropped and not layers_out:
            raise ValueError("too_big")
        head = {"origin": [ox, oy], "extent": [extent.left, extent.bottom, extent.right, extent.top],
                "clipped": clip is not None, "layers": layers_out, "triFloats": len(tri), "edgeFloats": len(edg),
                "dropped": dropped,
                "stack": (kind + ":" + Path(techfile).name) if techfile else "generic",
                "top": s.top.name}
    hb = json.dumps(head).encode("utf-8")
    hb += b" " * ((4 - (len(hb) % 4)) % 4)
    return struct.pack("<I", len(hb)) + hb + tri.tobytes() + edg.tobytes()
