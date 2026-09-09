// Copyright 2026 LanEx Contributors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0

// LanEx.exe — the whole Windows-side UI of LanEx: a tray icon, and nothing else.
//
// LanEx drives OpenROAD, Yosys, Magic and KLayout, none of which run natively on
// Windows, so on Windows it lives inside a private, isolated Ubuntu WSL distro
// that LanEx-Setup.exe imports — the appliance pattern Docker Desktop and
// Rancher Desktop use. This launcher is what makes that invisible: the user
// clicks "LanEx" in the Start menu and, some seconds later, a real desktop
// window opens. No terminal, no Ubuntu, no bash, no password prompt. Ever.
//
// It does four things:
//
//  1. Enforces a single instance — a second click re-opens the window, never
//     starts a second server (main.go).
//  2. Starts the server with exactly ONE `wsl.exe` invocation (wsl.go; that
//     constraint is not cosmetic — see the comment on startServer).
//  3. Waits for /api/health, then sits in the tray (probe.go, tray.go).
//  4. Stops the server and shuts the appliance down on Quit.
//
// The initial app window is opened from Windows only after the Windows-side
// /api/health probe succeeds. A process spawned inside WSL cannot prove that
// Windows localhost forwarding works; opening there produced a convincing but
// dead Edge window while the launcher still waited in the tray.
//
// Windows-only by construction (Win32 mutex, message boxes, registry, tray):
//
//	GOOS=windows GOARCH=amd64 go build -ldflags "-H windowsgui -s -w"
//
// `-H windowsgui` is what stops a console window flashing on every launch.
package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"

	"golang.org/x/sys/windows"
)

const (
	appName    = "LanEx"
	installDir = "LanEx" // subdirectory of %LOCALAPPDATA% for logs
	appUser    = "lanex"

	// Global\ (not Local\) so the instance check spans terminal-server
	// sessions: two logged-in users each starting LanEx would otherwise both
	// start a server, and both would fight over port 8765 on the same host.
	mutexName = `Global\LanExLauncher`

	// First launch after a reboot starts a cold WSL VM: the Linux userspace
	// boots, systemd brings up the Docker daemon, then Python starts. 90 s is
	// deliberately generous — a premature "could not start" dialog is far more
	// damaging than a longer wait, and the tray icon is already visible.
	startupTimeout = 90 * time.Second
	probeInterval  = 500 * time.Millisecond

	// CREATE_NO_WINDOW. Every child here (wsl.exe, cmd.exe, explorer.exe) is a
	// console program; without this flag each one flashes a black window.
	createNoWindow = 0x08000000

	// CREATE_NEW_CONSOLE — the exact opposite, and used exactly once: the tray's
	// "Open LanEx shell" is the only child the user asked to SEE (wsl.go's
	// openShell). A `-H windowsgui` process has no console to inherit, so
	// without this the shell would start with nowhere to draw.
	createNewConsole = 0x00000010

	releasesURL = "https://github.com/AkshatIsWired/lanex/releases/latest"
)

func main() {
	loadApplianceConfig()
	first, err := acquireSingleInstance()
	if err != nil {
		// A mutex we could not create must never block a launch — worst case we
		// lose the "don't start twice" guarantee, which the health probe below
		// mostly covers anyway.
		logf("single-instance check failed: %v", err)
	}
	if !first {
		secondInstance()
		return
	}

	if !distroPresent() {
		// Only reachable if the appliance was removed behind Setup's back
		// (`wsl --unregister lanex`, or a wiped %LOCALAPPDATA%). Reinstalling is
		// genuinely the fix: the distro is where LanEx itself lives.
		if askYesNo("LanEx's environment is missing.\n\n" +
			"Please reinstall LanEx to restore it — your Windows settings are untouched.\n\n" +
			"Open the download page now?") {
			openURL(releasesURL)
		}
		os.Exit(1)
	}

	server, err := startServer()
	if err != nil {
		showError(fmt.Sprintf("LanEx could not start its environment.\n\n%v\n\n"+
			"Try again. If it keeps failing, run  wsl --shutdown  from a Windows "+
			"terminal, then relaunch LanEx.", err))
		os.Exit(1)
	}
	runTray(server)
}

