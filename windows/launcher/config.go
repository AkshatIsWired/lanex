// Copyright 2026 LanEx Contributors
// Licensed under the Apache License, Version 2.0.

package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
)

// Legacy installs used the fixed name. New Setup writes appliance.json beside
// the launcher so a foreign-name collision can use a distinct owned distro.
var distroName = "lanex"

type applianceConfig struct {
	Schema     int    `json:"schema"`
	InstallID  string `json:"installId"`
	DistroName string `json:"distroName"`
	SourceSHA  string `json:"sourceSha"`
	Manifest   string `json:"manifestHash"`
}

var (
	distroNamePattern = regexp.MustCompile(`^[A-Za-z0-9._-]{1,64}$`)
	uuidPattern       = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)
	shaPattern        = regexp.MustCompile(`^[0-9a-fA-F]{40}$`)
	hashPattern       = regexp.MustCompile(`^[0-9a-fA-F]{64}$`)
)

func parseApplianceConfig(raw []byte) (applianceConfig, bool) {
	var cfg applianceConfig
	if err := json.Unmarshal(raw, &cfg); err != nil || cfg.Schema != 1 ||
		!uuidPattern.MatchString(cfg.InstallID) ||
		!distroNamePattern.MatchString(cfg.DistroName) ||
		!shaPattern.MatchString(cfg.SourceSHA) || !hashPattern.MatchString(cfg.Manifest) {
		return applianceConfig{}, false
	}
	return cfg, true
}

func loadApplianceConfig() {
	exe, err := os.Executable()
	if err != nil {
		return
	}
	raw, err := os.ReadFile(filepath.Join(filepath.Dir(exe), "appliance.json"))
	if err != nil {
		return
	}
	if cfg, ok := parseApplianceConfig(raw); ok {
		distroName = cfg.DistroName
	} else {
		logf("appliance.json is malformed; refusing to use an untrusted distro name")
	}
}
