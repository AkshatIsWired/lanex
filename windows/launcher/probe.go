// Copyright 2026 LanEx Contributors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0

// Finding the LanEx server: which port it landed on, and whether it is up.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

// LanEx asks for 8765 and walks upwards until a bind succeeds
// (app.py find_free_port: preferred..preferred+6), so on a machine where
// something else already owns 8765 the server is legitimately on 8766 or above.
// Probing only 8765 is why naive launchers report "LanEx failed to start" while
// LanEx is running happily one port over.
const (
	basePort = 8765
	portSpan = 7

	// How long a launch waits for the appliance to write ~/.lanex/server.json
	// before it will believe a port it merely found by scanning. See
	// scanForServer for why the scan is a last resort rather than the default;
	// without this window it wins the race on every cold start, because writing
	// the record takes a second or two and a stranger's server is answering the
	// whole time. Comfortably longer than the write, far short of
	// startupTimeout.
	recordGrace = 20 * time.Second
)

func candidatePorts() []int {
	ports := make([]int, 0, portSpan)
	for i := 0; i < portSpan; i++ {
		ports = append(ports, basePort+i)
	}
	return ports
}

func healthURL(port int) string {
	return fmt.Sprintf("http://127.0.0.1:%d/api/health", port)
}

// Short timeout on purpose: this runs every 500 ms while the user waits, against
// loopback. A slow answer is indistinguishable from no answer here — we just
// probe again.
var probeClient = &http.Client{Timeout: 1500 * time.Millisecond}

// healthyAt reports whether *url* is answered by a live LanEx server.
func healthyAt(url string) bool {
	resp, err := probeClient.Get(url)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return false
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, 4096))
	// Confirm it is actually LanEx and not some other dev server happy to answer
	// 200 on 8765: routes.py's h_health replies {"service": "lanex", ...}.
	return err == nil && bytes.Contains(body, []byte(`"lanex"`))
}

// findRunningServer returns the port of a live LanEx server, if there is one.
//
// The appliance's own record answers this whenever it exists — including when
// it says "nothing is running". Falling through to a scan after a record that
// did not check out is what would point the window at somebody else's server.
func findRunningServer() (int, bool) {
	if port, ok := serverJSONPort(); ok {
		return port, healthyAt(healthURL(port))
	}
	return scanForServer()
}

// scanForServer probes 8765..8771 for anything answering like LanEx.
//
// A LAST RESORT, not the normal path. It cannot tell our appliance apart from a
// LanEx the user runs themselves — same endpoint, same {"service": "lanex"}
// body — and it does not need bad luck to get it wrong: WSL 2 puts every distro
// on one shared network namespace, so a LanEx already running in the user's own
// distro holds 8765, the appliance's own server is pushed to 8766 by
// find_free_port, and scanning upwards finds theirs first. Verified on a machine
// with both: user's LanEx on 8765, appliance on 8766, both returning 200.
//
// It stays because an appliance older than the server.json feature writes no
// record at all, and there a live wrong-server beats a launcher that gives up.
// The next Repair upgrades that away.
func scanForServer() (int, bool) {
	for _, port := range candidatePorts() {
		if healthyAt(healthURL(port)) {
			return port, true
		}
	}
	return 0, false
}

// serverRecordPath is the file LanEx writes on start and removes on a clean
// exit (lanex/cli.py), read over the \\wsl.localhost share. A variable so the
// tests can point it at a real temp file.
var serverRecordPath = func() string {
	return filepath.Join(`\\wsl.localhost\`+distroName, "home", distroName,
		".lanex", "server.json")
}

// serverJSONPort reads the port the appliance recorded for itself.
//
// This is the only signal that is actually ABOUT our appliance rather than
// about whatever answered a loopback port, which is why the callers treat it as
// authoritative. It is still validated: a truncated or half-written file parses
// to nothing, and a stale one (hard kill, no clean shutdown) is caught by the
// health check the caller runs on the value.
func serverJSONPort() (int, bool) {
	raw, err := os.ReadFile(serverRecordPath())
	if err != nil {
		return 0, false
	}
	var rec struct {
		Port int `json:"port"`
	}
	if err := json.Unmarshal(raw, &rec); err != nil {
		return 0, false
	}
	if rec.Port <= 0 || rec.Port > 65535 {
		return 0, false
	}
	return rec.Port, true
}

// waitForHealth polls until the server answers, the deadline passes, or *done*
// closes (the server process died — no point probing a corpse).
func waitForHealth(timeout time.Duration, done <-chan struct{}) (int, bool) {
	deadline := time.Now().Add(timeout)
	scanAfter := time.Now().Add(recordGrace)
	for {
		// The record first and, for the first recordGrace, ONLY the record. We
		// have just started the server ourselves; it needs a moment to bind a
		// port and write the file. If the scan were allowed to answer during
		// that moment it would hand back a LanEx running in the user's own
		// distro — instantly, on the very first poll, every time.
		if port, ok := serverJSONPort(); ok && healthyAt(healthURL(port)) {
			return port, true
		}
		if time.Now().After(scanAfter) {
			if port, ok := scanForServer(); ok {
				return port, true
			}
		}
		if time.Now().After(deadline) {
			return 0, false
		}
		select {
		case <-done:
			return 0, false
		case <-time.After(probeInterval):
		}
	}
}
