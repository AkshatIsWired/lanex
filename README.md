<!-- LanEx — README -->
<div align="center">

<img src="lanex/server/static/vendor/lanex-logo.png" alt="LanEx" width="400">

### Take Verilog all the way to silicon — without living in a terminal.

A browser cockpit &amp; IDE for the [**LibreLane**](https://github.com/librelane/librelane) RTL&nbsp;→&nbsp;GDSII chip flow.

<br>

[![License](https://img.shields.io/badge/license-Apache%202.0-2f6fe0.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-2f6fe0?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/runtime%20deps-stdlib%20only-4da3ff?style=flat-square)](#architecture)
[![Tests](https://img.shields.io/badge/tests-383%20passing-3fb950?style=flat-square)](#testing)
[![Built on LibreLane](https://img.shields.io/badge/built%20on-LibreLane-2f6fe0?style=flat-square)](https://github.com/librelane/librelane)

<a href="#install"><b>Install</b></a> &nbsp;·&nbsp;
<a href="#quickstart"><b>Quickstart</b></a> &nbsp;·&nbsp;
<a href="#the-cockpit"><b>The&nbsp;cockpit</b></a> &nbsp;·&nbsp;
<a href="#gui--cli"><b>GUI&nbsp;↔&nbsp;CLI</b></a> &nbsp;·&nbsp;
<a href="#architecture"><b>Architecture</b></a>

<br>

<img src="docs/screenshots/pipeline.png" alt="LanEx pipeline view" width="88%">

</div>

---

> ### ⚠&nbsp; LanEx is a viewer, not a sign-off tool
>
> LanEx drives LibreLane and the EDA tools it orchestrates (OpenROAD, Yosys,
> Magic, KLayout, Netgen) and **displays their output**. It performs **no silicon
> analysis of its own** — every metric, report, and verdict it shows comes
> straight from those tools, passed through unmodified.
>
> **Do not fabricate from a LanEx verdict alone.** Before committing a design to
> manufacturing, always verify results against your foundry's official sign-off
> decks and your shuttle/MPW program's checks. LanEx is provided **AS&nbsp;IS,
> without warranty of any kind** (Apache-2.0 — see [LICENSE](LICENSE) and
> [NOTICE](NOTICE)).

---

## Contents

- [Why LanEx](#why-lanex)
- [The cockpit](#the-cockpit)
- [Install](#install)
- [Quickstart](#quickstart)
- [GUI ↔ CLI](#gui--cli)
- [Architecture](#architecture)
- [Testing](#testing)
- [Relationship to LibreLane](#relationship-to-librelane)
- [License](#license)

---

## Why LanEx

LibreLane is powerful, but terminal-first: you hand-write a `config.json`, learn
an ~80-step flow, install a compatible toolchain, and read raw logs to find out
why a run failed. **LanEx** ("lane extender") puts a real, reactive GUI on top —
and it is honest by design: **it renders exactly what the tools emit and computes
no numbers itself.**

|  | |
|---|---|
| **▸ Runs the flow for real** | Not a mock-up. Drives `librelane`, streams true per-step status over SSE, parses the real `metrics.json`. |
| **▸ RTL IDE** | Edit Verilog with syntax highlighting; lint and simulate (Verilator / Icarus) with a built-in VCD waveform viewer. |
| **▸ Verification Center** | DRC / LVS / antenna / timing roll-up by signoff stage, with an honest **3-state** verdict — it never flashes green "tape-out ready" for an incomplete run. |
| **▸ Analytics &amp; DSE** | Metric trends, run comparison, and design-space sweeps. |
| **▸ Real layout viewers** | Opens the actual GDS in KLayout / Magic / GDS3D / OpenROAD GUI; renders previews inline. |
| **▸ Tool &amp; PDK management** | Detects what's installed and installs what's missing — one click. |

LanEx is a **standalone, independent project** built on LibreLane. It is not
affiliated with or endorsed by the LibreLane project or its maintainers.

---

## The cockpit

<div align="center">

| Setup | Verification | Analytics |
|:---:|:---:|:---:|
| <img src="docs/screenshots/setup.png" width="260"> | <img src="docs/screenshots/verify.png" width="260"> | <img src="docs/screenshots/analytics.png" width="260"> |
| **RTL IDE** | **Layout** | **Design-space exploration** |
| <img src="docs/screenshots/ide.png" width="260"> | <img src="docs/screenshots/layout.png" width="260"> | <img src="docs/screenshots/dse.png" width="260"> |

<sub>More in <a href="docs/screenshots/"><code>docs/screenshots/</code></a></sub>

</div>

---

## Install

LanEx is a small Python GUI — the standard library plus `librelane`. Install it
once; from there it can **install LibreLane and every EDA tool for you**, or plug
straight into a toolchain you already run. The recommended toolchain is
LibreLane's official, version-matched **container image**: one click pulls it and
you need no native EDA installs at all.

> **Prerequisite:** Python ≥ 3.10. Docker or Podman is recommended but
> **optional** — LanEx can install an engine for you (you confirm the password
> prompt in your terminal if the system package needs `sudo`).

### Get LanEx

```bash
git clone https://github.com/AkshatIsWired/lanex.git
cd lanex
pip install .            # or, once published: pip install lanex
lanex                    # opens the cockpit at http://localhost:8765
```

Then open the **Tools** tab and follow the row that matches your situation.

<table>
<tr><th align="left" width="220">Your situation</th><th align="left">What to do</th></tr>

<tr><td><b>1 · Nothing yet</b><br><sub>no LibreLane, no tools</sub></td>
<td>Tools tab → <b>Install the toolchain (recommended)</b>. One click pulls the version-matched LibreLane container image; keep the <b>Container</b> engine selected and you're done — zero native tool installs.<br><br><b>No Docker or Podman?</b> The same card installs one for you first, then pulls the image, all in one go. It runs the official installer (e.g. <code>curl -fsSL https://get.docker.com | sudo sh</code> on Linux, <code>brew install podman</code> on macOS, or Docker Desktop with the WSL2 backend on Windows); you confirm the password prompt in your terminal.</td></tr>

<tr><td><b>2 · One command</b><br><sub>GUI <i>and</i> toolchain</sub></td>
<td>

```bash
pip install . && lanex --pull-image && lanex
```

`--pull-image` pulls the LibreLane container headless and exits, then `lanex`
launches the cockpit with the toolchain already in place. LanEx recognises the
pulled image as your container toolchain automatically.</td></tr>

<tr><td><b>3 · You already run LibreLane</b></td>
<td>Install LanEx into the <b>same</b> Python environment and run <code>lanex</code>. It auto-detects your setup: use the <b>Local tools</b> engine to run against your native toolchain, or <b>Container</b> to drive <code>librelane --dockerized</code>. Nothing extra to install.</td></tr>

<tr><td><b>4 · Recommended extras</b><br><sub>optional niceties</sub></td>
<td>The Tools tab's <b>Recommended extra tools</b> group one-click-installs <b>Icarus Verilog</b> (RTL simulation in the IDE), <b>Graphviz</b> (synthesis schematics), and <b>GDS3D</b> (3D layout viewer). System packages that need <code>sudo</code> prompt for your password in the launch terminal.</td></tr>
</table>

---

## Quickstart

```bash
lanex                                  # localhost cockpit, opens a browser
lanex --design-dir path/to/my_chip     # open already pointed at a design
lanex --no-browser --port 9000         # headless / custom port
lanex --host 0.0.0.0 --allow-remote    # expose on your network (no auth — take care)
```

**Your first chip in five clicks:**

1. **Setup** → pick your HDL folder (or click **Use the SPM example**).
2. **Tools** → confirm everything is installed (install anything red).
3. Confirm the **PDK** + standard-cell library match your target.
4. Choose **Full Auto** or **Step-by-step** in the top bar.
5. Press **Run**. Watch the pipeline light up; the GDS lands on **Preview**.

### The tabs

| Tab | What it does |
|-----|--------------|
| **Setup** | Pick design, PDK/SCL, flow; auto-generate a config. |
| **Pipeline** | Live per-step run timeline + logs + step output. |
| **RTL IDE** | Edit / lint / simulate Verilog; VCD waveform viewer. |
| **Verification** | DRC / LVS / antenna / timing signoff verdict. |
| **Analytics** | Metric trends, run comparison, cell usage. |
| **DSE** | Design-space sweeps and result viewer. |
| **Layout** | Open GDS in KLayout / Magic / GDS3D / OpenROAD. |
| **Cells &amp; Macros** | PDK std cells; insert custom cells + hard macros. |
| **Runs** | Browse history; pin, import, export, and bundle runs. |

---

## GUI ↔ CLI

LanEx never hides what it runs. Everything it does maps onto the ordinary
`librelane` CLI, and the **Manual** tab's **Reveal CLI** button always prints the
*exact* command for your current design, config, and overrides (container or
local). That button is authoritative; the table below is the quick mental model.

| GUI action | Equivalent CLI |
|-----------|----------------|
| Setup → **Run** (container) | `librelane --dockerized <config> --pdk <PDK> --scl <SCL>` |
| Setup → **Run** (local tools) | `librelane <config> --pdk <PDK> --scl <SCL>` |
| Pipeline **From / To / Skip** | `librelane … --from <Step> --to <Step> --skip <Step>` |
| Setup → **Run name** | `librelane … --run-tag <name>` |
| Verify → **re-run a check** | `librelane … --last-run --to <Checker>` |
| Runs → **Reproduce** | replays the run's persisted `gui-run.json` command verbatim |
| Manual tab console | runs the allow-listed tool you type, and streams its output |

Config overrides set in the form are passed as `-c KEY=VALUE` (plus a
`.gui-*.json` overlay for the nested `MACROS` / custom-cell variables a flat `-c`
string can't express). Reveal CLI shows the fully-expanded command, so you can
paste it into a terminal and get byte-identical behaviour.

---

## Architecture

LanEx is built to keep both the install and the trust surface small.

- **A pure-Python controller.** `lanex/controller/` imports only `librelane.*`
  and the standard library — no web framework, no ORM, no bundler. It never
  touches HTTP directly; it is the faithful, upstream-mergeable core.
- **A stdlib server.** `lanex/server/` is a `http.server` + Server-Sent-Events
  backend. Zero third-party runtime dependencies.
- **A vanilla frontend.** ES modules with a single vendored copy of ECharts — no
  React, no TypeScript, no build step.
- **Faithful by construction.** LanEx renders exactly what the tools emit. A
  golden-corpus regression suite and a startup compatibility probe fail loudly if
  the installed `librelane` ever drifts from what LanEx parses, so displayed
  numbers can't silently go wrong.

```
lanex/
├─ controller/   pure-Python core (librelane + stdlib only)
├─ server/       http.server + SSE; no third-party deps
│  └─ static/    vanilla ES-module SPA + vendored ECharts
└─ tests/        383 tests, incl. a golden-run corpus
```

---

## Testing

```bash
pip install pytest
python3 -m pytest lanex/tests -q     # 383 passed, 3 skipped
```

The suite includes a golden-run corpus (a clean run and a non-finite-metric run)
that locks LanEx's byte-faithful passthrough against regressions.

---

## Relationship to LibreLane

LanEx is an independent project that **uses** LibreLane; it does not modify it.
LibreLane is licensed under Apache-2.0 and is invoked as an external program.
See [NOTICE](NOTICE) for attribution. LanEx is not affiliated with or endorsed by
the LibreLane project.

## License

[Apache License 2.0](LICENSE). Provided **AS&nbsp;IS, without warranty** — see the
sign-off disclaimer at the top of this file and in [NOTICE](NOTICE).

<div align="center"><sub>Built for the open-silicon community.</sub></div>
