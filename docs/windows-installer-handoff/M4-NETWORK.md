# M4 network and launch recovery

Date: 2026-09-09
Implementation commits: `4aa748d`, `2f79507`, `04a8991`
Proof candidate source: `04a899175d870b62c8ae82e490b37407e0d68b59`

## Closed behavior

- Network diagnostics distinguish DNS, route/connection, TLS, timeout, proxy
  authentication/PAC, HTTP auth/status/rate limit, apt index/lock/interruption,
  permission and no-space failures. Diagnostics are bounded and redact URL,
  header and query credentials.
- Setup probes the actual Ubuntu, Docker, PyPI, GHCR and PDK redirect surfaces.
  HTTP 401/405 are valid reachability results for endpoints whose protocol uses
  them. A failed default family is compared with `curl -4` and `curl -6`; an
  evidenced winner is scoped to curl/apt commands instead of disabling IPv6.
- The old unconditional 8.8.8.8/1.1.1 rewrite is gone. Current WSL resolver and
  `[network]` configuration survive Repair. Only the exact LanEx-managed legacy
  override is migrated, after backups, with atomic write and rollback on failed
  verification. Bake cannot install a host DNS override.
- Explicit Windows HTTP(S)/NO_PROXY variables cross WSL through process-local
  `WSLENV`; values and credentials never enter the command line or installer
  log. A Windows PAC-only configuration is detected and explained honestly.
- Universal, appliance and in-app apt paths use a five-minute lock wait plus
  30-second fetch timeouts and three retries. Interrupted dpkg configuration is
  recovered only after the active owner releases the real locks; lock files are
  never deleted. Package caches and completed payloads remain available.
- Docker's remote installer is downloaded completely with bounded curl, then
  executed; a truncated `curl | sh` pipeline cannot run.

## Launch failure from the supplied screenshot

The installed launcher log said both `LanEx is running at ...8765` and `LanEx
opened in its own app window`, even though Edge showed connection refused. The
mechanism was real: Linux opened Edge on a fixed 0.5-second timer, while the
Windows launcher separately waited for `/api/health`. Spawning Edge was treated
as success without proving Windows-to-WSL localhost reachability.

The launcher now starts `lanex --no-browser`, polls the strict health endpoint
from Windows, and opens exactly one app window only after that probe succeeds.
Failure guidance no longer asks users to run global `wsl --shutdown`; Repair and
Quit remain scoped to the owner-bound LanEx appliance.

## Verification

Evidence: `C:\Users\itsva\Documents\Codex\2026-09-09\from-m0-to-m3-is-done\work\m4-evidence-20260909`.

- Windows focused checkpoint: 110 passed, 2 explicit platform skips.
- Isolated Ubuntu focused network/provision/install suite: 51 passed.
- Hermetic curl fixtures proved route is not mislabeled DNS and IPv4 fallback
  activates only after default-family failure.
- Windows launcher tests executed: strict health, record/port identity, distro
  decoding and `--no-browser` startup regression all passed; Go vet passed.
- Git Bash syntax and Ubuntu ShellCheck passed for both installers.
- Inno Setup compiled the hash-bound candidate successfully.
- Proof hashes: launcher
  `575f7e01467e6943b7842cfc0ae430fc38b2b6a62142348b7a967d0fc2b8d43f`;
  wheel `ec45f4712a967dace22c189a753e76d134c238484f9bcac465d91db0e90a9f37`;
  manifest `f4724d4b179f6ec93171460d5158847213832360a7ed6a9697bba2c8a0007e98`;
  Setup `ee3a489e2caf76471ea3b2a57fda59fa5437c661c2a7bec4ccd0e0a9b054aa4e`.

## Still requires a disposable Windows environment

W16 controlled Wi-Fi loss, slow route, VPN/proxy/PAC, TLS interception and live
IPv4/IPv6 mismatch remain real-machine tests. The proof Setup was compiled but
not installed or launched here. Existing WSL distributions, LanEx data/profile,
services and host network configuration were not changed.
