// Copyright 2026 LanEx Contributors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0

// Everything this launcher does *to* Windows and WSL: listing distros, starting
// the server, shutting the appliance down, and opening the app window.
package main

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unicode/utf16"

	"golang.org/x/sys/windows/registry"
)

// wsl.exe lives in System32. A 32-bit process would be redirected to SysWOW64,
// which has no wsl.exe — hence the x64-only build (see lanex.iss's
// ArchitecturesAllowed). Bare name, resolved on PATH, so an ARM64 host finds its
// own copy too.
const wslExe = "wsl.exe"

// ---------------------------------------------------------------- distro list --

// distroPresent reports whether the LanEx appliance distro is registered.
func distroPresent() bool {
	out, err := wslOutput("-l", "-q")
	if err != nil {
		// wsl.exe missing or erroring out means there is no appliance to talk to,
		// which is the same situation for the user either way.
		logf("wsl -l -q failed: %v", err)
		return false
	}
	for _, name := range decodeDistroList(out) {
		if strings.EqualFold(name, distroName) {
			return true
		}
	}
	return false
}

// wslOutput runs wsl.exe with *args* and returns its raw (undecoded) stdout.
func wslOutput(args ...string) ([]byte, error) {
	cmd := hiddenCmd(wslExe, args...)
	// WSL_UTF8 makes modern wsl.exe emit UTF-8 instead of UTF-16LE. Older builds
	// ignore it, which is why decodeConsole still sniffs the encoding.
	cmd.Env = append(os.Environ(), "WSL_UTF8=1")
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	err := cmd.Run()
	return stdout.Bytes(), err
}

// decodeDistroList turns `wsl -l -q` output into distro names.
func decodeDistroList(raw []byte) []string {
	var names []string
	for _, line := range strings.Split(decodeConsole(raw), "\n") {
		// Trailing \r from the console, and NULs when a UTF-16 stream was cut at
		// an odd byte, both survive TrimSpace unless named explicitly.
		line = strings.TrimSpace(strings.Trim(line, "\r\x00"))
		if line != "" {
			names = append(names, line)
		}
	}
	return names
}

// decodeConsole decodes wsl.exe output, which is UTF-16LE unless WSL_UTF8=1 was
// honoured.
//
// This is the classic silent bug in every home-grown WSL launcher: comparing
// "lanex" against "l\x00a\x00n\x00e\x00x\x00", concluding the distro is missing,
// and telling the user to reinstall a perfectly good install. Hence the unit
// tests in wsl_test.go.
func decodeConsole(raw []byte) string {
	switch {
	case len(raw) >= 2 && raw[0] == 0xFF && raw[1] == 0xFE: // UTF-16LE BOM
		return decodeUTF16LE(raw[2:])
	case len(raw) >= 3 && raw[0] == 0xEF && raw[1] == 0xBB && raw[2] == 0xBF: // UTF-8 BOM
		return string(raw[3:])
	case bytes.IndexByte(raw, 0) >= 0:
		// No BOM. Valid UTF-8 never contains a zero byte, while UTF-16LE ASCII is
		// every other byte NUL — so one NUL anywhere settles it.
		return decodeUTF16LE(raw)
	default:
		return string(raw)
	}
}

func decodeUTF16LE(b []byte) string {
	if len(b)%2 != 0 {
		b = b[:len(b)-1] // truncated stream: drop the dangling byte
	}
	units := make([]uint16, len(b)/2)
	for i := range units {
		units[i] = uint16(b[2*i]) | uint16(b[2*i+1])<<8
	}
	return string(utf16.Decode(units))
}

// -------------------------------------------------------------- server start --

