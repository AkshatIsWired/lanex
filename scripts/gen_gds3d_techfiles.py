"""Generator for lanex/data/gds3d/*.txt (kept for re-generation; not shipped).

Numbers are transcribed from the PDK files named in each header; run with the
output dir as argv[1].
"""
import sys
from pathlib import Path

LICENSE = """\
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
#
"""

FORMAT = """\
#
# Format: GDS3D process file (gds3d -p <this file>). Height and Thickness are
# in nanometres from the top of the substrate. LanEx's in-app 3D view reads
# the same file. Layers not listed here are not drawn in 3D.
"""


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def block(name, layer, dt, height, thick, color, metal):
    r, g, b = hexrgb(color)
    return (f"LayerStart: {name}\nLayer: {layer}\nDatatype: {dt}\n"
            f"Height: {height:g}\nThickness: {thick:g}\n"
            f"Red: {r:.2f}\nGreen: {g:.2f}\nBlue: {b:.2f}\nFilter: 0.0\n"
            f"Metal: {1 if metal else 0}\nShow: 1\nLayerEnd\n")


def write(out, stem, header, layers):
    text = LICENSE + header + FORMAT + "\n" + "\n".join(block(*L) for L in layers)
    (out / f"{stem}.txt").write_text(text, encoding="utf-8", newline="\n")


# ------------------------------------------------------------------ gf180mcu
# open_pdks 54435919 gf180mcu<V>/libs.tech/magic/gf180mcu<V>.tech, extract
# section ("units microns"): height <layer> <bottom> <thickness>. Colours from
# libs.tech/klayout/tech/gf180mcu.lyp. GDS numbers from the Magic cifoutput
# "calma" lines / gf180mcu.lyp.
GF_COL = {
    "Nwell": "#f9946b", "LVPWELL": "#3a2888", "COMP": "#bd74bd", "Poly2": "#2e9521",
    "Contact": "#c86634", "Metal1": "#eddd07", "Via1": "#f5e7f1", "Metal2": "#ccf338",
    "Via2": "#e1d8ca", "Metal3": "#97b91b", "Via3": "#53e2e8", "Metal4": "#80317c",
    "Via4": "#a7b1d1", "Metal5": "#cdc16b", "MetalTop": "#b1dd9c",
}
GF_GDS = {
    "Nwell": (21, 0), "LVPWELL": (204, 0), "COMP": (22, 0), "Poly2": (30, 0), "Contact": (33, 0),
    "Metal1": (34, 0), "Via1": (35, 0), "Metal2": (36, 0), "Via2": (38, 0), "Metal3": (42, 0),
    "Via3": (40, 0), "Metal4": (46, 0), "Via4": (41, 0), "Metal5": (81, 0), "MetalTop": (53, 0),
}
# (name, bottom nm, thickness nm, metal?) in Magic's order.
GF_FEOL = [("Nwell", 0, 14.5, False), ("LVPWELL", 0, 14.5, False), ("COMP", 14.5, 300, False),
           ("Poly2", 320, 200, False), ("Contact", 314.5, 915.5, True)]
GF_BEOL = [("Metal1", 1230, 550), ("Via1", 1780, 600), ("Metal2", 2380, 550), ("Via2", 2930, 600),
           ("Metal3", 3530, 550), ("Via3", 4080, 600), ("Metal4", 4680, 550), ("Via4", 5230, 600),
           ("Metal5", 5830, 0)]
# variant -> (metal count, top-metal thickness nm, the Magic device that says so)
GF_VAR = {"A": (3, 3000, "tm30k"), "B": (4, 1100, "tm11k"), "C": (5, 900, "tm9k"), "D": (5, 1100, "tm11k")}


def gf180(out):
    for v, (nm, top_t, dev) in GF_VAR.items():
        beol = GF_BEOL[:2 * nm - 1]
        top_name, top_h, _ = beol[-1]
        hdr = f"""\
# LanEx GDS3D process file: GlobalFoundries GF180MCU, variant gf180mcu{v}
# ({nm} metal layers; Metal{nm} is the top metal).
#
# Where the numbers come from (open_pdks 54435919, as installed by LanEx/ciel):
#   heights   gf180mcu{v}/libs.tech/magic/gf180mcu{v}.tech, extract section
#             ("units microns"; "height <layer> <bottom> <thickness>").
#   top metal Magic lists one generic 1.0025 um thickness for the top metal in
#             every variant; its device section names gf180mcu{v}'s top metal
#             {dev} ({top_t / 1000:g} um), which is used here instead.
#   GDS layer gf180mcu{v}.tech cifoutput "calma" lines; colours from
#             libs.tech/klayout/tech/gf180mcu.lyp.
# Contact (33/0) is one GDS layer for both diffusion and poly contacts; it is
# drawn as the diffusion contact (COMP top up to Metal1), as Magic does.
# MetalTop (53/0) is GF's name for the top metal in its own layer table; open_pdks
# streams the top metal on Metal{nm}'s number, so MetalTop shares its slot.
# DNWELL (12/0) has zero thickness in Magic's table and is left out, as are the
# pad opening and every marker layer.
"""
        layers = []
        for name, h, t, metal in GF_FEOL:
            L, D = GF_GDS[name]
            layers.append((name, L, D, h, t, GF_COL[name], metal))
        for name, h, t in beol:
            if name == top_name:
                t = top_t
            L, D = GF_GDS[name]
            layers.append((name, L, D, h, t, GF_COL[name], True))
        L, D = GF_GDS["MetalTop"]
        layers.append(("MetalTop", L, D, top_h, top_t, GF_COL["MetalTop"], True))
        write(out, f"gf180mcu{v}", hdr, layers)


