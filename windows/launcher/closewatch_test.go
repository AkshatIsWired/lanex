// Copyright 2026 LanEx Contributors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0

package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

var t0 = time.Date(2026, 10, 4, 12, 0, 0, 0, time.UTC)

func at(s float64) time.Time { return t0.Add(time.Duration(s * float64(time.Second))) }

// closed is a sample after the page said goodbye (a real close).
func closed(idle float64) presence {
	bye := 1.0
	return presence{Windows: 0, IdleSeconds: idle, ByeSeconds: &bye}
}

// vanished is a sample after the stream dropped with no goodbye (sleep, Wi-Fi).
func vanished(idle float64) presence { return presence{Windows: 0, IdleSeconds: idle} }

func TestCloseWatcherQuitsAfterGrace(t *testing.T) {
	var w closeWatcher
	if w.observe(presence{Windows: 1}, at(0)) {
		t.Fatal("quit with a window open")
	}
	// Window closed: quiet page traffic, then grace.
	if w.observe(closed(5), at(1)) {
		t.Fatal("quit on the first empty sample")
	}
	if w.observe(closed(9), at(1+closeGrace.Seconds()-0.5)) {
		t.Fatal("quit before the grace period ended")
	}
	if !w.observe(closed(10), at(1+closeGrace.Seconds())) {
		t.Fatal("did not quit after the grace period")
	}
}

func TestCloseWatcherNeverQuitsBeforeFirstWindow(t *testing.T) {
	var w closeWatcher
	for s := 0.0; s < 120; s++ {
		if w.observe(closed(s), at(s)) {
			t.Fatalf("quit at %vs although no window ever connected", s)
		}
	}
}

func TestCloseWatcherReloadDoesNotQuit(t *testing.T) {
	var w closeWatcher
	w.observe(presence{Windows: 1}, at(0))
	// The stream is gone while the reloaded page fetches its boot data for a
	// long time; recent page requests keep resetting the clock.
	for s := 1.0; s < 20; s++ {
		if w.observe(closed(0.5), at(s)) {
			t.Fatalf("quit during a reload at %vs", s)
		}
	}
	if w.observe(presence{Windows: 1}, at(20)) {
		t.Fatal("quit with the reloaded window open")
	}
}

func TestCloseWatcherWindowBackCancels(t *testing.T) {
	var w closeWatcher
	w.observe(presence{Windows: 1}, at(0))
	w.observe(closed(5), at(1))
	w.observe(presence{Windows: 1}, at(3)) // reopened from the Start menu
	if w.observe(closed(5), at(4)) || w.observe(closed(6), at(1+closeGrace.Seconds())) {
		t.Fatal("the earlier no-window stretch leaked past a reopen")
	}
}

func TestCloseWatcherUnknownBreaksStretch(t *testing.T) {
	var w closeWatcher
	w.observe(presence{Windows: 1}, at(0))
	w.observe(closed(5), at(1))
	w.unknown(at(2)) // server busy or restarting: says nothing about windows
	if w.observe(closed(10), at(1+closeGrace.Seconds())) {
		t.Fatal("a failed sample counted towards the grace period")
	}
}

func TestCloseWatcherResetDisarms(t *testing.T) {
	var w closeWatcher
	w.observe(presence{Windows: 1}, at(0))
	w.reset() // user answered "No"; the window is reopening
	for s := 1.0; s < 60; s++ {
		if w.observe(closed(s), at(s)) {
			t.Fatal("quit before the reopened window connected")
		}
	}
}

func TestCloseWatcherWaitsLongWithoutGoodbye(t *testing.T) {
	var w closeWatcher
	w.observe(presence{Windows: 1}, at(0))
	for s := 1.0; s < 1+quietGrace.Seconds(); s++ {
		if w.observe(vanished(600), at(s)) {
			t.Fatalf("quit %vs after the stream dropped with no goodbye", s)
		}
	}
	if !w.observe(vanished(900), at(1+quietGrace.Seconds())) {
		t.Fatal("never quit although the window stayed gone")
	}
}

func TestCloseWatcherHoldsAfterSleep(t *testing.T) {
	var w closeWatcher
	w.observe(presence{Windows: 1}, at(0))
	w.observe(presence{Windows: 1}, at(1))
	// The PC slept for an hour. On waking, the page's goodbye-less stream is
	// gone and even a stale goodbye from an earlier reload must not count.
	wake := 3600.0
	for s := wake; s < wake+resumeHold.Seconds(); s++ {
		if w.observe(closed(5000), at(s)) {
			t.Fatalf("quit %vs after waking up", s-wake)
		}
	}
	if !w.resumed(at(wake + 1)) {
		t.Fatal("sleep not noticed")
	}
	// The window came back once Edge woke up.
	if w.observe(presence{Windows: 1}, at(wake+resumeHold.Seconds()+1)) {
		t.Fatal("quit with the window back")
	}
}

func TestCloseWatcherSleepDuringGraceCancels(t *testing.T) {
	var w closeWatcher
	w.observe(presence{Windows: 1}, at(0))
	w.observe(vanished(600), at(1)) // stretch starts
	if w.observe(vanished(600), at(1+quietGrace.Seconds()+600)) {
		t.Fatal("a sleep counted towards the grace period")
	}
}

func TestBusyQuestionListsEverything(t *testing.T) {
	q := busyQuestion([]string{"a flow run", "KLayout"})
	for _, want := range []string{"a flow run", "KLayout", "Quit LanEx now?", "projects"} {
		if !strings.Contains(q, want) {
			t.Errorf("question missing %q:\n%s", want, q)
		}
	}
}

func TestFetchPresence(t *testing.T) {
	cases := []struct {
		name    string
		status  int
		body    string
		want    presence
		wantErr bool
	}{
		{"real routes.py envelope", 200,
			`{"ok":true,"data":{"windows":2,"idleSeconds":0.4,"byeSeconds":null,"busy":["a flow run"]}}`,
			presence{Windows: 2, IdleSeconds: 0.4, Busy: []string{"a flow run"}}, false},
		{"old server without the route", 404, `{"ok":false,"error":"not found"}`, presence{}, true},
		{"not ok", 200, `{"ok":false,"error":"boom"}`, presence{}, true},
		{"garbage", 200, `<html>`, presence{}, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/api/presence" {
					http.NotFound(w, r)
					return
				}
				w.WriteHeader(c.status)
				fmt.Fprint(w, c.body)
			}))
			defer srv.Close()
			port, _ := strconv.Atoi(srv.URL[strings.LastIndex(srv.URL, ":")+1:])
			got, err := fetchPresence(port)
			if (err != nil) != c.wantErr {
				t.Fatalf("err = %v, wantErr %v", err, c.wantErr)
			}
			if !c.wantErr && (got.Windows != c.want.Windows || got.IdleSeconds != c.want.IdleSeconds ||
				strings.Join(got.Busy, "|") != strings.Join(c.want.Busy, "|")) {
				t.Fatalf("got %+v, want %+v", got, c.want)
			}
		})
	}
}