// startServer starts LanEx inside the appliance and returns the running child.
//
// THE ONE `wsl.exe` INVOCATION. Three rules, all learned the hard way and
// documented in docs/windows-manual.md — break any of them and the desktop
// viewers (GTKWave, KLayout, GDS3D, OpenROAD GUI) open blank windows titled
// "[WARN: COPY MODE]":
//
//  1. `bash -ic`, never `bash -c`. WSLg only brings its GUI bridge up cleanly
//     for an INTERACTIVE shell.
//  2. Exactly ONE wsl.exe command. A second, separate invocation can block the
//     first from ever running and leaves WSLg half-initialised.
//  3. No LANEX_HW_GL / LIBRELANE_GUI_WSL_HW_GL. LanEx already selects safe
//     software GL on WSL; forcing hardware GL deadlocks a degraded vGPU bridge.
//
// `cd ~` first, and it is not cosmetic either. wsl.exe translates the CALLING
// process's Windows working directory into the Linux one, and this launcher is
// started from its own install dir — so without the cd the server runs with
// cwd = /mnt/c/Program Files/LanEx: a directory the appliance user cannot write
// and a slow 9p mount. Everything that defaults to the current directory then
// lands there ("Could not copy the SPM example: [Errno 13] Permission denied:
// '/mnt/c/Program Files/LanEx/spm_example'", the file picker's "Current dir").
// `;` not `&&`: a cd that somehow fails must not stop LanEx from starting.
//
// `exec lanex` replaces the shell, so the process tree stays wsl.exe -> lanex
// and killing the child is unambiguous. The Windows launcher owns the initial
// window: `--no-browser` prevents the Linux process from declaring success after
// merely spawning Edge, before Windows has proved that /api/health is reachable.
// tray.waitReady opens exactly one app window only after that Windows-side probe.
func startServer() (*exec.Cmd, error) {
	cmd := hiddenCmd(wslExe, startServerArgs()...)
	// The appliance's stdout/stderr is the only diagnostic that exists when a
	// launch fails, and the failure dialogs point the user at this file.
	if f, err := openLogFile(); err == nil {
		cmd.Stdout, cmd.Stderr = f, f
	} else {
		logf("could not open the log file: %v", err)
	}
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	return cmd, nil
}

func startServerArgs() []string {
	return []string{"-d", distroName, "-u", appUser, "--", "env",
		"LANEX_INSTANCE_ID=" + activeConfig.InstallID,
		"LANEX_SOURCE_SHA=" + activeConfig.SourceSHA,
		"LANEX_MANIFEST_HASH=" + activeConfig.Manifest,
		"bash", "-ic",
		"cd ~ 2>/dev/null; exec lanex --no-browser"}
}

// terminateDistro shuts the appliance VM down. Killing wsl.exe on the Windows
// side does NOT stop the Linux process it started — the server would keep
// running headless — so this is what "Quit LanEx" has to end with. It also
// returns the VM's RAM to Windows.
//
// Scoped to our own distro by name: the user's other distros are never touched,
// which is the promise the whole installer is built on (never `wsl --shutdown`).
func terminateDistro() {
	if err := hiddenCmd(wslExe, "--terminate", distroName).Run(); err != nil {
		logf("wsl --terminate %s: %v", distroName, err)
	}
}

// -------------------------------------------------------------- app window   --

// openAppWindow opens the cockpit in a chromeless browser window.
//
// Only used for "re-open" paths (a second click on the icon, the tray's Open
// LanEx). A normal start leaves this to LanEx itself, which does the same thing
// from inside WSL over the interop bridge (appwindow.py:272-303).
func openAppWindow(port int) error {
	args := []string{
		fmt.Sprintf("--app=http://127.0.0.1:%d/", port),
		// The very profile LanEx uses for its own window (appwindow.py:246-279),
		// so both routes produce ONE taskbar identity and neither drags LanEx
		// into the user's browsing session.
		"--user-data-dir=" + appProfileDir(),
		// Same geometry as the WSL-side launch (appwindow._window_flags): the
		// cockpit is a dense multi-pane IDE, so it opens maximized — a re-open
		// from the tray must not land in a small window when a normal start
		// would be maximized.
		"--start-maximized",
		"--window-size=1440,900",
	}
	if exe := chromiumPath(); exe != "" {
		return hiddenCmd(exe, args...).Start()
	}
	// Nothing found on disk (unusual — Edge ships with Windows): let the shell
	// resolve msedge through the App Paths registry key. The empty "" argument is
	// start's title parameter; without it start would eat the first quoted arg.
	return hiddenCmd("cmd.exe", append([]string{"/c", "start", "", "msedge"}, args...)...).Start()
}