// secondInstance handles a click on the icon while LanEx is already running:
// re-open the window, never start a second server.
func secondInstance() {
	if port, ok := findRunningServer(); ok {
		if err := openAppWindow(port); err != nil {
			showError(fmt.Sprintf("LanEx is running at http://127.0.0.1:%d/ but its "+
				"window could not be opened.\n\n%v", port, err))
		}
		return
	}
	// Mutex held but nothing answering yet: the first instance is still booting
	// the WSL VM. Saying so beats silence (the user just clicked and saw nothing).
	showInfo("LanEx is still starting.\n\nGive it a few more seconds, then click " +
		"the LanEx icon again.")
}

// ------------------------------------------------------------ single instance --

// instanceMutex is held for the process lifetime on purpose: Windows releases
// the name when the last handle closes, so a package-level reference is what
// keeps a later launch from being treated as the first one.
var instanceMutex windows.Handle

// acquireSingleInstance reports whether this process is the first instance.
func acquireSingleInstance() (bool, error) {
	name, err := windows.UTF16PtrFromString(mutexName)
	if err != nil {
		return true, err
	}
	// CreateMutex returns a VALID handle *and* ERROR_ALREADY_EXISTS when
	// somebody else got there first — the handle is still ours to hold.
	h, err := windows.CreateMutex(nil, false, name)
	if h != 0 {
		instanceMutex = h
	}
	if err == windows.ERROR_ALREADY_EXISTS {
		return false, nil
	}
	if h == 0 {
		return true, fmt.Errorf("CreateMutex: %w", err)
	}
	return true, nil
}

// ------------------------------------------------------------------- dialogs --

// MessageBoxW flags. Spelled out locally rather than pulled from a dependency:
// these five values have been stable since Windows 3.1.
const (
	mbOK            = 0x00000000
	mbYesNo         = 0x00000004
	mbIconError     = 0x00000010
	mbIconInfo      = 0x00000040
	mbSetForeground = 0x00010000
	idYes           = 6
)

func msgbox(text string, flags uint32) int32 {
	t, err1 := windows.UTF16PtrFromString(text)
	c, err2 := windows.UTF16PtrFromString(appName)
	if err1 != nil || err2 != nil {
		return 0
	}
	// A tray-only app has no window to parent the dialog to, so MB_SETFOREGROUND
	// is what keeps it from opening behind whatever the user is looking at.
	ret, _ := windows.MessageBox(0, t, c, flags|mbSetForeground)
	return ret
}

func showInfo(text string)  { msgbox(text, mbOK|mbIconInfo) }
func showError(text string) { msgbox(text, mbOK|mbIconError) }
func askYesNo(text string) bool {
	return msgbox(text, mbYesNo|mbIconError) == idYes
}

// openURL opens *raw* in the user's default browser via the shell — the one
// method that works from a GUI process with no console attached.
func openURL(raw string) {
	verb, _ := windows.UTF16PtrFromString("open")
	target, err := windows.UTF16PtrFromString(raw)
	if err != nil {
		return
	}
	if err := windows.ShellExecute(0, verb, target, nil, nil,
		windows.SW_SHOWNORMAL); err != nil {
		logf("ShellExecute(%s): %v", raw, err)
	}
}

// ----------------------------------------------------------------- logging  --

// logPath is where the appliance's own stdout/stderr lands: the first thing to
// ask a user for when LanEx will not start, and the path our failure dialogs
// name. One file, truncated per launch — a launcher that silently grows a log
// forever is its own bug report.
func logPath() string {
	dir := filepath.Join(os.Getenv("LOCALAPPDATA"), installDir, "logs")
	return filepath.Join(dir, "launcher.log")
}

func openLogFile() (*os.File, error) {
	p := logPath()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return nil, err
	}
	return os.Create(p)
}

// logf appends a launcher-side note to the same file. Best-effort: losing a log
// line must never take the app down.
func logf(format string, args ...any) {
	f, err := os.OpenFile(logPath(), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	fmt.Fprintf(f, "[launcher %s] %s\n", time.Now().Format(time.RFC3339),
		fmt.Sprintf(format, args...))
}

// hiddenCmd builds an exec.Cmd that never flashes a console window.
//
// CREATE_NO_WINDOW only, deliberately: SysProcAttr.HideWindow passes SW_HIDE as
// the child's initial show state, which console programs ignore but GUI programs
// obey — so setting it here would open the Edge app window INVISIBLY. The flag
// is ignored by GUI children, which is exactly what we want, since the same
// helper launches wsl.exe, cmd.exe, explorer.exe and the browser.
func hiddenCmd(name string, args ...string) *exec.Cmd {
	cmd := exec.Command(name, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: createNoWindow}
	return cmd
}
