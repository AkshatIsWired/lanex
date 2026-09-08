# Implementation plan: ready-to-use LanEx on Windows

Use alongside AUDIT and TEST-MATRIX. Proposed new filenames and command interfaces below are specifications to implement, not existing features. Existing source references are verified against the audited HEAD.

## Product decisions

1. Deliver one small online Setup EXE. It may download verified payloads during installation; it must finish the selected tools/PDKs before first launch. “One EXE” does not mean embedding several gigabytes into the executable. An offline bundle is a later enhancement, not required to finish this work.
2. Keep a private Ubuntu 24.04 WSL2 appliance. Reuse the machine's WSL platform when present, without converting, provisioning, unregistering or changing the default of the user's other distributions. Use a new owned appliance when absent.
3. Recommended setup is preselected: Docker CE in the appliance, version-matched LibreLane image, native supporting tools, and sky130A with all catalog-listed family libraries. Choose `sky130_fd_sc_hd` as the initial SPM standard-cell library. Validate that choice against the pinned build's catalog and bundled example; do not blindly hardcode a stale PDK hash.
4. Every supported PDK displayed by LanEx is selectable before install. Resolve the catalog from the locked Ciel/LibreLane build at packaging time and bundle it for Windows UI use. Unsupported/unvalidated combinations need an honest explanation, not a promise that every PDK can run every flow/template. All PDKs are not selected by default: show their real additional download/storage cost.
5. “All tools” means all user-facing capabilities available through their correct execution paths. Flow tools stay in the matched image; support tools needed by the IDE/viewers live in Ubuntu. Docker and Podman are alternative engines; do not install both by default. Native advanced flows are separate from the recommended container workflow.
6. Windows 11 x64 is the primary release target. Set technical GUI floor to at least Windows 10 build 19044; advertise Windows 10 only after the legacy acceptance leg passes, and disclose its support status accurately in release documentation. Reject ARM64 for the amd64 appliance. Do not spend this release implementing ARM64 or winget.
7. Finish has three honest outcomes: ready; incomplete with a resumable failed component; or explicitly user-selected minimal install. Minimal setup can be an advanced choice, but must never be labeled ready for RTL→GDS. Required failures cannot silently become deselections.

## Capability contract

Make one generated catalog/manifest enumerate every current Tools-page entry. A test must fail if a new entry has no install/availability/verification policy. Do not maintain independent hardcoded lists in Pascal, Python and tests.

| Capability | Default delivery | Required verification |
|---|---|---|
| Python, pip, LanEx, LibreLane, Ciel | Appliance Python environment, preserving pipx/venv fallback | Imports in the exact LanEx interpreter; app version/source SHA; locked LibreLane/Ciel versions. PATH absence of dependency entry points is not missing software. |
| Docker engine | Docker CE service inside appliance | Daemon ready as ordinary appliance user, selected socket/context, executable container. Do not accidentally use a Windows docker.exe or another daemon/context. |
| Yosys, OpenROAD, KLayout, Magic, Netgen, Verilator for flow | Exact LibreLane container image | Probe each via actual image environment, version-compatible result; image digest recorded. Container availability is verified, not inferred from a known tag or decorative green badge. |
| Icarus + vvp, Verilator for IDE, Graphviz | Native Ubuntu support packages | Compile/run tiny Verilog test, Verilator lint, DOT-to-SVG. Native Verilator's presence must not silently change the default flow mode away from the pinned container. |
| GTKWave | Native Ubuntu + display/runtime dependencies | Version/start checks and real VCD opening on WSLg. |
| GDS3D | Native build via existing shared recipe, ideally baked | Linux C++ compiler/make/git; X11/OpenGL headers; binary/linkage; real example GDS with valid process map on WSLg. |
| KLayout/Magic/OpenROAD/Netgen viewer controls | Existing container GUI paths | Open actual relevant output with configured PDK and display; no extra native installs merely to make PATH probes green. |
| sky130A default | Pinned Ciel family store under appliance user's home | Exact LibreLane-required version, selected libraries, enabled variant, permissions, `check_pdk_ready(..., scl='sky130_fd_sc_hd', run_mode='container')`, successful bundled SPM run. |
| Other selected PDKs/libraries | Same Ciel backend | Deduplicated family/version fetch, selected library artifacts and enabled variants; compatibility-appropriate smoke check. |

