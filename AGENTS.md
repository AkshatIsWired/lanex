# Windows installer work

These notes apply when a task concerns the LanEx Windows installer or its release. They do not turn an unrelated task into installer work.

## Where and how

- Work in `C:\Users\itsva\lanex`. The main line is `ui-redesign`; the Ship line phase works on `ship-line`, cut from it.
- Start from `installer-workspace/START-HERE.md`. Its newest section says what changed, the current artifact and its hash, and what is still open.
- Build with `python scripts/build_windows_release.py`. It builds the launcher, the wheel and the Inno Setup EXE and copies the deliverables to `installer-workspace/outputs/`.
- Scratch and build staging go in `installer-workspace/work/`, observed results (logs, screenshots) in `installer-workspace/evidence/<check>-<date>/`, deliverables in `installer-workspace/outputs/`.
- Installer sources: `windows/installer/lanex.iss` (wizard), `windows/setup/` (setup.ps1, the pinned manifest, constraints and lock files), `windows/provision/` (what runs inside the distro), `windows/launcher/` (LanEx.exe).

## What the installer must do

- Wizard: Welcome -> License -> one Configure page -> Installing -> Finished. Nothing else asks the user a question.
- Every download is pinned and hash-verified. A partial or corrupt file is retried, never used. Never turn a check off to make the wizard finish.
- Restart and resume work: the WSL feature enable, the reboot it needs, a dropped network, a closed window, a PC that slept.
- Every failure says what went wrong in plain words, the next step, and the install log's path.

## Data preservation

- Upgrade, repair and uninstall keep the user's projects, run results and caches. Uninstall says what it kept and how to remove it.
- Never touch, unregister or delete a WSL distro LanEx did not create, and never delete a distro or its VHDX to get past a repair failure.
- Test on VMs, never on the development PC's own Windows. That PC's `lanex` distro holds the editable dev install; leave it alone.

## Needs the user's OK

Pushing, merging, publishing a release, uploading mirror files, enabling a GitHub workflow, and deleting user data or WSL distros. Commit locally; do not push.
