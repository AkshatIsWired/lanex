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
"""Layout and 3D on every PDK LanEx supports: sky130, gf180mcu, ihp-sg13g2.

* the GDS3D process file lookup (LanEx's bundled files, exact name first);
* the bundled files themselves (real, ordered heights; gf180 top metal per
  variant; IHP Activ on 1/0);
* .lyp parsing for gf180mcu, whose layer names live only in the source;
* layer groups and stacking order for gf180 and IHP names;
* the PDK's KLayout 2.5D stack as a fallback;
* the viewer display environment on every launch path (manual console,
  container, the appliance's shell profile).
"""

import json
import struct
from pathlib import Path

import pytest

from lanex.controller import container_tools, desktop, platform_env
from lanex.controller import layoutview as lv

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def no_gds3d_install(tmp_path, monkeypatch):
    """A home with no GDS3D checkout and no gds3d binary: only bundled files."""
    monkeypatch.setenv("LANEX_HOME", str(tmp_path))
    monkeypatch.setattr(platform_env, "resolve_user_bin", lambda *a, **k: None)
    return tmp_path / "tools" / "GDS3D" / "techfiles"


# ----------------------------------------------------------------- techfile lookup
@pytest.mark.parametrize("pdk,expect", [
    ("sky130A", "sky130A.txt"),
    ("sky130B", "sky130B.txt"),
    ("gf180mcuA", "gf180mcuA.txt"),
    ("gf180mcuB", "gf180mcuB.txt"),
    ("gf180mcuC", "gf180mcuC.txt"),
    ("gf180mcuD", "gf180mcuD.txt"),
    ("ihp-sg13g2", "ihp-sg13g2.txt"),
    ("sg13g2", "ihp-sg13g2.txt"),          # bare variant name -> the family's file
    ("gf180mcu", "gf180mcuD.txt"),         # family with no variant -> LanEx's target
])
def test_bundled_process_file_for_each_pdk(no_gds3d_install, pdk, expect):
    got = desktop.gds3d_process_file(pdk)
    assert got and Path(got).name == expect
    assert Path(got).parent == desktop.BUNDLED_GDS3D_DIR


def test_unknown_pdk_has_no_process_file(no_gds3d_install):
    assert desktop.gds3d_process_file("someotherpdk") is None
    assert desktop.gds3d_process_file(None) is None


def test_exact_name_beats_family_and_upstream_files(no_gds3d_install):
    tf = no_gds3d_install
    tf.mkdir(parents=True)
    # GDS3D's upstream set: a family-token match must never beat LanEx's exact file.
    for name in ("sky130.txt", "sg13g2.txt", "example.txt"):
        (tf / name).write_text("# upstream\n", encoding="utf-8")
    assert Path(desktop.gds3d_process_file("ihp-sg13g2")).parent == desktop.BUNDLED_GDS3D_DIR
    assert Path(desktop.gds3d_process_file("sky130A")).name == "sky130A.txt"
    # Bundled files are searched first, so even an exact-named file in GDS3D's
    # folder doesn't replace LanEx's checked stack...
    (tf / "gf180mcuD.txt").write_text("# other\n", encoding="utf-8")
    assert Path(desktop.gds3d_process_file("gf180mcuD")).parent == desktop.BUNDLED_GDS3D_DIR
    # ...but a PDK LanEx has no file for is found there by its exact name.
    (tf / "mypdk.txt").write_text("# mine\n", encoding="utf-8")
    assert Path(desktop.gds3d_process_file("mypdk")).parent == tf


def test_family_token_still_finds_a_user_file_for_other_pdks(no_gds3d_install):
    tf = no_gds3d_install
    tf.mkdir(parents=True)
    (tf / "mypdk_x.txt").write_text("# x\n", encoding="utf-8")
    (tf / "mypdk_longer_name.txt").write_text("# y\n", encoding="utf-8")
    assert Path(desktop.gds3d_process_file("mypdk")).name == "mypdk_x.txt"