GDS3D dependency baseline to preserve from universal installer: `build-essential libx11-dev libxmu-dev libxi-dev libgl1-mesa-dev libglu1-mesa-dev freeglut3-dev`, plus git and existing X11 font/Mesa runtime packages. Keep their authoritative recipe shared. Detect a usable Linux C++ driver; `cc` alone and a Windows tool on PATH are insufficient.

## Installation flow

```text
Welcome → preflight → recommended components / PDKs → summary / space estimate
  → enable/update WSL when necessary [limited elevation]
  → persist state → restart only if required → resume same user/build/selection
  → verify/download base payload → import owned appliance
  → base provision using bundled universal installer
  → terminate ONLY owned appliance → boot and verify systemd + Docker
  → install/verify selected image, native support tools, PDKs
  → operational checks → readiness report → Finish / Launch LanEx

Any phase failure → clear reason + live details + Retry / Save and exit
Retry → re-probe completed work → continue missing/failed work
```

The phase between base provision and full finalization is essential. Merely removing `LANEX_SKIP_PULL=1` inside current base provision will attempt the pull before Docker is running.

## Data and interface contracts

Implement three small versioned JSON records, not a general workflow platform:

- **Build manifest** (immutable, shipped with Setup): schema, source SHA/repository, app version/channel, target OS/architecture and WSL capability floors, rootfs URL/hash/size, Python wheel/source payload hash, locked Python versions, GDS3D source commit, selected image reference/digest, PDK catalog + required hashes/library sets, measured size estimates.
- **Install state** (atomically written, owner-scoped): schema, install UUID, original Windows SID, manifest hash, operation (install/repair/update), choices, appliance name + registry identity + canonical path, phase and component status, boot identity/restart attempt count, cancellation/failure code, last event cursor. Never contain secrets or arbitrary executable commands. Component inputs have fingerprints; a prior success is reusable only when current verification and inputs match.
- **Readiness report**: source identity, manifest hash, user/instance identity, actual engine/image/PDK versions, per-component checks and failures, overall status. Shared by Setup, support diagnostics and LanEx's setup status display. A successful help command alone cannot create it.

Proposed Windows bridge: `windows/setup/setup.ps1` for orchestration with subprocess argument arrays and structured events. Inno starts the worker asynchronously and polls an append-only UTF-8 NDJSON event file while keeping its own UI responsive. Prefer this bounded addition over a new Electron/WPF app or a second Go GUI. If a native helper becomes necessary for safe argument/process handling, keep it narrowly scoped and document why.

Event fields: schema, sequence, UTC timestamp, install ID, phase/component, event type, human message, optional bytes done/total, exit/error code. Separate raw subprocess log from structured state. Poll incrementally; incomplete final JSON line is retried, not fatal. Keep a bounded visible tail; flush output during quiet phases with elapsed-time/heartbeat messages. Do not fabricate percentages when a tool supplies no total.

Proposed headless Python interfaces: `lanex --install-pdk <variant>` with validated repeatable library selection, and `lanex --setup-check <manifest>` (or an equivalent narrow module command). Add a synchronous backend helper returning final structured results; keep existing asynchronous UI methods as wrappers around it. Reuse this for all setup entry points. Do not poll a global SSE bus and assume the first child `installer_done` means the entire PDK job succeeded.

On Windows, let the original unelevated user own Setup orchestration and appliance import. Elevate only allowlisted machine-feature/update operations. Bind helper requests/results to that operation and original user; never accept arbitrary shell text from the state file. Validate bundled helper integrity and protect elevated staging against replacement. Per-user launcher installation under the user's Programs directory is the target; explicitly migrate legacy machine-wide Program Files/AppId installs without wiping their appliance. Preserve AppId identity unless an unavoidable migration is designed/tested. Existing installations launched elevated require detection and a clear relaunch/continuation path, not guessing which account should own the distro.

