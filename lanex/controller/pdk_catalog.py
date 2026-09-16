"""Authoritative PDK catalog, pinned release evidence, and preset definitions.

Audited for LibreLane 3.0.4 and Ciel 2.6.1.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

LOCKED_ENVIRONMENT = {
    "librelane": "3.0.4",
    "ciel": "2.6.1",
}

PINNED_PDK_VERSIONS: Dict[str, str] = {
    "sky130": "8afc8346a57fe1ab7934ba5a6056ea8b43078e71",
    "gf180mcu": "54435919abffb937387ec956209f9cf5fd2dfbee",
    "ihp-sg13g2": "c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c",
}

# Library category mapping
# stdcell: synthesis standard cell libraries
# io: pad and general IO cell libraries
# primitives: layout/device primitives, models, spice
# sram: SRAM macros/IP
# utility: layout fonts, lettering, artwork
LIBRARY_METADATA: Dict[str, Dict[str, Any]] = {
    # SKY130 (common: 6,421,325 bytes)
    "sky130_fd_io": {"category": "io", "size": 112997219, "digest": "sha256:74fb482cba90c464527fc1471651cff796bba37f483c25bdb854dabe6ebd5812"},
    "sky130_fd_pr": {"category": "primitives", "size": 14306043, "digest": "sha256:0ce4d03701a750ee0d697d03536cb2e3ec89c8c7f4ca37d1a7736d546874fae6"},
    "sky130_fd_pr_reram": {"category": "primitives", "size": 24424, "digest": "sha256:15922b527882ab2eda29fd08828f479862d33ee45406d68a78ac028b1def2cb5", "variants": ["sky130B"]},
    "sky130_fd_sc_hd": {"category": "stdcell", "size": 127299820, "digest": "sha256:17047505cfff30841bf53960b8cbf9e7c79b2a3bbb2ebec0bb254eb441e4ce1e"},
    "sky130_fd_sc_hdll": {"category": "stdcell", "size": 126153898, "digest": "sha256:0cc49c9a4583a10c83c496d6e29eb9c87edd91ba36d8532559c1abeb526ac803"},
    "sky130_fd_sc_hs": {"category": "stdcell", "size": 632894277, "digest": "sha256:4d0259dc6667ac243cbd2fee72a481bbf986bbb8cdf4f75ef4e2186c246c48e5"},
    "sky130_fd_sc_hvl": {"category": "stdcell", "size": 47985136, "digest": "sha256:48a29a3b6f801241d576a93f120ec461d59de38d06147b1cc23d4149ca1b249b"},
    "sky130_fd_sc_lp": {"category": "stdcell", "size": 515889195, "digest": "sha256:c9895f5fd56ca06cf79142154c1b9ac6b3b8f9cfd420b0e4f639a0f6e0533e74"},
    "sky130_fd_sc_ls": {"category": "stdcell", "size": 742658068, "digest": "sha256:4f49c1602a205b5c8413540aab8ef1c03b3529f97efb47b3d327f8de162ec89c"},
    "sky130_fd_sc_ms": {"category": "stdcell", "size": 589649223, "digest": "sha256:998f931bc50d6e0d7b82a92045245fa7b49d5f4301bd0ee4e494346439b36439"},
    "sky130_ml_xx_hd": {"category": "utility", "size": 9528, "digest": "sha256:cf8112330ca3d9328c0ef1ca28cd71d384ff0c7bebb0bf2e735b89f716b2bbdd"},
    "sky130_sram_macros": {"category": "sram", "size": 29367245, "digest": "sha256:b97d4dbfe372530ff5657e38e4ccde6d2db5163d5e3c49ff5b394fc766ae5fcd"},

    # GF180MCU (common: 170,189,754 bytes)
    "gf180mcu_as_sc_mcu7t3v3": {"category": "stdcell", "size": 2060981, "digest": "sha256:d9224c2f1bc3f0b8f6249614a4fab2044f3fa7304a0b5646835df974d65ac141"},
    "gf180mcu_fd_io": {"category": "io", "size": 25225541, "digest": "sha256:5875e8bfd7f6a12fcf26d2cd61dbbc0043e8bd2de999745fc4252613ac10a314"},
    "gf180mcu_fd_ip_sram": {"category": "sram", "size": 27113343, "digest": "sha256:7997263ec6798c6dd78dff0df2763693e19f07af4f6aaac7fc7299702acafb8a"},
    "gf180mcu_fd_pr": {"category": "primitives", "size": 50776, "digest": "sha256:86a6ffdaad229aef38f005ddbf2a4672747743d29a518e393081ce96be85f929"},
    "gf180mcu_fd_sc_mcu7t5v0": {"category": "stdcell", "size": 180129421, "digest": "sha256:dcacb088f91d71a399a733e0cda749aa5ad3c7ec41d15b2cc32856d39cdbe678"},
    "gf180mcu_fd_sc_mcu9t5v0": {"category": "stdcell", "size": 179966491, "digest": "sha256:96c79dee32428300f396c6c869fb36f132898688ee37559825436c6d1c5c3378"},
    "gf180mcu_ocd_alpha_large": {"category": "utility", "size": 1159, "digest": "sha256:150607c16496ac60a889c21f3b62c948a561ed30c42aff560ec8b966c853c2d4"},
    "gf180mcu_ocd_alpha_misc": {"category": "utility", "size": 2246, "digest": "sha256:7e00bc6ea11a7028cfe0fca0b7eec48ad95ec39e57c6924f1c703ce0c0f72f5f"},
    "gf180mcu_ocd_alpha_small": {"category": "utility", "size": 8535, "digest": "sha256:28944768e9e35a5ad9cb12b670263fa843acdc30d9bb778485ec1452c45d8875"},
    "gf180mcu_ocd_io": {"category": "io", "size": 43553342, "digest": "sha256:2c991cb11328548cb67996a39831ebd4d7150b20516921977891b138cff67139"},
    "gf180mcu_osu_sc_gp12t3v3": {"category": "stdcell", "size": 13311865, "digest": "sha256:415b3ac1df3c8ab6e309f81b247c9245368309e0e9521f5c16d8c0c6c9264a6f"},
    "gf180mcu_osu_sc_gp9t3v3": {"category": "stdcell", "size": 13333115, "digest": "sha256:d865a4ebfd2ff59f43fbf83790e8910e096974adbcb06ca7fead8df4705a60ce"},

    # IHP SG13G2 (common: 384,869,154 bytes)
    "sg13g2_io": {"category": "io", "size": 12837819, "digest": "sha256:0abc1a6c269f064a9fb31252f751f04a2e63098523b96d0659c05c5296262db6"},
    "sg13g2_pr": {"category": "primitives", "size": 175934, "digest": "sha256:95c328dd7486cccab4d48fdc5370f628dccd461a9fe266739523a629a5544f1a"},
    "sg13g2_sram": {"category": "sram", "size": 2418451, "digest": "sha256:185f266584d85a316dcc518af46a04f20f46a47deda040946d43cbce81dac6af"},
    "sg13g2_stdcell": {"category": "stdcell", "size": 6262256, "digest": "sha256:c3dec00ae2cc4a894c5d2478c9e049e38ae0bc1635a55a7d5e0993b1c73879ab"},
}

# Unavailable published assets in Ciel 2.6.1 for GF180MCU
UNAVAILABLE_LIBRARIES: Dict[str, Dict[str, str]] = {
    "gf180mcu": {
        "gf180mcu_ocd_ip_sram": "Not published for this release",
        "gf180mcu_re_efuse": "Not published for this release",
    }
}

SKY130A_PUBLISHED_LIBS = [
    "sky130_fd_io",
    "sky130_fd_pr",
    "sky130_fd_sc_hd",
    "sky130_fd_sc_hdll",
    "sky130_fd_sc_hs",
    "sky130_fd_sc_hvl",
    "sky130_fd_sc_lp",
    "sky130_fd_sc_ls",
    "sky130_fd_sc_ms",
    "sky130_ml_xx_hd",
    "sky130_sram_macros",
]

SKY130B_PUBLISHED_LIBS = SKY130A_PUBLISHED_LIBS + ["sky130_fd_pr_reram"]

GF180_PUBLISHED_LIBS = [
    "gf180mcu_as_sc_mcu7t3v3",
    "gf180mcu_fd_io",
    "gf180mcu_fd_ip_sram",
    "gf180mcu_fd_pr",
    "gf180mcu_fd_sc_mcu7t5v0",
    "gf180mcu_fd_sc_mcu9t5v0",
    "gf180mcu_ocd_alpha_large",
    "gf180mcu_ocd_alpha_misc",
    "gf180mcu_ocd_alpha_small",
    "gf180mcu_ocd_io",
    "gf180mcu_osu_sc_gp12t3v3",
    "gf180mcu_osu_sc_gp9t3v3",
]

IHP_PUBLISHED_LIBS = [
    "sg13g2_io",
    "sg13g2_pr",
    "sg13g2_sram",
    "sg13g2_stdcell",
]

# Ciel 2.6.1 default starter sets
SKY130_STARTER_LIBS = [
    "sky130_fd_io",
    "sky130_fd_pr",
    "sky130_fd_sc_hd",
    "sky130_fd_sc_hvl",
    "sky130_ml_xx_hd",
    "sky130_sram_macros",
]

GF180_STARTER_LIBS = [
    "gf180mcu_fd_io",
    "gf180mcu_fd_pr",
    "gf180mcu_fd_sc_mcu7t5v0",
    "gf180mcu_fd_sc_mcu9t5v0",
    "gf180mcu_fd_ip_sram",
]

IHP_STARTER_LIBS = list(IHP_PUBLISHED_LIBS)

# Synthesis SCL sets for project picker
SYNTHESIS_SCLS: Dict[str, List[str]] = {
    "sky130A": [
        "sky130_fd_sc_hd",
        "sky130_fd_sc_hdll",
        "sky130_fd_sc_hvl",
        "sky130_fd_sc_hs",
        "sky130_fd_sc_ls",
        "sky130_fd_sc_ms",
    ],
    "sky130B": [
        "sky130_fd_sc_hd",
        "sky130_fd_sc_hdll",
        "sky130_fd_sc_hvl",
        "sky130_fd_sc_hs",
        "sky130_fd_sc_ls",
        "sky130_fd_sc_ms",
    ],
    "gf180mcuD": [
        "gf180mcu_fd_sc_mcu7t5v0",
        "gf180mcu_fd_sc_mcu9t5v0",
        "gf180mcu_osu_sc_gp12t3v3",
        "gf180mcu_osu_sc_gp9t3v3",
        "gf180mcu_as_sc_mcu7t3v3",
    ],
    "ihp-sg13g2": [
        "sg13g2_stdcell",
    ],
}


def is_synthesis_scl(pdk_variant: str, library_name: str) -> bool:
    """Check if library_name is a valid digital synthesis standard cell library."""
    valid = SYNTHESIS_SCLS.get(pdk_variant)
    if valid is not None:
        return library_name in valid
    if any(pattern in library_name for pattern in ("_sc_", "_stdcell")):
        if not any(excluded in library_name for excluded in ("_ml_", "_alpha_", "_sram", "_io", "_pr")):
            return True
    return False


PRESET_NAMES = ["recommended", "custom", "minimal", "complete"]

PRESET_DESCRIPTIONS = {
    "recommended": "Tools, viewers and SKY130A. Ready to design.",
    "complete": "All supported tools and PDKs. Largest download.",
    "maximum": "All supported tools and PDKs. Largest download.",
    "custom": "Choose your tools and PDKs.",
    "minimal": "Install LanEx now. Add tools and PDKs later.",
}

DEFAULT_NATIVE_TOOLS = ["verilator", "iverilog", "graphviz", "gtkwave", "gds3d"]

# Canonical preset expansions
PRESET_EXPANSIONS: Dict[str, Dict[str, Any]] = {
    "recommended": {
        "schema": 1,
        "profile": "recommended",
        "engine": "docker",
        "image": True,
        "nativeTools": list(DEFAULT_NATIVE_TOOLS),
        "pdks": ["sky130A"],
        "libraries": {
            "sky130A": list(SKY130_STARTER_LIBS),
        },
    },
    "complete": {
        "schema": 1,
        "profile": "complete",
        "engine": "docker",
        "image": True,
        "nativeTools": list(DEFAULT_NATIVE_TOOLS),
        "pdks": ["sky130A", "sky130B", "gf180mcuD", "ihp-sg13g2"],
        "libraries": {
            "sky130A": list(SKY130A_PUBLISHED_LIBS),
            "sky130B": list(SKY130B_PUBLISHED_LIBS),
            "gf180mcuD": list(GF180_PUBLISHED_LIBS),
            "ihp-sg13g2": list(IHP_PUBLISHED_LIBS),
        },
    },
    "maximum": {
        "schema": 1,
        "profile": "maximum",
        "engine": "docker",
        "image": True,
        "nativeTools": list(DEFAULT_NATIVE_TOOLS),
        "pdks": ["sky130A", "sky130B", "gf180mcuD", "ihp-sg13g2"],
        "libraries": {
            "sky130A": list(SKY130A_PUBLISHED_LIBS),
            "sky130B": list(SKY130B_PUBLISHED_LIBS),
            "gf180mcuD": list(GF180_PUBLISHED_LIBS),
            "ihp-sg13g2": list(IHP_PUBLISHED_LIBS),
        },
    },
    "custom": {
        "schema": 1,
        "profile": "custom",
        "engine": "docker",
        "image": True,
        "nativeTools": list(DEFAULT_NATIVE_TOOLS),
        "pdks": ["sky130A"],
        "libraries": {
            "sky130A": list(SKY130_STARTER_LIBS),
        },
    },
    "minimal": {
        "schema": 1,
        "profile": "minimal",
        "engine": "none",
        "image": False,
        "nativeTools": [],
        "pdks": [],
        "libraries": {},
    },
}


def build_canonical_pdk_catalog() -> Dict[str, Dict[str, Any]]:
    """Return the authoritative per-variant PDK catalog dictionary."""
    return {
        "sky130A": {
            "label": "sky130A",
            "family": "sky130",
            "foundry": "SkyWater Technology",
            "node": "130 nm",
            "description": (
                "SkyWater 130 nm open PDK — the most widely used process for "
                "open-source tapeouts. Variant A is the default starter technology."
            ),
            "default_variant": True,
            "supported": True,
            "libraries": list(SKY130A_PUBLISHED_LIBS),
            "default_libraries": list(SKY130_STARTER_LIBS),
            "approx_gb": 2.5,
        },
        "sky130B": {
            "label": "sky130B",
            "family": "sky130",
            "foundry": "SkyWater Technology",
            "node": "130 nm",
            "description": (
                "SkyWater 130 nm open PDK — variant B adds ReRAM and SONOS non-volatile "
                "memory device models."
            ),
            "default_variant": False,
            "supported": True,
            "libraries": list(SKY130B_PUBLISHED_LIBS),
            "default_libraries": list(SKY130_STARTER_LIBS),
            "approx_gb": 2.5,
        },
        "gf180mcuD": {
            "label": "gf180mcuD",
            "family": "gf180mcu",
            "foundry": "GlobalFoundries",
            "node": "180 nm",
            "description": (
                "GlobalFoundries 180 nm MCU open PDK. Variant D is the supported "
                "target for the LibreLane flow."
            ),
            "default_variant": True,
            "supported": True,
            "libraries": list(GF180_PUBLISHED_LIBS),
            "default_libraries": list(GF180_STARTER_LIBS),
            "unavailable_libraries": dict(UNAVAILABLE_LIBRARIES["gf180mcu"]),
            "approx_gb": 1.8,
        },
        "ihp-sg13g2": {
            "label": "ihp-sg13g2",
            "family": "ihp-sg13g2",
            "foundry": "IHP",
            "node": "130 nm SiGe BiCMOS",
            "description": (
                "IHP SG13G2 — 130 nm SiGe BiCMOS open PDK with high-frequency "
                "bipolar devices, suited to RF and analog/mixed-signal designs."
            ),
            "default_variant": True,
            "supported": True,
            "libraries": list(IHP_PUBLISHED_LIBS),
            "default_libraries": list(IHP_STARTER_LIBS),
            "approx_gb": 1.9,
        },
        "gf180mcuA": {
            "label": "gf180mcuA",
            "family": "gf180mcu",
            "foundry": "GlobalFoundries",
            "node": "180 nm",
            "description": "GlobalFoundries 180 nm MCU variant A (unsupported by LibreLane flow).",
            "default_variant": False,
            "supported": False,
            "libraries": list(GF180_STARTER_LIBS),
            "default_libraries": list(GF180_STARTER_LIBS),
            "approx_gb": 1.8,
        },
        "gf180mcuB": {
            "label": "gf180mcuB",
            "family": "gf180mcu",
            "foundry": "GlobalFoundries",
            "node": "180 nm",
            "description": "GlobalFoundries 180 nm MCU variant B (unsupported by LibreLane flow).",
            "default_variant": False,
            "supported": False,
            "libraries": list(GF180_STARTER_LIBS),
            "default_libraries": list(GF180_STARTER_LIBS),
            "approx_gb": 1.8,
        },
        "gf180mcuC": {
            "label": "gf180mcuC",
            "family": "gf180mcu",
            "foundry": "GlobalFoundries",
            "node": "180 nm",
            "description": "GlobalFoundries 180 nm MCU variant C (legacy variant).",
            "default_variant": False,
            "supported": False,
            "libraries": list(GF180_STARTER_LIBS),
            "default_libraries": list(GF180_STARTER_LIBS),
            "approx_gb": 1.8,
        },
    }
