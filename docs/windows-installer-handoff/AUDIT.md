# LanEx Windows packaging audit

Audited 2026-09-08 against `725dcb650e8ac436641bc8a84e856991ca806881` on `windows-installer-support`. Line numbers below refer to that revision. This is source inspection plus bounded diagnostic checks, not certification of an installed candidate.

## Conclusion

The existing architecture is suitable. The completion contract is not: Setup currently provisions an app launcher and Docker executable, deliberately defers major tools, and does not install a PDK. Changing two skip flags alone will not solve this: Docker deliberately starts only after the current provisioning stage, optional failures are warnings, and there is no final operational gate.

Akshat's concern has a concrete basis, but “not all original commands run” is only part of the explanation. The wrapper DOES call the universal installer. Its old environment-export bug was already fixed. The current wrapper deliberately bypasses the universal installer's GDS3D dependency/build stage and image pull. The universal installer itself is best-effort for these extras. The reported apt failure's underlying cause cannot be established without its apt output; the pasted final error proves dependencies remained absent, not why apt failed. `[Errno 101] Network is unreachable` does not by itself prove a DNS problem.

## Confirmed findings and consequences

| ID | Priority | Evidence at audited revision | Consequence / required change |
|---|---|---|---|
| A01 | Release blocker | `windows/provision/provision.sh:39–46,267–289`: normal `SKIP_GDS3D=1`, exported `LANEX_SKIP_PULL=1`; `lanex.iss:853–860` tells users to install toolchain later | Directly contradicts requested ready-to-use setup. Introduce explicit selected-component finalization after Docker boots. |
| A02 | Release blocker | `provision.sh` main has no PDK stage; `lanex.iss` Tasks contains desktop icon only | No sky130 default or PDK/library selection. Installer completion cannot support a fresh RTL→GDS run. |
| A03 | Release blocker | `scripts/install.sh:127–135,375–438`: git, graphics, GTKWave, GDS3D and image errors are warnings; `provision.sh:296–313` checks app help and Docker presence; selftest omits selected tools/image/PDK/daemon | Exit zero is not readiness. Require postconditions for every selected capability; keep optional semantics for ordinary non-appliance installs. Bake can currently succeed without usable GDS3D. |
| A04 | High | `lanex.iss:337–350,726–733`: synchronous hidden command, log redirected to file; `SetStatus` sets phase text only | No live command output in Setup, no bounded command/cancellation UI. Existing label fix is useful but does not satisfy live logs or prove responsiveness. |
| A05 | High | `lanex.iss:443–459` only considers feature enabled + no hypervisor | Fresh PC with feature disabled and firmware virtualization disabled passes preflight. Conversely pending restart or disabled hypervisor launch can be mislabeled “BIOS off.” Use distinct supported/enabled/pending/unknown facts. |
| A06 | High | `OpenHelp`, `lanex.iss:482–487`, points to `main/docs/INSTALL.md`; HTTP HEAD returned 404 | Broken help is still real. Use verified Microsoft virtualization page directly, with bundled brief fallback text and a copyable URL. |
| A07 | High | `lanex.iss:165–169`: `x64compatible`, Windows build 19041; WSL update failures tolerated at 777–783 | x64 emulation does not make an amd64 Linux rootfs native on ARM64. OS floor permits systems below documented WSLg GUI floor; systemd capability not enforced. Gate actual host architecture and required WSL capabilities. |
| A08 | High | `lanex.iss:568–617,751–774`: first DISM result overwritten; modern enable only recognizes zero; unchecked HKLM RunOnce write; only RESUME flag saved | May claim enable success despite one failed feature, repeat restart attempts, lose original user/choices, or fail to resume after cancelled elevation. Check each result; durable state and bounded resume. |
| A09 | High | `PrivilegesRequired=admin`, per-user AppData/distro, machine-wide install/shortcuts; resume in HKLM | Credential elevation under another admin can register distro for the wrong account; a different admin can consume RunOnce. Standard-user success is not established. Separate machine feature elevation from originating-user provisioning. |
| A10 | Release blocker | `scripts/install.sh:34` constructs `/archive/refs/heads/${REF}.tar.gz`, while workflow passes tag ref for releases | Tags and commit SHAs are not branches. Existing tag experiment gave 404 for branch-qualified URL and 200 for ref-aware URL. Fix source resolution and test branch/tag/SHA/local-wheel paths. |
| A11 | High | workflow uses `github.head_ref || github.ref_name`; `provision-e2e` falls back to base/main; provisioning fetches remote scripts and package from a ref | Candidate may install/test different code from checkout, especially fork PRs or moving branches. Bundle exact checked-out source/wheel and shared installer; stamp source SHA and hashes. Do not let fallback-to-main count as candidate proof. |
| A12 | High | `provision.sh:287–289`: `runuser -l … -c "export …; curl … | bash"` | Outer pipefail does not enable pipefail in the new login shell. Failed download can be hidden by successful empty bash; Repair may then verify the old app and report success. Fetch a file with checked result/hash, then execute it. |
| A13 | High | `provision.sh:66–129` treats any GitHub HEAD failure as DNS and writes 8.8.8.8/1.1.1.1; `platform_env.py:498–519` routes all WSL network failures to DNS guidance | Route, TLS, proxy, IPv6 or remote outage can be misdiagnosed. Public DNS replacement can break VPN/company resolution. Separate diagnosis and use modern WSL DNS behavior before targeted repair. |
| A14 | High | `provision.sh` DNS_FIXED resets per process; `wsl_conf()` only retains generateResolvConf=false when this run set DNS_FIXED | Repair after a successful static-DNS workaround rewrites configuration without preserving its managed state. A forced fix can also be baked into distributed images. Preserve/migrate settings deliberately; do not bake builder network configuration. |
| A15 | High | `installer.py:892–937`: every failed ciel fetch deletes version directory; after five failures loop ends in successful sleep and proceeds to enable | Reported six attempts are consistent with five fetches plus enable potentially fetching. No failure classification; deleting an existing valid version while adding libraries is possible. Preserve validated PDK versions and caches; fail explicitly after retry budget; serialize family/version operations. |
| A16 | High | `provision.sh:60` and universal apt stages only set lock timeout, unlike `_apt_install:1259` network timeouts; Docker convenience script and remote install retrieval lack bounded policy | Setup can wait a long time without feedback. Apply bounded network attempts and package lock progress throughout; retry only recoverable failures. |
| A17 | High | `lanex.iss:397–420,528–559,785–792,897–910` treats exact distro name as ownership and deletes paths even after unchecked unregister | Unrelated user-created `lanex` can be mistaken for appliance; failed unregister can be followed by VHDX deletion; uninstall can erase designs. Require ownership identity plus registered path; default data preservation/export; stop on unregister failure. |
| A18 | High | `%LOCALAPPDATA%\LanEx` contains appliance and lowercase `lanex\app-profile` predates installer; recursive AppDataRoot deletion at 903 | Windows case-insensitive paths can alias. Existing browser state from non-appliance LanEx can be deleted. Use an owned appliance subtree/profile and explicit legacy migration. |
| A19 | High | `launcher/probe.go:healthyAt` searches body for `"lanex"`; scan fallback remains after grace and when record absent; global launcher mutex in `main.go` | Wrong-instance attachment remains possible; same port may belong to another server, second user may be blocked. Compare strict service/schema and instance identity, scope mutex to owner, remove ambiguous scan for current appliances. |
| A20 | High | workflow build needs bake only; release upload independent of provision-lint, provision-e2e, rootfs-pin and main CI/differential; dispatch bake outputs release URL without upload on dispatch | Release can upload despite failed independent gate; dispatched installer can contain nonexistent preferred rootfs URL and silently fall back. Use a single gated candidate/publish graph and separate local artifacts from downloadable release assets. |
| A21 | High | main CI and differential push filters both `[main]`; current packaging run only tests packaging parts | Branch push does not exercise full Python/frontend/flow regression suites. Extend existing root workflows; files under `windows/.github` would not run. |
| A22 | Medium | fixed 10 GB floor and ~373 MB welcome; post-install note claims offline after image alone | Estimates exclude chosen PDKs and realistic extraction/run headroom. Cache exists only for completed rootfs copy, so general “continues where stopped” is unproven. Estimate per selection/volume and test interruption, low space, and offline use. |

