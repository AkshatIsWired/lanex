// Copyright 2026 LanEx Contributors
// Licensed under the Apache License, Version 2.0.

package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

// Legacy installs used the fixed name. New Setup writes appliance.json beside
// the launcher so a foreign-name collision can use a distinct owned distro.
var distroName = "lanex"
var activeConfig applianceConfig

type applianceConfig struct {
	Schema     int    `json:"schema"`
	InstallID  string `json:"installId"`
	OwnerSID   string `json:"ownerSid"`
	DistroName string `json:"distroName"`
	SourceSHA  string `json:"sourceSha"`
	Manifest   string `json:"manifestHash"`
}

type installerState struct {
	Schema       int    `json:"schema"`
	InstallID    string `json:"installId"`
	OwnerSID     string `json:"ownerSid"`
	ManifestHash string `json:"manifestHash"`
	Phase        string `json:"phase"`
	Source       struct {
		SHA string `json:"sha"`
	} `json:"source"`
	Appliance struct {
		Name       string `json:"name"`
		RegistryID string `json:"registryId"`
		BasePath   string `json:"basePath"`
	} `json:"appliance"`
}

var (
	distroNamePattern = regexp.MustCompile(`^[A-Za-z0-9._-]{1,64}$`)
	uuidPattern       = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)
	shaPattern        = regexp.MustCompile(`^[0-9a-fA-F]{40}$`)
	hashPattern       = regexp.MustCompile(`^[0-9a-fA-F]{64}$`)
	sidPattern        = regexp.MustCompile(`^S-1-[0-9]+(?:-[0-9]+)+$`)
	registryIDPattern = regexp.MustCompile(`^\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}$`)
)

func parseApplianceConfig(raw []byte) (applianceConfig, bool) {
	var cfg applianceConfig
	if err := json.Unmarshal(raw, &cfg); err != nil || cfg.Schema != 2 ||
		!uuidPattern.MatchString(cfg.InstallID) ||
		!sidPattern.MatchString(cfg.OwnerSID) ||
		!distroNamePattern.MatchString(cfg.DistroName) ||
		!shaPattern.MatchString(cfg.SourceSHA) || !hashPattern.MatchString(cfg.Manifest) {
		return applianceConfig{}, false
	}
	return cfg, true
}

func currentUserSID() (string, error) {
	user, err := windows.GetCurrentProcessToken().GetTokenUser()
	if err != nil {
		return "", err
	}
	return user.User.Sid.String(), nil
}

func statePath() string {
	return filepath.Join(os.Getenv("LOCALAPPDATA"), installDir, "installer-state.json")
}

func validateOwnedReadyState(cfg applianceConfig, raw []byte, ownerSID string) error {
	var state installerState
	if err := json.Unmarshal(raw, &state); err != nil {
		return fmt.Errorf("saved installer state is malformed: %w", err)
	}
	if state.Schema != 1 || state.Phase != "ready" {
		return fmt.Errorf("saved installer state is not ready")
	}
	if !strings.EqualFold(state.InstallID, cfg.InstallID) || state.OwnerSID != cfg.OwnerSID ||
		state.OwnerSID != ownerSID || !strings.EqualFold(state.ManifestHash, cfg.Manifest) ||
		!strings.EqualFold(state.Source.SHA, cfg.SourceSHA) ||
		!strings.EqualFold(state.Appliance.Name, cfg.DistroName) ||
		!registryIDPattern.MatchString(state.Appliance.RegistryID) || state.Appliance.BasePath == "" {
		return fmt.Errorf("saved installer state does not match this owned launcher and appliance")
	}
	return nil
}

func validateOwnedRegistration(raw []byte) error {
	var state installerState
	if err := json.Unmarshal(raw, &state); err != nil {
		return err
	}
	key, err := registry.OpenKey(registry.CURRENT_USER,
		`Software\Microsoft\Windows\CurrentVersion\Lxss\`+state.Appliance.RegistryID,
		registry.QUERY_VALUE)
	if err != nil {
		return fmt.Errorf("owned WSL registration is missing: %w", err)
	}
	defer key.Close()
	name, _, nameErr := key.GetStringValue("DistributionName")
	base, _, baseErr := key.GetStringValue("BasePath")
	if nameErr != nil || baseErr != nil || !strings.EqualFold(name, state.Appliance.Name) ||
		!strings.EqualFold(filepath.Clean(os.ExpandEnv(base)), filepath.Clean(os.ExpandEnv(state.Appliance.BasePath))) {
		return fmt.Errorf("owned WSL registration name/path no longer matches saved state")
	}
	return nil
}

func loadApplianceConfig() error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	raw, err := os.ReadFile(filepath.Join(filepath.Dir(exe), "appliance.json"))
	if err != nil {
		return fmt.Errorf("launcher identity is missing: %w", err)
	}
	cfg, ok := parseApplianceConfig(raw)
	if !ok {
		return fmt.Errorf("launcher identity is malformed")
	}
	ownerSID, err := currentUserSID()
	if err != nil {
		return fmt.Errorf("could not identify the current Windows user: %w", err)
	}
	stateRaw, err := os.ReadFile(statePath())
	if err != nil {
		return fmt.Errorf("saved installer state is missing: %w", err)
	}
	if err := validateOwnedReadyState(cfg, stateRaw, ownerSID); err != nil {
		return err
	}
	if err := validateOwnedRegistration(stateRaw); err != nil {
		return err
	}
	activeConfig = cfg
	distroName = cfg.DistroName
	return nil
}
