# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Curated error -> remediation knowledge base.

The moat. Each entry turns a ``OpenROADAlert`` / Checker failure signature
into a plain-English card the student can act on without rereading a manual.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .models import AdvisoryCard, to_json

# A reason taxonomy keyed off LibreLane's regex match on alert codes.
# Codes are derived from OpenROAD's diagnostic registry and may be missing
# for some releases; the lightweight alert fallback covers those cases.
ALERT_RX = re.compile(r"^\[(WARNING|ERROR)(?:\s+([A-Z]+\-\d+))?\]\s*(.+)")


def _known_var_names() -> set:
    """The set of config variables LibreLane actually recognises."""
    try:
        from .introspect import list_variables

        return {v["name"] for v in list_variables()}
    except Exception:
        return set()


def _valid_fix(fix: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    """Keep only one-click fixes whose variable really exists in this LibreLane.

    Applying an unknown config variable would make the run fail, so we never
    offer a fix we cannot verify against the live registry. This also makes the
    knowledge base resilient to LibreLane renaming variables across versions.
    """
    names = _known_var_names()
    if not names:
        return []
    return [f for f in (fix or []) if f.get("var") in names]


# ---------------------------------------------------------------- knowledge base
# A short, opinionated, mostly-correct map. ``fix`` items are applied config
# overrides (variable => value) that the user can one-click apply.
KB: List[Dict[str, Any]] = [
    {
        "key": "antenna.violations",
        "match_kind": "checker",
        "what": "Antenna violations on long metal wires. During fabrication plasma-etch can charge a wire's metal area above a gate; the discharge then damages the gate oxide.",
        "why": "OpenROAD found wires whose metal ratio exceeds the process antenna limits. The discharge path through a gate can destroy it before any diode protects it.",
        "remediations": [
            "Raise GRT_ANTENNA_REPAIR_ITERS (more antenna-repair passes during routing).",
            "Set DIODE_ON_PORTS to place protection diodes on I/O ports.",
            "Reduce PL_TARGET_DENSITY_PCT slightly to ease routing congestion.",
        ],
        "fix": [
            {"var": "GRT_ANTENNA_REPAIR_ITERS", "value": "3"},
        ],
    },
    {
        "key": "trc.routing_drc",
        "match_kind": "checker",
        "what": "Routing DRC violations. Wires are too close, too thin, or use forbidden vias for this node.",
        "why": "Detailed routing (TritonRoute) couldn't satisfy all foundry spacing rules. Common offenders are clock-tree metals and supply routing on metal 3/4.",
        "remediations": [
            "Raise FP_CORE_UTILIZATON margins by dropping it by ~5.",
            "Disable ROUTING_CORES if your machine has fewer than 4 cores.",
            "Increase routing layer access via RT_LAYER_ADJUSTMENTS if your PDK supports it.",
        ],
        "fix": [],
    },
    {
        "key": "yosys.unmapped_cells",
        "match_kind": "checker",
        "what": "Yosys couldn't map some RTL cells to your standard cell library.",
        "why": "Your Verilog contains a primitive (e.g. an analog cell, a behavioural RAM model, a vendor-specific cell) that sky130/gf180mcu doesn't have.",
        "remediations": [
            "For behavioural RAMs: switch to RAMLIB inference (sky130_fd_sc_hd has `sky130_fd_sc_hd__dfxram_pp`).",
            "For vendor cells: replace with inferred logic, or blacklist with `SYNTH_EXCLUDED_CELL_TYPES`.",
            "Add `SYNTH_LATCH_MAP` to infer latches correctly.",
        ],
        "fix": [],
    },
    {
        "key": "lvs.mismatch",
        "match_kind": "checker",
        "what": "LVS reports a mismatch between the routed netlist and your schematic.",
        "why": "Either you modified the RTL after synthesis, or the layout lost some pins/wires (DRC cleaned them up).",
        "remediations": [
            "Re-run from Yosys.Synthesis to refresh the netlist.",
            "Verify `SPICE_FILES` matches your PDK's libs.tech entries.",
            "Inspect LVS report for unmatched device classes — that's a clue.",
        ],
        "fix": [],
    },
    {
        "key": "timing.setup_violations",
        "match_kind": "checker",
        "what": "Setup (max-delay) violations: signals can't get from one FF to the next within a clock period.",
        "why": "Combinational delay > clock period minus FF setup. Usually placement density or a long wire path.",
        "remediations": [
            "Drop PL_TARGET_DENSITY_PCT to ~55-65 (it is a percentage, 0-100).",
            "Bump SYNTH_STRATEGY to AREA 1 first, then back to DELAY 2/3.",
            "Reduce CLOCK_PERIOD by 5-10% to expose slack headroom for diagnosis.",
        ],
        "fix": [],
    },
    {
        "key": "timing.hold_violations",
        "match_kind": "checker",
        "what": "Hold (min-delay) violations: signals arriving too fast at a FF.",
        "why": "Adjacent FFs ended up so close their wire delays don't satisfy min-path constraints.",
        "remediations": [
            "Re-run from OpenROAD.CTS so hold buffers can be inserted along the tree.",
            "Increase PL_RESIZER_HOLD_SLACK_MARGIN so the optimiser targets more hold headroom.",
            "Check that the hold corner/SDC is realistic for this clock.",
        ],
        "fix": [],
    },
    {
        "key": "disconnected_pins",
        "match_kind": "checker",
        "what": "Some pins ended up unconnected after routing.",
        "why": "Either the placer dropped a cell incorrectly, or you have virtual/obsolete pins in your SDC.",
        "remediations": [
            "Re-run from Odb.SetPowerConnections to restore the VDD/VSS grid for macros.",
            "Verify pin_order.cfg matches your RTL port names.",
            "Re-run from OpenROAD.RepairDesignPostGRT.",
        ],
        "fix": [],
    },
    {
        "key": "illegal_overlap",
        "match_kind": "checker",
        "what": "Overlapping shapes in the layout. Foundry thinks they're connected; we don't.",
        "why": "Usually macro abutment or an OBS layer leaking into the core.",
        "remediations": [
            "Verify Odb.SetPowerConnections ran cleanly.",
            "Check that your macro LEF abstracts put power pins on the right metal.",
            "Try MAGIC_ZEROIZE_GDS=0 (sometimes magic merges too aggressively).",
        ],
        "fix": [],
    },
    {
        "key": "wirelength.violation",
        "match_kind": "checker",
        "what": "Total wire length exceeds the configured budget.",
        "why": "Often a sign of fanout problems, or a too-thin placement density forcing long routes.",
        "remediations": [
            "Raise WIRE_LENGTH_THRESHOLD by 5-10% to give headroom.",
            "Increase PL_RAND_LOW (placement randomisation) to spread cells.",
            "Drop FP_CORE_UTIL to give the placer more room.",
        ],
        "fix": [],
    },
    {
        "key": "pdn.ir_drop",
        "match_kind": "checker",
        "what": "IR drop or electromigration on the power grid.",
        "why": "Either the core has too high current draw for the strap widths, or rails aren't wide enough.",
        "remediations": [
            "Increase PDN_VWIDTH and PDN_HWIDTH by 1.5x.",
            "Add an extra strap layer via PDN_HSPACING_OVD.",
            "Reduce clock buffer count if clocks dominate the current.",
        ],
        "fix": [],
    },
    {
        "key": "lint.errors",
        "match_kind": "checker",
        "what": "Verilator lint flagged errors in your RTL.",
        "why": "Undeclared wires, blocking assignments in always_ff, width mismatches, unsized ports, etc.",
        "remediations": [
            "Run `verilator --lint-only -Wall` for a clear list.",
            "Wrap suspicious blocks with `/* verilator lint_off */ ... /* lint_on */` only after rationale.",
        ],
        "fix": [],
    },
    {
        "key": "lint.warnings",
        "match_kind": "checker",
        "what": "Verilator lint warnings. They may be benign but often hide design smells.",
        "why": "Implicit nets, unused signals, or style violations.",
        "remediations": [
            "Treat as errors by adding `-Werror-IMPLICIT` and `-Werror-UNUSED`.",
        ],
        "fix": [],
    },
    {
        "key": "xor.tool_mismatch",
        "match_kind": "checker",
        "what": "Magic vs KLayout stream-out disagree about the GDS.",
        "why": "One of the two tools virtual-tied shapes the other ignored. Almost always a layer-stack mismatch.",
        "remediations": [
            "Run with FP_EMULATION mode on to debug.",
            "Recompute KLAYOUT_DRC layer map against MAGIC_LAYOUT.",
        ],
        "fix": [],
    },
    {
        "key": "klayout.density_violation",
        "match_kind": "checker",
        "what": "Metal density outside the foundry window.",
        "why": "Either not enough metal or too much in some region — CMP will struggle.",
        "remediations": [
            "Add FILL_CELL config and re-run from OpenROAD.FillInsertion.",
        ],
        "fix": [],
    },
    {
        "key": "klayout.antenna",
        "match_kind": "checker",
        "what": "KLayout antenna check (orthogonal to OpenROAD's).",
        "why": "Same root cause as OpenROAD-style antenna violations but flagged earlier in the pipeline.",
        "remediations": [
            "Same fix as OpenROAD antenna: bump DIODE_INSERTION_STRATEGY.",
        ],
        "fix": [],
    },
    {
        "key": "ORYX-1001",
        "match_kind": "alert",
        "alert_code": "ORYX-1001",
        "what": "OpenROAD ran out of memory while reading a DEF. The PDK is large or the design is dense.",
        "why": "You allocated fewer cores/threads than the design needs.",
        "remediations": [
            "Re-run on a machine with at least 16GB free RAM.",
            "Subset the design and run incrementally.",
        ],
        "fix": [],
    },
    {
        "key": "IOST-0032",
        "match_kind": "alert",
        "alert_code": "IOST-0032",
        "what": "OpenROAD couldn't place I/O pins because the constraints conflict with the pad ring.",
        "why": "Pin assignments in your SDC or the pad ring don't agree.",
        "remediations": [
            "Verify pin_order.cfg and the pad ring lib match.",
            "Run with IO_PLACER_CFG=<explicit-config>.",
        ],
        "fix": [],
    },
]


def _find_by_key(key: str) -> Optional[Dict[str, Any]]:
    for entry in KB:
        if entry.get("key") == key or entry.get("alert_code") == key:
            return entry
    return None


def _fingerprint_checker(name: str, metric: Optional[str] = None) -> str:
    """Map a Checker class name to a knowledge base key."""
    n = name.lower()
    if "antenna" in n:
        return "antenna.violations"
    if "trdrc" in n:
        return "trc.routing_drc"
    if "yosysunmappedcells" in n:
        return "yosys.unmapped_cells"
    if "lvs" in n:
        return "lvs.mismatch"
    if "timing" in n:
        if metric and "hold" in metric.lower():
            return "timing.hold_violations"
        return "timing.setup_violations"
    if "disconnectedpin" in n.replace("_", ""):
        return "disconnected_pins"
    if "illegaloverlap" in n.replace("_", ""):
        return "illegal_overlap"
    if "wirelength" in n:
        return "wirelength.violation"
    if "powergrid" in n or "pdn" in n:
        return "pdn.ir_drop"
    if "linterror" in n.replace("_", ""):
        return "lint.errors"
    if "lintwarning" in n.replace("_", ""):
        return "lint.warnings"
    if "xor" in n:
        return "xor.tool_mismatch"
    if "klayoutdensity" in n.replace("_", ""):
        return "klayout.density_violation"
    if "klayoutantenna" in n.replace("_", ""):
        return "klayout.antenna"
    if "magicdrc" in n.replace("_", ""):
        return "trc.routing_drc"
    return ""


def explain_alert(message: str) -> Dict[str, Any]:
    """Turn an OpenROADAlert log line into an AdvisoryCard."""
    m = ALERT_RX.match(message)
    code: Optional[str] = None
    if m:
        code = m.group(2)
    entry = _find_by_key(code) if code else None
    if entry is None:
        # Best-effort fingerprint from message text.
        text = message.lower()
        guess = ""
        for key in (
            "antenna",
            "tr_drc",
            "unmapped",
            "lvs",
            "setup",
            "hold",
            "disconnect",
            "overlap",
            "wire length",
            "ir drop",
            "xor",
            "density",
        ):
            if key in text:
                guess = _find_by_key(key) or {}
                break
        entry = guess or {
            "what": message,
            "why": "An OpenROAD warning/error was emitted. See the linked help for the step in the LibreLane docs.",
            "remediations": [
                "Click the step node, then 'Help' to read the upstream docstring.",
                "Google the alert code (e.g. 'OpenROAD ORPX-1234').",
            ],
            "fix": [],
        }
    return to_json(
        AdvisoryCard(
            title=code or _fingerprint_checker("generic") or "Issue",
            what=entry.get("what", ""),
            why=entry.get("why", ""),
            remediations=list(entry.get("remediations", [])),
            fix=_valid_fix(entry.get("fix")),
        )
    )


def explain_checker_failure(checker_class: str, metric: Optional[str] = None) -> Dict[str, Any]:
    """Map a Checker step class name + (optional) metric to an AdvisoryCard."""
    key = _fingerprint_checker(checker_class, metric)
    entry = _find_by_key(key)
    if entry is None:
        return to_json(
            AdvisoryCard(
                title=checker_class,
                what=f"{checker_class} failed.",
                why="See the linked help for step-specific diagnosis.",
                remediations=[
                    "Click 'Help' for this step to read its docstring.",
                    "Search `metrics.json` for the most relevant metric and re-run that stage.",
                ],
                fix=[],
            )
        )
    return to_json(
        AdvisoryCard(
            title=key,
            what=entry.get("what", ""),
            why=entry.get("why", ""),
            remediations=list(entry.get("remediations", [])),
            fix=_valid_fix(entry.get("fix")),
        )
    )
