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
;  Windows Settings removes the launcher while preserving projects/appliance
;  data by default. Their own WSL distros, if they have any, are never touched.
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
;    * Appliance ownership is a UUID plus exact HKCU registration/path and a
;      Linux marker. A matching distro name never authorizes repair or deletion.
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
#define VirtualizationHelpURL "https://support.microsoft.com/en-US/Windows/Experience/enable-virtualization-on-windows"
#define RepoRoot       "..\..\"
#ifndef LauncherExe
  #define LauncherExe  "..\launcher\LanEx.exe"
#endif
#define IconFile       "..\launcher\assets\lanex.ico"

; The git ref this Setup was built from, handed to provision.sh so the appliance
; installs the LanEx that belongs WITH this installer.
;
; It used to be unset, and provision.sh defaults to `main`: so a Setup built from
; a tag or a branch installed main's LanEx anyway, and — worse — every *Repair*
; silently replaced a branch build with main, undoing whatever the user
; reinstalled to get. The bake job already stamps its own ref for exactly this
; reason (windows-installer.yml, "Bake"); this closes the same hole on the
; user's machine.
#ifndef LanexRef
  #define LanexRef     "main"
#endif
#ifndef LanexSourceRepo
  #define LanexSourceRepo "AkshatIsWired/lanex"
#endif
#ifndef LanexSourceSha
  #error LanexSourceSha is required: Setup must identify an exact checked-out commit
#endif
#ifndef LanexWheel
  #error LanexWheel is required: build the checkout wheel before compiling Setup
#endif
#ifndef SetupWorkerSha256
  #error SetupWorkerSha256 is required: elevated helper must be bound to the bundled worker
#endif

; The appliance's identity. Same three strings in windows/provision/provision.sh
; and windows/launcher/main.go — change one, change all three.
#define PreferredDistroName "lanex"
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

; ---------------------------------------------------------------------------
; Phase 2a — the pre-baked appliance image (optional at compile time).
;
; The image above is a bare Ubuntu that provision.sh then spends several minutes
; turning into the appliance, live, on the user's machine — which also means
; every install depends on apt, GitHub and Docker's repository all being up at
; that moment. The `bake-rootfs` CI job runs the SAME provision.sh once, in a
; container, and publishes the result as a release asset; a tag build passes it
; in here:
;
;   iscc /DBakedRootfsUrl=https://.../lanex-rootfs-amd64.tar.gz ^
;        /DBakedRootfsSha256=<hash> /DBakedRootfsSizeMB=<n> lanex.iss
;
; Undefined — every PR build, every local build, and any tag whose bake job did
; not produce an asset — the installer compiles EXACTLY as it did before. That
; is deliberate: a build must never carry a URL that does not exist yet.
;
; At runtime the baked path is still only a preference. Setup verifies the hash,
; and on any failure at all (asset deleted, corrupt download, no route) it logs
; the reason and falls back to the Ubuntu image, which always works. A dead
; release asset can slow an install down; it can never brick one.
#ifdef BakedRootfsUrl
  #ifndef BakedRootfsSha256
    #error BakedRootfsUrl requires BakedRootfsSha256 (an unverified rootfs is not shippable)
  #endif
  #ifndef BakedRootfsFile
    #define BakedRootfsFile "lanex-rootfs-amd64.tar.gz"
  #endif
  #ifndef BakedRootfsSizeMB
    #define BakedRootfsSizeMB "900"
  #endif
#endif