def test_launch_uses_the_bundled_file_for_gf180(no_gds3d_install, tmp_path, monkeypatch):
    gds = tmp_path / "top.gds"
    gds.write_bytes(b"\0")
    seen = {}

    class _P:
        pid = 1

    monkeypatch.setattr(desktop, "_resolve_bin", lambda spec: "/usr/bin/gds3d")
    monkeypatch.setattr(platform_env, "host_display_available", lambda: True)
    monkeypatch.setattr(platform_env, "mesa_dri_present", lambda: True)
    monkeypatch.setattr(platform_env, "x11_fixed_fonts_present", lambda: True)
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda argv, **kw: seen.setdefault("argv", argv) and _P())
    from lanex.controller import activity
    monkeypatch.setattr(activity, "track_viewer", lambda *a, **k: None)
    res = desktop.open_in_tool("gds3d", gds, pdk="gf180mcuD")
    assert res["ok"], res
    assert seen["argv"][:3] == ["/usr/bin/gds3d", "-p", str(desktop.BUNDLED_GDS3D_DIR / "gf180mcuD.txt")]


# ----------------------------------------------------------------- bundled files
def _stack(name):
    path = str(desktop.BUNDLED_GDS3D_DIR / name)
    stack, got = lv._parse_gds3d(path)
    assert got == path
    return stack


def _ordered(stack, keys):
    """Each layer's bottom sits at or above the previous one's bottom."""
    z0 = [stack[k]["z0"] for k in keys]
    assert z0 == sorted(z0), [(k, stack[k]["z0"]) for k in keys]


def test_every_bundled_file_parses_with_real_heights():
    files = sorted(desktop.BUNDLED_GDS3D_DIR.glob("*.txt"))
    assert {f.stem for f in files} >= {"sky130A", "sky130B", "gf180mcuA", "gf180mcuB", "gf180mcuC",
                                        "gf180mcuD", "ihp-sg13g2"}
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert "Licensed under the Apache License" in text and "Where the numbers come from" in text, f.name
        stack = _stack(f.name)
        assert len(stack) >= 8, f.name
        for key, L in stack.items():
            assert L["z1"] > L["z0"], (f.name, key)
            assert L["color"].startswith("#") and len(L["color"]) == 7


def test_gf180mcuD_stack():
    s = _stack("gf180mcuD.txt")
    metals = ["22/0", "30/0", "34/0", "35/0", "36/0", "38/0", "42/0", "40/0", "46/0", "41/0", "81/0"]
    assert set(metals) | {"33/0", "53/0", "21/0"} <= set(s)
    _ordered(s, metals)
    # Contact runs from the COMP top up to Metal1; each via joins the metals around it.
    assert s["33/0"]["z0"] == pytest.approx(s["22/0"]["z1"])
    assert s["33/0"]["z1"] == pytest.approx(s["34/0"]["z0"])
    assert s["35/0"]["z0"] == pytest.approx(s["34/0"]["z1"]) and s["35/0"]["z1"] == pytest.approx(s["36/0"]["z0"])
    # gf180mcuD's top metal is the 11 kA one; MetalTop (53/0) shares its slot.
    assert s["81/0"]["z1"] - s["81/0"]["z0"] == pytest.approx(1.1)
    assert (s["53/0"]["z0"], s["53/0"]["z1"]) == (s["81/0"]["z0"], s["81/0"]["z1"])
    assert s["53/0"]["name"] == "MetalTop" and s["81/0"]["name"] == "Metal5"
    # markers, labels and dummies are never stacked
    assert not {"34/10", "34/4", "34/3", "0/0"} & set(s)


def test_gf180_top_metal_differs_per_variant():
    top = {"A": ("42/0", 3.0), "B": ("46/0", 1.1), "C": ("81/0", 0.9), "D": ("81/0", 1.1)}
    for v, (key, thick) in top.items():
        s = _stack(f"gf180mcu{v}.txt")
        assert s[key]["z1"] - s[key]["z0"] == pytest.approx(thick), v
        assert max(L["z1"] for L in s.values()) == pytest.approx(s[key]["z1"]), v


def test_ihp_stack_has_activ_on_1_0_and_the_top_metals():
    s = _stack("ihp-sg13g2.txt")
    assert "1/0" in s and s["1/0"]["z0"] == 0
    assert "0/0" not in s
    order = ["1/0", "5/0", "8/0", "19/0", "10/0", "29/0", "30/0", "49/0", "50/0", "66/0", "67/0",
             "125/0", "126/0", "133/0", "134/0"]
    _ordered(s, order)
    assert s["134/0"]["z1"] == pytest.approx(14.23)    # TopMetal2 top, sg13g2_beol.lyd25