## M0 — Baseline and test harness

Dependencies: none. Findings: A21 and baseline-test contradiction.

Files: existing root workflows, `lanex/tests/test_installer.py`, round75 tests; new repository copy of handoff.

Tasks:

- Reconcile Git/host inventory with STATE; keep existing distributions protected. Adopt the handoff in the repository and choose a named scratch/evidence directory.
- Generate the exact Tools/PDK capability inventory using installed pinned dependencies in an isolated Linux environment. Record the mapping above; inspect all frontend special controls.
- Repair the stale passwordless-sudo test to match current intended streaming semantics. Mock Popen, sudo probes and all system changes before invoking either branch. Keep both password-required and passwordless tests; don't weaken assertions or revert the bug fix to satisfy the stale test.
- Establish Linux unit-test environment with `pip install .` + pytest in a task venv/container. Do not run these packages/tests by installing into an existing user's application environment. Use explicit Git Bash only for Windows shell syntax diagnostics; app backend tests belong on Linux with actual dependencies.
- Run baseline full Python suite, frontend behavior/syntax, wheel asset test and current Go tests in supported environments. Record pre-existing failures with cause. Do not hide them behind blanket skips.

Done: reproducible test commands, inventory and baseline results saved; unrelated dirty files preserved; no regression test can accidentally run host apt.

## M1 — Identity, exact payloads and durable state

Dependencies: M0. Findings: A08–A12, A17–A18 (foundations).

Files: `scripts/install.sh`, `windows/provision/provision.sh`, `windows/installer/lanex.iss`, new `windows/setup/setup.ps1`, build-manifest generation, narrow state tests.

Tasks:

- Fix universal Git source resolution to support branch, tag and SHA without branch-only URL. Prefer a packaged wheel/local source path for Windows using existing `LANEX_FROM`; make all script/payload inputs the same checked-out commit.
- Bundle `scripts/install.sh` with Setup and base provision payload. Download dependencies when required, but never fetch moving main to replace the candidate being tested. Check fetch exit before execution; no root or login-shell curl pipelines. Preserve universal shim compatibility.
- Pin LibreLane client to the selected image-compatible version using Windows build constraints; retain the ordinary project's supported range outside Windows packaging. Produce image/PDK pins from that locked environment, not an unrelated developer install. Record provenance for GDS3D and dependency resolution.
- Implement atomic owner-scoped install state and appliance identity marker; bind Windows registration's exact path and Linux marker to install UUID. New isolated installs use an owned subtree (e.g. `%LOCALAPPDATA%\LanEx\appliance`) and separate appliance profile. A matching name alone grants no repair/delete authority.
- On legacy `lanex`, inspect registration path, existing installer metadata and contents read-only; adopt only when ownership is proven. If ambiguous, leave untouched and choose a safe distinct appliance name or ask the user to identify it. Pass chosen name/ID to launcher rather than adding another hardcoded constant.
- Preserve user options, build SHA, installer hash, original SID, and restart counters across both manual reruns and automatic resume. Readiness/state schemas need explicit migration and rejection of malformed/newer records.
- Make no-op Repair verify installed identity without silently upgrading dependencies. Update is explicit; failed app update retains/restores previous functional app environment. Plan data-preserving legacy Program Files migration before changing privilege mode.

Done: branch/tag/SHA and local-wheel tests; simulated interrupted state write; foreign-name collision protected; changed manifest invalidates relevant completion markers; repair never switches source branch silently. Test artifact contains exact checkout even for fork PR.

## M2 — Preflight, user context and reliable restart

Dependencies: M1. Findings: A05–A09, A22.

Files: Inno wizard, setup worker/helper, Windows preflight/resume tests, user install docs.

Tasks:

