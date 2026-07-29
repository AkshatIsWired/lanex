; Copyright 2026 LanEx Contributors
;
; Licensed under the Apache License, Version 2.0 (the "License");
; you may not use this file except in compliance with the License.
; You may obtain a copy of the License at
;
;      http://www.apache.org/licenses/LICENSE-2.0
;
; =============================================================================
;  lanex.iss — builds LanEx-Setup.exe, the public face of LanEx on Windows.
; =============================================================================
;
;  THE PROMISE THIS FILE KEEPS
;  A person who does not know what a terminal is downloads one exe, clicks
;  Next -> Next -> Finish, and gets a Start-menu app called LanEx. They never
;  see WSL, Ubuntu, bash, sudo, a password prompt, or Docker. Uninstalling from
;  Windows Settings removes every trace. Their own WSL distros, if they have
;  any, are never touched.
;
;  HOW
;  LanEx and every EDA tool it drives (OpenROAD, Yosys, Magic, KLayout) are
;  Linux programs; a native Windows port is not possible. So Setup imports a
;  PRIVATE Ubuntu distro — an appliance — with `wsl --import`, exactly the
;  pattern Docker Desktop, Rancher Desktop and Podman Desktop use:
;
;    * `wsl --import` means NO Microsoft Store dependency and NO Ubuntu
;      first-run screen asking for a username and password.
;    * A distro of our own means the user's existing Ubuntu (and its files) is
;      never read, written, upgraded, or even listed by us for anything other
;      than checking our own name.
;    * Uninstall is `wsl --unregister lanex` plus deleting one folder. Total,
;      clean, and provable — which is what makes the promise above trustworthy.
;
;  THE FOUR PIECES
;    LanEx.exe        ../launcher    starts the appliance, sits in the tray
;    provision.sh     ../provision   turns the imported distro into the appliance
;    lanex.iss        (this file)    preflight, WSL, download, import, shortcuts
;    docs/INSTALL.md                 what to do when one of them says no
;
;  BUILD
;    iscc /DAppVersion=1.2.3 /DLauncherExe=..\launcher\LanEx.exe lanex.iss
;  Requires Inno Setup 6.3+ (for ArchitecturesAllowed=x64compatible) — see
;  .github/workflows/windows-installer.yml.

#define AppName        "LanEx"
#ifndef AppVersion
  #define AppVersion   "1.0.0"
#endif
#define AppPublisher   "LanEx Contributors"
#define AppURL         "https://github.com/AkshatIsWired/lanex"
#define RepoRoot       "..\..\"
#ifndef LauncherExe
  #define LauncherExe  "..\launcher\LanEx.exe"
#endif
#define IconFile       "..\launcher\assets\lanex.ico"

; The appliance's identity. Same three strings in windows/provision/provision.sh
; and windows/launcher/main.go — change one, change all three.
#define DistroName     "lanex"
#define AppUser        "lanex"
#define DataDirName    "LanEx"

