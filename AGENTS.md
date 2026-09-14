# Windows installer release work

These instructions apply when the task concerns the LanEx Windows installer or its release. They do not expand an unrelated task into installer work.

## Canonical workspace

- Work from `C:\Users\itsva\lanex` on `windows-installer-support`, origin `https://github.com/AkshatIsWired/lanex.git`.
- Start with `installer-workspace/START-HERE.md`, then `installer-workspace/handoff/IMPLEMENTATION-HANDOFF.md`. The adjacent audit contains the evidence and source locations from both sweeps.
- Keep implementation in this checkout. Use `installer-workspace/work/` for scratch/build staging, `installer-workspace/evidence/` for observed results, and `installer-workspace/outputs/` for deliverables. Standard compiler outputs may remain at their repository-defined paths; collect deliverables in the canonical outputs directory.
- Do not create another dated Codex output tree, cloned checkout, or alternate handoff unless the user explicitly requests it. Update the existing starting point and handoff in place.
- Baseline `installer-workspace/baseline/test.3/` is the known-broken audited candidate. Preserve it for comparison. Never present it as the fixed release.

## Scope and completion

Repair the existing Inno/PowerShell/WSL implementation. Preserve the useful ownership, payload-integrity, selected-component readiness and data-preservation work. Correct broken contracts; do not disable checks to make the wizard finish.

The requested flow is Welcome -> License -> one Configure page -> Installing -> Finished. The intended output is one easy-to-install EXE and a usable app, including prerequisite/restart recovery.

Use the concrete handoff rather than restarting historical M0-M8 milestones. Make targeted changes and use existing checks plus a few focused regressions. Prove the actual rebuilt EXE through fresh installation/restart, launch and a small supplied flow, recovery, and representative profile/lifecycle behavior. Compilation, mock tests, or the Finish page alone are not release proof. Record unperformed checks honestly.

Preserve existing projects, caches and unrelated WSL environments. Never delete a distro/VHDX or erase ownership state to bypass a repair failure. Do not publish a release, push, merge, or remove user data without applicable user authorization.

Keep progress notes short in START-HERE.md: changes made, actual artifact path/hash, observed results, and remaining blockers. Do not produce another audit instead of implementing known fixes when implementation is requested.
