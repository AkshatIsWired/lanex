# Candidate acceptance and evidence

No case below is marked passed by this audit. Existing July evidence and the green packaging workflow are useful baselines, not acceptance of the proposed full installer.

## Evidence rules

Each run records candidate source SHA, Setup SHA256, manifest hash, Windows build/native architecture, WSL version, test environment name and date. Use PASS / FAIL / BLOCKED / NOT RUN; SKIPPED is not PASS. Keep one short result row with evidence path. Logs/screenshots belong in a per-run directory, not the checkpoint.

Recommended record: `case-id | result | candidate SHA/EXE hash | environment | command or UI steps | observed result | evidence path | issue/next action`.

Use disposable test appliances with explicit ownership markers and unique names. Existing `lanex`, `Ubuntu`, and `Ubuntu-22.04` on the development PC are protected. Snapshot fixture state before fault injection. A VM without working nested virtualization can test early rejection but cannot prove WSL2 installation. Do not change the host's hypervisor/BitLocker/Secure Boot settings as test setup without separately agreed action.

## A. Automated regression and build tests

| Case | Scenario | Pass condition |
|---|---|---|
| U01 | Catalog completeness | Every Tools-page entry including special GDS3D/engine controls maps to delivery, default choice and operational probe. PDK catalog from locked dependencies matches bundled UI catalog. |
| U02 | Original recipe parity | Each applicable universal stage is executed or explicitly deferred then verified. Original GDS3D headers/fonts/runtime, PATH, pipx/venv fallback and WSL settings retained. Neither normal nor baked setup silently skips a selected tool. |
| U03 | Ref/payload identity | Branch/tag/SHA/local-wheel sources work; fork PR candidate is actual checkout; unavailable payload is a failure, never silent fallback to main. Failed script fetch cannot become successful Repair. |
| U04 | Preflight truth table | Firmware disabled with WSL absent; firmware enabled with features absent; pending feature reboot; hypervisor active; old WSL; query failure; architecture mismatch all yield distinct correct decisions. |
| U05 | Resume/state | Atomic-write interruption, wrong SID, wrong manifest, stale phase, duplicate launch, unchanged boot, corrupt JSON and failed trigger registration handled safely. Choices survive. Reboot budget bounded. |
| U06 | Strict readiness | Mock a zero installer exit but missing GDS3D/PDK/image/daemon/library: final ready fails. Async 'started' and intermediate child success cannot satisfy final PDK completion. |
| U07 | PDK lifecycle | Partial extraction, valid version + failed added library, concurrent same-family variants, exhausted retries, cancellation and root-owned store: valid data retained; no enable after exhausted fetch; correct nonzero final result. |
| U08 | Networks | DNS succeeds + ENETUNREACH is route failure, not DNS. Separate DNS/TLS/proxy/HTTP auth/rate-limit/apt-lock/disk-full fixtures. Existing DNS strategy survives repair. |
| U09 | Subprocess safety | Both sudo branches completely mocked in unit tests. Passwordless path streams; password-needed path behaves correctly. Test a tty-cached credential separately from true NOPASSWD: detached probe must not promise privileges it loses. Cancellation never kills the server process group. |
| U10 | Argument/path handling | Windows username/path with spaces, apostrophe, ampersand, percent, non-ASCII; CRLF scripts; UTF-8 and UTF-16 WSL output; localized command errors. No shell interpolation executes user-controlled strings. |
| U11 | Ownership and deletion | Foreign distro called lanex, mismatched registration path/marker, failed unregister, cancelled/failed export and legacy browser-profile alias: no protected data deleted. |
| U12 | Launcher identity | Stale/malformed server record, unrelated service returning 'lanex', other LanEx on same port, slow start beyond grace, two users, double click: only own instance opens. |
| U13 | Progress protocol | Truncated last JSON line, log rotation, silent child, huge output, cancellation, error exit and UI restart handled; finite memory and no fabricated ready state. |
| U14 | Full existing suites | Root CI Python matrix, frontend behavior/syntax/hygiene, wheel assets, GTKWave handoff, compatibility policy, RTL→GDS, differential and live API pass on candidate as applicable. Existing failures explained/fixed, not broadly skipped. |
| U15 | Windows build | Go vet/gofmt/tests; setup worker tests; all shell syntax/lint; Inno compile; metadata and source identity coherent; no secret/helper payload omissions. |
| U16 | Publish graph | Any required gate failure prevents public release upload. Dispatch cannot embed nonexistent release assets. Every referenced artifact/hash exists and matches; fork input cannot inject shell commands. |