def test_sky130B_sits_higher_from_via1_up():
    a, b = _stack("sky130A.txt"), _stack("sky130B.txt")
    assert a["68/20"] == b["68/20"]
    assert b["69/20"]["z0"] - a["69/20"]["z0"] == pytest.approx(0.295)


# ----------------------------------------------------------------- .lyp parsing
@pytest.mark.parametrize("name,source,expect", [
    # gf180mcu: empty <name/>, the name lives in the source
    ("", "COMP 22/0@1", ("COMP", "", "22/0", "COMP")),
    ("", "MetalTop 53/0@1", ("MetalTop", "", "53/0", "MetalTop")),
    ("", "Metal1_Label 34/10@1", ("Metal1", "label", "34/10", "Metal1_Label")),
    ("", "Metal3_Dummy 42/4@1", ("Metal3", "dummy", "42/4", "Metal3_Dummy")),
    ("", "Metal2_Slot 36/3@1", ("Metal2", "slot", "36/3", "Metal2_Slot")),
    ("", "PR_bndry 0/0@1", ("PR_bndry", "", "0/0", "PR_bndry")),
    # sky130
    ("met1.drawing - 68/20", "68/20@1", ("met1", "drawing", "68/20", "met1.drawing")),
    # ihp-sg13g2
    ("Activ.drawing", "1/0", ("Activ", "drawing", "1/0", "Activ.drawing")),
    ("TopMetal1.pin", "126/2", ("TopMetal1", "pin", "126/2", "TopMetal1.pin")),
    # no .lyp at all: KLayout's own numbers
    ("", "1/222@1", ("1/222", "", "1/222", "1/222")),
    # a DEF layer KLayout named from the map file
    ("", "met2.drawing 69/20@1", ("met2", "drawing", "69/20", "met2.drawing")),
])
def test_layer_ident(name, source, expect):
    assert lv._layer_ident(name, source) == expect


@pytest.mark.parametrize("base,purpose,group", [
    ("Metal1", "", "metal"), ("Metal5", "", "metal"), ("MetalTop", "", "metal"),
    ("Via1", "", "metal"), ("Via5", "", "metal"),
    ("Contact", "", "local"), ("Poly2", "", "device"), ("COMP", "", "device"),
    ("Nwell", "", "well"), ("DNWELL", "", "well"), ("LVPWELL", "", "well"),
    ("Nplus", "", "well"), ("Pplus", "", "well"),
    ("Metal1", "label", "pin"), ("Metal2", "slot", "misc"), ("Metal4", "blk", "misc"),
    ("PR_bndry", "", "misc"),
    # ihp-sg13g2
    ("TopVia1", "drawing", "metal"), ("TopVia2", "drawing", "metal"),
    ("TopMetal1", "drawing", "metal"), ("TopMetal2", "drawing", "metal"),
    ("Cont", "drawing", "local"), ("Activ", "drawing", "device"), ("GatPoly", "drawing", "device"),
    ("nSD", "drawing", "well"), ("NWell", "drawing", "well"),
])
def test_groups_for_gf180_and_ihp(base, purpose, group):
    assert lv._group_of(base, purpose) == group


def _rank_order(names):
    z = [lv._z_rank(n, "drawing") for n in names]
    assert all(a < b for a, b in zip(z, z[1:])), list(zip(names, z))


def test_z_rank_orders_each_pdks_stack():
    _rank_order(["nwell", "diff", "poly", "licon1", "li1", "mcon", "met1", "via", "met2", "via2",
                 "met3", "via3", "met4", "via4", "met5", "rdl"])
    _rank_order(["Nwell", "COMP", "Poly2", "Contact", "Metal1", "Via1", "Metal2", "Via2", "Metal3",
                 "Via3", "Metal4", "Via4", "Metal5", "Via5", "MetalTop"])
    _rank_order(["NWell", "Activ", "GatPoly", "Cont", "Metal1", "Via1", "Metal2", "Via2", "Metal3",
                 "Via3", "Metal4", "Via4", "Metal5", "TopVia1", "TopMetal1", "TopVia2", "TopMetal2"])
    # a label reports above its layer's shapes
    assert lv._z_rank("Metal1", "label") > lv._z_rank("Metal1", "")


