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

There are two ways in. **Newcomers want Option A.**

### Option A — Docker bundle (everything included) · recommended

The bundled image is based on the official LibreLane image, so the entire EDA
toolchain is already inside. You need **only Docker** — no Python, no LibreLane,
no tool installs.

```bash
git clone https://github.com/AkshatIsWired/lanex.git
cd lanex
docker compose up          # builds the image, then serves the cockpit
```

Then open **http://localhost:8765**. Put your HDL projects under `./work`
(mounted at `/work` in the container).

Or without compose:

```bash
docker build -t lanex:latest .
docker run --rm -p 8765:8765 -v "$PWD/work:/work" lanex:latest
```

> Pin a specific LibreLane release for reproducible tool versions:
> `docker build --build-arg LIBRELANE_TAG=3.0.4 -t lanex:latest .`

### Option B — add-on to an existing LibreLane install

If you already run LibreLane in a Python environment, install LanEx into the
same environment:

```bash
pip install lanex          # from PyPI (or: pip install . from a clone)
lanex                      # opens the cockpit in your browser
```

LanEx declares `librelane` as its only dependency and otherwise uses the Python
standard library. With a local toolchain it runs flows natively; with Docker
available it can also drive `librelane --dockerized`.

**Requirements (Option B):** Python ≥ 3.10, an installed `librelane`, and either
a local EDA toolchain or Docker/Podman for container runs.

### Independence & self-hosting

LanEx is built on LibreLane but is designed to keep working no matter what happens
upstream. A built image is a frozen, self-contained snapshot — once published it
needs none of LibreLane's servers to pull, run, or restore. Maintainers ship a
release with one command:

```sh
docker login ghcr.io
VERSION=0.1.0 ./scripts/release.sh        # mirror base → build → push → cold tarball
```

This (1) mirrors the LibreLane base into your own registry and pins its exact
`@sha256:` digest in `base-image.lock`, (2) builds + pushes `ghcr.io/<you>/lanex`,
and (3) writes a cold `docker save` tarball restorable with zero registry. Full
runbook: [`docs/RELEASE.md`](docs/RELEASE.md).

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