- Probe native architecture, Windows build, firmware virtualization support/enabled status (CIM `Win32_Processor` as one signal), hypervisor presence, optional-feature states, pending reboot and installed WSL version/capabilities. Use structured outputs and check process exit status. HypervisorPresent=true should avoid misleading firmware false negatives; unknown is not “disabled.”
- Before Windows feature changes/reboot, show a specific firmware-disabled block when evidence supports it. Offer Microsoft help from AUDIT; include PC manufacturer/model when available. For unknown firmware state, show a short prerequisite notice and recheck after WSL setup. Do not recommend Secure Boot changes.
- Distinguish firmware-disabled, feature-disabled, pending-reboot, old WSL, policy restriction and failed kernel boot. Validate each feature command result separately and preserve original errors. Accept documented success/restart codes per operation; don't apply DISM codes indiscriminately to all tools.
- Keep feature elevation separate from original-user import, state, shortcuts and first launch. Test standard user with a different admin's UAC credentials. If policy denies WSL, explain that an administrator must enable it; do not promise an automatic bypass.
- WSL that already meets capabilities is reused without global default-version change or unconditional disruptive updates. If update/restart affects other WSL work, show the impact and defer safely. Never shut down all distros as ordinary recovery.
- Schedule an owner-bound resume trigger appropriate to the unelevated flow. Do not rely only on HKLM RunOnce. Use durable state plus manual “Continue setup” fallback; verify registration succeeded. Bound automatic feature/reboot attempts per recorded boot identity. Cancelling UAC or choosing restart later must retain a recoverable setup, not false completion or a login loop.
- Persist the staged installer safely; verify its identity on resume. Revalidate current disk space, ownership and capabilities. Reboot must never reset PDK choices.

Done: preflight fixtures pass; no-WSL/firmware-off blocks before feature changes; feature pending is not BIOS error; original user owns appliance after different-admin elevation; reboot/manual-resume tests in matrix pass or remain explicit release blockers.

## M3 — Shared component installation and readiness

Dependencies: M1; real finalization needs M2. Findings: A01–A03, A15–A16.

Files: universal installer and provision/selftest scripts, `lanex/cli.py`, `installer.py`, new narrow provisioning/check module, `pdk.py`/`tools.py` only as necessary, tests.

Tasks:

- Split provisioning into `base` and `finalize` modes with explicit schemas/inputs. Base invokes every applicable universal stage; stages deferred due to missing daemon run in finalization through the same shared implementation. Mark deferred explicitly in logs and parity tests.
- Keep universal interactive defaults intact. Add appliance strictness at selected-component postconditions (or an explicit strict mode), not a global `set -e` rewrite that breaks fallback chains. Each original applicable command is accounted for as executed, already verified, or intentionally scheduled later.
- Ensure systemd and required Ubuntu packages exist. After base, terminate only owned distro, boot it, wait with bounded progress for systemd/Docker, then execute finalization as the appliance user in a writable home with Linux tools selected. Validate Docker local socket/context.
- Install native support tools and GDS3D by shared backend; all errors and subprocess output must reach Setup. Verify headers, genuine C++ driver, binary linkage and runtime dependencies. A baked binary may satisfy checks without rebuilding; hashes/provenance must match.
- Implement synchronous PDK job with final return status, shared by CLI and async UI wrapper. Resolve `required_pdk_version` from locked LibreLane; fail actionable if a required pin is missing instead of silently choosing latest for the strict appliance mode. Validate variants/libraries against manifest/catalog; never interpolate unvalidated library strings into shell commands.
- Default sky130A selects all `Family.all_libraries` from build catalog, including any mandatory/default dependencies validated from Ciel. Advanced library selection includes required set plus selected libraries. Deduplicate by family/version; sky130 variants must not concurrently write the same tree. Prove selected variant and libraries are present with readiness checks.
- Fix ciel retry: explicit final failure code, backoff on transient errors, no repeat for permanent incompatibility/permission/policy errors. Never delete an installed valid version after a failed add-library request. Stage safely where possible; cleanup only diagnosed incomplete owned extraction, retaining verified tar/layer caches. Cancellation must not proceed into another strategy or enable after exhausted fetch attempts.
- Image pull uses matched pinned digest with existing engine resolver and records it. Running a container tool is required; presence in image cache alone is insufficient. Preserve pull resume behavior and operation cancellation.
- Finalization emits readiness report and exits nonzero if ANY selected requirement fails. `--setup-check` is read-only and returns machine-readable results. Verify module-aware Python tools, native support, container binaries, PDK/version/libraries and functional minimal simulation. Run full SPM during candidate acceptance, not on every user's installation; installation should use a bounded smoke probe/config validation and may offer an explicit sample run.