def test_layer_words_cover_gf180_and_ihp_names():
    assert "metal wiring layer 3" in lv._layer_words("Metal3")
    assert lv._layer_words("Poly2").startswith("polysilicon")
    assert lv._layer_words("COMP").startswith("diffusion")
    assert lv._layer_words("Activ").startswith("diffusion")
    assert lv._layer_words("Contact").startswith("contact")
    assert lv._layer_words("TopMetal2") and lv._layer_words("MetalTop")
    assert lv._layer_words("TopVia1").startswith("via")


def test_generic_stack_keeps_gf180_metals_but_not_their_labels():
    def L(i, src):
        base, purpose, s, label = lv._layer_ident("", src)
        return {"id": i, "name": base, "purpose": purpose, "src": s, "label": label, "fill": "#123456",
                "group": lv._group_of(base, purpose), "z": lv._z_rank(base, purpose)}
    layers = [L(0, "Metal1 34/0@1"), L(1, "Metal1_Label 34/10@1"), L(2, "Metal1_Dummy 34/4@1"),
              L(3, "Poly2 30/0@1"), L(4, "Contact 33/0@1"), L(5, "PR_bndry 0/0@1")]
    g = lv._generic_stack(layers)
    assert set(g) == {0, 3, 4}
    assert g[3]["z0"] < g[4]["z0"] < g[0]["z0"]


# ----------------------------------------------------------------- KLayout 2.5D fallback
_LYD25 = """<?xml version="1.0" encoding="utf-8"?>
<klayout-macro>
 <interpreter>dsl</interpreter>
 <text>Activ = input(1,0)
Metal1 = input(8, 0)
GatPoly  = input(5,0) | PolyRes
Cont_to_Activ   = Cont - GatPoly
z(Metal1, name:"Metal1",  zstart: 1.040, height: 0.420, color: 0x39bfff)
z(Cont_to_Activ, name:"Cont-&gt;Activ", zstart: 0.400, height: 0.640, color: 0x00ffff)
z(GatPoly, name:"GatPoly", zstart: 0.400, height: 0.140, color: 0x0000ff)
z(Activ,  name:"Activ",   zstart: 0.000, height: 0.400, color: 0x00ff00)
z(input(134, 0), name:"TopMetal2", zstart: 11.23, height: 3.0, color: 0xff8000)
 </text>
</klayout-macro>
"""


def test_d25_stack_reads_the_pdks_2_5d_file(tmp_path):
    d25 = tmp_path / "mypdk" / "libs.tech" / "klayout" / "tech" / "d25"
    d25.mkdir(parents=True)
    (d25 / "beol.lyd25").write_text(_LYD25, encoding="utf-8")
    stack, path = lv._d25_stack({"PDK": "mypdk", "PDK_ROOT": str(tmp_path)})
    assert path and path.endswith("beol.lyd25")
    # derived layers (boolean expressions) have no single GDS layer to key by
    assert set(stack) == {"1/0", "8/0", "134/0"}
    assert stack["8/0"]["z0"] == pytest.approx(1.04) and stack["8/0"]["z1"] == pytest.approx(1.46)
    assert stack["8/0"]["color"] == "#39bfff" and stack["134/0"]["name"] == "TopMetal2"


def test_d25_stack_absent_is_empty(tmp_path):
    assert lv._d25_stack({"PDK": "nopdk", "PDK_ROOT": str(tmp_path)}) == ({}, None)


# ----------------------------------------------------------------- real KLayout round trip
klayout_ok = lv.available()["ok"]

# A layer-properties file written the way gf180mcu.lyp is: empty names, the
# layer name in the source.
_GF_LYP = """<?xml version="1.0" encoding="utf-8"?>
<layer-properties>
""" + "".join(
    f" <properties><frame-color>#{c}</frame-color><fill-color>#{c}</fill-color><visible>true</visible>"
    f"<name/><source>{src}@1</source></properties>\n"
    for src, c in (("COMP 22/0", "bd74bd"), ("Poly2 30/0", "2e9521"), ("Contact 33/0", "c86634"),
                   ("Metal1 34/0", "eddd07"), ("Via1 35/0", "f5e7f1"), ("Metal2 36/0", "ccf338"),
                   ("Metal1_Label 34/10", "eddd07"))) + "</layer-properties>\n"