Safe Linux test environment should install this candidate's package and pytest into a disposable venv/container, then run `python -m pytest lanex/tests -q --junitxml=<evidence-file>`. Run Windows Go tests on Windows. Explicit Git Bash syntax checks are useful but do not replace Linux behavior tests. Do not copy a full test command into an environment with an unreviewed stale test that might execute real apt.

## B. Linux/appliance integration

| Case | Scenario | Pass condition |
|---|---|---|
| L01 | Bare Ubuntu 24.04 base | Base provisioning installs exact candidate and all required native components; shared script parity report complete. |
| L02 | Baked image | Selftest checks actual baked contents including GDS3D, no builder secrets/network overrides, manifest match. Import and boot tested separately on Windows. |
| L03 | Real daemon finalization | Own Docker runs under appliance service/user. Image pulled or loaded, digest and each required binary verified; Docker Desktop/other user daemon not used by accident. |
| L04 | sky130 default | All selected family libraries present, exact pinned hash, enabled sky130A and HD SCL ready in container mode. Store/user ownership correct. |
| L05 | Additional PDKs | Each exposed supported PDK family/variant/library selection installs and validates. Shared-family dedup works. Record install support separately from flow compatibility. |
| L06 | Repair and warm reuse | Re-run validates installed state, keeps design/hash sentinels, preserves valid PDK versions and caches, does not redownload valid image or upgrade app unexpectedly. |
| L07 | Tool repair after installation | In a disposable appliance remove one native support component at a time, then use Tools UI/shared backend to restore GDS3D, GTKWave, Icarus and Graphviz without terminal. Repeat PDK addition and image repair. |
| L08 | Interruptions | Network loss / process kill during pull, source build and PDK extraction; safe retry and correct failure reports; no sibling data corruption. Apt interruption recovery does not remove live lock files. |
| L09 | Minimal choices | Deliberate image/PDK deselection gives accurate limited readiness. Later Modify/Tools install reaches full readiness using same implementation. |

Container base tests do not prove systemd/WSLg/Windows integration. Record this explicitly; do not promote L01 into W01.

## C. Actual EXE on Windows