Done: bare and baked paths converge to identical selected readiness; failed GDS3D/PDK cannot finish successfully; rerun preserves valid tools/PDKs/projects and only retries missing work. No terminal needed in appliance path. Complete parity table with tests.

## M4 — Network diagnosis and recovery

Dependencies: M1/M3 contracts. Findings: A13–A16.

Files: `platform_env.py`, universal/provision network helpers, shared installer network handling, setup worker proxy handling, fault-injection tests.

Tasks:

- Classify DNS lookup vs route/connection, TLS/certificate, HTTP status/rate limit, proxy auth, timeout, apt index/lock, permissions and no-space failures. Preserve original error category and useful log tail. ENETUNREACH must never assert DNS is broken when resolution succeeds.
- Probe Windows and appliance connectivity with bounded operations. Check relevant endpoints (Ubuntu/Docker repositories, PyPI/download hosts, GHCR auth/layers and PDK release redirects), not only github.com HEAD. An endpoint's HTTP 401/405 may prove reachability; interpret its protocol correctly.
- Prefer current WSL DNS tunneling/Windows resolver behavior where supported. Preserve VPN/internal DNS. Migrate a LanEx-owned legacy forced-DNS setting with backup/restore and verification; never erase administrator/user config without consent. Static DNS is a narrowly diagnosed recovery choice, not every install's default. Do not bake resolv.conf overrides or proxy credentials.
- Propagate explicitly provided proxy values through login-shell boundaries; redact credentials in display/logs/state. Windows PAC files are not automatically shell proxy URLs: detect and explain unsupported enterprise setup rather than pretend to handle it. Don't disable TLS verification.
- Apply apt network timeout/retry + lock-progress policy consistently across universal/base and in-app paths. Start from existing `_apt_install` behavior. After interrupted dpkg, detect incomplete configuration and perform a bounded appliance-scoped recovery when no active package manager owns the lock; never delete lock files to force progress.
- Detect IPv4/IPv6 difference with evidence; a per-download/package-manager fallback is preferable to globally disabling IPv6. Treat historical MTU 1300 as a machine-specific clue, not a value to ship to everyone. Global .wslconfig or host firewall changes are not automatic default repairs.

Done: DNS, route, proxy, TLS, IPv6, apt-lock and interruption tests classify correctly; caches retained; repair doesn't undo DNS strategy on reboot; no secrets in diagnostics; modern network config survives unrelated Repair.

## M5 — Wizard, live progress and recovery UX

Dependencies: M1–M4. Findings: A02, A04, A08, A22.

Files: Inno wizard + async worker, packaged PDK catalog, localized/user documentation, progress tests.

Tasks:

- Add recommended/custom component selection with Docker/toolchain/native support/GDS3D/sky130 selected. Make extra PDKs and advanced libraries selectable. Dependencies cannot be deselected into an impossible choice; reflect compatibility and storage implications.
- Show download and installed-space estimates by selected components, including temporary copies, image extraction, PDK extraction and practical run headroom. Measure before choosing thresholds; account for different temp/cache/distro volumes and existing usable caches. Recheck free space between large phases. Display estimates honestly; remove fixed “few minutes/373 MB” promises for full setup.
- Show current component, overall phase count, real bytes when available, elapsed activity, expandable live log and copy/open/save diagnostics. Phase progress must continue during slow apt/build tasks; use a worker and responsive UI, not repeated blocking Exec calls. A visible CMD window can be optional, not required for ordinary use.
- Retry/Save and exit/Cancel operate on the current job. Cancellation cooperates with Linux worker and process groups; killing wsl.exe alone is insufficient. During a dpkg critical section show 'Stopping safely…'; don't corrupt package state for instant UI feedback. Finalization cannot continue after cancellation.
- Resume re-probes component postconditions before skipping. Completed valid image/PDK/cache data reused; corrupted downloads revalidated. Build resumable rootfs download only if its range/partial/hash behavior is actually implemented; otherwise say full completed downloads are reused.
- Finish derives solely from readiness report. Show selected tools/PDKs ready and Launch button. Failure page names the failed component and recovery action, not 'almost always network.' Minimal deliberate setup states what remains.
- Add supported silent flags/selection file with validation and documented exit semantics: ready, failure, cancelled, restart required. Silent mode must never wait on a hidden modal prompt or automatically erase data. Keyboard navigation and high-DPI layout must be verified.