Additional concrete defects worth covering in relevant milestones: GDS3D compiler probe (`installer.py:1497`) accepts `cc` and uses `shutil.which` rather than Linux-only resolution; a C compiler is not proof of a C++ build driver. GDS3D source follows an unpinned git branch (`1737–1739`). `PowerShellCapture` checks launch success, not process exit, and embeds paths in script text; usernames with apostrophes/non-ASCII and localized failures need tests. Setup changes global `wsl --set-default-version 2` despite explicitly importing version 2; avoid that unnecessary global preference change. Launcher error guidance still suggests global `wsl --shutdown`; an appliance repair action should target its owned distro.

These are bounded source findings, not a claim that every scenario has been reproduced on hardware. The identity, ARM64, standard-user and restart paths require tests below.

## Original installer parity: what actually runs

`scripts/install-wsl.sh` is a compatibility shim to `scripts/install.sh`, not an additional independent recipe. `scripts/install.sh` is unchanged between audited main and packaging branch. The Windows wrapper invokes the universal installer as the `lanex` user with exported configuration; preserve that reuse.

| Universal stage | Normal Setup today | Required appliance behavior |
|---|---|---|
| Platform and privilege detection, network check | Runs | Preserve, but correct network classification. |
| Python/venv and pipx fallback | Runs | Preserve fallback and module-aware interpreter handling; stamp actual package identity. |
| Git, X11 fonts, Mesa/GL runtime, GTKWave | Attempted; failures may warn | All selected viewer/support dependencies must be verified, including usable display on final boot. |
| Build toolchain retry for Python install | Only after Python package install fails | Do not mistake this conditional stage for guaranteed GDS3D dependencies. |
| App install, PATH, help check | Runs | Keep; strengthen immutable source/provenance and installed-wheel verification. |
| LibreLane image pre-pull | Explicitly skipped | Run after Docker is operational, from shared implementation; require selected image digest and tool probes. |
| GDS3D dependencies + build | Skipped in normal Setup; enabled in bake, best-effort | Default selected; use identical dependency/build recipe and verify result on both image paths. |
| PDK install | Not present in universal main | Add shared headless PDK entry point and explicit finalization stage; do not claim it was already in this script. |
| Icarus/Graphviz | No universal stage guarantees them | Include native support tools explicitly. |

