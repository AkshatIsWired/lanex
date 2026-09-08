// Copyright 2026 LanEx Contributors
// Licensed under the Apache License, Version 2.0.

package main

import "testing"

func TestParseApplianceConfig(t *testing.T) {
	raw := []byte(`{"schema":1,"installId":"11111111-2222-3333-4444-555555555555","distroName":"lanex-11111111","sourceSha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","manifestHash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}`)
	cfg, ok := parseApplianceConfig(raw)
	if !ok || cfg.DistroName != "lanex-11111111" {
		t.Fatalf("valid config rejected: %#v ok=%v", cfg, ok)
	}
}

func TestParseApplianceConfigRejectsCommandText(t *testing.T) {
	raw := []byte(`{"schema":1,"installId":"11111111-2222-3333-4444-555555555555","distroName":"lanex & wsl --shutdown","sourceSha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","manifestHash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}`)
	if _, ok := parseApplianceConfig(raw); ok {
		t.Fatal("unsafe distro name accepted")
	}
}
