"""The :mod:`lanex.controller` package — pure Python moat.

Zero imports from ``http.server``, ``webbrowser``, or anything in
:mod:`lanex.server`.  Fully unit-testable in isolation.  This is the
upstream-mergeable core.

Public API
----------
.. autofunction:: list_variables
.. autofunction:: list_design_formats
.. autofunction:: list_steps
.. autofunction:: list_flows
.. autofunction:: get_step
.. autofunction:: get_flow
"""

from __future__ import annotations

from . import alerts
from . import events
from . import fsbrowser
from . import history
from . import installer
from . import introspect
from . import models
from . import pdk
from . import reports
from . import runner
from . import tools

from .alerts import explain_alert, explain_checker_failure
from .history import list_runs, get_run, diff_runs
from .introspect import (
    list_variables,
    list_design_formats,
    list_steps,
    list_flows,
    get_step,
    get_flow,
)
from .installer import install_popen, install_ciel
from .fsbrowser import (
    DEFAULT_SOURCE_EXTS,
    list_dir,
    list_run_reports,
    read_text,
    walk_sources,
)
from .models import (
    AdvisoryCard,
    DRCReport,
    DesignFormatInfo,
    Event,
    EventType,
    FlowInfo,
    MetricSet,
    PDK,
    RunSummary,
    RunView,
    StepInfo,
    StepStatus,
    VariableInfo,
    Violation,
    ViolationSeverity,
    to_json,
)
from .pdk import list_pdks, list_scls, check_pdk_ready
from .reports import parse_drc, parse_lvs
from .runner import FlowRunner
from .tools import check_tools, install_tool, EDA_TOOLS

__all__ = [
    # Sub-modules
    "alerts",
    "events",
    "fsbrowser",
    "installer",
    "history",
    "introspect",
    "models",
    "pdk",
    "reports",
    "runner",
    "tools",
    # Functions
    "explain_alert",
    "explain_checker_failure",
    "list_runs",
    "get_run",
    "diff_runs",
    "list_variables",
    "list_design_formats",
    "list_steps",
    "list_flows",
    "get_step",
    "get_flow",
    "list_pdks",
    "list_scls",
    "check_pdk_ready",
    "parse_drc",
    "parse_lvs",
    "list_dir",
    "walk_sources",
    "read_text",
    "list_run_reports",
    "DEFAULT_SOURCE_EXTS",
    "check_tools",
    "install_tool",
    "install_popen",
    "install_ciel",
    "EDA_TOOLS",
    # Classes
    "AdvisoryCard",
    "DRCReport",
    "DesignFormatInfo",
    "Event",
    "EventType",
    "FlowInfo",
    "FlowRunner",
    "MetricSet",
    "PDK",
    "RunSummary",
    "RunView",
    "StepInfo",
    "StepStatus",
    "VariableInfo",
    "Violation",
    "ViolationSeverity",
    "to_json",
]