| Case | Environment/action | Required observation |
|---|---|---|
| W01 | Clean Windows 11 x64, WSL absent, firmware virtualization enabled | One EXE; understandable choices; WSL setup and necessary restart; automatic continuation for same account; all defaults ready before app opens. No Linux username/password or terminal commands. |
| W02 | WSL absent, firmware virtualization disabled | Clear early prerequisite notice/block before enable/reboot/download when detectable; live Microsoft help link opens. After user enables it, rerun continues correctly. |
| W03 | Features enabled, restart pending; separately hypervisor launch disabled | Correct distinct messages; no false BIOS claim; no unbounded restart sequence. |
| W04 | Existing modern WSL2 and user distributions | Only new owned appliance created. Other distro registrations/default settings and data unchanged; no global shutdown/conversion. |
| W05 | Old WSL/inbox WSL or WSL1 default | Upgrade capabilities only as needed; private distro version 2; existing WSL1 distro retained unchanged. Unavailable update produces recovery, not false-ready. |
| W06 | Windows 10 GUI-capable supported target, if advertised | WSLg, systemd, default setup and real flow/viewers pass. Otherwise narrow support claims before release. |
| W07 | Windows ARM64 and too-old Windows | Rejected before rootfs download with correct requirement; never installs amd64 rootfs because x64 EXE emulation is available. |
| W08 | Standard user authorizes feature setup with another admin's credentials | Original user owns distro/state/shortcuts/app and resume; helper admin gets no accidental appliance. No later administrator prompt for in-appliance installs. |
| W09 | Denied UAC, managed-policy denial, restart later, cancelled resume UAC, different user logs in first | State remains safe/recoverable; no false completion; original user can Continue; other user cannot consume/modify the install. |
| W10 | Restart twice / crash after each major boundary | Selections/source identity retained; checkpoints revalidated; interrupted import recovered without deleting foreign data; no loop or endless login prompt. |
| W11 | Default components selected | Tools page shows all capabilities available with accurate native/container labels. Docker, native tools, GDS3D and sky130 ready; no additional Install clicks required. |
| W12 | Simulation / waveform | Use bundled/known Verilog test via UI; real Icarus compile+vvp output, Verilator lint and VCD. GTKWave opens that VCD with correct traces, not an empty placeholder. |
| W13 | RTL→GDS | Copy bundled SPM into writable appliance workspace; run actual LanEx container workflow with sky130A/HD; successful completed flow and genuine output GDS/metrics. Compare existing CI expectations; do not equate UI green color with correct flow. |
| W14 | Layout tools | Open output in KLayout/Magic/GDS3D; exercise OpenROAD/Netgen applicable controls. Real visible windows/content and correct PDK/process mapping, no blank '[WARN: COPY MODE]' window. Capture evidence. |
| W15 | Offline after completed setup | Disconnect test environment network; reopen app, simulate and run tested SPM flow using installed image/PDK without automatic downloads. Document capability scope, not blanket all-features offline. |
| W16 | Wi-Fi/network drop, slow connection, VPN/proxy, working DNS with unreachable route, IPv6 mismatch | Responsive phase/logs, correct classification and retry; no unconditional public-DNS replacement. Use controlled lab faults; do not reconfigure development host. |
| W17 | Low disk before setup and disk fills mid-image/PDK extraction | Accurate volume/selection estimate; actionable stop; verified completed data kept; freeing space and retry succeeds. |
| W18 | Baked URL unavailable / corrupt cache / bare fallback | Corrupt payload never imported. Allowed bare fallback reaches SAME final selected readiness. Failure/cancel does not unexpectedly start another massive download without visible state. |
| W19 | Cancel during apt, image pull, GDS3D build, PDK extraction | UI responds and explains safe stopping; no orphan download or subsequent step; next Continue works; other LanEx server remains alive. |
| W20 | Existing legacy install + generic browser profile + project/run sentinels | Migration/Repair preserves files/profile and install ownership; current candidate identity correct. A foreign manually-created lanex is not automatically adopted. |
| W21 | Explicit update failure / rerun old installer | Previous app remains recoverable; no silent downgrade or switch to main; no PDK/project loss. |
| W22 | Double-launch / other LanEx service / second Windows user | Correct own app window, one own server, no wrong-port takeover or global-user mutex collision. |
| W23 | Uninstall keep-data / export / explicit erase / failed unregister | Keep/export defaults honest; cancellation retains all data; unregister failure preserves VHDX; explicit erase affects only verified owned resources. No global WSL removal, unrelated profile deletion, or stale resume. |
| W24 | Silent mode, paths/locales, accessibility | Documented exit codes, no hidden prompts, selection validated; Unicode/special-character paths work; keyboard and 125–200% DPI readable; logs save/open. |
| W25 | Reinstall after each uninstall mode | Preserved appliance re-adopted only with verified ownership; clean erase allows clean install; other distributions remain intact. |

## Candidate release gate

1. All mandatory automated and integration cases pass for the candidate commit. Any unsupported PDK/platform is explicitly narrowed in product claims rather than silently skipped.
2. W01, W02, W04, W08–W15 and data safety/recovery cases have actual suitable Windows evidence. W06 is required only if Windows 10 is advertised. All other applicable Windows cases need an explicit disposition; no unexamined critical failure can be waived by a build badge.
3. Candidate EXE and downloaded payload identity/hashes recorded; actual candidate (not a locally patched substitute) used in clean install test.
4. Akshat receives the testing candidate only when sharing/publication is authorized. Main remains unchanged pending his test results and merge authorization.
5. Final tester note states exact versions, tested PCs/VMs, limitations and remaining actions. Signing/SmartScreen behavior is reported as observed, not promised.

## Minimal tester note template

Candidate: <version + commit>
Download/file: <actual EXE>
SHA256: <hash>
Recommended defaults: Docker + full Tools capabilities + sky130A / HD
Verified environments: <Windows/WSL/CPU; fresh vs existing>
Please test: install/restart/first launch; simulate + GTKWave; SPM→GDS; GDS3D/layout; repair with saved project; uninstall keep/export.
Known limitations: <specific or none observed in tested cases>
Logs: <Open diagnostics button/path>
Release state: candidate for testing, not merged to main.