# ------------------------------------------------------------------ IHP SG13G2
# ihp-sg13g2/libs.tech/klayout/tech/d25/sg13g2_beol.lyd25 (IHP Open PDK,
# Apache-2.0): z(<layer>, zstart: <um>, height: <um>, color: <hex>).
IHP = [
    ("Activ", 1, 0, 0, 400, "#00ff00", False),
    ("GatPoly", 5, 0, 400, 140, "#0000ff", False),
    ("Cont", 6, 0, 400, 640, "#00ffff", True),
    ("Metal1", 8, 0, 1040, 420, "#39bfff", True),
    ("Via1", 19, 0, 1460, 540, "#ccccff", True),
    ("Metal2", 10, 0, 2000, 490, "#ccccd9", True),
    ("Via2", 29, 0, 2490, 540, "#ff3736", True),
    ("Metal3", 30, 0, 3030, 490, "#d80000", True),
    ("Via3", 49, 0, 3520, 540, "#9ba940", True),
    ("Metal4", 50, 0, 4060, 490, "#93e837", True),
    ("Via4", 66, 0, 4550, 540, "#deac5e", True),
    ("Metal5", 67, 0, 5090, 490, "#dcd146", True),
    ("MIM", 36, 0, 5604, 150, "#268c6b", True),
    ("Vmim", 129, 0, 5754, 676, "#c0c0c0", True),
    ("TopVia1", 125, 0, 5580, 850, "#ffe6bf", True),
    ("TopMetal1", 126, 0, 6430, 2000, "#ffe6bf", True),
    ("TopVia2", 133, 0, 8430, 2800, "#ff8000", True),
    ("TopMetal2", 134, 0, 11230, 3000, "#ff8000", True),
]


def ihp(out):
    hdr = """\
# LanEx GDS3D process file: IHP SG13G2 (ihp-sg13g2), 5 thin metals + TopMetal1/2.
#
# Where the numbers come from: the PDK's own 2.5D stack,
# ihp-sg13g2/libs.tech/klayout/tech/d25/sg13g2_beol.lyd25 (IHP Open PDK,
# Apache-2.0), "z(<layer>, zstart, height, color)" lines, with the GDS numbers
# from that file's input() lines (they match libs.tech/klayout/tech/sg13g2.lyp).
# Activ is 1/0 (GDS3D's upstream sg13g2.txt has it on layer 0, so it never drew).
# Cont (6/0) is drawn as the contact down to Activ (the stack's Cont->Activ);
# its contacts onto GatPoly are the same GDS layer. The stack file has no wells
# or implants, so none are drawn.
"""
    write(out, "ihp-sg13g2", hdr, IHP)


# ------------------------------------------------------------------ sky130
# open_pdks sky130A/libs.tech/magic/sky130A.tech extract section (units
# microns). Colours from libs.tech/klayout/tech/sky130A.lyp.
SKY = [
    ("dnwell", 64, 18, -100, 100, "#c8ffc8", False),
    ("nwell", 64, 20, 0, 206.2, "#00cc66", False),
    ("diff", 65, 20, 206.2, 120, "#00ff00", False),
    ("tap", 65, 44, 206.2, 120, "#d9cc00", False),
    ("poly", 66, 20, 326.2, 180, "#ff0000", False),
    ("licon1", 66, 44, 326.2, 610, "#ffffcc", True),
    ("li1", 67, 20, 936.1, 100, "#ffe6bf", True),
    ("mcon", 67, 44, 1036.1, 340, "#ccccd9", True),
    ("met1", 68, 20, 1376.1, 360, "#0000ff", True),
    ("via", 68, 44, 1736.1, 270, "#5e00e6", True),
    ("met2", 69, 20, 2006.1, 360, "#ff00ff", True),
    ("via2", 69, 44, 2366.1, 420, "#ff8000", True),
    ("met3", 70, 20, 2786.1, 845, "#00ffff", True),
    ("via3", 70, 44, 3631.1, 390, "#268c6b", True),
    ("met4", 71, 20, 4021.1, 845, "#5e00e6", True),
    ("via4", 71, 44, 4866.1, 505, "#ffff00", True),
    ("met5", 72, 20, 5371.1, 1260, "#d9cc00", True),
    ("rdl", 74, 20, 7261.1, 3000, "#e61f0d", True),
]


# sky130B: same front end, a thicker via (0.565 um), so everything from met2 up
# sits 0.295 um higher (sky130B.tech extract section).
SKY_B = {"via": (1736.1, 565), "met2": (2301.1, 360), "via2": (2661.1, 420), "met3": (3081.1, 845),
         "via3": (3926.1, 390), "met4": (4316.1, 845), "via4": (5161.1, 505), "met5": (5666.1, 1260),
         "rdl": (7556.1, 3000)}


def sky130(out):
    for v in ("A", "B"):
        hdr = f"""\
# LanEx GDS3D process file: SkyWater SKY130, variant sky130{v}.
#
# Where the numbers come from (open_pdks 54435919, as installed by LanEx/ciel):
# sky130{v}/libs.tech/magic/sky130{v}.tech, extract section ("units microns";
# "height <layer> <bottom> <thickness>"); GDS numbers and colours from
# libs.tech/klayout/tech/sky130{v}.lyp. licon1 (66/44) is drawn as the diffusion
# contact (diff top up to li1). MiM capacitor and marker layers are left out.
"""
        layers = SKY if v == "A" else [
            (n, L, D) + (SKY_B[n] if n in SKY_B else (h, t)) + (c, m) for n, L, D, h, t, c, m in SKY]
        write(out, f"sky130{v}", hdr, layers)


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    gf180(out)
    ihp(out)
    sky130(out)
