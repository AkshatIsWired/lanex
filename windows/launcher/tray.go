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
	"bytes"
	_ "embed"
	"encoding/json"
	"fmt"
	"os/exec"
	"sync"
	"sync/atomic"
	"time"

	"fyne.io/systray"
)

// The same icon Setup and the Start-menu shortcut use, generated from the
// cockpit's own favicon (see assets/make-icon.py). Embedded rather than read
// from {app} so a moved or half-uninstalled directory can't leave a blank tray.
//
//go:embed assets/lanex.ico
var iconICO []byte

type tray struct {
	cur atomic.Pointer[serverProc] // the wsl.exe client running the server now

	port     atomic.Int64 // 0 until the server answers /api/health
	quitting atomic.Bool  // true once we are tearing down on purpose
	stopOnce sync.Once
	stopped  chan struct{} // closed when LanEx is down for good (no restart)
	shells   atomic.Int32  // "Open LanEx shell" consoles still open

	restartMu sync.Mutex
	restarts  []time.Time // recent automatic restarts, to give up on a loop
}

// serverProc is one wsl.exe client and the moment it exits.
type serverProc struct {
	cmd    *exec.Cmd
	exited chan struct{}
}

func watchProc(cmd *exec.Cmd) *serverProc {
	p := &serverProc{cmd: cmd, exited: make(chan struct{})}
	go func() { _ = cmd.Wait(); close(p.exited) }()
	return p
}

func runTray(server *exec.Cmd) {
	t := &tray{stopped: make(chan struct{})}
	t.cur.Store(watchProc(server))
	// systray.Run owns the main goroutine (it needs the Win32 message loop on the
	// thread that created the window) and only returns after systray.Quit().
	systray.Run(t.onReady, t.onExit)
	// systray.Quit runs onExit on the goroutine that called it, while the
	// message loop above has already ended, so returning now would exit the
	// process halfway through stopServer and leave the appliance running.
	// stopOnce makes this wait for that in-flight stop (or do it, if none ran).
	if t.quitting.Load() {
		t.stopServer()
	}
	logf("launcher exiting")
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
				cmd, err := openShell()
				if err != nil {
					showError(fmt.Sprintf("Could not open a LanEx shell.\n\n%v", err))
					break
				}
				// Quitting terminates the appliance, shell included, so an open
				// shell counts as work in progress when the window closes.
				t.shells.Add(1)
				go func() { _ = cmd.Wait(); t.shells.Add(-1) }()
			case <-quit.ClickedCh:
				// Set BEFORE Quit so watchServer and waitReady know the exit is
				// intentional and stay quiet.
				logf("Quit LanEx chosen from the tray")
				t.quitting.Store(true)
				systray.Quit()
				return
			}
		}
	}()
}

// waitReady flips the tray from "starting…" to "running", or explains why not.
func (t *tray) waitReady(open *systray.MenuItem) {
	first := t.cur.Load()
	port, ok := waitForHealth(startupTimeout, first.exited)
	if ok {
		t.port.Store(int64(port))
		systray.SetTooltip(fmt.Sprintf("%s — running on port %d", appName, port))
		logf("server ready on port %d", port)
		open.Enable()
		if err := openAppWindow(port); err != nil {
			showError(fmt.Sprintf("LanEx is ready at http://127.0.0.1:%d/ but its "+
				"window could not be opened.\n\n%v", port, err))
		}
		go t.watchWindows(port)
		return
	}
	if t.quitting.Load() {
		return
	}
	select {
	case <-first.exited:
		// The process died; watchServer owns that dialog. Two message boxes for
		// one failure is worse than none.
		return
	default:
	}
	// Still alive but not answering after 90 s. Stop only this owned appliance;
	// never tell the user to shut down every WSL distribution on the machine.
	logf("server did not answer /api/health within %s", startupTimeout)
	t.quitting.Store(true)
	t.stopServer()
	showError("LanEx could not start.\n\n" +
		"Windows could not reach the LanEx health check. Retry once; if it keeps " +
		"failing, use Repair so LanEx can diagnose its own WSL networking without " +
		"stopping your other WSL environments.\n\nDetails are in:\n" + logPath())
	systray.Quit()
}

