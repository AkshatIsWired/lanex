# M0 baseline and capability inventory

Recorded 2026-09-08 from source `725dcb650e8ac436641bc8a84e856991ca806881`
plus the M0 working-tree fixes described below. Detailed logs are in
`C:\Users\itsva\Documents\Codex\2026-09-08\implement-the-lanex-windows-installer-handoff\work\m0-evidence-20260908`.

## Safety and environment

- Local and remote `windows-installer-support` both began at `725dcb6`; remote
  `main` remained `ff0759b`. The working tree was clean before M0.
- Existing `Ubuntu`, `lanex`, and `Ubuntu-22.04` WSL2 distributions were
  inventoried and treated as protected. No distro was imported, converted,
  terminated, unregistered, provisioned, or used as the installer target.
- Linux tests used a disposable source clone, HOME, and venv under
  `/tmp/lanex-m0-20260908` in `Ubuntu`. No `apt`, `sudo`, or system package
  install ran. Python dependencies were installed only into that venv.
- Dependency catalog baseline: Python 3.12.3, LanEx 1.0.0, LibreLane 3.0.4,
  Ciel 2.6.1. Node 20.19.5 and Windows Go 1.22.12 archives were downloaded
  from their official sites and SHA256-verified before use.

## Capability mapping

The machine-generated record is `CAPABILITY-INVENTORY.json`. It is generated
from `EDA_TOOLS` and Ciel's `Family` registry in the pinned Linux venv, rather
than from a hand-maintained PDK list.

| Tools-page capability | Windows appliance delivery | Required acceptance probe |
|---|---|---|
| Python, pip, LanEx, LibreLane | appliance Python environment | exact interpreter imports and stamped versions/source |
| Yosys | matched LibreLane image | execute version probe in selected image |
| OpenROAD | matched image; container GUI control | version probe and real GUI/output open |
| KLayout | matched image; container GUI control | version probe and real GDS open |
| Magic | matched image; container GUI control | version probe and real PDK-mapped GDS open |
| Netgen | matched image; container control | version probe and PDK-mapped LVS control |
| Verilator | matched image for flow; native package for IDE | image version plus native lint |
| Icarus Verilog + vvp | native Ubuntu package | compile and run a small simulation |
| Graphviz | native Ubuntu package | render DOT to SVG |
| GTKWave | native Ubuntu package + WSLg runtime | version/start plus real VCD open |
| Ciel | appliance Python environment | exact version and writable owned store |
| GDS3D (frontend special control) | shared native source-build recipe | C++/headers, linkage, binary, real GDS/process-map open |
| Docker / Podman (frontend special controls) | Docker CE default; Podman alternative | selected local daemon/socket and executable container |
| LibreLane image pull (frontend special control) | matched pinned image | digest plus execution of each required tool |

The backend catalog contains 13 entries: `python`, `pip`, `librelane`, `yosys`,
`openroad`, `klayout`, `magic`, `netgen`, `verilator`, `iverilog`, `graphviz`,
`gtkwave`, and `ciel`. Frontend inspection adds the four special rows/actions
above. Container-launchable viewer controls are exactly `magic`, `klayout`,
`openroad`, and `netgen`.

Ciel 2.6.1 exposes seven variants: `sky130A`, `sky130B`, `gf180mcuA`,
`gf180mcuB`, `gf180mcuC`, `gf180mcuD`, and `ihp-sg13g2`. The JSON records every
variant's full and default library sets. Ciel marks each family's own default
variant as recommended (`sky130A`, `gf180mcuD`, and `ihp-sg13g2`); that field
must not be interpreted as selecting three installer defaults. The product
default remains sky130A with all 12 catalog libraries and
`sky130_fd_sc_hd` as the initial SCL, subject to M1/M3 pin validation.

## M0 changes

- Root CI and Differential push coverage now includes
  `windows-installer-support`; pull-request, main, and schedule coverage remain.
- The stale passwordless-sudo test now matches the intended implementation:
  passwordless sudo uses streamed isolated `Popen`; password-required sudo uses
  the tty. Both branches mock the sudo decision and all process execution, so a
  unit test cannot invoke host apt or sudo.
- Added the missing round-76 CI Summary implication discovered by the first
  baseline run. No test was skipped or weakened to make the suite green.

## Reproducible checks and results

Preparation scripts used for this run are retained in the task `work`
directory (`m0-prepare-linux.sh`, `m0-linux-baseline.sh`,
`m0-go-windows.ps1`, and `m0-inventory.py`). The substantive commands were:

```text
python -m pytest lanex/tests -q --junitxml=<evidence>/pytest-report.xml -p no:cacheprovider
python -m build --wheel --outdir <evidence>/dist
node lanex/tests/frontend_test.mjs
node --check <app.js and every first-party module>
go test -v ./...
go vet ./...
go build -trimpath .
gofmt -l .
Git Bash: bash -n scripts/install.sh scripts/install-wsl.sh windows/provision/provision.sh windows/provision/selftest.sh
```

Verified results:

- Full Python suite: **737 passed, 6 skipped, 0 failed**.
- Focused installer/round-75 safety suite: **29 passed**.
- Frontend behavior: **41 checks passed**; all JS syntax and static pictograph
  hygiene checks passed.
- Wheel build and all required nested asset sentinels passed.
- Windows launcher: Go tests, vet, build, and formatting all passed.
- Explicit Git Bash syntax checks passed for all four install/provision scripts.

The six environment-gated skips were Graphviz SVG exclusion, real-browser
dialog layout, a LibreLane-version-specific `RUN_LVS` case, two absent bundled
SPM fixtures, and a PDK-liberty canary. They are not failures and do not stand
in for later real GTKWave, PDK, flow, browser, WSLg, or installer acceptance.

An initial diagnostic run directly from the Windows checkout was intentionally
not accepted as the Linux baseline: CRLF shell files, the venv's `/mnt/c` path,
and the existing WSL user's PDK store contaminated three tests, while Windows
Node cannot run the Linux-targeted dynamic-import fixture. Re-running from the
disposable ext4 clone and isolated HOME produced the verified result above.

No installer EXE, WSL import/provision, daemon, GUI, reboot/resume, PDK download,
or RTL-to-GDS hardware acceptance case ran in M0. Those remain assigned to the
later milestones and must not be inferred from this baseline.
