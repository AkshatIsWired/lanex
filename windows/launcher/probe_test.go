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
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestHealthyAt(t *testing.T) {
	cases := []struct {
		name   string
		status int
		body   string
		want   bool
	}{
		// What routes.py's h_health actually replies.
		{"lanex", 200, `{"service": "lanex", "alive": true, "compat": {"ok": true}}`, true},
		// A 200 from something else on 8765 must NOT be mistaken for LanEx —
		// otherwise the launcher points its window at a stranger's dev server.
		{"other server", 200, `{"service": "vite", "ok": true}`, false},
		{"html", 200, "<!doctype html><title>hello</title>", false},
		{"not found", 404, `{"service": "lanex"}`, false},
		{"server error", 500, "boom", false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(tc.status)
				_, _ = w.Write([]byte(tc.body))
			}))
			defer srv.Close()
			if got := healthyAt(srv.URL + "/api/health"); got != tc.want {
				t.Errorf("healthyAt(%s) = %v, want %v", tc.name, got, tc.want)
			}
		})
	}
}

func TestHealthyAtNothingListening(t *testing.T) {
	// Closed port: the common case on every probe before the server is up. Must
	// be a fast false, never a panic or a hang.
	srv := httptest.NewServer(http.NotFoundHandler())
	url := srv.URL + "/api/health"
	srv.Close()
	if healthyAt(url) {
		t.Errorf("healthyAt(%s) = true for a closed port", url)
	}
}

// The port range must match app.py's find_free_port (preferred..preferred+6).
func TestCandidatePorts(t *testing.T) {
	got := candidatePorts()
	want := []int{8765, 8766, 8767, 8768, 8769, 8770, 8771}
	if len(got) != len(want) {
		t.Fatalf("candidatePorts() = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("candidatePorts() = %v, want %v", got, want)
		}
	}
}

func TestHealthURL(t *testing.T) {
	if got := healthURL(8766); got != "http://127.0.0.1:8766/api/health" {
		t.Errorf("healthURL(8766) = %q", got)
	}
}

// withRecord points serverRecordPath at a temp file containing *body* (or at a
// path that does not exist, when body is "").
func withRecord(t *testing.T, body string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "server.json")
	if body != "" {
		if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	orig := serverRecordPath
	serverRecordPath = func() string { return path }
	t.Cleanup(func() { serverRecordPath = orig })
}

func TestServerJSONPort(t *testing.T) {
	cases := []struct {
		name string
		body string
		want int
		ok   bool
	}{
		{"what cli.py writes", `{"url": "http://127.0.0.1:8766/", "port": 8766, "pid": 405}`, 8766, true},
		{"absent — an appliance older than the feature", "", 0, false},
		// A file being written when we read it, and a shutdown that left the
		// key behind. Both must read as "no record", never as port 0.
		{"truncated", `{"url": "http://127.0.0`, 0, false},
		{"zero port", `{"port": 0}`, 0, false},
		{"out of range", `{"port": 70000}`, 0, false},
		{"no port key", `{"url": "http://127.0.0.1:8766/"}`, 0, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			withRecord(t, tc.body)
			got, ok := serverJSONPort()
			if got != tc.want || ok != tc.ok {
				t.Errorf("serverJSONPort() = (%d, %v), want (%d, %v)", got, ok, tc.want, tc.ok)
			}
		})
	}
}

// The regression this guards: on a machine that already runs LanEx somewhere
// else, the user's server holds 8765 and the appliance is pushed to 8766 (WSL 2
// shares one network namespace across distros). A scan finds 8765 first and the
// launcher opens a window onto the wrong server. The appliance's own record is
// the only thing that knows which is ours, so it decides — and when it says the
// port is dead, that is an answer too, not a reason to go looking.
func TestFindRunningServerUsesTheRecord(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"service": "lanex", "alive": true}`))
	}))
	defer srv.Close()
	port, err := strconv.Atoi(srv.URL[strings.LastIndex(srv.URL, ":")+1:])
	if err != nil {
		t.Fatal(err)
	}

	withRecord(t, fmt.Sprintf(`{"port": %d}`, port))
	got, ok := findRunningServer()
	if !ok || got != port {
		t.Errorf("findRunningServer() = (%d, %v), want (%d, true)", got, ok, port)
	}

	// Same record, server gone: not running. Anything answering 8765..8771 now
	// belongs to somebody else.
	srv.Close()
	if got, ok := findRunningServer(); ok {
		t.Errorf("findRunningServer() = (%d, true) for a stale record, want not-found", got)
	}
}