// watchServer reacts to the server process ending.
//
// Once LanEx has been up, an unexpected end is restarted rather than taken as
// a quit: the window may still be open with unsaved work, and its page
// reconnects by itself as soon as the server answers again. That covers
// wsl.exe dying after the PC wakes up, a WSL service restart (WSL updates
// itself in the background), and the recovery in checkUnreachable.
func (t *tray) watchServer() {
	for {
		p := t.cur.Load()
		<-p.exited
		if t.quitting.Load() {
			close(t.stopped)
			return
		}
		logf("LanEx's server process ended unexpectedly (%v)", p.cmd.ProcessState)
		// Closing the app WINDOW does not get here: the server outlives the browser.
		// watchWindows is what turns a closed window into a quit.
		if t.port.Load() == 0 {
			// waitReady is still waiting on this process; it returns on exited.
			showError("LanEx stopped before it finished starting.\n\n" +
				"Try again. If it keeps failing, run LanEx Setup and choose Repair. " +
				"Your projects and other WSL environments are preserved.\n\nDetails are in:\n" + logPath())
			close(t.stopped)
			systray.Quit()
			return
		}
		if !t.restart() {
			t.quitting.Store(true)
			close(t.stopped)
			systray.Quit()
			return
		}
	}
}

const (
	maxRestarts   = 3
	restartWindow = 10 * time.Minute
)

// restart brings the server back after it went away on its own. False means
// give up (it keeps dying, or will not come back), after telling the user.
func (t *tray) restart() bool {
	t.restartMu.Lock()
	defer t.restartMu.Unlock()
	now := time.Now()
	recent := t.restarts[:0]
	for _, at := range t.restarts {
		if now.Sub(at) < restartWindow {
			recent = append(recent, at)
		}
	}
	t.restarts = recent
	if len(t.restarts) >= maxRestarts {
		logf("server stopped %d times in %s; not restarting again", maxRestarts, restartWindow)
		showError("LanEx stopped unexpectedly several times in a few minutes, so it was not " +
			"restarted again.\n\nYour projects and finished runs are kept. Open LanEx again " +
			"from the Start menu; if this keeps happening, run Repair LanEx.\n\nDetails are in:\n" + logPath())
		return false
	}
	t.restarts = append(t.restarts, now)
	systray.SetTooltip(appName + " — reconnecting…")

	old := int(t.port.Load())
	var cmd *exec.Cmd
	var err error
	if old > 0 && healthyAt(healthURL(old)) {
		// Only the Windows-side client went away; the server inside is fine and
		// may be in the middle of a run. Keep it, and give the distro a new
		// client so WSL does not stop it for being idle.
		logf("server still answers on port %d; reattaching", old)
		cmd, err = startKeepalive()
	} else {
		logf("starting the server again")
		cmd, err = startServer()
	}
	if err != nil {
		logf("restart failed: %v", err)
		showError(fmt.Sprintf("LanEx stopped unexpectedly and could not be started again.\n\n%v\n\n"+
			"Your projects and finished runs are kept. Open LanEx again from the Start menu."+
			"\n\nDetails are in:\n%s", err, logPath()))
		return false
	}
	p := watchProc(cmd)
	t.cur.Store(p)
	port, ok := waitForHealth(startupTimeout, p.exited)
	if !ok {
		select {
		case <-p.exited:
			// watchServer sees this exit next and counts another attempt.
			logf("restarted server ended before answering")
			return true
		default:
		}
		logf("restarted server did not answer within %s", startupTimeout)
		showError("LanEx stopped unexpectedly and did not come back.\n\n" +
			"Your projects and finished runs are kept. Open LanEx again from the Start " +
			"menu; if it keeps failing, run Repair LanEx.\n\nDetails are in:\n" + logPath())
		return false
	}
	t.port.Store(int64(port))
	systray.SetTooltip(fmt.Sprintf("%s — running on port %d", appName, port))
	logf("server back on port %d", port)
	go t.reopenIfNoWindow(port)
	return true
}

// reopenIfNoWindow opens a window after a restart if none reconnects: a page
// that had already shown "refused to connect" does not come back by itself.
func (t *tray) reopenIfNoWindow(port int) {
	select {
	case <-t.stopped:
		return
	case <-time.After(20 * time.Second):
	}
	if t.quitting.Load() || int(t.port.Load()) != port {
		return
	}
	if p, err := fetchPresence(port); err == nil && p.Windows == 0 {
		logf("no window reconnected after the restart; opening one")
		if err := openAppWindow(port); err != nil {
			logf("could not reopen the window: %v", err)
		}
	}
}

// How long the server may stay unreachable from Windows before the launcher
// looks from inside the distro, and how long before it restarts a server
// that does not answer there either.
const (
	unreachableProbe   = 90 * time.Second
	unreachableRestart = 3 * time.Minute
)