“All commands run” should mean every platform-applicable recipe is accounted for and its required outcome is verified. It must not mean executing Fedora/macOS branches on Ubuntu or redundantly installing alternative engines and unversioned native flow tools.

## Reuse inventory

- Tools catalog: `lanex/controller/tools.py:92` (`EDA_TOOLS`) — Python, pip, LibreLane, Yosys, OpenROAD, KLayout, Magic, Netgen, Verilator, Icarus, Graphviz, GTKWave, Ciel. GDS3D and engine controls also appear in the frontend; include them.
- Shared installer: `lanex/controller/installer.py` — `_apt_install`, `install_tool`, `_install_gds3d`, `install_pdk`, `pull_image`, image digest recording and cancellation.
- CLI: `lanex/cli.py` — `--install-tool` and `--pull-image` already stream/return terminal status; no equivalent general `--install-pdk` exists. Do not treat `install_pdk()`'s immediate `{status: started}` as completion.
- PDK readiness: `lanex/controller/pdk.py` — `required_pdk_version`, `check_pdk_ready`, container readiness and library checks.
- Image resolution: `lanex/controller/container_run.py`; engine resolution: `tools.resolve_engine`.
- GUI launch: `container_tools.py` includes Magic/KLayout/OpenROAD/Netgen; GTKWave and GDS3D use host paths. Preserve tested WSL software rendering defaults and app-window behavior.
- Full flow tests: `scripts/ci-rtl2gds.sh`, `scripts/ci/differential_run.py`, `api_e2e.py`, `gtkwave_probe.py`. Extend/reuse, not replacement mock flow tests.

