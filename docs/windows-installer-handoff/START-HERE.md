# LanEx Windows installer: implementation handoff

Prepared 2026-09-08. This is an audited implementation plan, not a finished installer.

## Objective

One downloadable Windows EXE that sets up WSL when needed, resumes after a required reboot, installs LanEx plus its recommended toolchain, every supported Tools-page capability, and sky130A by default. Users can select additional PDKs/libraries before installation. Successful completion means the selected environment is verified and usable without opening a terminal or clicking Install in LanEx.

Keep the existing Inno Setup + Go launcher + private Ubuntu WSL distro design. Extend it; do not replace it with a new desktop framework.

## Exact starting point

- Repository: `C:\Users\itsva\lanex`
- Branch: `windows-installer-support`
- Audited HEAD: `725dcb650e8ac436641bc8a84e856991ca806881`
- Default branch is **main**, not master. Audited main: `ff0759b11dccf05378615894fa8a11a392e410c7`.
- At audit time: clean working tree, packaging branch 26 commits ahead / 0 behind main; both remote heads matched local refs.
- GitHub CLI authenticated as `VaradhaCodes`. No new token needed. Recheck access without printing tokens.
- Existing WSL distributions: `Ubuntu`, `lanex`, `Ubuntu-22.04`. All were stopped at initial inventory. Treat all as user-owned; the existing `lanex` is NOT a disposable test fixture.
- Historical evidence: `C:\Users\itsva\lanex-test-evidence`. Its July report/checklist is context, not current acceptance proof. It incorrectly describes the host as having no installed lanex distro for today's purposes.
- Canonical handoff directory: `docs/windows-installer-handoff/` in this repository.
- The original output pack is an adoption snapshot only; do not update it except
  for its `STATE.md` pointer to this canonical copy.

## Read efficiently

1. Read this file and `STATE.md` in every fresh session.
2. First implementation session: read `AUDIT.md`, then `IMPLEMENTATION-PLAN.md`.
3. Later sessions: read only the active milestone in `IMPLEMENTATION-PLAN.md`, its cited source functions, and the applicable cases in `TEST-MATRIX.md`. Read more only if changed code or failing evidence requires it.
4. Recheck Git status and HEAD. If they differ from STATE, reconcile the changes before editing. Preserve unrelated work.

## Instructions to the implementing agent

Implement milestones M0–M8 in dependency order, with focused commits/checkpoints and meaningful regression tests. Continue through safe, authorized implementation and testing; do not stop merely to offer the next step. Never label a milestone verified because code compiles or a script exits zero when its actual acceptance checks have not run.

The user requested planning in the audit session. Executing this handoff requires the user to instruct the next agent to implement it. Publishing releases, merging to main, contacting Akshat, rebooting this working PC, deleting an existing distro, or changing host boot/security/network settings are not implicitly authorized by this document. Prepare a reviewable candidate and request the necessary action at the relevant boundary. Use dedicated test machines/VMs for disruptive tests.

The user expects Akshat to test the Windows branch before it is merged to main. Make a tested candidate available for that review when publication is authorized; do not merge first simply because old documentation says so.

## Fresh-chat prompt: copy this

> Implement the LanEx Windows installer handoff at `C:\Users\itsva\Documents\Codex\2026-09-08\i\outputs\lanex-installer-handoff\START-HERE.md`. Read START-HERE and STATE first, check the repository status, then continue the first unfinished milestone. Follow the acceptance checks, preserve the existing WSL distributions and user data, and update the compact STATE checkpoint at each milestone or before stopping. Work through implementation and safe testing; prepare the installer for Akshat's testing before any merge to main. Do not reread old chats or bulk logs unless current evidence requires it. Report verified work separately from tests that still require hardware, reboot, approval, or network access.

## Checkpoint discipline

`STATE.md` is the working memory: keep it approximately 60–100 lines. Update at milestone completion, a material blocker, or before ending a session—not after every command. Record HEAD, dirty files, completed milestone evidence, current next action, test command/result, and any live resource ownership. Keep detailed logs in a per-run evidence directory; link them, do not paste them into STATE.

At implementation start, put a maintained copy of this pack under `docs/windows-installer-handoff/` in the repository so commits carry the handoff between machines. Declare that copy canonical in both STATE files. Until then this output directory is canonical. Do not maintain two independently evolving plans.

If a session ends abruptly, the next agent uses `git status`, `git diff`, and the active milestone to reconstruct the small delta since STATE. It must not reset uncommitted changes to match the checkpoint.
