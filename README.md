<p align="center">
  <img src="lanex/server/static/vendor/lanex-logo.png" alt="LanEx" width="380">
</p>

<p align="center">
  <b>A browser cockpit &amp; IDE for the LibreLane RTL&nbsp;→&nbsp;GDSII chip flow.</b><br>
  Take Verilog all the way to silicon — without living in a terminal.
</p>

---

> ### ⚠ LanEx is a viewer, not a sign-off tool
>
> LanEx drives [LibreLane](https://github.com/librelane/librelane) and the EDA
> tools it orchestrates (OpenROAD, Yosys, Magic, KLayout, Netgen) and **displays
> their output**. It performs **no silicon analysis of its own** — every metric,
> report, and verdict it shows comes straight from those tools, passed through
> unmodified.
>
> **Do not fabricate from a LanEx verdict alone.** Before committing a design to
> manufacturing, always verify results against your foundry's official sign-off
> decks and your shuttle/MPW program's checks. LanEx is provided **AS IS, without
> warranty of any kind** (Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE)).

---

## What it is

LibreLane is powerful but terminal-first: you hand-write a `config.json`, learn
an ~80-step flow, install a compatible toolchain, and read logs to find out why a
run failed. **LanEx** ("lane extender") puts a real, reactive GUI on top:

- **Runs the flow for real** — it is not a mock-up. It drives `librelane`, streams
  true per-step status over SSE, and parses the real `metrics.json`.
- **An RTL IDE** — edit Verilog with syntax highlighting, lint, and simulate
  (Verilator / Icarus), with a built-in VCD waveform viewer.
- **Verification Center** — DRC / LVS / antenna / timing roll-up, organized by
  signoff stage, with an honest 3-state verdict (it never shows green
  "tape-out ready" for an incomplete run).
- **Analytics & DSE** — metric trends, run comparison, and design-space sweeps.
- **Real layout viewers** — opens the actual GDS in KLayout / Magic / GDS3D /
  OpenROAD GUI; renders previews inline.
- **Tool & PDK management** — detects what's installed, installs what's missing.

It is a **standalone, independent project** built on LibreLane. It is not
affiliated with or endorsed by the LibreLane project or its maintainers.

<p align="center"><img src="docs/screenshots/pipeline.png" alt="LanEx pipeline view" width="80%"></p>

---

## Install

LanEx is a small Python GUI (the Python standard library + `librelane`). Install
it once; from there it can **install LibreLane and every EDA tool for you**, or
plug into a toolchain you already run. The recommended toolchain is LibreLane's
official, version-matched **container image** — one click pulls it and you need no
native EDA installs at all.

**Prerequisite:** Python ≥ 3.10. Docker or Podman is recommended but **optional** —
LanEx can install an engine for you (you confirm the password prompt in your
terminal if the system package needs `sudo`).

### Get LanEx

```bash
git clone https://github.com/AkshatIsWired/lanex.git
cd lanex
pip install .            # or, once published: pip install lanex
lanex                    # opens the cockpit at http://localhost:8765
```

Then open the **Tools** tab and follow the row that matches your situation.

### 1 · You have nothing yet — no LibreLane, no tools

Tools tab → **Install the toolchain (recommended)**. One click pulls the
version-matched LibreLane container image; keep the **Container** engine selected
and you're done — zero native tool installs.

**No Docker or Podman?** The same card installs one for you first, then pulls the
image — all in one go. (It runs the official installer, e.g.
`curl -fsSL https://get.docker.com | sudo sh` on Linux, `brew install podman` on
macOS, or Docker Desktop with the WSL2 backend on Windows; you confirm the
password prompt in your terminal.)

### 2 · One command — GUI **and** toolchain

```bash
pip install . && lanex --pull-image && lanex
```

`--pull-image` pulls the LibreLane container headless and exits, then `lanex`
launches the cockpit with the toolchain already in place. LanEx **recognises the
pulled image as your container toolchain automatically** — the Tools tab shows
*image pulled · Container ready*.

### 3 · You already run LibreLane

Install LanEx into the **same** Python environment and run it:

```bash
pip install .
lanex
```

LanEx auto-detects your setup. Use the **Local tools** engine to run flows against
your native toolchain, or **Container** to drive `librelane --dockerized`. Nothing
extra to install — it works with what you already have.

### 4 · Recommended extras (optional)

The Tools tab's **Recommended extra tools** group one-click-installs the niceties
LanEx adds on top: **Icarus Verilog** (RTL simulation in the IDE), **Graphviz**
(synthesis schematics), and **GDS3D** (3D layout viewer). System packages that
need `sudo` prompt for your password in the launch terminal.

---

## Run it

```bash
lanex                                  # localhost cockpit, opens a browser
lanex --design-dir path/to/my_chip     # open already pointed at a design
lanex --no-browser --port 9000         # headless / custom port
lanex --host 0.0.0.0 --allow-remote    # expose on your network (no auth — care)
```

### Your first chip in 5 clicks

1. **Setup** tab → pick your HDL folder (or click **Use the SPM example**).
2. **Tools** tab → confirm everything is installed (Install anything red).
3. Confirm the **PDK** + standard-cell library match your target.
4. Choose **Full Auto** or **Step-by-step** in the top bar.
5. Press **Run**. Watch the pipeline light up; the GDS lands on **Preview**.

---

## Screenshots & tabs

| Tab | What it does |
|-----|--------------|
| **Setup** | Pick design, PDK/SCL, flow; auto-generate a config. |
| **Pipeline** | Live per-step run timeline + logs + step output. |
| **RTL IDE** | Edit / lint / simulate Verilog; VCD waveform viewer. |
| **Verification** | DRC / LVS / antenna / timing signoff verdict. |
| **Analytics** | Metric trends, run comparison, cell usage. |
| **DSE** | Design-space sweeps and result viewer. |
| **Layout** | Open GDS in KLayout / Magic / GDS3D / OpenROAD. |
| **Cells & Macros** | PDK std cells; insert custom cells + hard macros. |
| **Runs** | Browse run history; download result bundles. |

Screenshots live in [`docs/screenshots/`](docs/screenshots/).

---

## How it stays clean

LanEx's controller layer (`lanex/controller/`) is pure Python that imports only
`librelane.*` and the standard library — no web framework, no bundler, no React.
The frontend is vanilla ES modules with a vendored copy of ECharts. This keeps
installs trivial and the trust surface small: **LanEx renders exactly what the
tools emit and computes no numbers itself.**

---

## Tests

```bash
pip install pytest
python3 -m pytest lanex/tests -q
```

---

## Relationship to LibreLane

LanEx is an independent project that **uses** LibreLane; it does not modify it.
LibreLane is licensed under Apache-2.0 and is invoked as an external program.
See [NOTICE](NOTICE) for attribution. LanEx is not affiliated with or endorsed
by the LibreLane project.

## License

[Apache License 2.0](LICENSE). Provided **AS IS, without warranty** — see the
sign-off disclaimer at the top of this file and in [NOTICE](NOTICE).
