"""Export Windows PDK pins from the exact locked LanEx/LibreLane environment."""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
from pathlib import Path

from lanex.controller.pdk import required_pdk_version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    if metadata.version("librelane") != "3.0.4" or metadata.version("ciel") != "2.6.1":
        raise SystemExit("PDK pins must be exported with librelane==3.0.4 and ciel==2.6.1")
    families: dict[str, str] = {}
    variants: dict[str, dict[str, object]] = {}
    for variant, entry in sorted(catalog["pdk_catalog"].items()):
        family = str(entry["family"])
        if family not in families:
            required = required_pdk_version(family)
            if not required:
                raise SystemExit(f"LibreLane exposes no required PDK version for {family}")
            families[family] = required
        variants[variant] = {
            "family": family,
            "requiredVersion": families[family],
            "libraries": entry["libraries"],
            "defaultLibraries": entry["default_libraries"],
        }
    output = {
        "environment": {"librelane": "3.0.4", "ciel": "2.6.1"},
        "families": families,
        "variants": variants,
    }
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
