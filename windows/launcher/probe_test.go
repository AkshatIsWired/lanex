// Copyright 2026 LanEx Contributors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0

package main

import (
	"net/http"
	"net/http/httptest"
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
