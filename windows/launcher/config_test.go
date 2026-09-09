// Copyright 2026 LanEx Contributors
// Licensed under the Apache License, Version 2.0.

package main

import "testing"

func TestParseApplianceConfig(t *testing.T) {
	raw := []byte(`{"schema":2,"installId":"11111111-2222-3333-4444-555555555555","ownerSid":"S-1-5-21-1000-1000-1000-1001","distroName":"lanex-11111111","sourceSha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","manifestHash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}`)
	cfg, ok := parseApplianceConfig(raw)
	if !ok || cfg.DistroName != "lanex-11111111" {
		t.Fatalf("valid config rejected: %#v ok=%v", cfg, ok)
	}
}

func TestParseApplianceConfigRejectsCommandText(t *testing.T) {
	raw := []byte(`{"schema":2,"installId":"11111111-2222-3333-4444-555555555555","ownerSid":"S-1-5-21-1000-1000-1000-1001","distroName":"lanex & wsl --shutdown","sourceSha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","manifestHash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}`)
	if _, ok := parseApplianceConfig(raw); ok {
		t.Fatal("unsafe distro name accepted")
	}
}

func TestValidateOwnedReadyState(t *testing.T) {
	cfg := applianceConfig{Schema: 2, InstallID: "11111111-2222-3333-4444-555555555555",
		OwnerSID: "S-1-5-21-1000-1000-1000-1001", DistroName: "lanex-11111111",
		SourceSHA: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		Manifest:  "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
	raw := []byte(`{"schema":1,"installId":"11111111-2222-3333-4444-555555555555","ownerSid":"S-1-5-21-1000-1000-1000-1001","manifestHash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","source":{"sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"phase":"ready","appliance":{"name":"lanex-11111111","registryId":"{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}","basePath":"C:\\owned"}}`)
	if err := validateOwnedReadyState(cfg, raw, cfg.OwnerSID); err != nil {
		t.Fatalf("valid owner state rejected: %v", err)
	}
	if err := validateOwnedReadyState(cfg, raw, "S-1-5-21-9999"); err == nil {
		t.Fatal("different Windows user accepted")
	}
}

func TestMutexIsScopedToOwnerAndAppliance(t *testing.T) {
	a := applianceConfig{InstallID: "11111111-2222-3333-4444-555555555555", OwnerSID: "S-1-5-21-1", DistroName: "lanex-a"}
	b := a
	b.OwnerSID = "S-1-5-21-2"
	if scopedMutexName(a) == scopedMutexName(b) {
		t.Fatal("different Windows users share a launcher mutex")
	}
}