@pytest.mark.skipif(not klayout_ok, reason="klayout Python package not installed")
def test_gf180_layout_stacks_in_3d_with_its_own_lyp(tmp_path, no_gds3d_install):
    import klayout.db as kdb

    run = tmp_path / "design" / "runs" / "RUN_GF"
    (run / "final" / "gds").mkdir(parents=True)
    lyp = tmp_path / "gf180mcu.lyp"
    lyp.write_text(_GF_LYP, encoding="utf-8")
    (run / "resolved.json").write_text(json.dumps({"PDK": "gf180mcuD", "KLAYOUT_PROPERTIES": str(lyp)}))
    ly = kdb.Layout()
    ly.dbu = 0.005
    top = ly.create_cell("top")
    for (l, d), box in (((22, 0), (0, 0, 400, 200)), ((30, 0), (100, -40, 140, 240)),
                        ((33, 0), (20, 20, 60, 60)), ((34, 0), (0, 0, 400, 80)),
                        ((35, 0), (300, 10, 340, 50)), ((36, 0), (280, 0, 360, 400))):
        top.shapes(ly.layer(l, d)).insert(kdb.Box(*box))
    top.shapes(ly.layer(34, 10)).insert(kdb.Text("VDD", kdb.Trans(kdb.Point(10, 10))))
    ly.write(str(run / "final" / "gds" / "top.gds"))

    info = lv.open_session(run, "final")
    assert info["ok"], info
    by_src = {L["src"]: L for L in info["layers"]}
    assert set(by_src) >= {"22/0", "30/0", "33/0", "34/0", "35/0", "36/0"}
    assert by_src["34/0"]["label"] == "Metal1" and by_src["34/0"]["group"] == "metal"
    assert by_src["22/0"]["group"] == "device" and by_src["33/0"]["group"] == "local"

    blob = lv.mesh(info["sid"], None, None)
    n = struct.unpack("<I", blob[:4])[0]
    head = json.loads(blob[4:4 + n])
    assert head["stack"] == "gds3d:gf180mcuD.txt"
    got = {L["name"]: L for L in head["layers"]}
    assert set(got) == {"COMP", "Poly2", "Contact", "Metal1", "Via1", "Metal2"}
    assert all(L["tris"] > 0 for L in got.values())
    z = [got[k]["z0"] for k in ("COMP", "Poly2", "Metal1", "Via1", "Metal2")]
    assert z == sorted(z) and len(set(z)) == len(z)


# ----------------------------------------------------------------- viewer display env
def test_manual_console_runs_with_the_wsl_viewer_env(monkeypatch, tmp_path):
    from lanex.controller import manualcmd

    monkeypatch.setattr(platform_env, "wsl_gui_env",
                        lambda base=None: {**(base or {}), "GDK_BACKEND": "x11,*", "LIBGL_ALWAYS_SOFTWARE": "1"})
    seen = {}
    monkeypatch.setattr(manualcmd.ManualJob, "_run",
                        lambda self, argv, cwd, env, shown: (seen.update(env=env), setattr(self, "_running", False)))
    job = manualcmd.ManualJob()
    res = job.start("klayout -v", cwd=str(tmp_path))
    assert res["ok"], res
    job._thread.join(5)
    assert seen["env"]["GDK_BACKEND"] == "x11,*" and seen["env"]["LIBGL_ALWAYS_SOFTWARE"] == "1"


def test_container_viewers_skip_qt_glx_like_the_native_path(monkeypatch):
    monkeypatch.delenv("LIBRELANE_GUI_WSL_HW_GL", raising=False)
    monkeypatch.delenv("LANEX_HW_GL", raising=False)
    flags = container_tools._x11_flags()
    assert "QT_XCB_GL_INTEGRATION=none" in flags and "LIBGL_ALWAYS_SOFTWARE=1" in flags
    monkeypatch.setenv("LANEX_HW_GL", "1")
    assert "QT_XCB_GL_INTEGRATION=none" not in container_tools._x11_flags()


def test_appliance_shell_profile_forces_software_gl():
    provision = (REPO / "windows/provision/provision.sh").read_text(encoding="utf-8")
    profile = provision[provision.index("cat > /etc/profile.d/lanex-wslg.sh"):provision.index("chmod 0644 /etc/profile.d/lanex-wslg.sh")]
    for var in ("LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER", "QT_XCB_GL_INTEGRATION", "LANEX_HW_GL"):
        assert var in profile