; Ubuntu 24.04 LTS WSL image, pinned by URL *and* SHA256.
;
; The URL and hash come from Microsoft's own WSL distribution manifest
; (https://raw.githubusercontent.com/microsoft/WSL/master/distributions/DistributionInfo.json)
; — the exact image `wsl --install -d Ubuntu-24.04 --web-download` would fetch,
; published by Canonical on releases.ubuntu.com. Pinning both means a swapped
; file can never be imported, and the weekly `rootfs-pin` CI job re-reads that
; manifest and fails when Canonical ships a new point release, so the pin is
; updated on purpose rather than drifting silently.
;
; 24.04 (not 26.04) deliberately: it is the release LibreLane and LanEx's own
; scripts/install.sh are tested against.
#define RootfsUrl      "https://releases.ubuntu.com/24.04.4/ubuntu-24.04.4-wsl-amd64.wsl"
#define RootfsSha256   "9b2f7730dc68227dd04a9f3e5eab86ad85caf556b8606ad94f1f29ff5c4fd3f5"
#define RootfsFile     "ubuntu-24.04.4-wsl-amd64.wsl"
#define RootfsSizeMB   "373"

; Space needed on the %LOCALAPPDATA% volume: the imported distro (~2 GB after
; provisioning) plus headroom for the ~3 GB LibreLane image the Tools tab pulls
; on first launch, plus run output.
#define MinFreeGB      10

[Setup]
; NEVER change AppId: it is the identity Windows uses to find the previous
; install (upgrade in place) and the uninstall entry in Settings.
AppId={{B7E9D0F4-3C2A-4B7E-9F51-6D0A8C4E21B3}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
LicenseFile={#RepoRoot}LICENSE
OutputBaseFilename=LanEx-Setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\LanEx.exe
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Admin: turning the WSL feature on is a machine-wide change. This is also why
; a standard user cannot install LanEx (documented in docs/INSTALL.md) — and why
; the person who runs Setup must be the person who will USE LanEx: WSL registers
; distros per user, so {localappdata} below has to be their profile.
PrivilegesRequired=admin
; WSL 2 is 64-bit only. x64compatible also covers ARM64 running x64 code, but
; the launcher is x64 (see windows/launcher/wsl.go) so the appliance is too.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; WSL 2 needs Windows 10 2004 (build 19041). Enforced here so the friendly
; message below is the first thing an unsupported machine sees.
MinVersion=10.0.19041
; Refuse to install over a running LanEx — the mutex the launcher holds
; (windows/launcher/main.go). Inno asks the user to close it first, which is far
; better than importing over a distro that is mid-run.
AppMutex=Global\LanExLauncher
SetupMutex=LanExSetupMutex
; The wizard is Welcome -> License -> Tasks -> progress -> Finish. Everything
; else is hidden on purpose: an appliance has no install directory worth
; choosing and no components to pick, and every extra page is a page our target
; user can get stuck on.
DisableWelcomePage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
; The download is ~{#RootfsSizeMB} MB, so the exe itself stays small.
OutputDir=.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
; Inno's stock text for an unsupported Windows version is generic; ours names
; the version and the reason.
WindowsVersionNotSupported=LanEx needs Windows 10 version 2004 (build 19041) or newer, because it runs on WSL 2. Windows 11 is recommended.
; The wizard's own words, in the language of the person we are installing for.
WelcomeLabel2=This will install [name/ver] on your computer.%n%nLanEx sets up its own private, self-contained environment — it will not change or touch any other software on your PC, and uninstalling removes every trace.%n%nSetup needs to download about {#RootfsSizeMB} MB and takes a few minutes.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#LauncherExe}"; DestDir: "{app}"; DestName: "LanEx.exe"; Flags: ignoreversion
Source: "{#IconFile}"; DestDir: "{app}"; DestName: "lanex.ico"; Flags: ignoreversion
; provision.sh is never installed: it runs once, inside the distro, from {tmp}.
; dontcopy + ExtractTemporaryFile is what lets PrepareToInstall use it before
; the file-copy step has happened at all.
Source: "..\provision\provision.sh"; Flags: dontcopy

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\LanEx.exe"; IconFilename: "{app}\lanex.ico"
; A shortcut straight into the appliance's home directory. Small feature, large
; payoff: it proves to the user that their designs are ordinary files on their
; own PC, not something sealed inside a black box.
Name: "{group}\{#AppName} Project Files"; Filename: "\\wsl.localhost\{#DistroName}\home\{#AppUser}"; IconFilename: "{app}\lanex.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\LanEx.exe"; IconFilename: "{app}\lanex.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\LanEx.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent; Check: InstallCompleted

[Code]
var
  // Set in InitializeSetup, read in PrepareToInstall.
  RepairExisting: Boolean;   // a lanex distro is already there: keep its data
  RemoveExisting: Boolean;   // ...or wipe it and import a fresh one
  // True when Setup stopped early to reboot for WSL; suppresses the "Launch
  // LanEx" checkbox, because nothing has been provisioned yet.
  WslPending: Boolean;

// ---------------------------------------------------------------- locations --

// Everything Setup creates outside {app} lives under one directory, so the
// uninstaller can remove it with a single DelTree and the "no trace" promise is
// one line of code rather than a list.
//
// %LOCALAPPDATA% (per user) is not a choice: `wsl --import` registers the distro
// under HKCU for the user who runs it, so a machine-wide location would be a lie.
function AppDataRoot: String;
begin
  Result := ExpandConstant('{localappdata}\{#DataDirName}');
end;

function DistroDir: String;  begin Result := AppDataRoot + '\distro'; end;
function CacheDir: String;   begin Result := AppDataRoot + '\cache';  end;
function LogDir: String;     begin Result := AppDataRoot + '\logs';   end;
function LogFile: String;    begin Result := LogDir + '\install.log'; end;
function RootfsPath: String; begin Result := CacheDir + '\{#RootfsFile}'; end;

function WslExe: String;
begin
  // {sys} is the real System32 even from a 32-bit process; wsl.exe does not
  // exist under SysWOW64, so never rely on PATH resolution here.
  Result := ExpandConstant('{sys}\wsl.exe');
end;

// ------------------------------------------------------------------- helpers --

procedure LogLine(const S: String);
begin
  ForceDirectories(LogDir);
  // Append, so this interleaves correctly with the command output that cmd.exe
  // redirects into the same file (see RunLogged).
  SaveStringToFile(LogFile, S + #13#10, True);
end;

procedure SetStatus(const S: String);
begin
  // The one progress surface the user sees during the slow parts. Without it a
  // five-minute provision looks like a hang.
  if WizardForm <> nil then
  begin
    WizardForm.StatusLabel.Caption := S;
    WizardForm.StatusLabel.Update;
  end;
  LogLine('--- ' + S);
end;

// StripNulls turns a UTF-16LE byte stream that was loaded as bytes into
// something comparable.
//
// This is the single most common bug in Windows code that talks to WSL:
// `wsl -l -q` writes UTF-16LE, so a naive read yields "l\0a\0n\0e\0x\0", the
// name comparison fails, and a perfectly healthy install is declared missing.
// We ask for UTF-8 (WSL_UTF8=1) *and* strip NULs, because older WSL builds
// ignore that variable.
function StripNulls(const S: String): String;
var
  I: Integer;
begin
  Result := '';
  for I := 1 to Length(S) do
    if (S[I] <> #0) and (S[I] <> #$FEFF) then
      Result := Result + S[I];
end;

// PowerShellCapture runs a snippet and returns everything it printed.
// Inno's Exec cannot capture output, hence the temp file. PowerShell rather than
// cmd because the facts we need (HypervisorPresent, an optional feature's state)
// have no plain-command equivalent.
function PowerShellCapture(const Snippet: String; var Output: String): Boolean;
var
  OutFile, Params: String;
  Raw: AnsiString;
  Code: Integer;
begin
  Output := '';
  OutFile := ExpandConstant('{tmp}\ps-capture.txt');
  DeleteFile(OutFile);
  // *>&1 folds error/warning streams in so a failure leaves a message rather
  // than an empty file. -Encoding ascii keeps the result BOM-free.
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "& { '
    + Snippet + ' } *>&1 | Out-File -LiteralPath ''' + OutFile + ''' -Encoding ascii"';
  Result := Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, Code);
  if FileExists(OutFile) and LoadStringFromFile(OutFile, Raw) then
    Output := Trim(StripNulls(String(Raw)));
end;

// RunLogged runs a command with its output appended to install.log.
// The nested-quote shape (/C ""prog" args >> "log"") is cmd's documented rule
// for a command line whose program path is quoted.
function RunLogged(const FileName, Params: String; var ResultCode: Integer): Boolean;
begin
  ForceDirectories(LogDir);
  LogLine('$ ' + FileName + ' ' + Params);
  Result := Exec(ExpandConstant('{cmd}'),
    '/C ""' + FileName + '" ' + Params + ' >> "' + LogFile + '" 2>&1"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

// LogTail returns the last Count lines of install.log, for failure dialogs: the
// user should be able to read (or paste into an issue) what actually broke
// without hunting for a file.
function LogTail(Count: Integer): String;
var
  Lines: TArrayOfString;
  I, First: Integer;
begin
  Result := '';
  if not LoadStringsFromFile(LogFile, Lines) then
    Exit;
  First := GetArrayLength(Lines) - Count;
  if First < 0 then
    First := 0;
  for I := First to GetArrayLength(Lines) - 1 do
    Result := Result + StripNulls(Lines[I]) + #13#10;
end;

// WindowsToWslPath converts C:\dir\file to /mnt/c/dir/file — how the appliance
// sees a file on the Windows drive (automount is on by default, and
// provision.sh's wsl.conf pins it on).
function WindowsToWslPath(const WinPath: String): String;
var
  S: String;
begin
  S := WinPath;
  StringChangeEx(S, '\', '/', True);
  if (Length(S) >= 2) and (S[2] = ':') then
    S := '/mnt/' + Lowercase(Copy(S, 1, 1)) + Copy(S, 3, Length(S) - 2);
  Result := S;
end;

// --------------------------------------------------------------- WSL queries --

// ListedDistros returns the output of `wsl -l -q`, NUL-stripped.
function ListedDistros: String;
var
  Output: String;
begin
  // $env:WSL_UTF8 makes modern wsl.exe emit UTF-8; StripNulls in the capture
  // helper covers the builds that ignore it.
  PowerShellCapture('$env:WSL_UTF8=''1''; & "' + WslExe + '" -l -q', Output);
  Result := Output;
end;

// DistroExists reports whether OUR distro is registered — by EXACT name, so a
// user's own "lanex-experiments" is never mistaken for ours, and never touched.
// Whole-line comparison (not a substring search) is the load-bearing detail.
function DistroExists: Boolean;
var
  Text, Line: String;
  P: Integer;
begin
  Result := False;
  Text := ListedDistros + #10;
  // Hand-rolled line split: Inno's StringSplit helpers are 6.3-only, and this
  // parser has to work on whatever version a contributor has installed.
  repeat
    P := Pos(#10, Text);
    if P = 0 then
      Break;      // cannot happen (a #10 is appended above), but never loop forever
    Line := Trim(Copy(Text, 1, P - 1));
    Text := Copy(Text, P + 1, Length(Text) - P);
    if CompareText(Line, '{#DistroName}') = 0 then
    begin
      Result := True;
      Exit;
    end;
  until Length(Text) = 0;
end;

function WslUsable: Boolean;
var
  Code: Integer;
begin
  // --status exits 0 only when the WSL feature AND a kernel are in place, which
  // is exactly the precondition for --import.
  Result := Exec(WslExe, '--status', '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

// ------------------------------------------------------------------ preflight --

// VirtualizationBlocked detects the #1 real-world WSL failure: CPU
// virtualization switched off in BIOS/UEFI.
//
// The logic is deliberately asymmetric. No hypervisor running is NORMAL on a PC
// that has never had WSL — Windows only starts one once the platform feature is
// enabled. It is a problem only when the feature IS enabled and Windows still
// has no hypervisor: that combination means Windows tried and the CPU said no.
// Anything we cannot determine is treated as fine — a false block would stop an
// install that would have worked.
function VirtualizationBlocked: Boolean;
var
  Hypervisor, Feature: String;
begin
  Result := False;
  if not PowerShellCapture('(Get-CimInstance Win32_ComputerSystem).HypervisorPresent',
                           Hypervisor) then
    Exit;
  if Pos('true', Lowercase(Hypervisor)) > 0 then
    Exit;
  if not PowerShellCapture(
      '(Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform).State',
      Feature) then
    Exit;
  // 'Disabled' does not contain 'enabled', so this substring test is safe.
  Result := Pos('enabled', Lowercase(Feature)) > 0;
end;

function EnoughDiskSpace(var FreeGB: Integer): Boolean;
var
  FreeMB, TotalMB: Cardinal;
begin
  FreeGB := 0;
  // Unknown free space must not block the install; only a definite shortfall does.
  if not GetSpaceOnDisk(ExpandConstant('{localappdata}'), True, FreeMB, TotalMB) then
  begin
    Result := True;
    Exit;
  end;
  FreeGB := FreeMB div 1024;
  Result := FreeGB >= {#MinFreeGB};
end;

function IsResumeRun: Boolean;
begin
  // Set by the RunOnce entry we write before the one possible restart.
  Result := ExpandConstant('{param:RESUME|0}') = '1';
end;

procedure OpenHelp(const Anchor: String);
var
  Code: Integer;
begin
  ShellExec('open', '{#AppURL}/blob/main/docs/INSTALL.md' + Anchor, '', '',
            SW_SHOWNORMAL, ewNoWait, Code);
end;

function InitializeSetup(): Boolean;
var
  FreeGB: Integer;
  Choice: Integer;
begin
  Result := True;
  RepairExisting := False;
  RemoveExisting := False;
  WslPending := False;

  // 1. Virtualization off in BIOS. Checked first because it is unfixable from
  //    inside Windows and there is no point downloading 373 MB before it.
  if VirtualizationBlocked then
  begin
    if MsgBox('LanEx cannot run because your computer''s virtualization feature '
      + 'is switched off.' + #13#10#13#10
      + 'It is a one-time setting in your PC''s BIOS/UEFI screen, not something '
      + 'Windows can change. The LanEx install guide has step-by-step '
      + 'instructions, including the key to press for common PC brands.'
      + #13#10#13#10 + 'Open the instructions now?',
      mbError, MB_YESNO) = IDYES then
      OpenHelp('#enable-virtualization');
    Result := False;
    Exit;
  end;

  // 2. Disk space, on the volume that will hold the distro.
  if not EnoughDiskSpace(FreeGB) then
  begin
    MsgBox('LanEx needs at least {#MinFreeGB} GB free on your Windows drive, and '
      + 'there is only ' + IntToStr(FreeGB) + ' GB.' + #13#10#13#10
      + 'That covers LanEx''s environment plus the chip-design toolchain it '
      + 'downloads on first launch. Please free some space and run Setup again.',
      mbError, MB_OK);
    Result := False;
    Exit;
  end;

  // 3. An existing appliance. NOTHING here can affect any other distro: the
  //    only name we ever act on is our own.
  if DistroExists then
  begin
    if IsResumeRun then
    begin
      // Unattended continuation after the reboot — never prompt; provisioning
      // is idempotent, so repairing is always the safe choice.
      RepairExisting := True;
      Exit;
    end;
    Choice := MsgBox('LanEx is already installed on this computer.'
      + #13#10#13#10 + 'Yes  -  Repair it and update LanEx (your projects are kept).'
      + #13#10 + 'No   -  Remove it completely and install fresh (ERASES the '
      + 'projects stored inside LanEx).'
      + #13#10 + 'Cancel  -  Leave everything as it is.',
      mbConfirmation, MB_YESNOCANCEL);
    if Choice = IDYES then
      RepairExisting := True
    else if Choice = IDNO then
    begin
      if MsgBox('Really erase the LanEx environment and everything stored inside '
        + 'it?' + #13#10#13#10 + 'Your designs live in the LanEx environment. If '
        + 'you want to keep them, choose No and use Repair instead — or open '
        + '\\wsl.localhost\{#DistroName}\home\{#AppUser} first and copy them out.',
        mbError, MB_YESNO) <> IDYES then
      begin
        Result := False;
        Exit;
      end;
      RemoveExisting := True;
    end
    else
      Result := False;
  end;
end;

// --------------------------------------------------------------- install work --

// EnableWsl turns the Windows feature on. Three strategies, weakest last.
function EnableWsl: Boolean;
var
  Code: Integer;
begin
  // 1. The modern one-shot. --no-distribution because we import our own;
  //    --web-download because the Store is blocked or absent on many managed
  //    and LTSC machines.
  if RunLogged(WslExe, '--install --no-distribution --web-download', Code) and (Code = 0) then
  begin
    Result := True;
    Exit;
  end;
  // 2. Same thing without --web-download: some builds of wsl.exe do not know
  //    the flag and reject the whole command line because of it.
  if RunLogged(WslExe, '--install --no-distribution', Code) and (Code = 0) then
  begin
    Result := True;
    Exit;
  end;
  // 3. Windows 10's inbox path: enable both features with DISM, then let the
  //    post-restart resume pull the kernel with `wsl --update`. This is what
  //    makes Setup work on Windows 10 22H2, where `wsl --install` can be too
  //    old to understand the flags above.
  SetStatus('Turning on the Windows features LanEx needs…');
  RunLogged(ExpandConstant('{sys}\dism.exe'),
    '/online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart', Code);
  RunLogged(ExpandConstant('{sys}\dism.exe'),
    '/online /enable-feature /featurename:VirtualMachinePlatform /all /norestart', Code);
  // DISM's 3010 means "done, restart required" — success as far as we care.
  Result := (Code = 0) or (Code = 3010);
end;

// ScheduleResume arranges for Setup to continue by itself after the restart.
procedure ScheduleResume;
var
  SetupCopy: String;
begin
  // Run the copy in our own cache, not {srcexe}: people delete the installer
  // from Downloads, and a resume that cannot find its own exe is a half-installed
  // machine. The copy goes away with everything else at uninstall.
  ForceDirectories(CacheDir);
  SetupCopy := CacheDir + '\LanEx-Setup.exe';
  if not FileCopy(ExpandConstant('{srcexe}'), SetupCopy, False) then
    SetupCopy := ExpandConstant('{srcexe}');
  // RunOnce (not Run): it fires exactly once and deletes itself, so a failed
  // resume can never turn into a boot loop. /RESUME=1 makes the second run skip
  // straight to the progress page.
  RegWriteStringValue(HKEY_LOCAL_MACHINE,
    'SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce', 'LanExSetupResume',
    '"' + SetupCopy + '" /RESUME=1 /SP-');
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if ProgressMax > 0 then
  begin
    // NB: an argument list must not start a line in an .iss file — Inno reads a
    // line beginning with '[' as a section tag and aborts the compile.
    SetStatus(Format('Downloading the LanEx environment… %d%% of %d MB', [
      Progress * 100 div ProgressMax, ProgressMax div 1048576]));
    if WizardForm <> nil then
    begin
      // Inno runs the "preparing" page with a marquee bar (unknown duration);
      // a 373 MB download has a known one, and a real percentage is the
      // difference between waiting and wondering.
      WizardForm.ProgressGauge.Style := npbstNormal;
      WizardForm.ProgressGauge.Min := 0;
      WizardForm.ProgressGauge.Max := 1000;
      WizardForm.ProgressGauge.Position := Progress * 1000 div ProgressMax;
    end;
  end;
  Result := True;
end;

// EnsureRootfs downloads the Ubuntu image unless a verified copy is cached.
// Returns '' on success or a message for the user.
function EnsureRootfs: String;
var
  Downloaded: String;
begin
  Result := '';
  ForceDirectories(CacheDir);
  // A cached file is only trusted after it re-hashes: a half-finished download
  // from a cancelled run is exactly the file that would otherwise import into a
  // broken distro.
  if FileExists(RootfsPath) then
  begin
    SetStatus('Checking the downloaded LanEx environment…');
    if CompareText(GetSHA256OfFile(RootfsPath), '{#RootfsSha256}') = 0 then
    begin
      LogLine('cached rootfs verified: ' + RootfsPath);
      Exit;
    end;
    LogLine('cached rootfs failed its checksum — downloading again');
    DeleteFile(RootfsPath);
  end;
  SetStatus('Downloading the LanEx environment (about {#RootfsSizeMB} MB)…');
  try
    // Inno verifies the SHA256 itself and raises if it differs, so a corrupted
    // or substituted download can never reach `wsl --import`.
    DownloadTemporaryFile('{#RootfsUrl}', '{#RootfsFile}', '{#RootfsSha256}',
                          @OnDownloadProgress);
    Downloaded := ExpandConstant('{tmp}\{#RootfsFile}');
    if not FileCopy(Downloaded, RootfsPath, False) then
    begin
      Result := 'Could not save the downloaded file to' + #13#10 + RootfsPath;
      Exit;
    end;
  except
    Result := 'The download did not finish.' + #13#10#13#10 + GetExceptionMessage
      + #13#10#13#10 + 'Check your internet connection (and any company proxy or '
      + 'VPN), then run Setup again — it continues from where it stopped.';
  end;
end;

// ProvisionDistro runs provision.sh inside the freshly imported distro.
function ProvisionDistro: String;
var
  ScriptPath, LinuxPath, Params: String;
  Code, Answer: Integer;
begin
  Result := '';
  ExtractTemporaryFile('provision.sh');
  ScriptPath := ExpandConstant('{tmp}\provision.sh');
  LinuxPath := WindowsToWslPath(ScriptPath);
  // `tr -d '\r'` before running: if this repo is ever checked out with Windows
  // line endings (a CI runner with core.autocrlf=true), bash would fail on the
  // shebang with "bad interpreter: No such file or directory" — a bewildering
  // error for a script that is obviously present. .gitattributes pins LF too;
  // this is the belt to that braces.
  Params := '-d {#DistroName} -u root -- bash -c "tr -d ''\r'' < ''' + LinuxPath
    + ''' > /tmp/lanex-provision.sh; bash /tmp/lanex-provision.sh"';
  repeat
    SetStatus('Preparing the LanEx environment — this takes a few minutes…');
    if RunLogged(WslExe, Params, Code) and (Code = 0) then
      Exit;
    Answer := MsgBox('Setting up the LanEx environment did not finish.'
      + #13#10#13#10 + 'This is almost always a network problem, and retrying is '
      + 'safe — it continues where it left off.' + #13#10#13#10
      + 'Last lines of the log:' + #13#10 + LogTail(12), mbError, MB_RETRYCANCEL);
  until Answer <> IDRETRY;
  Result := 'The LanEx environment could not be prepared.' + #13#10#13#10
    + 'The full log is at:' + #13#10 + LogFile + #13#10#13#10
    + 'Please report it — the log tells us exactly which step failed.';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Result := '';
  ForceDirectories(LogDir);
  LogLine('');
  LogLine('=== LanEx Setup {#AppVersion} — ' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':')
    + ' (resume=' + ExpandConstant('{param:RESUME|0}') + ') ===');

  // 1. WSL itself.
  if not WslUsable then
  begin
    SetStatus('Setting up Windows Subsystem for Linux (one-time)…');
    if not EnableWsl then
    begin
      Result := 'Windows Subsystem for Linux could not be turned on.' + #13#10#13#10
        + 'On a company-managed PC this is usually blocked by policy. '
        + 'docs/INSTALL.md has a manual path that works in that case.'
        + #13#10#13#10 + 'Last lines of the log:' + #13#10 + LogTail(10);
      Exit;
    end;
    if not WslUsable then
    begin
      // The one restart this installer can ever require. It resumes itself.
      ScheduleResume;
      WslPending := True;
      NeedsRestart := True;
      MsgBox('Windows needs to restart once to finish switching on the Linux '
        + 'subsystem LanEx runs on.' + #13#10#13#10
        + 'Setup will continue by itself after the restart — approve the '
        + '"LanEx Setup" prompt when it appears, and leave it to finish.',
        mbInformation, MB_OK);
      Exit;
    end;
  end;

  // 2. Belt-and-braces settings. Both are best-effort: an old inbox WSL that
  //    refuses --update still imports and runs our distro just fine, and we pass
  //    --version 2 explicitly at import time regardless of the default.
  RunLogged(WslExe, '--set-default-version 2', Code);
  SetStatus('Updating Windows Subsystem for Linux…');
  if not (RunLogged(WslExe, '--update --web-download', Code) and (Code = 0)) then
    RunLogged(WslExe, '--update', Code);

  // 3. A previous appliance the user asked us to erase.
  if RemoveExisting then
  begin
    SetStatus('Removing the previous LanEx environment…');
    RunLogged(WslExe, '--terminate {#DistroName}', Code);
    RunLogged(WslExe, '--unregister {#DistroName}', Code);
    DelTree(DistroDir, True, True, True);
  end;

  // 4./5. Download and import — skipped entirely when repairing, where the
  //       distro already exists and only provisioning needs to re-run.
  if not (RepairExisting and DistroExists) then
  begin
    Result := EnsureRootfs;
    if Result <> '' then
      Exit;
    SetStatus('Creating the LanEx environment…');
    ForceDirectories(DistroDir);
    // --version 2 explicitly: Docker and the GUI viewers need WSL 2, and the
    // user's default version is none of our business.
    if not (RunLogged(WslExe, '--import {#DistroName} "' + DistroDir + '" "'
        + RootfsPath + '" --version 2', Code) and (Code = 0)) then
    begin
      Result := 'The LanEx environment could not be created.' + #13#10#13#10
        + 'Last lines of the log:' + #13#10 + LogTail(10) + #13#10
        + 'Full log: ' + LogFile;
      Exit;
    end;
  end;

  // 6. Provision (idempotent — this is also the Repair path).
  Result := ProvisionDistro;
  if Result <> '' then
    Exit;

  // 7. Restart the distro so it boots with the systemd + default-user settings
  //    provision.sh just wrote. Without this, the first launch would run as root
  //    with no Docker daemon.
  SetStatus('Finishing up…');
  RunLogged(WslExe, '--terminate {#DistroName}', Code);
  LogLine('=== provisioning complete ===');
end;

// InstallCompleted gates the "Launch LanEx" checkbox: after a reboot-pending
// run there is no appliance yet, so offering to launch it would only produce an
// error dialog.
function InstallCompleted: Boolean;
begin
  Result := not WslPending;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  // The self-resuming run after the restart goes straight to the progress page:
  // the user already accepted the licence and chose their options.
  Result := IsResumeRun and
            ((PageID = wpWelcome) or (PageID = wpLicense) or (PageID = wpSelectTasks));
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and not WslPending then
    // Set expectations for the one thing that still has to happen: LanEx's own
    // Tools tab pulls the ~3 GB toolchain image on first launch (with a progress
    // bar). Setup deliberately does not — see provision.sh's LANEX_SKIP_PULL.
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10
      + 'First launch: open the Tools tab and click "Install the toolchain". '
      + 'That is a one-time download of about 3 GB, with a progress bar. '
      + 'After it finishes, LanEx is fully offline-capable.';
end;

// ------------------------------------------------------------------ uninstall --

procedure OpenProjectFolder;
var
  Code: Integer;
begin
  ShellExec('open', '\\wsl.localhost\{#DistroName}\home\{#AppUser}', '', '',
            SW_SHOWNORMAL, ewNoWait, Code);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code, Answer: Integer;
  ProfileDir: String;
begin
  if CurUninstallStep <> usUninstall then
    Exit;

  // Removing LanEx removes the user's designs with it — they live inside the
  // appliance. Anything less than an explicit warning here would be a trap, so
  // the dialog also offers to open the folder first, and keeps offering until
  // the user makes a decision.
  repeat
    Answer := MsgBox('This removes LanEx AND everything stored inside its '
      + 'environment, including your designs and run results.' + #13#10#13#10
      + 'Yes  -  Open the LanEx project folder first (nothing is removed yet).'
      + #13#10 + 'No   -  Remove LanEx now.'
      + #13#10 + 'Cancel  -  Keep LanEx.', mbError, MB_YESNOCANCEL);
    if Answer = IDYES then
      OpenProjectFolder
    else if Answer = IDCANCEL then
      Abort;   // nothing has been removed at this point — a clean bail-out
  until Answer = IDNO;

  // The appliance itself. --terminate first: --unregister on a running distro
  // can fail and leave a phantom registration behind.
  Exec(WslExe, '--terminate {#DistroName}', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(WslExe, '--unregister {#DistroName}', '', SW_HIDE, ewWaitUntilTerminated, Code);

  // Distro disk, cached rootfs, the resume copy of Setup, and the logs.
  DelTree(AppDataRoot, True, True, True);

  // The Windows-side browser profile the app window uses
  // (appwindow.py:246-279) — note the lowercase directory, which is LanEx's own
  // and predates this installer.
  ProfileDir := ExpandConstant('{localappdata}\lanex');
  DelTree(ProfileDir + '\app-profile', True, True, True);
  RemoveDir(ProfileDir);   // only succeeds if nothing else of LanEx's is left

  // Deliberately NOT undone: the Windows Subsystem for Linux feature. It is a
  // machine-wide setting other software may now rely on, and turning it off
  // would need another reboot. Documented in docs/INSTALL.md; it is the one
  // trace we leave, and it is inert.
end;