## Checks actually performed

1. Read-only Git status/branches/remotes/worktrees and remote HEAD comparison. Clean tree; main ancestor; no fetch/checkout/reset/push.
2. GitHub CLI auth and latest six branch workflow statuses inspected. Latest [packaging run](https://github.com/AkshatIsWired/lanex/actions/runs/30563641369) at audited HEAD passed provision lint, container provision and build; bake/rootfs-pin were skipped. Main CI/differential were not shown for that push.
3. Existing Windows install log contains explicit GDS3D skip and successful completion. Historical evidence is July-era and does not prove current full acceptance.
4. Official installer help target returned 404. Ubuntu pinned image URL returned 200 and matched Microsoft's current distribution manifest. No rootfs downloaded during audit.
5. Existing tag `windows-test-2026-07-30`: codeload `/tar.gz/refs/heads/<tag>` returned 404; `/tar.gz/<tag>` returned 200. Confirms source URL defect without running an install.
6. `C:\Program Files\Git\bin\bash.exe -n` explicitly applied to `scripts/install.sh`, `scripts/install-wsl.sh`, `windows/provision/provision.sh`, `selftest.sh`: all exit zero.
7. `python -m pytest lanex/tests/test_fixes_round75.py lanex/tests/test_fixes_round76.py -q -p no:cacheprovider`: **23 passed, 2 skipped** on Windows Python 3.13.
8. Broader selected run (`test_install_script`, `test_install_foolproof`, `test_installer`, round75, round76): **68 passed, 5 skipped, 7 failed**. Two failures use Windows bash shim with Windows path strings; four assume LibreLane/Ciel installed in Python (absent here). These six are not packaging-regression proof. Remaining failure is stale `test_run_argv_sudo_with_tty_uses_terminal_even_if_passwordless` at `test_installer.py:103`, which asserts the opposite of the intentional new passwordless streaming path. It only mocks the old branch, allowing real subprocess execution on the new branch. Repair tests safely before running them with Linux sudo access. A narrower rerun repeated the two bash-shim failures; explicit Git Bash syntax checks above resolve syntax uncertainty.
9. Go unavailable on PATH/default Program Files path; no local Go suite/build claimed. Inno Setup installed. No full CI, provisioning, EXE, GUI, reboot, or RTL→GDS acceptance run performed in this planning session.

## External facts verified, not guessed

- [Microsoft virtualization instructions](https://support.microsoft.com/en-US/Windows/Experience/enable-virtualization-on-windows) provide UEFI entry guidance and manufacturer links. Use this help target; the relevant firmware setting is CPU virtualization (Intel VT-x/VMX or AMD-V/SVM), not a request to enable/disable Secure Boot.
- [WSLg requirements](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps) specify Windows 10 build 19044+ or Windows 11 and WSL2. A WSL2-only minimum is insufficient for all GUI tools.
- [Systemd support](https://learn.microsoft.com/en-us/windows/wsl/systemd) requires WSL 0.67.6+ and documents required systemd packages. Probe running services, not only configuration text.
- [WSL networking](https://learn.microsoft.com/en-us/windows/wsl/networking) documents DNS tunneling and proxy integration on supported Windows 11 versions. [Troubleshooting](https://learn.microsoft.com/en-us/windows/wsl/troubleshooting) documents that generateResolvConf should not be disabled for DNS tunneling. Do not universally apply an old static-DNS workaround.
- [RunOnce behavior](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys): HKLM RunOnce runs for administrator logons; normally deleted before execution; timing is not guaranteed. It is not a durable transaction/checkpoint mechanism.

## Audit boundaries

No product code changed; no installer rebuilt; no environment repair performed. The plan can remove known failure modes, but “perfect on every PC” cannot be proven from a prepared development machine. Firmware-disabled first installs, user-context elevation and restart continuation are mandatory release evidence on suitable Windows hardware or VMs.