// appProfileDir mirrors appwindow.py:250,279 exactly — including the lowercase
// "lanex" (the app-window profile predates this installer's %LOCALAPPDATA%\LanEx
// install root, and the uninstaller removes both).
func appProfileDir() string {
	return filepath.Join(os.Getenv("LOCALAPPDATA"), installDir, "app-profile", activeConfig.InstallID)
}

// Edge first: it ships with every Windows 10/11, so this practically always
// resolves — the same ordering, for the same reason, as appwindow.py:96-102.
var browserExeNames = []string{"msedge.exe", "chrome.exe"}

var browserExeSuffixes = []string{
	`Microsoft\Edge\Application\msedge.exe`,
	`Google\Chrome\Application\chrome.exe`,
}

func chromiumPath() string {
	for _, name := range browserExeNames {
		if p := appPathsLookup(name); p != "" {
			return p
		}
	}
	// Registry-less fallback: the well-known install roots. LOCALAPPDATA covers
	// per-user Chrome installs, which corporate machines often have.
	for _, suffix := range browserExeSuffixes {
		for _, root := range []string{
			os.Getenv("ProgramFiles(x86)"), os.Getenv("ProgramFiles"),
			os.Getenv("LOCALAPPDATA"),
		} {
			if root == "" {
				continue
			}
			p := filepath.Join(root, suffix)
			if st, err := os.Stat(p); err == nil && !st.IsDir() {
				return p
			}
		}
	}
	return ""
}

// appPathsLookup resolves an executable through the App Paths registry key —
// the mechanism `start msedge` itself uses, read directly so we can spawn the
// browser without a cmd.exe in the middle.
func appPathsLookup(exe string) string {
	const base = `SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\`
	for _, root := range []registry.Key{registry.LOCAL_MACHINE, registry.CURRENT_USER} {
		k, err := registry.OpenKey(root, base+exe, registry.QUERY_VALUE)
		if err != nil {
			continue
		}
		v, _, err := k.GetStringValue("") // the key's default value is the full path
		k.Close()
		if err != nil {
			continue
		}
		v = strings.Trim(strings.TrimSpace(v), `"`)
		if st, err := os.Stat(v); err == nil && !st.IsDir() {
			return v
		}
	}
	return ""
}

// openShell opens an interactive shell inside the appliance, in a VISIBLE console.
//
// The one place the appliance's isolation works against the user: a tool that
// genuinely needs a shell (a hand-rolled apt package, a git clone LanEx has no
// button for) is unreachable, because the whole installer's promise is that no
// terminal ever appears. So: on demand, never on startup. A console kept open in
// the background would be a window users close and then believe the app died,
// and it would inherit this process's Windows cwd (`C:\Program Files\LanEx`)
// anyway — hence the `cd ~`, which lands the user next to their own designs.
//
// Deliberately NOT hiddenCmd: this is the one child that must show its window.
// `wsl.exe` is a console program, so CREATE_NEW_CONSOLE gives it one of its own.
//
// `bash -lic 'cd ~; exec bash -i'` rather than the tidier `wsl --cd ~`: --cd
// needs WSL 0.51+, and an unsupported flag would greet the user with
// "Invalid command line option" instead of a shell. This form works on every
// WSL2 build. It IS a second wsl.exe invocation, which startServer's rule 2
// forbids — that rule is about the cold-boot race, where a second invocation
// can stall the first and half-initialise WSLg. This one only ever runs on a
// menu click, long after the server answered /api/health.
func openShell() error {
	cmd := exec.Command(wslExe, "-d", distroName, "--",
		"bash", "-lic", "cd ~ 2>/dev/null; exec bash -i")
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: createNewConsole}
	return cmd.Start()
}

// openProjectFiles shows the user's designs in File Explorer.
//
// Small feature, large trust payoff: it proves the projects are real files on
// their own PC, not something locked inside a black box. \\wsl.localhost is the
// modern share name (\\wsl$ is the pre-2021 alias).
func openProjectFiles() {
	path := filepath.Join(`\\wsl.localhost\`+distroName, "home", appUser)
	// explorer.exe exits non-zero even on success, so its error is not a signal.
	_ = hiddenCmd("explorer.exe", path).Run()
}
