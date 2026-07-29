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
func findRunningServer() (int, bool) {
	if port, ok := serverJSONPort(); ok && healthyAt(healthURL(port)) {
		return port, true
	}
	for _, port := range candidatePorts() {
		if healthyAt(healthURL(port)) {
			return port, true
		}
	}
	return 0, false
}

// serverJSONPort reads the port LanEx recorded in ~/.lanex/server.json inside the
// appliance, over the \\wsl.localhost share.
//
// Purely an optimisation — one hit instead of up to seven probes — and treated
// as untrusted: an older LanEx in the appliance has no such file, and a stale
// file (hard kill, no clean shutdown) is filtered out by the health check the
// caller runs on the value. The port scan stays the source of truth.
func serverJSONPort() (int, bool) {
	path := filepath.Join(`\\wsl.localhost\`+distroName, "home", distroName,
		".lanex", "server.json")
	raw, err := os.ReadFile(path)
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
	for {
		if port, ok := findRunningServer(); ok {
			return port, true
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
