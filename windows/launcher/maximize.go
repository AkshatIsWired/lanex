// Copyright 2026 LanEx Contributors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0

package main

// Maximizing the app window after the browser has drawn it.
//
// `--start-maximized` is not enough on its own: Chromium applies it to normal
// browser windows, but an `--app` window opens at the placement saved in the
// profile (`app_window_placement` in Default\Preferences), which the first
// launch records as the --window-size bounds. So the window came up 1440x900
// on every launch, whatever the flags said. The launcher fixes it from the
// outside instead: find the new window and ask Windows to maximize it. Once
// it has been closed maximized, the profile remembers that too.

import (
	"fmt"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	user32            = windows.NewLazySystemDLL("user32.dll")
	procEnumWindows   = user32.NewProc("EnumWindows")
	procGetClassName  = user32.NewProc("GetClassNameW")
	procGetWindowText = user32.NewProc("GetWindowTextW")
	procIsWindowVis   = user32.NewProc("IsWindowVisible")
	procIsZoomed      = user32.NewProc("IsZoomed")
	procShowWindow    = user32.NewProc("ShowWindow")
)

const (
	swMaximize = 3
	// Every Chromium-family top-level window (Edge, Chrome) uses this class.
	chromiumWindowClass = "Chrome_WidgetWin_1"
	// The browser normally shows the window well under a second after spawn;
	// a cold Edge on a slow disk can take several.
	maximizeTimeout = 15 * time.Second
	maximizePoll    = 100 * time.Millisecond
)

// enumMu serializes EnumWindows so the single callback below can collect into
// one shared map. The callback is created once: syscall.NewCallback slots are
// never freed, and the poll loop would otherwise use one per tick.
var (
	enumMu    sync.Mutex
	enumFound map[windows.HWND]string
	enumCB    = syscall.NewCallback(func(h windows.HWND, _ uintptr) uintptr {
		if vis, _, _ := procIsWindowVis.Call(uintptr(h)); vis == 0 {
			return 1
		}
		cls := make([]uint16, 64)
		n, _, _ := procGetClassName.Call(uintptr(h), uintptr(unsafe.Pointer(&cls[0])), uintptr(len(cls)))
		if windows.UTF16ToString(cls[:n]) != chromiumWindowClass {
			return 1
		}
		title := make([]uint16, 256)
		n, _, _ = procGetWindowText.Call(uintptr(h), uintptr(unsafe.Pointer(&title[0])), uintptr(len(title)))
		enumFound[h] = windows.UTF16ToString(title[:n])
		return 1
	})
)

// chromiumWindows lists the visible top-level Chromium windows by title.
func chromiumWindows() map[windows.HWND]string {
	enumMu.Lock()
	defer enumMu.Unlock()
	enumFound = map[windows.HWND]string{}
	procEnumWindows.Call(enumCB, 0)
	return enumFound
}

// isAppWindowTitle reports whether *title* is the LanEx app window: the page
// title once loaded ("LanEx: ..."), or the bare origin Chromium shows while
// the page is still loading.
func isAppWindowTitle(title string, port int) bool {
	return strings.HasPrefix(title, appName) ||
		strings.Contains(title, fmt.Sprintf("127.0.0.1:%d", port))
}

// maximizeNewAppWindow waits for a LanEx window that was not in *before* and
// maximizes it. Runs in the background; giving up just leaves the window at
// the browser's own size.
func maximizeNewAppWindow(before map[windows.HWND]string, port int) {
	deadline := time.Now().Add(maximizeTimeout)
	for time.Now().Before(deadline) {
		for h, title := range chromiumWindows() {
			if _, old := before[h]; old || !isAppWindowTitle(title, port) {
				continue
			}
			if zoomed, _, _ := procIsZoomed.Call(uintptr(h)); zoomed == 0 {
				procShowWindow.Call(uintptr(h), swMaximize)
			}
			return
		}
		time.Sleep(maximizePoll)
	}
	logf("app window for port %d did not appear within %s; left unmaximized", port, maximizeTimeout)
}
