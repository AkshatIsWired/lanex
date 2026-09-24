# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two audiences, weighted slightly toward the first:

- **Beginners**: college students and newcomers to chip design, mostly on Windows,
  who install LanEx with one `.exe`. They have never set up a Linux EDA toolchain and
  should be able to go from Verilog to a GDS without touching a terminal.
- **Experienced designers**: people who already know LibreLane and Linux, and install
  with one command. LanEx is new to them too. They must be able to do everything the
  terminal flow lets them do, without the UI getting in their way.

The balance: a beginner is never lost, and a power user never feels held back.

## Product Purpose

LanEx ("lane extender") is a desktop cockpit and IDE for the LibreLane RTL→GDSII flow.
It closes the gap between "I wrote some Verilog" and "I have a layout", which today
means setting up Linux, installing a version-matched EDA toolchain, hand-writing
`config.json`, learning an ~80-step flow and reading raw logs.

One application covers setup, PDKs, tools, editing, running, results and viewers.
Success: a first-time user gets a GDS from an example design in one sitting, and an
experienced user chooses LanEx over the terminal for day-to-day runs.

## Positioning

LanEx drives the real LibreLane flow and renders exactly what the tools emit. It
computes no silicon numbers itself, and every metric and setting traces back to the
tool's own file with one click (provenance). It is a viewer and driver, not a sign-off
tool. It is an independent project, not affiliated with or endorsed by LibreLane.

## Operating Context

- **Windows**: the installer sets up a private WSL distro (`lanex`) with the
  LibreLane container image and PDKs (via ciel). The Go launcher `LanEx.exe` opens
  the UI in an Edge app window. The Python server runs inside WSL, so designs live on
  the WSL filesystem.
- **Linux**: one-command install; the UI opens in a browser tab or app window.
- A session: pick or create a design (a design folder with RTL and a config), choose
  PDK/SCL, run the flow (container engine by default), watch the pipeline, then
  inspect runs, analytics, verification (DRC/LVS/antenna/timing), layout viewers
  (KLayout, Magic, OpenROAD GUI, GDS3D) and compare or sweep configurations (DSE).
- The appliance may be offline. Every asset (fonts, icons, scripts) ships locally.
- Screens: design for browser viewports of **1280 CSS px wide and up** (a 1080p
  laptop at 125–150% Windows scaling), scaling cleanly to 1440p and 4K. Narrower
  windows must degrade gracefully (collapse, scroll), never break or overlap.

## Capabilities and Constraints

- Run modes: Full Auto (default, most users) and Step-by-step. Engines: Container
  (default, recommended) and Local tools.
- A "project" is a design folder. The server remembers opened designs
  (`/api/known-designs`); templates scaffold new ones (`/api/project/new`).
- New projects default to a folder in the WSL home, with a way to reveal them in
  Windows Explorer and to reach Windows drives from the folder picker.
- Frontend: vanilla ES modules plus CSS, no build step and no UI framework. Python
  standard-library server. The static UI is served with `Cache-Control: no-store`.
- Core flow logic, metric parsing and calculations must not change during UI work.
  Software behaviour around them (navigation, panels, project handling) may.
- Existing tests (`lanex/tests/frontend_test.mjs`, pytest suite) must keep passing.

## Brand Commitments

- Name: **LanEx**. Keep the circuit "L" mark (`static/vendor/lanex-mark-*.png`,
  `lanex-logo-*.png`). The wordmark treatment is open to redesign. The
  "RTL → GDSII, no terminal" subline is dropped from the app chrome.
- Voice: plain, direct English that a student understands and an expert doesn't find
  patronising. Honest about limits: the "not sign-off, verify with foundry decks"
  disclaimer must stay visible somewhere in the app.
- Licence: Apache-2.0, provided AS IS.

## Evidence on Hand

- Bundled templates: Blinky, 8-bit Counter, Synchronous FIFO, Registered Multiplier,
  Empty; SPM example design.
- Screenshots in `docs/screenshots/`; README describes features.
- No testimonials, user counts or benchmarks exist. Do not invent any.

## Product Principles

1. **Beginner-safe, expert-fast.** Defaults carry a newcomer to a GDS; every expert
   control stays one step away, never hidden behind the beginner path.
2. **The tools' truth, shown honestly.** Never imply sign-off; every number is traceable.
3. **One place for everything.** Setup, tools, PDKs, runs and viewers live in one app
   with no terminal detours.
4. **Chrome recedes, the design leads.** The frame stays quiet so the user's design,
   run state and results carry the screen.
5. **Works on the machine students actually have.** Correct at 1280 px, crisp at 4K,
   no reliance on the network.

## Accessibility & Inclusion

Keyboard-operable throughout (existing shortcuts and command palette), visible focus,
WCAG AA contrast in both dark and light themes, and honouring `prefers-reduced-motion`.
