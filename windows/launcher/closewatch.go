// Copyright 2026 LanEx Contributors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0

package main

// Closing the last LanEx window quits LanEx.
//
// The appliance is a whole Linux VM: left running headless in the tray it
// keeps gigabytes of RAM and a share of the CPU, and users who clicked X
// reasonably believe they closed the app. So the tray icon only lives as long
// as a window does. When the last window has been gone for closeGrace, the
// launcher quits exactly as "Quit LanEx" does. If quitting would interrupt
// something (a flow run, a download, KLayout still open, a LanEx shell), it
// asks first; "No" reopens the window instead.
//
// The server is the only party that sees windows come and go reliably: every
// LanEx page holds one /api/events stream for its lifetime, and
// /api/presence reports how many are open. Watching browser processes or
// window titles from here would break on Edge's background mode, a shared
// profile, or a user's own tab titled "LanEx".

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

const (
	presencePoll = 1 * time.Second
	// How long no window may be open before LanEx quits. Long enough for a
	// reload (the stream drops while the page boots) and for "click the Start
	// menu icon again" to win the race; short enough that memory comes back
	// while the user is still looking.
	closeGrace = 6 * time.Second
	// A page still fetching is a page still alive, even before its stream
	// reconnects.
	pageQuietFor = 3 * time.Second
)

type presence struct {
	Windows     int      `json:"windows"`
	IdleSeconds float64  `json:"idleSeconds"`
	Busy        []string `json:"busy"`
}

func presenceURL(port int) string {
	return fmt.Sprintf("http://127.0.0.1:%d/api/presence", port)
}

// fetchPresence asks the server what is open. Any failure, including a server
// too old to have the endpoint, is an error, and an error never counts as
// "window closed".
func fetchPresence(port int) (presence, error) {
	var p presence
	resp, err := probeClient.Get(presenceURL(port))
	if err != nil {
		return p, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return p, fmt.Errorf("presence: HTTP %d", resp.StatusCode)
	}
	var envelope struct {
		OK   bool     `json:"ok"`
		Data presence `json:"data"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 16384)).Decode(&envelope); err != nil {
		return p, err
	}
	if !envelope.OK {
		return p, fmt.Errorf("presence: not ok")
	}
	return envelope.Data, nil
}

// closeWatcher decides, one presence sample at a time, when the last window
// has really gone. Pure logic so the timing rules are unit-tested.
type closeWatcher struct {
	armed     bool      // a window has been seen since start or the last reset
	goneSince time.Time // first sample of the current no-window stretch
}

// observe records a sample and reports whether LanEx should now quit.
func (w *closeWatcher) observe(p presence, now time.Time) bool {
	if p.Windows > 0 {
		w.armed = true
		w.goneSince = time.Time{}
		return false
	}
	// Never quit before the first window has connected: a slow first boot, or
	// a window that failed to open, must not tear LanEx down behind the user.
	// The tray's Quit stays available for that case.
	if !w.armed || time.Duration(p.IdleSeconds*float64(time.Second)) < pageQuietFor {
		w.goneSince = time.Time{}
		return false
	}
	if w.goneSince.IsZero() {
		w.goneSince = now
		return false
	}
	return now.Sub(w.goneSince) >= closeGrace
}

// unknown records a failed sample: it says nothing, so it breaks the stretch.
func (w *closeWatcher) unknown() { w.goneSince = time.Time{} }

// reset disarms the watcher until a window connects again (after "No").
func (w *closeWatcher) reset() { *w = closeWatcher{} }

// busyQuestion is the confirmation shown when quitting would interrupt work.
func busyQuestion(busy []string) string {
	var b strings.Builder
	b.WriteString("You closed the LanEx window, but LanEx is still busy with:\n\n")
	for _, item := range busy {
		b.WriteString("    •  " + item + "\n")
	}
	b.WriteString("\nQuit LanEx now? That stops everything above and frees the " +
		"memory LanEx uses. Your projects and finished runs are kept.\n\n" +
		"Yes: quit LanEx.\nNo: keep working (the window reopens).")
	return b.String()
}
