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
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
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
	var health struct {
		Service    string `json:"service"`
		Alive      bool   `json:"alive"`
		InstanceID string `json:"instanceId"`
		Source     struct {
			SHA          string `json:"sha"`
			ManifestHash string `json:"manifestHash"`
		} `json:"source"`
	}
	decoder := json.NewDecoder(io.LimitReader(resp.Body, 4096))
	if err := decoder.Decode(&health); err != nil {
		return false
	}
	var trailing any
	if decoder.Decode(&trailing) != io.EOF {
		return false
	}
	return health.Service == "lanex" && health.Alive &&
		strings.EqualFold(health.InstanceID, activeConfig.InstallID) &&
		strings.EqualFold(health.Source.SHA, activeConfig.SourceSHA) &&
		strings.EqualFold(health.Source.ManifestHash, activeConfig.Manifest)
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
	return 0, false
}

// serverRecordPath is the file LanEx writes on start and removes on a clean
// exit (lanex/cli.py), read over the \\wsl.localhost share. A variable so the
// tests can point it at a real temp file.
var serverRecordPath = func() string {
	return filepath.Join(`\\wsl.localhost\`+distroName, "home", appUser,
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
		Port       int    `json:"port"`
		InstanceID string `json:"instanceId"`
		Source     struct {
			SHA          string `json:"sha"`
			ManifestHash string `json:"manifestHash"`
		} `json:"source"`
	}
	if err := json.Unmarshal(raw, &rec); err != nil {
		return 0, false
	}
	if rec.Port <= 0 || rec.Port > 65535 ||
		!strings.EqualFold(rec.InstanceID, activeConfig.InstallID) ||
		!strings.EqualFold(rec.Source.SHA, activeConfig.SourceSHA) ||
		!strings.EqualFold(rec.Source.ManifestHash, activeConfig.Manifest) {
		return 0, false
	}
	return rec.Port, true
}

// waitForHealth polls until the server answers, the deadline passes, or *done*
// closes (the server process died — no point probing a corpse).
func waitForHealth(timeout time.Duration, done <-chan struct{}) (int, bool) {
	deadline := time.Now().Add(timeout)
	for {
		// Only the identity-bound record can select a port. A scan cannot
		// distinguish this appliance from a LanEx server in another distro.
		if port, ok := serverJSONPort(); ok && healthyAt(healthURL(port)) {
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