// watchWindows quits LanEx once its last window has closed (see closewatch.go),
// and notices a server that Windows can no longer reach.
func (t *tray) watchWindows(port int) {
	var w closeWatcher
	var failSince, lastProbe time.Time
	for {
		select {
		case <-t.stopped:
			return
		case <-time.After(presencePoll):
		}
		if t.quitting.Load() {
			return
		}
		if p := int(t.port.Load()); p > 0 && p != port {
			port = p // restarted on another port
		}
		now := time.Now()
		p, err := fetchPresence(port)
		if err != nil {
			w.unknown(now)
			if w.resumed(now) {
				// Just woke up: WSL's network needs a moment. Not a failure yet.
				failSince = time.Time{}
				continue
			}
			if failSince.IsZero() {
				failSince = now
			}
			if down := now.Sub(failSince); down >= unreachableProbe && now.Sub(lastProbe) >= unreachableProbe/2 {
				lastProbe = now
				t.checkUnreachable(port, down)
			}
			continue
		}
		if !failSince.IsZero() {
			logf("server reachable again after %s", now.Sub(failSince).Round(time.Second))
			failSince = time.Time{}
		}
		if !w.observe(p, now) {
			continue
		}
		busy := p.Busy
		if t.shells.Load() > 0 {
			busy = append(busy, "a LanEx shell window")
		}
		if len(busy) > 0 {
			quit := askQuit(busyQuestion(busy))
			// The question can sit unanswered for minutes; a window the user
			// reopened from the Start menu meanwhile settles it.
			if again, err := fetchPresence(port); err == nil && again.Windows > 0 {
				w.reset()
				continue
			}
			if !quit {
				w.reset()
				if err := openAppWindow(port); err != nil {
					showError(fmt.Sprintf("Could not reopen the LanEx window.\n\n%v\n\n"+
						"LanEx is still running: use the LanEx icon in the taskbar tray.", err))
				}
				continue
			}
		}
		how := "the window said goodbye"
		if p.ByeSeconds == nil || *p.ByeSeconds > byeRecent.Seconds() {
			how = fmt.Sprintf("no window for %s and no goodbye", quietGrace)
		}
		logf("last window closed; quitting (%s; busy: %v)", how, busy)
		t.quitting.Store(true)
		systray.Quit()
		return
	}
}

// checkUnreachable runs when Windows has not reached the server for a while
// although its wsl.exe client is alive. Either WSL's localhost forwarding
// broke (seen after hibernate) or the server itself hung. The answer from
// inside the distro tells which; a restart fixes both, but never while LanEx
// is in the middle of something.
func (t *tray) checkUnreachable(port int, down time.Duration) {
	out, err := wslOutput(20*time.Second, "-d", distroName, "-u", appUser, "--",
		"python3", "-c", insidePresenceScript(port))
	var p presence
	inside := err == nil && json.Unmarshal(bytes.TrimSpace(out), &p) == nil
	d := down.Round(time.Second)
	switch {
	case inside && len(p.Busy) > 0:
		logf("server unreachable from Windows for %s but alive inside and busy (%v); waiting", d, p.Busy)
		systray.SetTooltip(appName + " — busy; reconnecting to Windows…")
		return
	case inside:
		logf("server unreachable from Windows for %s but alive inside; restarting it to restore the connection", d)
	case down < unreachableRestart:
		logf("server unreachable from Windows for %s and from inside (%v); waiting", d, err)
		return
	default:
		logf("server unreachable from Windows and from inside for %s; restarting it", d)
	}
	// Stop the server; watchServer sees the exit and starts it again.
	terminateDistro()
}

// insidePresenceScript asks the server for /api/presence from inside the
// distro, where WSL's port forwarding plays no part.
func insidePresenceScript(port int) string {
	return fmt.Sprintf("import json,urllib.request as u;"+
		"print(json.dumps(json.load(u.urlopen('http://127.0.0.1:%d/api/presence',timeout=10))['data']))", port)
}

// onExit runs after systray.Quit(), on the way out.
func (t *tray) onExit() {
	if t.quitting.Load() {
		t.stopServer()
	}
}

// stopServer ends the server and the appliance. Idempotent: the timeout path
// calls it before quitting, and onExit calls it again.
//
// Terminate first, kill second. Killing wsl.exe first left the distro
// "Running" for another ~10 s after the launcher had exited (observed on
// WSL 2.x); terminating first stops it at once, and wsl.exe then exits on its
// own. The kill only covers a client that somehow outlives the terminate.
func (t *tray) stopServer() {
	t.stopOnce.Do(func() {
		terminateDistro()
		p := t.cur.Load()
		select {
		case <-p.exited:
		case <-time.After(5 * time.Second):
			if proc := p.cmd.Process; proc != nil {
				if err := proc.Kill(); err != nil {
					logf("could not kill wsl.exe: %v", err)
				}
			}
		}
	})
}
