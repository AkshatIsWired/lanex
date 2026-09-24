# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Open the operating system's own file or folder picker.

On the Windows appliance the picker is Windows' own Explorer dialog, driven
through PowerShell from WSL; the chosen Windows paths come back translated to
WSL paths. On a Linux desktop it is zenity or kdialog. When none is available
the caller falls back to LanEx's built-in folder browser.

The call blocks until the person picks or cancels, so it must only run on a
request thread (the server is a ThreadingHTTPServer). Stdlib only; never raises.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from . import platform_env

_POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
_TIMEOUT = 900  # a person may take a while to find the folder

# The folder picker is the Vista+ IFileOpenDialog in folder mode (the same
# dialog Explorer uses); WinForms' FolderBrowserDialog on .NET Framework is the
# old tree view. Files use OpenFileDialog, which is already the modern dialog.
# A hidden top-most owner window keeps the dialog in front of the LanEx window.
_PS_SCRIPT = r'''
param([string]$Mode, [string]$Title, [string]$Start)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class LanexPicker {
  [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")] class FileOpenDialogRCW {}
  [ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IFileDialog {
    [PreserveSig] int Show(IntPtr parent);
    void SetFileTypes(uint c, IntPtr f); void SetFileTypeIndex(uint i); void GetFileTypeIndex(out uint i);
    void Advise(IntPtr p, out uint c); void Unadvise(uint c);
    void SetOptions(uint fos); void GetOptions(out uint fos);
    void SetDefaultFolder(IShellItem si); void SetFolder(IShellItem si);
    void GetFolder(out IShellItem si); void GetCurrentSelection(out IShellItem si);
    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string n);
    void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string n);
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string t);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string t);
    void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string t);
    void GetResult(out IShellItem si);
  }
  [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellItem {
    void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
    void GetParent(out IShellItem ppsi);
    void GetDisplayName(uint sigdn, [MarshalAs(UnmanagedType.LPWStr)] out string name);
  }
  [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
  static extern void SHCreateItemFromParsingName(string path, IntPtr pbc, ref Guid riid, out IShellItem item);
  public static string PickFolder(IntPtr owner, string title, string start) {
    var dlg = (IFileDialog)new FileOpenDialogRCW();
    dlg.SetOptions(0x20 | 0x40 | 0x800);   // PICKFOLDERS | FORCEFILESYSTEM | PATHMUSTEXIST
    if (!string.IsNullOrEmpty(title)) dlg.SetTitle(title);
    if (!string.IsNullOrEmpty(start)) {
      try {
        Guid iid = new Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE");
        IShellItem folder; SHCreateItemFromParsingName(start, IntPtr.Zero, ref iid, out folder);
        dlg.SetFolder(folder);
      } catch { }
    }
    if (dlg.Show(owner) != 0) return null;
    IShellItem item; dlg.GetResult(out item);
    string path; item.GetDisplayName(0x80058000, out path);   // SIGDN_FILESYSPATH
    return path;
  }
}
"@
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.StartPosition = "Manual"
$owner.Location = New-Object System.Drawing.Point(-32000, -32000)
$owner.Size = New-Object System.Drawing.Size(1, 1)
$owner.Show()
$owner.Activate()
try {
  if ($Mode -eq "files") {
    $d = New-Object System.Windows.Forms.OpenFileDialog
    $d.Multiselect = $true
    $d.Title = $Title
    if ($Start -and (Test-Path $Start)) { $d.InitialDirectory = $Start }
    if ($d.ShowDialog($owner) -eq "OK") { $d.FileNames | ForEach-Object { Write-Output $_ } }
  } else {
    $p = [LanexPicker]::PickFolder($owner.Handle, $Title, $Start)
    if ($p) { Write-Output $p }
  }
} finally { $owner.Close() }
'''


def _ps_quote(s: str) -> str:
    return "'" + (s or "").replace("'", "''") + "'"


def _windows_start(start: str) -> str:
    if not start:
        return ""
    win = platform_env.wsl_windows_path(start)
    return win or ""


def _pick_windows(mode: str, title: str, start: str) -> Optional[List[str]]:
    if not os.path.exists(_POWERSHELL):
        return None
    # -EncodedCommand sidesteps every quoting layer between WSL and PowerShell.
    body = "& {" + _PS_SCRIPT + "} " + " ".join(
        ["-Mode", _ps_quote(mode), "-Title", _ps_quote(title), "-Start", _ps_quote(_windows_start(start))])
    enc = base64.b64encode(body.encode("utf-16-le")).decode("ascii")
    try:
        out = subprocess.run(
            [_POWERSHELL, "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", enc],
            capture_output=True, timeout=_TIMEOUT, cwd="/mnt/c",
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    text = out.stdout.decode("utf-8", errors="replace").lstrip("﻿")
    paths = [platform_env.to_host_path(line.strip()) for line in text.splitlines() if line.strip()]
    return paths


def _pick_linux(mode: str, title: str, start: str) -> Optional[List[str]]:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return None
    start_dir = (start.rstrip("/") + "/") if start else ""
    if shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--title", title or "Choose"]
        if mode == "files":
            cmd += ["--multiple", "--separator", "\n"]
        else:
            cmd += ["--directory"]
        if start_dir:
            cmd += ["--filename", start_dir]
    elif shutil.which("kdialog"):
        if mode == "files":
            cmd = ["kdialog", "--getopenfilename", start_dir or ".", "--multiple", "--separate-output"]
        else:
            cmd = ["kdialog", "--getexistingdirectory", start_dir or "."]
        if title:
            cmd += ["--title", title]
    else:
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
    except Exception:
        return None
    if out.returncode not in (0, 1):   # 1 = cancelled
        return None
    return [line for line in (out.stdout or "").splitlines() if line.strip()]


def pick(mode: str = "folder", title: str = "", start: str = "") -> Dict[str, Any]:
    """``{"native": bool, "paths": [...]}``. ``native`` False means no system
    picker exists here and the caller should use the built-in browser; an
    empty ``paths`` with ``native`` True means the person cancelled."""
    mode = "files" if mode == "files" else "folder"
    if platform_env.is_wsl():
        got = _pick_windows(mode, title, start)
    else:
        got = _pick_linux(mode, title, start)
    if got is None:
        return {"native": False, "paths": []}
    return {"native": True, "paths": got}