; Space needed on the %LOCALAPPDATA% volume. The two download paths differ, so
; this is sized for the larger one:
;   cached image       ~0.4 GB (Ubuntu) or ~0.9 GB (baked, kept for Repair)
;   imported distro    ~2 GB before selected native tools/PDKs
;   LibreLane image    ~3 GB, pulled and verified by Setup after systemd boot
;   run output         the rest
; 10 GB leaves real headroom on both, and refusing an install that would have
; worked is worse than a tight fit — so this stays a floor, not an estimate.
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
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
LicenseFile={#RepoRoot}LICENSE
OutputBaseFilename=LanEx-Setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\LanEx.exe
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; The launcher, appliance registration, state and shortcuts belong to the user
; who started Setup. Only the two optional-feature operations use a small,
; explicit runas helper. Credential elevation under another administrator must
; never move HKCU or {localappdata} work into that administrator's profile.
PrivilegesRequired=lowest
; WSL 2 is 64-bit only. x64compatible also covers ARM64 running x64 code, but
; the launcher is x64 (see windows/launcher/wsl.go) so the appliance is too.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; WSL 2 needs Windows 10 2004 (build 19041). Enforced here so the friendly
; message below is the first thing an unsupported machine sees.
MinVersion=10.0.19044
; Refuse to install over a running LanEx — the mutex the launcher holds
; (windows/launcher/main.go). Inno asks the user to close it first, which is far
; better than importing over a distro that is mid-run.
AppMutex=LanExLauncher
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
WindowsVersionNotSupported=LanEx needs Windows 10 version 21H2 (build 19044) or newer for WSLg desktop tools. Windows 11 x64 is recommended.
; The wizard's own words, in the language of the person we are installing for.
WelcomeLabel2=This will install [name/ver] on your computer.%n%nLanEx sets up its own private, self-contained environment. It preserves your existing WSL distributions and their data. If required, Windows asks separately before Setup enables WSL features or updates WSL.%n%nRemoving the Windows app preserves your projects and environment by default.%n%nSetup first downloads about {#RootfsSizeMB} MB; the selected toolchain and PDKs need additional space and downloads.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#LauncherExe}"; DestDir: "{app}"; DestName: "LanEx.exe"; Flags: ignoreversion
Source: "{#IconFile}"; DestDir: "{app}"; DestName: "lanex.ico"; Flags: ignoreversion
; provision.sh is never installed: it runs once, inside the distro, from {tmp}.
; dontcopy + ExtractTemporaryFile is what lets PrepareToInstall use it before
; the file-copy step has happened at all.
Source: "..\provision\provision.sh"; Flags: dontcopy
Source: "..\provision\selftest.sh"; Flags: dontcopy
Source: "{#RepoRoot}scripts\install.sh"; Flags: dontcopy
Source: "..\setup\setup.ps1"; Flags: dontcopy
Source: "..\setup\constraints.txt"; Flags: dontcopy
Source: "..\setup\build-manifest.json"; Flags: dontcopy
Source: "{#LanexWheel}"; DestName: "lanex-candidate.whl"; Flags: dontcopy

[Icons]
Name: "{userprograms}\{#AppName}\{#AppName}"; Filename: "{app}\LanEx.exe"; IconFilename: "{app}\lanex.ico"
; A shortcut straight into the appliance's home directory. Small feature, large
; payoff: it proves to the user that their designs are ordinary files on their
; own PC, not something sealed inside a black box.
Name: "{userprograms}\{#AppName}\{#AppName} Project Files"; Filename: "{code:DistroProjectPath}"; IconFilename: "{app}\lanex.ico"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\LanEx.exe"; IconFilename: "{app}\lanex.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\LanEx.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent; Check: InstallCompleted

[Code]
var
  // Set in InitializeSetup, read in PrepareToInstall.
  RepairExisting: Boolean;   // a lanex distro is already there: keep its data
  // True when Setup stopped early to reboot for WSL; suppresses the "Launch
  // LanEx" checkbox, because nothing has been provisioned yet.
  WslPending: Boolean;
  // Which image `wsl --import` will read. Set by EnsureRootfs — the pre-baked
  // appliance when this build has one and it downloaded cleanly, the pinned
  // Ubuntu image otherwise.
  ImportPath: String;
  DistroNameValue: String;
  InstallIdValue: String;
  ManifestHashValue: String;
  PreflightDecision: String;
  BootIdentityValue: String;
  ComputerDisplayValue: String;
  FirmwareNoticeValue: Boolean;

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

function ApplianceRoot: String; begin Result := AppDataRoot + '\appliance'; end;
function DistroDir: String;  begin Result := ApplianceRoot + '\distro'; end;
function CacheDir: String;   begin Result := AppDataRoot + '\installer-cache';  end;
function LogDir: String;     begin Result := AppDataRoot + '\logs';   end;
function LogFile: String;    begin Result := LogDir + '\install.log'; end;
function StateFile: String;  begin Result := AppDataRoot + '\installer-state.json'; end;
function RootfsPath: String; begin Result := CacheDir + '\{#RootfsFile}'; end;
#ifdef BakedRootfsUrl
function BakedRootfsPath: String; begin Result := CacheDir + '\{#BakedRootfsFile}'; end;
#endif

function WslExe: String;
begin
  // {sys} is the real System32 even from a 32-bit process; wsl.exe does not
  // exist under SysWOW64, so never rely on PATH resolution here.
  Result := ExpandConstant('{sys}\wsl.exe');
end;

function DistroProjectPath(Param: String): String;
begin
  Result := '\\wsl.localhost\' + DistroNameValue + '\home\{#AppUser}';
end;

function PSQuote(const S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '''', '''''', True);
  Result := '''' + Result + '''';
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
  //
  // TWO labels, and PreparingLabel is the one that matters. Everything slow in
  // this installer — the 373 MB download, the import, the whole provisioning
  // run — happens inside PrepareToInstall, and PrepareToInstall runs while the
  // *Preparing* page is on screen. StatusLabel and ProgressGauge belong to the
  // *Installing* page, which is not reached until all of that is already over.
  // Setting only StatusLabel meant a real user sat in front of a blank white
  // page for eight minutes with no text, no bar and no way to tell a working
  // install from a hung one. StatusLabel is still set for the file-copy step
  // afterwards; writing to an off-screen control is harmless.
  if WizardForm <> nil then
  begin
    WizardForm.PreparingLabel.Caption := S;
    WizardForm.PreparingLabel.Update;
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
  Result := Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, Code)
    and (Code = 0);
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
  // `set WSL_UTF8=1&&` first, with no space before the &&, or the space becomes
  // part of the value. Without it wsl.exe writes UTF-16LE straight into a log
  // that is otherwise single-byte, and every WSL line comes back as
  // "T h e   o p e r a t i o n   c o m p l e t e d" — in the one file we ask
  // users to send us when an install fails.
  Result := Exec(ExpandConstant('{cmd}'),
    '/C "set WSL_UTF8=1&& "' + FileName + '" ' + Params
      + ' >> "' + LogFile + '" 2>&1"',
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
    if CompareText(Line, DistroNameValue) = 0 then
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

function TakeLine(var Text: String): String;
var
  P: Integer;
begin
  P := Pos(#10, Text);
  if P = 0 then
  begin
    Result := Trim(Text);
    Text := '';
  end
  else
  begin
    Result := Trim(Copy(Text, 1, P - 1));
    Text := Copy(Text, P + 1, Length(Text) - P);
  end;
end;

// RunPreflight asks the versioned worker for one structured snapshot. Inno uses
// three stable fields to drive UI; the complete JSON goes to install.log so a
// query failure never gets collapsed into a misleading BIOS message.
function RunPreflight(var Failure: String): Boolean;
var
  Worker, Output, Snippet, JsonLine: String;
begin
  Failure := '';
  ExtractTemporaryFile('setup.ps1');
  Worker := ExpandConstant('{tmp}\setup.ps1');
  Snippet := '$p = (& ' + PSQuote(Worker)
    + ' -Action Preflight | ConvertFrom-Json); '
    + '$p.decision.code; $p.bootIdentity; '
    + '(($p.computer.manufacturer + '' '' + $p.computer.model) -replace ''[\r\n\t]'','' '').Trim(); '
    + '$p.decision.firmwareNotice; '
    + '($p | ConvertTo-Json -Depth 20 -Compress)';
  Result := PowerShellCapture(Snippet, Output);
  if not Result then
  begin
    Failure := Output;
    Exit;
  end;
  PreflightDecision := TakeLine(Output);
  BootIdentityValue := TakeLine(Output);
  ComputerDisplayValue := TakeLine(Output);
  FirmwareNoticeValue := CompareText(TakeLine(Output), 'true') = 0;
  JsonLine := TakeLine(Output);
  LogLine('preflight: ' + JsonLine);
  Result := (PreflightDecision <> '') and (BootIdentityValue <> '');
  if not Result then
    Failure := 'The structured preflight result was incomplete.';
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
  // Set only by the owner-bound automatic trigger after a recorded restart.
  Result := ExpandConstant('{param:RESUME|0}') = '1';
end;

function IsContinuationRun: Boolean;
begin
  Result := IsResumeRun or (ExpandConstant('{param:CONTINUE|0}') = '1');
end;

procedure OpenHelp(const Anchor: String);
var
  Code: Integer;
begin
  ShellExec('open', '{#VirtualizationHelpURL}', '', '',
            SW_SHOWNORMAL, ewNoWait, Code);
end;

function InitializeSetup(): Boolean;
var
  FreeGB: Integer;
  Failure, Detail: String;
begin
  Result := True;
  RepairExisting := False;
  WslPending := False;
  DistroNameValue := '{#PreferredDistroName}';
  InstallIdValue := '';
  ManifestHashValue := '';
  PreflightDecision := '';
  BootIdentityValue := '';
  ComputerDisplayValue := '';
  FirmwareNoticeValue := False;

  if not RunPreflight(Failure) then
  begin
    MsgBox('LanEx could not inspect this PC''s Windows and WSL prerequisites.'
      + #13#10#13#10 + Failure + #13#10#13#10
      + 'No Windows feature, WSL distribution, or user data was changed.',
      mbError, MB_OK);
    Result := False;
    Exit;
  end;

  if PreflightDecision = 'unsupported-architecture' then
  begin
    MsgBox('This LanEx installer contains an amd64 Linux appliance and requires '
      + 'an x64 Windows PC. ARM64 and other native architectures are not '
      + 'supported by this build.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if PreflightDecision = 'unsupported-windows' then
  begin
    MsgBox('LanEx needs Windows build 19044 or newer so its WSLg desktop tools '
      + 'can open correctly. Windows 11 x64 is recommended.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if PreflightDecision = 'preflight-query-failed' then
  begin
    MsgBox('Windows did not allow Setup to determine the required WSL feature '
      + 'states. On a managed PC, ask an administrator to enable Windows '
      + 'Subsystem for Linux and Virtual Machine Platform, then run Setup again.'
      + #13#10#13#10 + 'No feature or distribution was changed.', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  // Firmware disabled is the only early BIOS/UEFI block. A running hypervisor
  // overrides misleading firmware=false signals; unknown produces a notice.
  if PreflightDecision = 'firmware-disabled' then
  begin
    Detail := '';
    if ComputerDisplayValue <> '' then
      Detail := #13#10#13#10 + 'PC: ' + ComputerDisplayValue;
    if MsgBox('LanEx cannot run because your computer''s virtualization feature '
      + 'is switched off.' + #13#10#13#10
      + 'It is a one-time setting in your PC''s BIOS/UEFI screen, not something '
      + 'Windows can change. Microsoft''s instructions include manufacturer links.'
      + Detail
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
      + 'downloads before Setup finishes. Please free some space and run Setup again.',
      mbError, MB_OK);
    Result := False;
    Exit;
  end;

  // Existing distro names are not ownership proof. The state worker resolves
  // and binds the exact HKCU registration/path later, before any WSL mutation.
end;

function InitializeDurableState: String;
var
  Worker, Manifest, OperationName, Output, Snippet, SetupCopy: String;
  HadState: Boolean;
begin
  Result := '';
  ExtractTemporaryFile('setup.ps1');
  ExtractTemporaryFile('build-manifest.json');
  ExtractTemporaryFile('install.sh');
  ExtractTemporaryFile('constraints.txt');
  ExtractTemporaryFile('lanex-candidate.whl');
  Worker := ExpandConstant('{tmp}\setup.ps1');
  Manifest := ExpandConstant('{tmp}\build-manifest.json');
  HadState := FileExists(StateFile);
  if ExpandConstant('{param:UPDATE|0}') = '1' then
    OperationName := 'update'
  else if HadState then
    OperationName := 'repair'
  else
    OperationName := 'install';

  Snippet := '& ' + PSQuote(Worker) + ' -Action InitializeState -StatePath '
    + PSQuote(StateFile) + ' -ManifestPath ' + PSQuote(Manifest)
    + ' -Operation ' + OperationName
    + ' -ChoicesJson ''{"pdks":["sky130A"],"libraries":"all","engine":"docker"}'''
    + ' -InstallerPath ' + PSQuote(ExpandConstant('{srcexe}'));
  if IsResumeRun then
    Snippet := Snippet + ' -ResumeMode 1 -BootIdentity ' + PSQuote(BootIdentityValue);
  if not PowerShellCapture(Snippet, Output) then
  begin
    Result := 'LanEx could not validate its saved setup state.' + #13#10#13#10
      + Output + #13#10#13#10
      + 'No WSL distribution or user data was changed.';
    Exit;
  end;

  if (PreflightDecision = 'features-required') and FirmwareNoticeValue then
    MsgBox('Windows could not confirm the firmware virtualization setting. '
      + 'Setup will enable the two Windows features it needs and check again '
      + 'after restart. If the PC then reports virtualization is disabled, '
      + 'Setup will stop with Microsoft''s manufacturer-specific guidance.',
      mbInformation, MB_OK);

  Snippet := '& ' + PSQuote(Worker) + ' -Action ResolveAppliance -StatePath '
    + PSQuote(StateFile) + ' -PreferredDistroName {#PreferredDistroName}'
    + ' -ExpectedBasePath ' + PSQuote(DistroDir);
  if not PowerShellCapture(Snippet, Output) then
  begin
    Result := 'LanEx could not prove ownership of the saved appliance.'
      + #13#10#13#10 + Output + #13#10#13#10
      + 'The existing distribution was left untouched.';
    Exit;
  end;
  if not PowerShellCapture(
      '(Get-Content -LiteralPath ' + PSQuote(StateFile)
        + ' -Raw | ConvertFrom-Json).appliance.name', DistroNameValue) then
  begin
    Result := 'LanEx could not read the selected appliance name from setup state.';
    Exit;
  end;
  if not PowerShellCapture(
      '(Get-Content -LiteralPath ' + PSQuote(StateFile)
        + ' -Raw | ConvertFrom-Json).installId', InstallIdValue) then
  begin
    Result := 'LanEx could not read the install identity from setup state.';
    Exit;
  end;
  ManifestHashValue := Lowercase(GetSHA256OfFile(Manifest));

  // Keep an immutable candidate copy and a manual continuation shortcut before
  // UAC. If elevation is cancelled or policy blocks it, the originating user
  // still has a recoverable setup entry independent of Downloads.
  ForceDirectories(CacheDir);
  SetupCopy := CacheDir + '\LanEx-Setup.exe';
  if CompareText(ExpandConstant('{srcexe}'), SetupCopy) <> 0 then
    if not FileCopy(ExpandConstant('{srcexe}'), SetupCopy, False) then
    begin
      Result := 'LanEx could not stage a durable copy of this exact installer.'
        + #13#10#13#10 + 'No Windows feature or WSL distribution was changed.';
      Exit;
    end;
  Snippet := '& ' + PSQuote(Worker) + ' -Action StageInstaller -StatePath '
    + PSQuote(StateFile) + ' -ResumeInstallerPath ' + PSQuote(SetupCopy);
  if not PowerShellCapture(Snippet, Output) then
  begin
    Result := 'LanEx could not verify its cached installer or manual Continue '
      + 'shortcut.' + #13#10#13#10 + Output
      + #13#10#13#10 + 'No Windows feature or WSL distribution was changed.';
    Exit;
  end;
  RepairExisting := HadState and DistroExists;
  LogLine('owned setup identity: ' + InstallIdValue + ' distro=' + DistroNameValue
    + ' manifest=' + ManifestHashValue);
end;

// --------------------------------------------------------------- install work --

// EnableWsl is the only elevated operation in Setup. The helper can enable
// exactly two named optional features; appliance import/state/shortcuts remain
// in this original unelevated user's HKCU and profile even when UAC credentials
// belong to a different administrator.
function EnableWsl: Boolean;
var
  Code: Integer;
  Worker, OutputFile, Params: String;
  Raw: AnsiString;
begin
  SetStatus('Turning on the Windows features LanEx needs...');
  Worker := ExpandConstant('{tmp}\setup.ps1');
  OutputFile := ExpandConstant('{tmp}\feature-results.json');
  DeleteFile(OutputFile);
  if CompareText(GetSHA256OfFile(Worker), '{#SetupWorkerSha256}') <> 0 then
  begin
    LogLine('elevated worker hash does not match the compile-time payload hash');
    Result := False;
    Exit;
  end;
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'
    + Worker + '" -Action EnableFeatures -ExpectedSelfSha256 {#SetupWorkerSha256}'
    + ' -OutputPath "' + OutputFile + '"';
  LogLine('$ elevated feature helper: Windows Subsystem for Linux + Virtual Machine Platform');
  Result := ShellExec('runas',
    ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '',
    SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
  if FileExists(OutputFile) and LoadStringFromFile(OutputFile, Raw) then
    LogLine('feature helper result: ' + Trim(String(Raw)))
  else
    Result := False;
  if not Result then
    LogLine('feature helper failed or UAC was cancelled; exit=' + IntToStr(Code));
end;

// ScheduleResume arranges for Setup to continue by itself after the restart.
function ScheduleResume: Boolean;
var
  Worker, Output, Snippet: String;
begin
  // The worker writes and verifies HKEY_CURRENT_USER RunOnce for this owner.
  // Durable state bounds two attempts total and one per boot. The independently
  // verified Start-menu shortcut remains the manual fallback if RunOnce is
  // blocked, consumed, or cancelled.
  Worker := ExpandConstant('{tmp}\setup.ps1');
  Snippet := '& ' + PSQuote(Worker) + ' -Action RegisterResume -StatePath '
    + PSQuote(StateFile) + ' -BootIdentity ' + PSQuote(BootIdentityValue);
  Result := PowerShellCapture(Snippet, Output);
  if not Result then
    LogLine('resume registration failed: ' + Output);
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if ProgressMax > 0 then
  begin
    // NB: an argument list must not start a line in an .iss file — Inno reads a
    // line beginning with '[' as a section tag and aborts the compile.
    // The percentage has to live in the TEXT. The Preparing page has no
    // progress bar at all — ProgressGauge is on the Installing page, which this
    // download runs long before — so a number in the label is the only honest
    // signal available here, and it is the difference between waiting and
    // wondering.
    SetStatus(Format('Downloading the LanEx environment... %d%% of %d MB', [
      Progress * 100 div ProgressMax, ProgressMax div 1048576]));
  end;
  Result := True;
end;

// FetchRootfs downloads one image unless a copy that matches Sha256 is already
// cached. Returns '' on success, or a message that is shown to the user on the
// Ubuntu path and merely LOGGED on the baked path (see EnsureRootfs).
function FetchRootfs(const Url, FileName, Sha256, Dest, SizeMB: String): String;
var
  Downloaded: String;
begin
  Result := '';
  ForceDirectories(CacheDir);
  // A cached file is only trusted after it re-hashes: a half-finished download
  // from a cancelled run is exactly the file that would otherwise import into a
  // broken distro.
  if FileExists(Dest) then
  begin
    SetStatus('Checking the downloaded LanEx environment...');
    if CompareText(GetSHA256OfFile(Dest), Sha256) = 0 then
    begin
      LogLine('cached rootfs verified: ' + Dest);
      Exit;
    end;
    LogLine('cached rootfs failed its checksum — downloading again: ' + Dest);
    DeleteFile(Dest);
  end;
  SetStatus('Downloading the LanEx environment (about ' + SizeMB + ' MB)...');
  try
    // Inno verifies the SHA256 itself and raises if it differs, so a corrupted
    // or substituted download can never reach `wsl --import`.
    DownloadTemporaryFile(Url, FileName, Sha256, @OnDownloadProgress);
    Downloaded := ExpandConstant('{tmp}\') + FileName;
    if not FileCopy(Downloaded, Dest, False) then
    begin
      Result := 'Could not save the downloaded file to' + #13#10 + Dest;
      Exit;
    end;
  except
    Result := 'The download did not finish.' + #13#10#13#10 + GetExceptionMessage
      + #13#10#13#10 + 'Check your internet connection (and any company proxy or '
      + 'VPN), then run Setup again — it continues from where it stopped.';
  end;
end;

// EnsureRootfs puts an importable image on disk and sets ImportPath to it.
// Returns '' on success or a message for the user.
function EnsureRootfs: String;
begin
#ifdef BakedRootfsUrl
  // Preferred: the appliance CI already cooked for this exact build. One
  // download, ~1 minute of import, and apt/GitHub/Docker being down stops being
  // an install-time failure.
  Result := FetchRootfs('{#BakedRootfsUrl}', '{#BakedRootfsFile}',
                        '{#BakedRootfsSha256}', BakedRootfsPath, '{#BakedRootfsSizeMB}');
  if Result = '' then
  begin
    ImportPath := BakedRootfsPath;
    LogLine('using the pre-baked appliance image');
    Exit;
  end;
  // Deleted asset, corrupt file, no route — none of it is worth failing over
  // when a path that always works is right here. The reason goes in the log so
  // a broken release is diagnosable from a user's install.log alone.
  LogLine('pre-baked image unavailable, falling back to the Ubuntu image. Reason: '
    + Result);
#endif
  ImportPath := RootfsPath;
  Result := FetchRootfs('{#RootfsUrl}', '{#RootfsFile}', '{#RootfsSha256}',
                        RootfsPath, '{#RootfsSizeMB}');
end;

// ProvisionDistro runs provision.sh inside the freshly imported distro.
function ProvisionDistro: String;
var
  ScriptPath, InstallPath, WheelPath, ConstraintPath, ManifestPath, LinuxPath, LinuxInstall,
  LinuxWheel, LinuxConstraint, LinuxManifest, LinuxChoices, Params: String;
  Code, Answer: Integer;
begin
  Result := '';
  ExtractTemporaryFile('provision.sh');
  ExtractTemporaryFile('build-manifest.json');
  ScriptPath := ExpandConstant('{tmp}\provision.sh');
  InstallPath := ExpandConstant('{tmp}\install.sh');
  WheelPath := ExpandConstant('{tmp}\lanex-candidate.whl');
  ConstraintPath := ExpandConstant('{tmp}\constraints.txt');
  ManifestPath := ExpandConstant('{tmp}\build-manifest.json');
  LinuxPath := WindowsToWslPath(ScriptPath);
  LinuxInstall := WindowsToWslPath(InstallPath);
  LinuxWheel := WindowsToWslPath(WheelPath);
  LinuxConstraint := WindowsToWslPath(ConstraintPath);
  LinuxManifest := WindowsToWslPath(ManifestPath);
  LinuxChoices := WindowsToWslPath(StateFile);
  // `tr -d '\r'` before running: if this repo is ever checked out with Windows
  // line endings (a CI runner with core.autocrlf=true), bash would fail on the
  // shebang with "bad interpreter: No such file or directory" — a bewildering
  // error for a script that is obviously present. .gitattributes pins LF too;
  // this is the belt to that braces.
  // `export`, not a `VAR=... bash script` prefix: provision.sh's own header
  // records why (a prefix applies to the one command it prefixes, so every knob
  // passed that way was silently inert).
  Params := '-d "' + DistroNameValue + '" -u root -- env '
    + 'LANEX_REPO="{#LanexSourceRepo}" LANEX_REF="{#LanexRef}" '
    + 'LANEX_SOURCE_SHA="{#LanexSourceSha}" LANEX_INSTALL_ID="' + InstallIdValue + '" '
    + 'LANEX_MANIFEST_HASH="' + ManifestHashValue + '" '
    + 'LANEX_INSTALL_SCRIPT="' + LinuxInstall + '" LANEX_FROM="' + LinuxWheel + '" '
    + 'LANEX_PIP_CONSTRAINT="' + LinuxConstraint + '" '
    + 'LANEX_BUILD_MANIFEST="' + LinuxManifest + '" LANEX_SETUP_CHOICES="' + LinuxChoices + '" '
    + 'bash "' + LinuxPath + '" base';
  repeat
    SetStatus('Preparing the LanEx environment - this takes a few minutes...');
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

function VerifyRepairIdentity(var Failure: String): Boolean;
var
  WorkerOutput, Snippet: String;
begin
  Failure := '';
  Snippet := '$m = (& ' + PSQuote(WslExe) + ' -d ' + PSQuote(DistroNameValue)
    + ' -u root -- cat /etc/lanex/appliance.json) | ConvertFrom-Json; '
    + 'if ($m.schema -ne 1 -or $m.installId -ne ' + PSQuote(InstallIdValue)
    + ' -or $m.manifestHash -ne ' + PSQuote(ManifestHashValue)
    + ' -or $m.sourceSha -ne ''{#LanexSourceSha}'') '
    + '{ throw ''Linux appliance identity does not match owner/build state.'' }; ''identity-ok''';
  Result := PowerShellCapture(Snippet, WorkerOutput);
  if not Result then
    Failure := WorkerOutput;
end;

function HealthyRepairNeedsNoChanges: Boolean;
var
  SelfTestPath, ManifestPath, LinuxSelfTest, LinuxManifest, LinuxChoices: String;
  Code: Integer;
begin
  ExtractTemporaryFile('selftest.sh');
  ExtractTemporaryFile('build-manifest.json');
  SelfTestPath := ExpandConstant('{tmp}\selftest.sh');
  ManifestPath := ExpandConstant('{tmp}\build-manifest.json');
  LinuxSelfTest := WindowsToWslPath(SelfTestPath);
  LinuxManifest := WindowsToWslPath(ManifestPath);
  LinuxChoices := WindowsToWslPath(StateFile);
  Result := RunLogged(WslExe, '-d "' + DistroNameValue
    + '" -u root -- env LANEX_BUILD_MANIFEST="' + LinuxManifest
    + '" LANEX_SETUP_CHOICES="' + LinuxChoices + '" bash "'
    + LinuxSelfTest + '"', Code) and (Code = 0);
end;

function FinalizeDistro: String;
var
  ScriptPath, ManifestPath, LinuxScript, LinuxManifest, LinuxChoices, Params: String;
  Code, Answer: Integer;
begin
  Result := '';
  ExtractTemporaryFile('provision.sh');
  ExtractTemporaryFile('build-manifest.json');
  ScriptPath := ExpandConstant('{tmp}\provision.sh');
  ManifestPath := ExpandConstant('{tmp}\build-manifest.json');
  LinuxScript := WindowsToWslPath(ScriptPath);
  LinuxManifest := WindowsToWslPath(ManifestPath);
  LinuxChoices := WindowsToWslPath(StateFile);
  Params := '-d "' + DistroNameValue + '" -u root -- env '
    + 'LANEX_USER="lanex" LANEX_BUILD_MANIFEST="' + LinuxManifest + '" '
    + 'LANEX_SETUP_CHOICES="' + LinuxChoices + '" bash "' + LinuxScript + '" finalize';
  repeat
    SetStatus('Installing and verifying the selected tools, image, and PDKs...');
    if RunLogged(WslExe, Params, Code) and (Code = 0) then
      Exit;
    Answer := MsgBox('The selected LanEx components did not all become ready.'
      + #13#10#13#10 + 'Retrying preserves completed tools, image layers, PDKs, and projects.'
      + #13#10#13#10 + 'Last lines of the log:' + #13#10 + LogTail(16),
      mbError, MB_RETRYCANCEL);
  until Answer <> IDRETRY;
  Result := 'LanEx base setup is intact, but selected-component readiness failed.'
    + #13#10#13#10 + 'No existing distribution or project was deleted.'
    + #13#10#13#10 + 'Full log: ' + LogFile;
end;

procedure MarkAppComplete;
var
  Output, Worker, Manifest, Snippet: String;
begin
  Worker := ExpandConstant('{tmp}\setup.ps1');
  Manifest := ExpandConstant('{tmp}\build-manifest.json');
  Snippet := '$f=(Get-Content -LiteralPath ' + PSQuote(Manifest)
    + ' -Raw | ConvertFrom-Json).componentFingerprints.app; & '
    + PSQuote(Worker) + ' -Action SetComponent -StatePath ' + PSQuote(StateFile)
    + ' -Component app -ComponentStatus complete -InputFingerprint $f -Phase base-provisioned';
  if not PowerShellCapture(Snippet, Output) then
    LogLine('WARNING: could not checkpoint app component: ' + Output);
end;

function MarkSelectionsComplete: Boolean;
var
  Output, Worker, Manifest, Snippet: String;
begin
  Worker := ExpandConstant('{tmp}\setup.ps1');
  Manifest := ExpandConstant('{tmp}\build-manifest.json');
  Snippet := '$ErrorActionPreference=''Stop''; $m=Get-Content -LiteralPath ' + PSQuote(Manifest)
    + ' -Raw|ConvertFrom-Json; & ' + PSQuote(Worker) + ' -Action SetComponent -StatePath '
    + PSQuote(StateFile) + ' -Component image -ComponentStatus complete '
    + '-InputFingerprint $m.componentFingerprints.image -Phase finalizing; & '
    + PSQuote(Worker) + ' -Action SetComponent -StatePath ' + PSQuote(StateFile)
    + ' -Component pdks -ComponentStatus complete '
    + '-InputFingerprint $m.componentFingerprints.pdks -Phase ready';
  Result := PowerShellCapture(Snippet, Output);
  if not Result then
    LogLine('could not checkpoint selected components: ' + Output);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
  Output, Worker, IdentityFailure: String;
  NeedProvision: Boolean;
begin
  Result := '';
  ForceDirectories(LogDir);
  LogLine('');
  LogLine('=== LanEx Setup {#AppVersion} — ' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':')
    + ' (resume=' + ExpandConstant('{param:RESUME|0}') + ') ===');

  // Establish immutable owner/build/appliance identity before enabling WSL,
  // downloading, importing, terminating, or provisioning anything.
  Result := InitializeDurableState;
  if Result <> '' then
    Exit;

  // Revalidate immediately before every machine-level or large operation. The
  // wizard may have been open for a while, and resume never trusts stale facts.
  if not RunPreflight(Output) then
  begin
    Result := 'LanEx could not recheck Windows/WSL prerequisites.'
      + #13#10#13#10 + Output + #13#10#13#10
      + 'Use Continue LanEx Setup from the Start menu after resolving the issue.';
    Exit;
  end;

  if PreflightDecision = 'firmware-disabled' then
  begin
    Result := 'Firmware virtualization is disabled. No feature, distribution, '
      + 'or user data was changed. Use Microsoft''s virtualization instructions '
      + 'and then choose Continue LanEx Setup from the Start menu.';
    Exit;
  end;
  if (PreflightDecision = 'unsupported-architecture') or
     (PreflightDecision = 'unsupported-windows') or
     (PreflightDecision = 'preflight-query-failed') then
  begin
    Result := 'This PC did not pass the structured Windows/WSL preflight: '
      + PreflightDecision + '.' + #13#10#13#10
      + 'No Windows feature or WSL distribution was changed.';
    Exit;
  end;

  // Only the feature operation crosses UAC. A different administrator may
  // authorize it, but execution returns here before any user-owned work.
  if PreflightDecision = 'features-required' then
  begin
    SetStatus('Requesting permission for two Windows features...');
    if not EnableWsl then
    begin
      Result := 'Windows Subsystem for Linux could not be turned on.' + #13#10#13#10
        + 'The administrator prompt may have been cancelled, or company policy '
        + 'may block Windows Subsystem for Linux / Virtual Machine Platform. '
        + 'An administrator must enable those features; Setup cannot bypass policy.'
        + #13#10#13#10 + 'Your choices and exact installer are saved. Use '
        + 'Continue LanEx Setup from the Start menu when ready.'
        + #13#10#13#10 + 'Last lines of the log:' + #13#10 + LogTail(10);
      Exit;
    end;
    if not ScheduleResume then
    begin
      Result := 'The Windows features were enabled, but Setup could not verify '
        + 'the owner-only continuation trigger. Restart was not requested. '
        + 'Use Continue LanEx Setup from the Start menu after restarting Windows.';
      Exit;
    end;
    WslPending := True;
    NeedsRestart := True;
    MsgBox('Windows needs to restart to finish switching on the Linux subsystem.'
      + #13#10#13#10 + 'Setup registered one owner-only automatic continuation. '
      + 'If Windows blocks it, use Continue LanEx Setup in your Start menu. '
      + 'Your component and PDK choices are already saved.', mbInformation, MB_OK);
    Exit;
  end;

  if PreflightDecision = 'restart-required' then
  begin
    if not ScheduleResume then
    begin
      Result := 'Windows reports a pending WSL feature restart, but Setup could '
        + 'not verify the owner-only continuation trigger. Use Continue LanEx '
        + 'Setup from the Start menu after restarting Windows.';
      Exit;
    end;
    WslPending := True;
    NeedsRestart := True;
    Exit;
  end;

  if PreflightDecision = 'wsl-update-required' then
  begin
    if MsgBox('LanEx needs a newer WSL runtime for systemd and desktop tools.'
      + #13#10#13#10 + 'Updating WSL is machine-wide and can briefly affect '
      + 'other WSL work. Save active WSL work before continuing. Setup will '
      + 'not shut down or convert any distribution.' + #13#10#13#10
      + 'Update WSL now?', mbConfirmation, MB_YESNO) <> IDYES then
    begin
      Result := 'WSL update deferred. Your choices and exact installer are saved; '
        + 'choose Continue LanEx Setup from the Start menu when ready.';
      Exit;
    end;
    SetStatus('Updating Windows Subsystem for Linux...');
    if not (RunLogged(WslExe, '--update --web-download', Code) and (Code = 0)) and
       not (RunLogged(WslExe, '--update', Code) and (Code = 0)) then
    begin
      Result := 'Windows could not update WSL. This may be a managed-policy or '
        + 'network restriction; the existing distributions were not stopped or '
        + 'changed.' + #13#10#13#10 + LogTail(12);
      Exit;
    end;
    if not RunPreflight(Output) then
    begin
      Result := 'WSL updated, but Setup could not verify its capabilities.'
        + #13#10#13#10 + Output;
      Exit;
    end;
    if PreflightDecision = 'restart-required' then
    begin
      if not ScheduleResume then
      begin
        Result := 'WSL updated but its restart continuation could not be verified. '
          + 'Use Continue LanEx Setup after restarting Windows.';
        Exit;
      end;
      WslPending := True;
      NeedsRestart := True;
      Exit;
    end;
    if PreflightDecision <> 'ready' then
    begin
      Result := 'The WSL runtime still does not provide the required capabilities: '
        + PreflightDecision + '.' + #13#10#13#10 + LogTail(12);
      Exit;
    end;
  end;

  if (PreflightDecision <> 'ready') or (not WslUsable) then
  begin
    Result := 'WSL could not start the private appliance kernel. Setup will not '
      + 'download or import an environment until this prerequisite is healthy.'
      + #13#10#13#10 + 'No existing distribution was stopped or changed.';
    Exit;
  end;

  // Download and import — skipped entirely when repairing, where the
  //       distro already exists and only provisioning needs to re-run.
  if not (RepairExisting and DistroExists) then
  begin
    Result := EnsureRootfs;
    if Result <> '' then
      Exit;
    SetStatus('Creating the LanEx environment...');
    ForceDirectories(DistroDir);
    // --version 2 explicitly: Docker and the GUI viewers need WSL 2, and the
    // user's default version is none of our business.
    // --version 2 explicitly (again): `wsl --import` reads plain tar and .tar.gz
    // alike, so the baked and the Ubuntu path use one identical command.
    if not (RunLogged(WslExe, '--import "' + DistroNameValue + '" "' + DistroDir + '" "'
        + ImportPath + '" --version 2', Code) and (Code = 0)) then
    begin
      Result := 'The LanEx environment could not be created.' + #13#10#13#10
        + 'Last lines of the log:' + #13#10 + LogTail(10) + #13#10
        + 'Full log: ' + LogFile;
      Exit;
    end;
    Worker := ExpandConstant('{tmp}\setup.ps1');
    if not PowerShellCapture('& ' + PSQuote(Worker) + ' -Action BindAppliance -StatePath '
        + PSQuote(StateFile), Output) then
    begin
      Result := 'The LanEx environment was imported, but Setup could not bind its '
        + 'exact Windows registration identity.' + #13#10#13#10 + Output
        + #13#10#13#10 + 'It was left intact for a safe retry.';
      Exit;
    end;
  end;

  // 5. A no-op Repair proves owner/build identity and runs the appliance
  // self-test without invoking pip or apt. Only a failed health check re-enters
  // idempotent provisioning; an identity mismatch is never overwritten.
  NeedProvision := True;
  if RepairExisting then
  begin
    if not VerifyRepairIdentity(IdentityFailure) then
    begin
      Result := 'The registered environment does not match this saved LanEx '
        + 'installation.' + #13#10#13#10 + IdentityFailure
        + #13#10#13#10 + 'It was left untouched.';
      Exit;
    end;
    if HealthyRepairNeedsNoChanges then
    begin
      NeedProvision := False;
      LogLine('repair verified exact identity and health; no dependencies changed');
    end;
  end;

  // 6. Provision a new or unhealthy-but-owned appliance.
  if NeedProvision then
  begin
    Result := ProvisionDistro;
    if Result <> '' then
      Exit;
  end;
  MarkAppComplete;

  // 7. Restart ONLY the owner-bound appliance, then run the shared strict
  //    finalizer after systemd and Docker are reachable. The finalizer executes
  //    as the appliance user and exits nonzero until every saved selection is
  //    operational; image/PDK caches and completed work survive Retry.
  SetStatus('Restarting the private LanEx environment...');
  if not (RunLogged(WslExe, '--terminate "' + DistroNameValue + '"', Code) and (Code = 0)) then
  begin
    Result := 'Windows could not restart the owner-bound LanEx environment.'
      + #13#10#13#10 + 'No other WSL distribution was stopped.' + #13#10#13#10
      + LogTail(10);
    Exit;
  end;
  Result := FinalizeDistro;
  if Result <> '' then
    Exit;
  if not MarkSelectionsComplete then
  begin
    Result := 'The selected components are ready, but Setup could not save their '
      + 'owner-bound completion checkpoint. The appliance and all data were preserved.';
    Exit;
  end;
  Worker := ExpandConstant('{tmp}\setup.ps1');
  if not PowerShellCapture('& ' + PSQuote(Worker) + ' -Action ClearResume -StatePath '
      + PSQuote(StateFile), Output) then
    LogLine('WARNING: could not clear owned continuation shortcut: ' + Output);
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
  Result := IsContinuationRun and
            ((PageID = wpWelcome) or (PageID = wpLicense) or (PageID = wpSelectTasks));
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and not WslPending then
    // Setup now closes selected readiness before presenting Finish; the Tools
    // page remains available for later additions/removal and diagnostics.
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10
      + 'Your selected tools, container image, and PDK libraries were installed '
      + 'and passed LanEx''s setup readiness checks.';
end;

// ------------------------------------------------------------------ uninstall --

procedure OpenProjectFolder;
var
  Code: Integer;
begin
  ShellExec('open', DistroProjectPath(''), '', '',
            SW_SHOWNORMAL, ewNoWait, Code);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep <> usUninstall then
    Exit;

  // M1 safety foundation: Windows removes the launcher only. The owned WSL
  // appliance, projects, PDKs, installer state, caches, and the pre-existing
  // browser profile are deliberately preserved until the later uninstall UI
  // can offer verified export plus an explicit, identity-checked data removal.
  MsgBox('LanEx will remove its Windows shortcuts and launcher. Your LanEx '
    + 'environment, projects, PDKs, and run results will be kept so they can be '
    + 'reused by a later install.' + #13#10#13#10
    + 'No other WSL distribution or Windows WSL feature will be changed.',
    mbInformation, MB_OK);

  // Deliberately NOT undone: the Windows Subsystem for Linux feature. It is a
  // machine-wide setting other software may now rely on, and turning it off
  // would need another reboot. Documented in docs/INSTALL.md; it is the one
  // trace we leave, and it is inert.
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Config: String;
begin
  if CurStep <> ssPostInstall then
    Exit;
  Config := '{"schema":1,"installId":"' + InstallIdValue
    + '","distroName":"' + DistroNameValue
    + '","sourceSha":"{#LanexSourceSha}","manifestHash":"'
    + ManifestHashValue + '"}' + #13#10;
  if not SaveStringToFile(ExpandConstant('{app}\appliance.json'), Config, False) then
    LogLine('WARNING: could not write launcher appliance identity');
end;
