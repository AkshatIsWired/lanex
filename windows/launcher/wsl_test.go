// Copyright 2026 LanEx Contributors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0

package main

import (
	"reflect"
	"testing"
)

// utf16le is the test's own encoder, so a bug in decodeUTF16LE cannot hide by
// being symmetric with the code under test.
func utf16le(s string) []byte {
	out := make([]byte, 0, len(s)*2)
	for _, r := range s {
		out = append(out, byte(r), byte(r>>8))
	}
	return out
}

// The whole point of these tests: `wsl -l -q` writes UTF-16LE, and mis-decoding
// it makes a healthy install look missing. CI cannot run WSL (no nested virt on
// GitHub runners), so this parser is the one piece we can and must verify there.
func TestDecodeDistroList(t *testing.T) {
	cases := []struct {
		name string
		raw  []byte
		want []string
	}{
		{"utf16 no bom", utf16le("Ubuntu\r\nlanex\r\n"), []string{"Ubuntu", "lanex"}},
		{"utf16 with bom", append([]byte{0xFF, 0xFE}, utf16le("lanex\r\n")...), []string{"lanex"}},
		{"utf8 (WSL_UTF8=1)", []byte("Ubuntu\r\nlanex\r\n"), []string{"Ubuntu", "lanex"}},
		{"utf8 with bom", append([]byte{0xEF, 0xBB, 0xBF}, "lanex\r\n"...), []string{"lanex"}},
		{"blank lines dropped", utf16le("\r\nlanex\r\n\r\n"), []string{"lanex"}},
		{"empty", nil, nil},
		// wsl.exe has been seen to cut a UTF-16 stream mid-unit on a pipe close;
		// a dangling byte must not panic or corrupt the last name.
		{"odd length", utf16le("lanex\r\n")[:13], []string{"lanex"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := decodeDistroList(tc.raw); !reflect.DeepEqual(got, tc.want) {
				t.Errorf("decodeDistroList(%q) = %q, want %q", tc.raw, got, tc.want)
			}
		})
	}
}

func TestDecodeConsoleUnicode(t *testing.T) {
	// A distro list can hold non-ASCII names; the NUL-sniffing heuristic must not
	// mangle real UTF-8.
	if got := decodeConsole([]byte("Ubuntu-Ärger\n")); got != "Ubuntu-Ärger\n" {
		t.Errorf("utf8 passthrough: got %q", got)
	}
	if got := decodeConsole(utf16le("Ubuntu-Ärger\n")); got != "Ubuntu-Ärger\n" {
		t.Errorf("utf16 decode: got %q", got)
	}
}

// distroPresent's comparison must be case-insensitive: WSL preserves the name we
// registered, but users (and `wsl --import` typos) do not.
func TestDistroNameMatching(t *testing.T) {
	names := decodeDistroList(utf16le("docker-desktop\r\nLanEx\r\nUbuntu-24.04\r\n"))
	found := false
	for _, n := range names {
		if equalFoldASCII(n, distroName) {
			found = true
		}
	}
	if !found {
		t.Errorf("%q did not match %q case-insensitively", names, distroName)
	}
}

// equalFoldASCII mirrors what distroPresent does via strings.EqualFold, kept
// separate so this test documents the requirement rather than the call.
func equalFoldASCII(a, b string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := 0; i < len(a); i++ {
		ca, cb := a[i], b[i]
		if 'A' <= ca && ca <= 'Z' {
			ca += 'a' - 'A'
		}
		if 'A' <= cb && cb <= 'Z' {
			cb += 'a' - 'A'
		}
		if ca != cb {
			return false
		}
	}
	return true
}