Done: slow/failing/cancelled worker fixtures show responsive meaningful UI; selections survive reboot; failure never produces ready text; all default selected components are ready before Launch.

## M6 — Launcher, upgrade and uninstall safety

Dependencies: M1–M5. Findings: A17–A19.

Files: `windows/launcher/{main,wsl,probe,tray}.go`, `lanex/cli.py`, health route and appwindow integration, Inno uninstall/repair, Go/Python tests.

Tasks:

- Launcher reads owned appliance identity and readiness record; uses explicit app user and writable home. Do not fall back to starting root or unwritable Program Files paths. Keep WSLg launch behavior unless a reproduced test justifies changing it.
- Health endpoint/server record include instance ID and source identity. Parse JSON strictly and compare owned instance; don't accept substring `"lanex"` or another server after a timeout. Bound discovery without port-scan ambiguity. Current appliances require identity; legacy migration is explicit.
- Scope single-instance mutex to original user/appliance. Double click opens own window; another user's app cannot hijack/block it. Use owned browser profile consistently in Python and Go; preserve pre-existing generic profile.
- Show clear startup/repair actions if Docker or readiness is broken; ordinary launch does not download large dependencies silently. Recovery uses existing Setup state/shared component checks. Startup error must not recommend global shutdown as first action.
- Repair preserves projects/run results/PDKs, user network settings and immutable build identity. Update changes explicit manifest only, with app rollback if health fails. Do not automatically downgrade when old Setup reruns. Incompatible schema/downgrade requires a clear choice, not destructive reinstall.
- Uninstall defaults to keep environment/data or offers verified export before explicit permanent removal. Check exact distro identity/path before terminate/unregister. If unregister fails, preserve disk/logs and report incomplete removal; never DelTree first or anyway. Export cancellation/failure cannot transition into delete.
- Remove only owned launcher/state/cache/profile/shortcuts/resume entries. Preserve other distributions, Windows WSL features, host settings and pre-existing generic profile. Make preserved data discoverable for later reinstall/adoption. Test old Program Files install migration under original and different-admin accounts.

Done: collision, port takeover, two-user, repair/update failure and uninstall/export matrix passes; saved project hashes unchanged; stale resume hooks cannot recreate a removed appliance.

## M7 — CI, artifacts and release gates

Dependencies: M0–M6 for complete candidate; wire basic branch coverage earlier in M0.

Files: existing `.github/workflows/ci.yml`, `differential.yml`, `windows-installer.yml`; existing CI scripts; new setup-worker/contract tests.

Tasks:

- Extend existing CI push filters to `windows-installer-support`, preserving main/schedule/PR coverage. Extend differential branch trigger too, with sensible same-branch concurrency. Do not duplicate master/main suites into a nested windows directory. Root workflows are the executing definitions.
- Preserve Python 3.10–3.13 matrix, frontend behavior/syntax/hygiene, wheel content, GTKWave handoff, compatibility canary, full RTL→GDS and differential/live API suites. Add Windows worker/preflight/state/quoting tests and launcher Go vet/format/tests/build.
- Provision from mounted/bundled checked-out candidate; never use remote base/main fallback as success for PR code. Pull requests with no secrets test local candidate payload; release upload jobs cannot run for them. Avoid interpolating untrusted branch strings directly into shell source.
- Minimal Ubuntu container tests prove base provisioning/recipe parity, strict selected native tools, PDK jobs where feasible and repair. They cannot prove real WSLg, owner/elevation or reboot. Engine-running finalization needs a real daemon in an isolated test environment; a mounted host Docker socket does not prove appliance Docker startup and grants broad access, so don't use it as a substitute.
- Test bake selfcheck and bare fallback separately. Bake native common dependencies/GDS3D if reliable, but do not require running dockerd inside ordinary rootfs bake. Pull image after appliance boot. If offering cached OCI payloads, explicitly load and verify them; docker export does not preserve external/volume content by magic.
- Snapshot dependency/package versions in build manifest; exclude credentials, builder identity/network configuration and caches that would invalidate reproducibility. Verify baked rootfs boot behavior in actual WSL.
- Add a publish gate depending on **all** required checks, rootfs verification and candidate acceptance evidence. Build jobs may upload CI artifacts for inspection on failure, but must not publish a public release EXE independently of failed checks.
- Make workflow_dispatch artifact builds self-contained: baked payload delivered as companion CI artifact with a local-test configuration, or publish to a real candidate release only when authorized. Do not embed a made-up `/releases/download/<branch>/...` URL. Validate downloads and hashes from the candidate access context.
- Stage candidate release assets before advertising the installer; create release intentionally instead of assuming it already exists. Avoid overwriting released payload hashes via `--clobber`; new candidate gets new version. Stamp PR/build/release identity coherently in PE, app, manifest and diagnostics.
- Keep signing support, validate signed launcher AND Setup when configured, timestamp appropriately. Unsigned builds must be labeled honestly; metadata alone cannot promise SmartScreen acceptance. Signing credentials/budget are a release-owner action, not something an agent invents. Include third-party attribution for distributed payloads.

Done: same commit has all required CI green; downloadable candidate artifacts match manifest; skipped jobs explicitly not counted; selected full environment tested from real candidate EXE. No public release until acceptance evidence and publication authority exist.

## M8 — Final Windows acceptance and handoff to Akshat

Dependencies: M7. Use TEST-MATRIX.

- Run default install on clean supported Windows with no WSL; prove first launch can simulate, view waveforms, run SPM to GDS, and open layout/GDS3D without installing anything else.
- Test firmware-disabled preflight and enable/reboot/resume on real hardware or a valid nested-virtualization environment. Avoid destabilizing the development PC for these cases. If suitable hardware is absent, mark blocked, prepare exact human checklist, and do not claim ready for full release.
- Test existing WSL/other distros, old installed LanEx migration, standard-user different-admin elevation, cancel/retry, disk/network failures, repair/update and data-preserving uninstall.
- Install every supported additional PDK selection at least in backend integration tests; verify family/variant/library contract. Only claim RTL→GDS compatibility for validated templates/configurations. Do not require nonsensical flow/PDK combinations.
- Repeat post-install basic operation offline with selected image/PDK already present. Prove no hidden download required for the tested sample. Refresh logs/report references with candidate SHA and EXE hash.
- Produce concise tester note: EXE path/URL/hash, versions, tested environments, outstanding known issues and exactly what Akshat should test. Leave main unchanged until his testing and merge authorization. No message sent on the user's behalf unless explicitly asked.

Done: acceptance ledger identifies PASS/FAIL/BLOCKED for every case, with evidence and candidate identity. Deliver a verified candidate or an honest blocked-release report; never a generic 'perfect' claim.

## Session sizing and scope control

Suggested sessions: M0; M1; M2; M3 (split backend contract and real finalization if needed); M4; M5; M6; M7; M8. They are work units, not time guarantees. Finish one coherent slice and its checks before starting another. A five-hour usage window is not a reason to leave no checkpoint or run everything again next session.

At each checkpoint update STATE only with changed facts, next action, test evidence and resource ownership. Store detailed failing logs once. Reuse passing evidence only if its tested inputs/source are unchanged. A source change invalidates affected checks; a GUI-only label edit does not justify repeating every multi-hour PDK download.

Out of scope until the release contract works: native Windows EDA port, new UI framework, Docker Desktop requirement, ARM64 support, winget, general package-manager rewrite, unrelated RTL flow/analytics changes, automatic firmware manipulation or host security disabling.
