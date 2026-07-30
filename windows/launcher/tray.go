// Copyright 2026 LanEx Contributors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0

// The tray icon — the launcher's entire visible surface on Windows.
package main

import (
	_ "embed"
	"fmt"
	"os/exec"
	"sync"
	"sync/atomic"

	"fyne.io/systray"
)

// The same icon Setup and the Start-menu shortcut use, generated from the
// cockpit's own favicon (see assets/make-icon.py). Embedded rather than read
// from {app} so a moved or half-uninstalled directory can't leave a blank tray.
//
//go:embed assets/lanex.ico
var iconICO []byte

type tray struct {
	server *exec.Cmd

	port     atomic.Int64 // 0 until the server answers /api/health
	quitting atomic.Bool  // true once we are tearing down on purpose
	stopOnce sync.Once
	stopped  chan struct{} // closed when the server process has exited
}

func runTray(server *exec.Cmd) {
	t := &tray{server: server, stopped: make(chan struct{})}
	// systray.Run owns the main goroutine (it needs the Win32 message loop on the
	// thread that created the window) and only returns after systray.Quit().
	systray.Run(t.onReady, t.onExit)
}

func (t *tray) onReady() {
	systray.SetIcon(iconICO)
	systray.SetTitle(appName)
	// The tooltip is this app's status bar: "starting…" is what the user sees
	// during the WSL cold boot, and it is why the wait needs no progress window.
	systray.SetTooltip(appName + " — starting…")

	open := systray.AddMenuItem("Open LanEx", "Bring the LanEx window back")
	open.Disable() // no port yet; enabling early would open a dead URL
	files := systray.AddMenuItem("Open project files",
		"See your designs in File Explorer")
	// The escape hatch, and the reason it is a menu item rather than a console
	// kept open behind the app: nothing supported needs it (LanEx installs its
	// own toolchains, GDS3D included), but a user who wants to run something
	// LanEx has no button for should not be told their only option is to
	// reinstall Ubuntu. Zero cost until clicked.
	shell := systray.AddMenuItem("Open LanEx shell",
		"A terminal inside LanEx's environment, in your projects folder")
	systray.AddSeparator()
	quit := systray.AddMenuItem("Quit LanEx", "Stop LanEx and shut its environment down")

	go t.watchServer()
	go t.waitReady(open)

	go func() {
		for {
			select {
			case <-open.ClickedCh:
				if port := int(t.port.Load()); port > 0 {
					if err := openAppWindow(port); err != nil {
						showError(fmt.Sprintf("Could not open the LanEx window.\n\n%v\n\n"+
							"LanEx is still running at http://127.0.0.1:%d/", err, port))
					}
				}
			case <-files.ClickedCh:
				openProjectFiles()
			case <-shell.ClickedCh:
				if err := openShell(); err != nil {
					showError(fmt.Sprintf("Could not open a LanEx shell.\n\n%v", err))
				}
			case <-quit.ClickedCh:
				// Set BEFORE Quit so watchServer and waitReady know the exit is
				// intentional and stay quiet.
				t.quitting.Store(true)
				systray.Quit()
				return
			}
		}
	}()
}

// waitReady flips the tray from "starting…" to "running", or explains why not.
func (t *tray) waitReady(open *systray.MenuItem) {
	port, ok := waitForHealth(startupTimeout, t.stopped)
	if ok {
		t.port.Store(int64(port))
		systray.SetTooltip(fmt.Sprintf("%s — running on port %d", appName, port))
		open.Enable()
		return
	}
	if t.quitting.Load() {
		return
	}
	select {
	case <-t.stopped:
		// The process died; watchServer owns that dialog. Two message boxes for
		// one failure is worse than none.
		return
	default:
	}
	// Still alive but not answering after 90 s. The overwhelmingly common cause
	// is broken Windows->WSL localhost forwarding, and `wsl --shutdown` is the
	// documented one-time fix — the same advice LanEx prints itself
	// (cli.py:296-301).
	t.stopServer()
	showError("LanEx could not start.\n\n" +
		"Try again. If it keeps failing, open a Windows terminal, run\n\n" +
		"    wsl --shutdown\n\n" +
		"and relaunch LanEx — that clears a known one-time WSL networking " +
		"problem.\n\nDetails are in:\n" + logPath())
	t.quitting.Store(true)
	systray.Quit()
}

// watchServer reacts to the server process ending.
func (t *tray) watchServer() {
	_ = t.server.Wait()
	close(t.stopped)
	if t.quitting.Load() {
		return
	}
	// Note what does NOT get here: closing the app WINDOW. That leaves the server
	// running headless on purpose, so clicking the icon again reopens the cockpit
	// instantly with every run still in place. Only Quit stops the server.
	if t.port.Load() == 0 {
		showError("LanEx stopped before it finished starting.\n\n" +
			"Try again. If it keeps failing, open a Windows terminal, run\n\n" +
			"    wsl --shutdown\n\nand relaunch LanEx.\n\nDetails are in:\n" + logPath())
	}
	systray.Quit()
}

// onExit runs after systray.Quit(), on the way out.
func (t *tray) onExit() {
	if t.quitting.Load() {
		t.stopServer()
	}
}

// stopServer ends the server and the appliance. Idempotent: the timeout path
// calls it before quitting, and onExit calls it again.
func (t *tray) stopServer() {
	t.stopOnce.Do(func() {
		if p := t.server.Process; p != nil {
			if err := p.Kill(); err != nil {
				logf("could not kill wsl.exe: %v", err)
			}
		}
		terminateDistro()
	})
}
