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
#ifndef AppVersionNumeric
  #define AppVersionNumeric AppVersion
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
#define LanexWheelFile ExtractFileName(LanexWheel)
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
; container. Candidate bundles place that verified image beside Setup; an
; explicitly staged release may also give Setup the immutable asset URL:
;
;   iscc /DBakedRootfsUrl=https://.../lanex-rootfs-amd64.tar.gz ^
;        /DBakedRootfsSha256=<hash> /DBakedRootfsSizeMB=<n> lanex.iss
;
; Undefined — ordinary push/PR and local builds — Setup uses the bare path.
; A dispatch candidate can use /DCompanionRootfsSha256 without inventing a
; release URL: the adjacent image is hash-checked before it reaches wsl import.
;
; At runtime the baked path is still only a preference. Setup verifies the hash,
; and on any failure at all (asset deleted, corrupt download, no route) it logs
; the reason and falls back to the Ubuntu image, which always works. A dead
; release asset can slow an install down; it can never brick one.
#ifndef BakedRootfsFile
  #define BakedRootfsFile "lanex-rootfs-amd64.tar.gz"
#endif
#ifndef BakedRootfsSizeMB
  #define BakedRootfsSizeMB "900"
#endif
#ifdef BakedRootfsUrl
  #ifndef BakedRootfsSha256
    #error BakedRootfsUrl requires BakedRootfsSha256 (an unverified rootfs is not shippable)
  #endif
#endif
#ifdef CompanionRootfsSha256
  #if Len(CompanionRootfsSha256) != 64
    #error CompanionRootfsSha256 must be a SHA256 digest
  #endif
#endif

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
; Windows' binary version is numeric, while candidate identities retain their
; full prerelease text in the version string resource and uninstall metadata.
VersionInfoVersion={#AppVersionNumeric}
VersionInfoProductVersion={#AppVersionNumeric}
VersionInfoTextVersion={#AppVersion}
VersionInfoProductTextVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
LicenseFile={#RepoRoot}LICENSE
OutputBaseFilename=LanEx-Setup
SetupIconFile={#IconFile}
WizardImageFile=..\launcher\assets\wizard.bmp
WizardSmallImageFile=..\launcher\assets\wizard-small.bmp
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
AllowCancelDuringInstall=yes
; WSL 2 is 64-bit only. x64compatible also covers ARM64 running x64 code, but
; the launcher is x64 (see windows/launcher/wsl.go) so the appliance is too.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; WSL 2 needs Windows 10 2004 (build 19041). Enforced here so the friendly
; message below is the first thing an unsupported machine sees.
MinVersion=10.0.19044
; The launcher mutex is dynamically scoped to owner SID + install + appliance,
; so a second Windows user cannot block this per-user Setup. Provisioning and
; uninstall still terminate only the exact owner-bound appliance when needed.
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
WelcomeLabel2=This will install [name/ver] on your computer.%n%nLanEx sets up its own private, self-contained environment. It preserves your existing WSL distributions and their data. If required, Windows asks separately before Setup enables WSL features or updates WSL.%n%nRemoving the Windows app preserves your projects and environment by default.%n%nBefore installing, Setup shows an honest estimate for your selected tools and PDKs. Actual download and disk use varies with reusable caches and selected libraries.


[Files]
#ifdef EmbeddedRootfs
Source: "{#LanexRootfs}"; DestName: "{#BakedRootfsFile}"; Flags: dontcopy
#endif
Source: "{#LauncherExe}"; DestDir: "{app}"; DestName: "LanEx.exe"; Flags: ignoreversion
Source: "{#IconFile}"; DestDir: "{app}"; DestName: "lanex.ico"; Flags: ignoreversion
; provision.sh is never installed: it runs once, inside the distro, from {tmp}.
; dontcopy + ExtractTemporaryFile is what lets PrepareToInstall use it before
; the file-copy step has happened at all.
Source: "..\provision\provision.sh"; Flags: dontcopy
Source: "..\provision\selftest.sh"; Flags: dontcopy
Source: "{#RepoRoot}scripts\install.sh"; Flags: dontcopy
Source: "..\setup\setup.ps1"; Flags: dontcopy
; The data-only worker remains available to the uninstaller for owner/marker
; validation, verified export, resume cleanup, and explicit removal.
Source: "..\setup\setup.ps1"; DestDir: "{app}"; DestName: "setup-worker.ps1"; Flags: ignoreversion
Source: "..\setup\constraints.txt"; Flags: dontcopy
Source: "..\setup\build-manifest.json"; Flags: dontcopy
Source: "{#LanexWheel}"; DestName: "{#LanexWheelFile}"; Flags: dontcopy

#define AppGroupName "LanEx (EDA)"

[Icons]
Name: "{userprograms}\{#AppGroupName}\{#AppName}"; Filename: "{app}\LanEx.exe"; IconFilename: "{app}\lanex.ico"
; A shortcut straight into the appliance's home directory. Small feature, large
; payoff: it proves to the user that their designs are ordinary files on their
; own PC, not something sealed inside a black box.
Name: "{userprograms}\{#AppGroupName}\{#AppName} Project Files"; Filename: "{code:DistroProjectPath}"; IconFilename: "{app}\lanex.ico"
Name: "{userprograms}\{#AppGroupName}\Repair {#AppName}"; Filename: "{localappdata}\{#DataDirName}\installer-cache\LanEx-Setup.exe"; Parameters: "/REPAIR=1"; IconFilename: "{app}\lanex.ico"


[Run]
Filename: "{app}\LanEx.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent; Check: InstallCompleted

[Code]
type
  TMsg = record
    hwnd: HWND;
    message: UINT;
    wParam: LongInt;
    lParam: LongInt;
    time: DWORD;
    pt: TPoint;
  end;

function PeekMessage(var lpMsg: TMsg; hWnd: HWND; wMsgFilterMin, wMsgFilterMax, wRemoveMsg: UINT): BOOL;
  external 'PeekMessageW@user32.dll stdcall';
function TranslateMessage(const lpMsg: TMsg): BOOL;
  external 'TranslateMessage@user32.dll stdcall';
function DispatchMessage(const lpMsg: TMsg): LongInt;
  external 'DispatchMessageW@user32.dll stdcall';

procedure ProcessSystemMessages;
var
  Msg: TMsg;
begin
  while PeekMessage(Msg, 0, 0, 0, 1) do
  begin
    TranslateMessage(Msg);
    DispatchMessage(Msg);
  end;
end;

function SetProcessEnvironmentVariable(lpName, lpValue: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';
function SetTimer(hWnd, nIDEvent, uElapse, lpTimerFunc: LongWord): LongWord;
  external 'SetTimer@user32.dll stdcall';
function KillTimer(hWnd, nIDEvent: LongWord): Boolean;
  external 'KillTimer@user32.dll stdcall';
function GetTickCount: LongWord;
  external 'GetTickCount@kernel32.dll stdcall';

var
  // Set in InitializeSetup, read in PrepareToInstall.
  RepairExisting: Boolean;   // a lanex distro is already there: keep its data
  UpdateExisting: Boolean;   // explicit manifest change with rollback checkpoint
  // True when Setup stopped early to reboot for WSL; suppresses the "Launch
  // LanEx" checkbox, because nothing has been provisioned yet.
  WslPending: Boolean;
  // Which image `wsl --import` will read. Set by EnsureRootfs — the pre-baked
  // appliance when this build has one and it downloaded cleanly, the pinned
  // Ubuntu image otherwise.
  ImportPath: String;
  DistroNameValue: String;
  InstallIdValue: String;
  OwnerSidValue: String;
  ManifestHashValue: String;
  PreflightDecision: String;
  BootIdentityValue: String;
  ComputerDisplayValue: String;
  FirmwareNoticeValue: Boolean;
  ConfigurePage: TWizardPage;
  ProfileRadioRecommended, ProfileRadioCustom, ProfileRadioMinimal: TRadioButton;
  ProfileDescLabel: TLabel;
  CustomCheckListBox: TNewCheckListBox;
  SummaryPanel: TPanel;
  SummaryDivider: TBevel;
  SummaryDownloadLabel, SummaryDiskLabel, SummaryStatusLabel: TLabel;
  DesktopShortcutCheckbox: TNewCheckBox;
  ProgressContainer: TPanel;
  ProgressPhaseLabel: TLabel;
  DistroBasePathValue: String;
  LiveLogMemo: TNewMemo;
  OpenLogButton, CopyLogButton, SaveLogButton: TNewButton;
  IdxDocker, IdxPodman: Integer;
  IdxImage, IdxNative, IdxGds3d: Integer;
  IdxSky130A, IdxSky130B, IdxSkyNone: Integer;
  IdxGfNone, IdxGf180A, IdxGf180B, IdxGf180C, IdxGf180D: Integer;
  IdxIhp: Integer;
  IdxSkyHdll, IdxSkyLp, IdxSkyLs, IdxSkyMs, IdxSkyHs, IdxSkyReram: Integer;
  ChoicesJsonValue, ChoicesPathValue: String;
  EstimateDownloadMB, EstimateInstalledMB, RequiredAppMB, RequiredTempMB: Int64;
  ProgressPhase, ProgressPhaseCount: Integer;
  ProgressActivity: String;
  ProgressStartedTick: LongWord;
  ProgressTimer: LongWord;
  CancelRequested: Boolean;
  BaseProvisionedForEstimate: Boolean;
  EstimateReuseApplied: Boolean;

// ---------------------------------------------------------------- locations --

// Setup-owned state lives under one root, but the historical lowercase LanEx
// browser profile aliases it on Windows. Explicit erase therefore removes only
// identity-scoped paths and never recursively deletes this whole root.
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
function BakedRootfsPath: String; begin Result := CacheDir + '\{#BakedRootfsFile}'; end;

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

procedure RotateInstallLog;
var
  Size: Integer;
begin
  ForceDirectories(LogDir);
  if FileSize(LogFile, Size) and (Size > 5 * 1024 * 1024) then
  begin
    DeleteFile(LogDir + '\install.previous.log');
    RenameFile(LogFile, LogDir + '\install.previous.log');
  end;
end;

function ElapsedText: String;
var
  Seconds: LongWord;
begin
  if ProgressStartedTick = 0 then
    Result := '0:00'
  else
  begin
    Seconds := (GetTickCount - ProgressStartedTick) div 1000;
    Result := IntToStr(Seconds div 60) + ':' + Format('%.2d', [Seconds mod 60]);
  end;
end;

procedure RefreshProgressCaption;
var
  Caption: String;
begin
  if ProgressActivity = '' then Exit;
  Caption := ProgressActivity;
  if ProgressStartedTick > 0 then
    Caption := Caption + '  (' + ElapsedText + ')';
  if WizardForm <> nil then
  begin
    WizardForm.PreparingLabel.Caption := Caption;
    WizardForm.PreparingLabel.Update;
    WizardForm.StatusLabel.Caption := Caption;
    WizardForm.StatusLabel.Update;
  end;
end;

procedure AppendLiveLine(const S: String);
begin
  if (LiveLogMemo = nil) or WizardSilent then Exit;
  LiveLogMemo.Lines.Add(S);
  while LiveLogMemo.Lines.Count > 400 do
    LiveLogMemo.Lines.Delete(0);
  LiveLogMemo.SelStart := Length(LiveLogMemo.Text);
  LiveLogMemo.Update;
end;

procedure SetPhase(Number, Total: Integer; const S: String);
begin
  ProgressPhase := Number;
  ProgressPhaseCount := Total;
  ProgressActivity := S;
  RefreshProgressCaption;
  if ProgressPhaseLabel <> nil then
  begin
    ProgressPhaseLabel.Caption := 'Phase ' + IntToStr(Number) + ' of ' + IntToStr(Total) + ': ' + S;
    ProgressPhaseLabel.Update;
  end;
  AppendLiveLine('--- Phase ' + IntToStr(Number) + '/' + IntToStr(Total) + ': ' + S);
  LogLine('--- phase ' + IntToStr(Number) + '/' + IntToStr(Total) + ': ' + S);
end;

procedure SetStatus(const S: String);
begin
  ProgressActivity := S;
  RefreshProgressCaption;
  if ProgressPhaseLabel <> nil then
  begin
    ProgressPhaseLabel.Caption := S;
    ProgressPhaseLabel.Update;
  end;
  AppendLiveLine('--- ' + S);
  LogLine('--- ' + S);
end;

procedure ProgressTimerProc(HWnd, Msg, IdEvent, Time: LongWord);
begin
  RefreshProgressCaption;
end;

function StripNulls(const S: String): String; forward;

function ProgressMessage(const Line: String): String;
var
  Marker, Rest: String;
  P: Integer;
begin
  Result := '';
  Marker := '"message":"';
  P := Pos(Marker, Line);
  if P = 0 then Exit;
  Rest := Copy(Line, P + Length(Marker), Length(Line));
  P := Pos('"', Rest);
  if P > 0 then Result := Copy(Rest, 1, P - 1);
end;

procedure CommandOutput(const S: String; const Error, FirstLine: Boolean);
var
  Line: String;
begin
  Line := Trim(StripNulls(S));
  if Error then Line := 'Output reader error: ' + Line;
  if Line = '' then Exit;
  LogLine(Line);
  AppendLiveLine(Line);
  if (Pos('@@LANEX:', Line) = 1) and (ProgressMessage(Line) <> '') then
    ProgressActivity := ProgressMessage(Line)
  else
    ProgressActivity := Copy(Line, 1, 140);
  RefreshProgressCaption;
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
    if (S[I] <> #0) and (Ord(S[I]) <> $FEFF) and (Ord(S[I]) <> $FFFE) then
      Result := Result + S[I];
  while (Length(Result) > 0) and ((Ord(Result[1]) = $FEFF) or (Ord(Result[1]) = $FFFE)) do
    Delete(Result, 1, 1);
  if (Length(Result) >= 3) and (Ord(Result[1]) = $EF) and (Ord(Result[2]) = $BB) and (Ord(Result[3]) = $BF) then
    Delete(Result, 1, 3);
end;

// PowerShellCapture runs a snippet and returns everything it printed.
// Inno's Exec cannot capture output, hence the temp file. PowerShell rather than
// cmd because the facts we need (HypervisorPresent, an optional feature's state)
// have no plain-command equivalent.
function PowerShellCapture(const Snippet: String; var Output: String): Boolean;
var
  OutFile, ScriptFile, Params: String;
  Raw: AnsiString;
  Code: Integer;
begin
  Output := '';
  OutFile := ExpandConstant('{tmp}\ps-capture.txt');
  ScriptFile := ExpandConstant('{tmp}\ps-runner.ps1');
  DeleteFile(OutFile);
  DeleteFile(ScriptFile);
  SaveStringToFile(ScriptFile,
    '$OutputEncoding = [System.Text.Encoding]::UTF8;' + #13#10 +
    '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;' + #13#10 +
    '$utf8NoBom = New-Object System.Text.UTF8Encoding($false);' + #13#10 +
    'try {' + #13#10 +
    '  $res = & { ' + Snippet + ' }' + #13#10 +
    '  if ($null -ne $res) { [IO.File]::WriteAllText(''' + OutFile + ''', ($res | Out-String), $utf8NoBom) }' + #13#10 +
    '} catch {' + #13#10 +
    '  [IO.File]::WriteAllText(''' + OutFile + ''', ($_.ToString() + [Environment]::NewLine + $_.ScriptStackTrace), $utf8NoBom);' + #13#10 +
    '  exit 1;' + #13#10 +
    '}' + #13#10, False);
  Params := '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + ScriptFile + '"';
  Result := Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
  if FileExists(OutFile) and LoadStringFromFile(OutFile, Raw) then
    Output := Trim(StripNulls(String(Raw)));
  DeleteFile(ScriptFile);
end;

// Output is consumed line-by-line using non-blocking execution so the wizard
// remains responsive, draggable, minimizable, and log-selectable throughout.
function RunLogged(const FileName, Params: String; var ResultCode: Integer): Boolean;
var
  PreviousWslEnv, ForwardedWslEnv, BatFile, OutFile, DoneFile, ExitCodeStr, Line: String;
  Raw: AnsiString;
  LastPos, CurrLen, DummyCode, P, NextNL: Integer;
begin
  ForceDirectories(LogDir);
  LogLine('$ ' + FileName + ' ' + Params);
  PreviousWslEnv := GetEnv('WSLENV');
  ForwardedWslEnv := 'HTTP_PROXY:HTTPS_PROXY:NO_PROXY:http_proxy:https_proxy:no_proxy';
  if PreviousWslEnv <> '' then
    ForwardedWslEnv := PreviousWslEnv + ':' + ForwardedWslEnv;
  SetProcessEnvironmentVariable('WSLENV', ForwardedWslEnv);
  try
    SetProcessEnvironmentVariable('WSL_UTF8', '1');
    BatFile := ExpandConstant('{tmp}\lanex_exec.bat');
    OutFile := ExpandConstant('{tmp}\lanex_exec.log');
    DoneFile := ExpandConstant('{tmp}\lanex_exec.done');
    DeleteFile(BatFile);
    DeleteFile(OutFile);
    DeleteFile(DoneFile);

    SaveStringToFile(BatFile,
      '@echo off' + #13#10 +
      'chcp 65001 >nul' + #13#10 +
      'set WSL_UTF8=1' + #13#10 +
      'set COLUMNS=120' + #13#10 +
      'set LINES=40' + #13#10 +
      'set TERM=dumb' + #13#10 +
      'call "' + FileName + '" ' + Params + ' >> "' + OutFile + '" 2>&1' + #13#10 +
      'echo %errorlevel% > "' + DoneFile + '"' + #13#10, False);

    Exec(ExpandConstant('{cmd}'), '/c ""' + BatFile + '""', '', SW_HIDE, ewNoWait, DummyCode);

    LastPos := 1;
    while not FileExists(DoneFile) do
    begin
      Sleep(50);
      ProcessSystemMessages;
      if FileSize(OutFile, CurrLen) and (CurrLen >= LastPos) then
      begin
        if LoadStringFromFile(OutFile, Raw) then
        begin
          CurrLen := Length(Raw);
          if CurrLen >= LastPos then
          begin
            P := LastPos;
            while P <= CurrLen do
            begin
              NextNL := P;
              while (NextNL <= CurrLen) and (Raw[NextNL] <> #10) do
                NextNL := NextNL + 1;
              if NextNL <= CurrLen then
              begin
                Line := Copy(String(Raw), P, NextNL - P);
                CommandOutput(Line, False, False);
                P := NextNL + 1;
                LastPos := P;
              end
              else
                Break;
            end;
          end;
        end;
      end;
      RefreshProgressCaption;
    end;

    // Drain any remaining output lines
    if FileExists(OutFile) and LoadStringFromFile(OutFile, Raw) then
    begin
      CurrLen := Length(Raw);
      if CurrLen >= LastPos then
      begin
        Line := Copy(String(Raw), LastPos, CurrLen - LastPos + 1);
        if Trim(Line) <> '' then
          CommandOutput(Line, False, False);
      end;
    end;

    ResultCode := -1;
    if FileExists(DoneFile) and LoadStringFromFile(DoneFile, Raw) then
    begin
      ExitCodeStr := Trim(String(Raw));
      ResultCode := StrToIntDef(ExitCodeStr, -1);
    end;

    DeleteFile(BatFile);
    DeleteFile(OutFile);
    DeleteFile(DoneFile);
    Result := (ResultCode = 0);
  finally
    SetProcessEnvironmentVariable('WSL_UTF8', '');
    SetProcessEnvironmentVariable('WSLENV', PreviousWslEnv);
  end;
end;

// ExecAndLogOutput is preserved as the streaming execution interface.
// Child processes run under RunLogged with message pumping to keep the UI responsive.
function ExecAndLogOutput(const FileName, Params, WorkingDir: String; ShowCmd: Integer;
  Wait: TExecWait; var ResultCode: Integer): Boolean;
begin
  Result := RunLogged(FileName, Params, ResultCode);
end;

function ProxyFailureHint: String;
var
  PacUrl: String;
begin
  Result := '';
  if (GetEnv('HTTP_PROXY') <> '') or (GetEnv('HTTPS_PROXY') <> '') or
     (GetEnv('http_proxy') <> '') or (GetEnv('https_proxy') <> '') then
    Exit;
  if RegQueryStringValue(HKCU,
       'Software\Microsoft\Windows\CurrentVersion\Internet Settings',
       'AutoConfigURL', PacUrl) and (PacUrl <> '') then
    Result := #13#10#13#10 + 'Windows is configured with an automatic proxy (PAC) file. '
      + 'Linux command-line downloads cannot use a PAC URL directly; ask your administrator '
      + 'for an explicit HTTPS proxy URL. The PAC address and proxy credentials are not logged.';
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
  Text, Line, Target: String;
  P: Integer;
begin
  Result := False;
  Target := Trim(StripNulls(DistroNameValue));
  if Target = '' then Exit;
  Text := ListedDistros + #10;
  // Hand-rolled line split: Inno's StringSplit helpers are 6.3-only, and this
  // parser has to work on whatever version a contributor has installed.
  repeat
    P := Pos(#10, Text);
    if P = 0 then
      Break;      // cannot happen (a #10 is appended above), but never loop forever
    Line := Trim(StripNulls(Copy(Text, 1, P - 1)));
    Text := Copy(Text, P + 1, Length(Text) - P);
    if CompareText(Line, Target) = 0 then
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
    Result := Trim(StripNulls(Text));
    Text := '';
  end
  else
  begin
    Result := Trim(StripNulls(Copy(Text, 1, P - 1)));
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

function PdkName(Index: Integer): String;
begin
  case Index of
    0: Result := 'sky130A';
    1: Result := 'sky130B';
    2: Result := 'gf180mcuA';
    3: Result := 'gf180mcuB';
    4: Result := 'gf180mcuC';
    5: Result := 'gf180mcuD';
    6: Result := 'ihp-sg13g2';
  else
    Result := '';
  end;
end;

procedure AddJsonString(var List: String; const Value: String);
begin
  if List <> '' then List := List + ',';
  List := List + '"' + Value + '"';
end;

function BuildChoicesJson: String;
var
  Native, Libraries, PdkList, SkyVariant, GfVariant, VariantLibs: String;
begin
  if (ProfileRadioRecommended <> nil) and ProfileRadioRecommended.Checked then
  begin
    Result := '{"profile":"recommended"}';
    Exit;
  end;

  if (ProfileRadioMinimal <> nil) and ProfileRadioMinimal.Checked then
  begin
    Result := '{"schema":1,"profile":"minimal","engine":"none","image":false,"nativeTools":[],"pdks":[],"libraries":{}}';
    Exit;
  end;

  Native := '';
  if (CustomCheckListBox <> nil) and CustomCheckListBox.Checked[IdxNative] then
  begin
    AddJsonString(Native, 'verilator');
    AddJsonString(Native, 'iverilog');
    AddJsonString(Native, 'graphviz');
    AddJsonString(Native, 'gtkwave');
  end;
  if (CustomCheckListBox <> nil) and CustomCheckListBox.Checked[IdxGds3d] then AddJsonString(Native, 'gds3d');

  SkyVariant := '';
  if (CustomCheckListBox <> nil) then
  begin
    if CustomCheckListBox.Checked[IdxSky130A] then SkyVariant := 'sky130A'
    else if CustomCheckListBox.Checked[IdxSky130B] then SkyVariant := 'sky130B';
  end;

  GfVariant := '';
  if (CustomCheckListBox <> nil) then
  begin
    if CustomCheckListBox.Checked[IdxGf180A] then GfVariant := 'gf180mcuA'
    else if CustomCheckListBox.Checked[IdxGf180B] then GfVariant := 'gf180mcuB'
    else if CustomCheckListBox.Checked[IdxGf180C] then GfVariant := 'gf180mcuC'
    else if CustomCheckListBox.Checked[IdxGf180D] then GfVariant := 'gf180mcuD';
  end;

  Libraries := '';
  if (CustomCheckListBox <> nil) and (SkyVariant <> '') then
  begin
    VariantLibs := '';
    if CustomCheckListBox.Checked[IdxSkyHdll] then AddJsonString(VariantLibs, 'sky130_fd_sc_hdll');
    if CustomCheckListBox.Checked[IdxSkyLp] then AddJsonString(VariantLibs, 'sky130_fd_sc_lp');
    if CustomCheckListBox.Checked[IdxSkyLs] then AddJsonString(VariantLibs, 'sky130_fd_sc_ls');
    if CustomCheckListBox.Checked[IdxSkyMs] then AddJsonString(VariantLibs, 'sky130_fd_sc_ms');
    if CustomCheckListBox.Checked[IdxSkyHs] then AddJsonString(VariantLibs, 'sky130_fd_sc_hs');
    if (SkyVariant = 'sky130B') and CustomCheckListBox.Checked[IdxSkyReram] then
      AddJsonString(VariantLibs, 'sky130_fd_pr_reram');
    Libraries := '"' + SkyVariant + '":[' + VariantLibs + ']';
  end;

  if (CustomCheckListBox <> nil) and (GfVariant <> '') then
  begin
    if Libraries <> '' then Libraries := Libraries + ',';
    Libraries := Libraries + '"' + GfVariant + '":[]';
  end;

  if (CustomCheckListBox <> nil) and CustomCheckListBox.Checked[IdxIhp] then
  begin
    if Libraries <> '' then Libraries := Libraries + ',';
    Libraries := Libraries + '"ihp-sg13g2":[]';
  end;

  PdkList := '';
  if SkyVariant <> '' then AddJsonString(PdkList, SkyVariant);
  if GfVariant <> '' then AddJsonString(PdkList, GfVariant);
  if (CustomCheckListBox <> nil) and CustomCheckListBox.Checked[IdxIhp] then AddJsonString(PdkList, 'ihp-sg13g2');

  Result := '{"schema":1,"profile":"custom","engine":"';
  if (CustomCheckListBox <> nil) and CustomCheckListBox.Checked[IdxPodman] then Result := Result + 'podman'
  else Result := Result + 'docker';
  Result := Result + '","image":';
  if (CustomCheckListBox <> nil) and (CustomCheckListBox.Checked[IdxImage] or (PdkList <> '')) then
    Result := Result + 'true'
  else
    Result := Result + 'false';
  Result := Result + ',"nativeTools":[' + Native + '],"pdks":[' + PdkList + '],"libraries":{' + Libraries + '}}';
end;

function ValidatePdkFamilies(var Failure: String): Boolean;
begin
  Result := True;
  Failure := '';
end;

function PlanSelections(const InputJson, InputPath: String; var Failure: String): Boolean;
var
  Worker, Manifest, Snippet, Output, StagedChoices: String;
begin
  Result := False;
  Failure := '';
  ExtractTemporaryFile('setup.ps1');
  ExtractTemporaryFile('build-manifest.json');
  Worker := ExpandConstant('{tmp}\setup.ps1');
  Manifest := ExpandConstant('{tmp}\build-manifest.json');
  Snippet := '$p=(& ' + PSQuote(Worker) + ' -Action PlanChoices -ManifestPath ' +
    PSQuote(Manifest);
  if InputPath <> '' then
    Snippet := Snippet + ' -ChoicesPath ' + PSQuote(InputPath)
  else
  begin
    // PowerShell's raw -Command command line is parsed by Windows before
    // PowerShell sees single-quoted JSON. Embedded double quotes can therefore
    // disappear even though PSQuote is correct PowerShell syntax. Stage JSON in
    // a UTF-8 file and pass only its quoted path across the process boundary.
    StagedChoices := ExpandConstant('{tmp}\choices-input.json');
    if not SaveStringToFile(StagedChoices, InputJson, False) then
    begin
      Failure := 'Setup could not stage the selected component choices.';
      Exit;
    end;
    Snippet := Snippet + ' -ChoicesPath ' + PSQuote(StagedChoices);
  end;
  Snippet := Snippet + ' | ConvertFrom-Json); ' +
    '($p.choices|ConvertTo-Json -Depth 30 -Compress); ' +
    '[math]::Ceiling($p.estimates.downloadBytes/1MB); ' +
    '[math]::Ceiling($p.estimates.installedBytes/1MB); ' +
    '[math]::Ceiling($p.estimates.volumes.appDataRequiredBytes/1MB); ' +
    '[math]::Ceiling($p.estimates.volumes.tempRequiredBytes/1MB); ' +
    '[math]::Ceiling($p.estimates.reusedInstalledBytes/1MB)';
  if not PowerShellCapture(Snippet, Output) then
  begin
    Failure := Output;
    Exit;
  end;
  ChoicesJsonValue := TakeLine(Output);
  try
    EstimateDownloadMB := StrToInt64(TakeLine(Output));
    EstimateInstalledMB := StrToInt64(TakeLine(Output));
    RequiredAppMB := StrToInt64(TakeLine(Output));
    RequiredTempMB := StrToInt64(TakeLine(Output));
    EstimateReuseApplied := StrToInt64(TakeLine(Output)) > 0;
    Result := ChoicesJsonValue <> '';
  except
    Failure := 'The selection estimate returned an invalid value.';
  end;
end;

function CheckSelectionSpace(var Failure: String): Boolean;
var
  AppFree, AppTotal, TempFree, TempTotal: Cardinal;
  AppNeed, TempNeed: Int64;
  RootfsFileSize: Integer;
begin
  Result := True;
  Failure := '';
  AppNeed := RequiredAppMB;
  TempNeed := RequiredTempMB;
  if BaseProvisionedForEstimate and not EstimateReuseApplied then
  begin
    AppNeed := AppNeed - 1332 - {#RootfsSizeMB};
    TempNeed := 0;
    if AppNeed < 0 then AppNeed := 0;
  end
  else if FileExists(RootfsPath) and FileSize(RootfsPath, RootfsFileSize) and
     (RootfsFileSize >= 300 * 1024 * 1024) then
  begin
    AppNeed := AppNeed - {#RootfsSizeMB};
    TempNeed := 0;
  end;
  if CompareText(ExtractFileDrive(AppDataRoot), ExtractFileDrive(ExpandConstant('{tmp}'))) = 0 then
  begin
    if not GetSpaceOnDisk(AppDataRoot, True, AppFree, AppTotal) then
    begin
      Failure := 'Setup could not determine available disk space on ' + ExtractFileDrive(AppDataRoot) + '.';
      Result := False;
    end
    else if (Int64(AppFree) < AppNeed + TempNeed) then
    begin
      Failure := 'The selected setup needs about ' + IntToStr(AppNeed + TempNeed) +
        ' MB free on ' + ExtractFileDrive(AppDataRoot) + ', but only ' +
        IntToStr(AppFree) + ' MB is available.';
      Result := False;
    end;
  end
  else
  begin
    if not GetSpaceOnDisk(AppDataRoot, True, AppFree, AppTotal) then
    begin
      Failure := 'Setup could not determine available disk space on ' + ExtractFileDrive(AppDataRoot) + '.';
      Result := False;
      Exit;
    end
    else if (Int64(AppFree) < AppNeed) then
    begin
      Failure := 'The selected setup needs about ' + IntToStr(AppNeed) +
        ' MB free for the LanEx environment, but only ' + IntToStr(AppFree) + ' MB is available.';
      Result := False;
      Exit;
    end;
    if not GetSpaceOnDisk(ExpandConstant('{tmp}'), True, TempFree, TempTotal) then
    begin
      Failure := 'Setup could not determine available disk space on ' + ExtractFileDrive(ExpandConstant('{tmp}')) + '.';
      Result := False;
    end
    else if (Int64(TempFree) < TempNeed) then
    begin
      Failure := 'Setup needs about ' + IntToStr(TempNeed) +
        ' MB temporarily on ' + ExtractFileDrive(ExpandConstant('{tmp}')) + '.';
      Result := False;
    end;
  end;
end;

procedure OpenDiagnostics(Sender: TObject);
var
  Code: Integer;
begin
  ShellExec('open', LogFile, '', '', SW_SHOWNORMAL, ewNoWait, Code);
end;

procedure CopyDiagnostics(Sender: TObject);
var
  Output: String;
begin
  if PowerShellCapture('Get-Content -LiteralPath ' + PSQuote(LogFile) +
      ' -Raw | Set-Clipboard; ''copied''', Output) then
    MsgBox('Diagnostics copied to the clipboard.', mbInformation, MB_OK)
  else
    MsgBox('Windows could not copy the log. Use Open log or Save log instead.', mbError, MB_OK);
end;

procedure SaveDiagnostics(Sender: TObject);
var
  Folder, Target: String;
begin
  Folder := ExpandConstant('{userdocs}');
  if BrowseForFolder('Choose a folder for the LanEx diagnostics log.', Folder, True) then
  begin
    Target := AddBackslash(Folder) + 'LanEx-install-diagnostics-' +
      GetDateTimeString('yyyymmdd-hhnnss', '', '') + '.log';
    if FileCopy(LogFile, Target, False) then
      MsgBox('Diagnostics saved to:' + #13#10 + Target, mbInformation, MB_OK)
    else
      MsgBox('The diagnostics log could not be saved there.', mbError, MB_OK);
  end;
end;

procedure CalculateEstimatesFast;
var
  DownloadMB, InstalledMB, AppMB, TempMB, HeadroomMB, ExtractMB: Int64;
  PdkDownloadMB, PdkInstalledMB: Int64;
  HasNative, HasImage: Boolean;
  Failure: String;
begin
  if (ProfileRadioRecommended <> nil) and ProfileRadioRecommended.Checked then
  begin
    DownloadMB := 11200;
    InstalledMB := 38100;
    AppMB := 46000;
    TempMB := 0;
  end
  else if (ProfileRadioMinimal <> nil) and ProfileRadioMinimal.Checked then
  begin
    DownloadMB := 922;
    InstalledMB := 1332;
    AppMB := 2356;
    TempMB := 0;
  end
  else
  begin
    DownloadMB := 922;
    InstalledMB := 1332;
    TempMB := 0;

    HasNative := (CustomCheckListBox <> nil) and CustomCheckListBox.Checked[IdxNative];
    if HasNative then
    begin
      DownloadMB := DownloadMB + 717;
      InstalledMB := InstalledMB + 1229;
    end;

    PdkDownloadMB := 0;
    PdkInstalledMB := 0;
    if (CustomCheckListBox <> nil) then
    begin
      if CustomCheckListBox.Checked[IdxSky130A] or CustomCheckListBox.Checked[IdxSky130B] then
      begin
        PdkDownloadMB := PdkDownloadMB + 2560;
        PdkInstalledMB := PdkInstalledMB + 15800;
      end;
      if CustomCheckListBox.Checked[IdxGf180A] or CustomCheckListBox.Checked[IdxGf180B] or
         CustomCheckListBox.Checked[IdxGf180C] or CustomCheckListBox.Checked[IdxGf180D] then
      begin
        PdkDownloadMB := PdkDownloadMB + 1844;
        PdkInstalledMB := PdkInstalledMB + 8500;
      end;
      if CustomCheckListBox.Checked[IdxIhp] then
      begin
        PdkDownloadMB := PdkDownloadMB + 1946;
        PdkInstalledMB := PdkInstalledMB + 4000;
      end;
    end;

    HasImage := (CustomCheckListBox <> nil) and
      (CustomCheckListBox.Checked[IdxImage] or (PdkDownloadMB > 0));
    if HasImage then
    begin
      DownloadMB := DownloadMB + 3200;
      InstalledMB := InstalledMB + 7175;
      HeadroomMB := 4096;
    end
    else
      HeadroomMB := 1024;

    InstalledMB := InstalledMB + PdkInstalledMB;
    DownloadMB := DownloadMB + PdkDownloadMB;

    if HasImage then
      ExtractMB := ((3200 + PdkDownloadMB) * 35 + 99) div 100
    else
      ExtractMB := (PdkDownloadMB * 35 + 99) div 100;

    AppMB := InstalledMB + HeadroomMB + ExtractMB;
  end;

  EstimateDownloadMB := DownloadMB;
  EstimateInstalledMB := InstalledMB;
  RequiredAppMB := AppMB;
  RequiredTempMB := TempMB;

  if EstimateDownloadMB >= 1024 then
    SummaryDownloadLabel.Caption := 'Download required: about ' + IntToStr(EstimateDownloadMB div 1024) + '.' + IntToStr((EstimateDownloadMB mod 1024) * 10 div 1024) + ' GB (' + IntToStr(EstimateDownloadMB) + ' MB)'
  else
    SummaryDownloadLabel.Caption := 'Download required: about ' + IntToStr(EstimateDownloadMB) + ' MB';

  if RequiredAppMB >= 1024 then
    SummaryDiskLabel.Caption := 'Disk space required: about ' + IntToStr(RequiredAppMB div 1024) + '.' + IntToStr((RequiredAppMB mod 1024) * 10 div 1024) + ' GB'
  else
    SummaryDiskLabel.Caption := 'Disk space required: about ' + IntToStr(RequiredAppMB) + ' MB';

  if not CheckSelectionSpace(Failure) then
  begin
    SummaryStatusLabel.Caption := Failure;
    SummaryStatusLabel.Font.Color := clRed;
  end
  else
  begin
    SummaryStatusLabel.Caption := 'Sufficient disk space is available.';
    SummaryStatusLabel.Font.Color := clGreen;
  end;
end;

procedure UpdateEstimates;
begin
  CalculateEstimatesFast;
end;

procedure OnProfileOptionChange(Sender: TObject);
begin
  if ProfileRadioRecommended.Checked then
  begin
    ProfileDescLabel.Caption :=
      'Recommended Profile Overview:'#13#10#13#10 +
      '• Container Engine: Docker CE'#13#10 +
      '• EDA Tools: Verilator, Icarus Verilog, Graphviz, GTKWave, GDS3D'#13#10 +
      '• Technology: SkyWater 130 nm (sky130A), GlobalFoundries 180 nm (gf180mcuD), and IHP 130 nm BiCMOS (ihp-sg13g2)'#13#10 +
      '• Turnkey flow: Complete RTL-to-GDS flow ready out of the box.';
    ProfileDescLabel.Visible := True;
    CustomCheckListBox.Visible := False;
  end
  else if ProfileRadioMinimal.Checked then
  begin
    ProfileDescLabel.Caption :=
      'Minimal Profile Overview:'#13#10#13#10 +
      '• Installs the isolated LanEx application core and Python cockpit only.'#13#10 +
      '• Fastest installation with the smallest download and disk footprint.'#13#10 +
      '• EDA tools, container engine, and PDKs can be installed later on demand from the Tools tab.';
    ProfileDescLabel.Visible := True;
    CustomCheckListBox.Visible := False;
  end
  else
  begin
    ProfileDescLabel.Visible := False;
    CustomCheckListBox.Visible := True;
    CustomCheckListBox.BringToFront;
  end;
  UpdateEstimates;
end;

procedure OnCustomCheck(Sender: TObject);
begin
  if (CustomCheckListBox <> nil) then
  begin
    if CustomCheckListBox.Checked[IdxSky130B] then
      CustomCheckListBox.ItemEnabled[IdxSkyReram] := True
    else
    begin
      CustomCheckListBox.Checked[IdxSkyReram] := False;
      CustomCheckListBox.ItemEnabled[IdxSkyReram] := False;
    end;
  end;
  UpdateEstimates;
end;

function ExtractJsonStringValue(const Json, Key: String): String;
var
  P, QuoteStart, QuoteEnd, Len: Integer;
  SearchKey: String;
begin
  Result := '';
  SearchKey := '"' + Key + '"';
  P := Pos(SearchKey, Json);
  if P = 0 then Exit;
  Len := Length(Json);
  P := P + Length(SearchKey);
  while (P <= Len) and (Json[P] <> ':') do P := P + 1;
  if P > Len then Exit;
  P := P + 1;
  while (P <= Len) and ((Json[P] = ' ') or (Json[P] = #9) or (Json[P] = #10) or (Json[P] = #13)) do P := P + 1;
  if (P <= Len) and (Json[P] = '"') then
  begin
    QuoteStart := P + 1;
    P := QuoteStart;
    while (P <= Len) and (Json[P] <> '"') do
    begin
      if (Json[P] = '\') and (P < Len) then P := P + 1;
      P := P + 1;
    end;
    QuoteEnd := P;
    Result := Copy(Json, QuoteStart, QuoteEnd - QuoteStart);
  end;
end;

function ExtractJsonBoolValue(const Json, Key: String; DefaultVal: Boolean): Boolean;
var
  P, Len: Integer;
  SearchKey, Token: String;
begin
  Result := DefaultVal;
  SearchKey := '"' + Key + '"';
  P := Pos(SearchKey, Json);
  if P = 0 then Exit;
  Len := Length(Json);
  P := P + Length(SearchKey);
  while (P <= Len) and (Json[P] <> ':') do P := P + 1;
  if P > Len then Exit;
  P := P + 1;
  while (P <= Len) and ((Json[P] = ' ') or (Json[P] = #9) or (Json[P] = #10) or (Json[P] = #13)) do P := P + 1;
  Token := Lowercase(Copy(Json, P, 5));
  if Pos('true', Token) = 1 then Result := True
  else if Pos('false', Token) = 1 then Result := False;
end;

function ExtractJsonArrayContains(const Json, Key, Item: String): Boolean;
var
  P, ArrayStart, ArrayEnd, Len, Nesting: Integer;
  SearchKey, ArraySub, SearchItem: String;
begin
  Result := False;
  SearchKey := '"' + Key + '"';
  P := Pos(SearchKey, Json);
  if P = 0 then Exit;
  Len := Length(Json);
  P := P + Length(SearchKey);
  while (P <= Len) and (Json[P] <> ':') do P := P + 1;
  if P > Len then Exit;
  P := P + 1;
  while (P <= Len) and ((Json[P] = ' ') or (Json[P] = #9) or (Json[P] = #10) or (Json[P] = #13)) do P := P + 1;
  if (P <= Len) and (Json[P] = '[') then
  begin
    ArrayStart := P;
    P := P + 1;
    Nesting := 1;
    while (P <= Len) and (Nesting > 0) do
    begin
      if Json[P] = '[' then Nesting := Nesting + 1
      else if Json[P] = ']' then Nesting := Nesting - 1;
      P := P + 1;
    end;
    ArrayEnd := P - 1;
    ArraySub := Copy(Json, ArrayStart, ArrayEnd - ArrayStart + 1);
    SearchItem := '"' + Item + '"';
    Result := (Pos(SearchItem, ArraySub) > 0);
  end;
end;

procedure InitializeWizard;
var
  SavedProfile, StateContent: String;
  RawState: AnsiString;
begin
  ConfigurePage := CreateCustomPage(wpLicense, 'Configure LanEx',
    'Choose your installation profile and review disk requirements.');

  ProfileRadioRecommended := TRadioButton.Create(WizardForm);
  ProfileRadioRecommended.Parent := ConfigurePage.Surface;
  ProfileRadioRecommended.Left := ScaleX(4);
  ProfileRadioRecommended.Top := ScaleY(2);
  ProfileRadioRecommended.Width := ConfigurePage.Surface.ClientWidth - ScaleX(8);
  ProfileRadioRecommended.Height := ScaleY(20);
  ProfileRadioRecommended.Caption := '&Recommended — Docker, all supported tools, GDS3D, recommended PDKs';
  ProfileRadioRecommended.Font.Style := [fsBold];
  ProfileRadioRecommended.OnClick := @OnProfileOptionChange;

  ProfileRadioCustom := TRadioButton.Create(WizardForm);
  ProfileRadioCustom.Parent := ConfigurePage.Surface;
  ProfileRadioCustom.Left := ScaleX(4);
  ProfileRadioCustom.Top := ScaleY(24);
  ProfileRadioCustom.Width := ConfigurePage.Surface.ClientWidth - ScaleX(8);
  ProfileRadioCustom.Height := ScaleY(20);
  ProfileRadioCustom.Caption := '&Custom — choose engine, tools, PDK variants and advanced libraries';
  ProfileRadioCustom.Font.Style := [fsBold];
  ProfileRadioCustom.OnClick := @OnProfileOptionChange;

  ProfileRadioMinimal := TRadioButton.Create(WizardForm);
  ProfileRadioMinimal.Parent := ConfigurePage.Surface;
  ProfileRadioMinimal.Left := ScaleX(4);
  ProfileRadioMinimal.Top := ScaleY(46);
  ProfileRadioMinimal.Width := ConfigurePage.Surface.ClientWidth - ScaleX(8);
  ProfileRadioMinimal.Height := ScaleY(20);
  ProfileRadioMinimal.Caption := '&Minimal — LanEx application only; tools can be added later';
  ProfileRadioMinimal.Font.Style := [fsBold];
  ProfileRadioMinimal.OnClick := @OnProfileOptionChange;

  // Fixed summary panel at the bottom of the page surface:
  SummaryPanel := TPanel.Create(WizardForm);
  SummaryPanel.Parent := ConfigurePage.Surface;
  SummaryPanel.Left := ScaleX(0);
  SummaryPanel.Height := ScaleY(56);
  SummaryPanel.Top := ConfigurePage.Surface.ClientHeight - SummaryPanel.Height;
  SummaryPanel.Width := ConfigurePage.Surface.ClientWidth;
  SummaryPanel.BevelOuter := bvNone;
  SummaryPanel.Anchors := [akLeft, akRight, akBottom];

  SummaryDivider := TBevel.Create(WizardForm);
  SummaryDivider.Parent := SummaryPanel;
  SummaryDivider.Left := ScaleX(0);
  SummaryDivider.Top := 0;
  SummaryDivider.Width := SummaryPanel.Width;
  SummaryDivider.Height := ScaleY(2);
  SummaryDivider.Shape := bsTopLine;
  SummaryDivider.Anchors := [akLeft, akTop, akRight];

  SummaryDownloadLabel := TLabel.Create(WizardForm);
  SummaryDownloadLabel.Parent := SummaryPanel;
  SummaryDownloadLabel.Left := ScaleX(4);
  SummaryDownloadLabel.Top := ScaleY(6);
  SummaryDownloadLabel.Width := SummaryPanel.Width - ScaleX(8);
  SummaryDownloadLabel.AutoSize := False;
  SummaryDownloadLabel.Caption := 'Download required: calculating...';

  SummaryDiskLabel := TLabel.Create(WizardForm);
  SummaryDiskLabel.Parent := SummaryPanel;
  SummaryDiskLabel.Left := ScaleX(4);
  SummaryDiskLabel.Top := ScaleY(22);
  SummaryDiskLabel.Width := SummaryPanel.Width - ScaleX(8);
  SummaryDiskLabel.AutoSize := False;
  SummaryDiskLabel.Caption := 'Disk space required: calculating...';

  SummaryStatusLabel := TLabel.Create(WizardForm);
  SummaryStatusLabel.Parent := SummaryPanel;
  SummaryStatusLabel.Left := ScaleX(4);
  SummaryStatusLabel.Top := ScaleY(38);
  SummaryStatusLabel.Width := SummaryPanel.Width - ScaleX(8);
  SummaryStatusLabel.AutoSize := False;
  SummaryStatusLabel.Caption := 'Checking space...';
  SummaryStatusLabel.Font.Style := [fsBold];

  // Dynamic middle area:
  ProfileDescLabel := TLabel.Create(WizardForm);
  ProfileDescLabel.Parent := ConfigurePage.Surface;
  ProfileDescLabel.Left := ScaleX(8);
  ProfileDescLabel.Top := ScaleY(72);
  ProfileDescLabel.Width := ConfigurePage.Surface.ClientWidth - ScaleX(16);
  ProfileDescLabel.Height := SummaryPanel.Top - ScaleY(78);
  ProfileDescLabel.AutoSize := False;
  ProfileDescLabel.WordWrap := True;
  ProfileDescLabel.Anchors := [akLeft, akTop, akRight, akBottom];

  CustomCheckListBox := TNewCheckListBox.Create(WizardForm);
  CustomCheckListBox.Parent := ConfigurePage.Surface;
  CustomCheckListBox.Left := ScaleX(0);
  CustomCheckListBox.Top := ScaleY(70);
  CustomCheckListBox.Width := ConfigurePage.Surface.ClientWidth;
  CustomCheckListBox.Height := SummaryPanel.Top - ScaleY(76);
  CustomCheckListBox.Anchors := [akLeft, akTop, akRight, akBottom];
  CustomCheckListBox.Visible := False;
  CustomCheckListBox.OnClickCheck := @OnCustomCheck;

  CustomCheckListBox.AddGroup('Container Engine', '', 0, nil);
  IdxDocker := CustomCheckListBox.AddRadioButton('Docker CE (recommended)', '', 0, True, True, nil);
  IdxPodman := CustomCheckListBox.AddRadioButton('Podman', '', 0, False, True, nil);

  CustomCheckListBox.AddGroup('Flow & Visualization Tools', '', 0, nil);
  IdxImage := CustomCheckListBox.AddCheckBox('Matched LibreLane container image', '', 0, True, True, False, True, nil);
  IdxNative := CustomCheckListBox.AddCheckBox('Simulation & report tools (Verilator, Icarus, Graphviz, GTKWave)', '', 0, True, True, False, True, nil);
  IdxGds3d := CustomCheckListBox.AddCheckBox('GDS3D layout viewer and runtime support', '', 0, True, True, False, True, nil);

  CustomCheckListBox.AddGroup('Process Design Kits (select one variant per family)', '', 0, nil);
  IdxSky130A := CustomCheckListBox.AddRadioButton('sky130A — SkyWater 130 nm, ~2.5 GB (recommended)', '', 0, True, True, nil);
  IdxSky130B := CustomCheckListBox.AddRadioButton('sky130B — SkyWater 130 nm with ReRAM/SONOS, ~2.5 GB', '', 0, False, True, nil);
  IdxSkyNone := CustomCheckListBox.AddRadioButton('No SkyWater PDK', '', 0, False, True, nil);
  IdxGfNone := CustomCheckListBox.AddRadioButton('No GF180 PDK', '', 0, True, True, nil);
  IdxGf180A := CustomCheckListBox.AddRadioButton('gf180mcuA — GlobalFoundries 180 nm, ~1.8 GB', '', 0, False, True, nil);
  IdxGf180B := CustomCheckListBox.AddRadioButton('gf180mcuB — GlobalFoundries 180 nm, ~1.8 GB', '', 0, False, True, nil);
  IdxGf180C := CustomCheckListBox.AddRadioButton('gf180mcuC — GlobalFoundries 180 nm, ~1.8 GB', '', 0, False, True, nil);
  IdxGf180D := CustomCheckListBox.AddRadioButton('gf180mcuD — GlobalFoundries 180 nm, ~1.8 GB', '', 0, False, True, nil);
  IdxIhp := CustomCheckListBox.AddCheckBox('IHP SG13G2 — 130 nm SiGe BiCMOS, ~1.9 GB', '', 0, False, True, False, True, nil);

  CustomCheckListBox.AddGroup('Advanced PDK libraries', '', 0, nil);
  IdxSkyHdll := CustomCheckListBox.AddCheckBox('sky130_fd_sc_hdll', '', 0, True, True, False, True, nil);
  IdxSkyLp := CustomCheckListBox.AddCheckBox('sky130_fd_sc_lp', '', 0, True, True, False, True, nil);
  IdxSkyLs := CustomCheckListBox.AddCheckBox('sky130_fd_sc_ls', '', 0, True, True, False, True, nil);
  IdxSkyMs := CustomCheckListBox.AddCheckBox('sky130_fd_sc_ms', '', 0, True, True, False, True, nil);
  IdxSkyHs := CustomCheckListBox.AddCheckBox('sky130_fd_sc_hs', '', 0, True, True, False, True, nil);
  IdxSkyReram := CustomCheckListBox.AddCheckBox('sky130_fd_pr_reram (sky130B only)', '', 0, False, False, False, True, nil);

  // Fast profile restoration without spawning PowerShell:
  SavedProfile := '';
  if FileExists(StateFile) then
  begin
    if LoadStringFromFile(StateFile, RawState) then
    begin
      StateContent := String(RawState);
      SavedProfile := ExtractJsonStringValue(StateContent, 'profile');
      if SavedProfile = 'minimal' then
        ProfileRadioMinimal.Checked := True
      else if SavedProfile = 'custom' then
      begin
        ProfileRadioCustom.Checked := True;
        CustomCheckListBox.Checked[IdxPodman] := (ExtractJsonStringValue(StateContent, 'engine') = 'podman');
        CustomCheckListBox.Checked[IdxNative] := ExtractJsonArrayContains(StateContent, 'nativeTools', 'gtkwave');
        CustomCheckListBox.Checked[IdxGds3d] := ExtractJsonArrayContains(StateContent, 'nativeTools', 'gds3d');
        CustomCheckListBox.Checked[IdxImage] := ExtractJsonBoolValue(StateContent, 'image', True);

        CustomCheckListBox.Checked[IdxSky130A] := ExtractJsonArrayContains(StateContent, 'pdks', 'sky130A');
        CustomCheckListBox.Checked[IdxSky130B] := ExtractJsonArrayContains(StateContent, 'pdks', 'sky130B');
        CustomCheckListBox.Checked[IdxGf180A] := ExtractJsonArrayContains(StateContent, 'pdks', 'gf180mcuA');
        CustomCheckListBox.Checked[IdxGf180B] := ExtractJsonArrayContains(StateContent, 'pdks', 'gf180mcuB');
        CustomCheckListBox.Checked[IdxGf180C] := ExtractJsonArrayContains(StateContent, 'pdks', 'gf180mcuC');
        CustomCheckListBox.Checked[IdxGf180D] := ExtractJsonArrayContains(StateContent, 'pdks', 'gf180mcuD');
        CustomCheckListBox.Checked[IdxIhp] := ExtractJsonArrayContains(StateContent, 'pdks', 'ihp-sg13g2');

        CustomCheckListBox.Checked[IdxSkyHdll] := ExtractJsonArrayContains(StateContent, 'sky130A', 'sky130_fd_sc_hdll') or ExtractJsonArrayContains(StateContent, 'sky130B', 'sky130_fd_sc_hdll');
        CustomCheckListBox.Checked[IdxSkyLp] := ExtractJsonArrayContains(StateContent, 'sky130A', 'sky130_fd_sc_lp') or ExtractJsonArrayContains(StateContent, 'sky130B', 'sky130_fd_sc_lp');
        CustomCheckListBox.Checked[IdxSkyLs] := ExtractJsonArrayContains(StateContent, 'sky130A', 'sky130_fd_sc_ls') or ExtractJsonArrayContains(StateContent, 'sky130B', 'sky130_fd_sc_ls');
        CustomCheckListBox.Checked[IdxSkyMs] := ExtractJsonArrayContains(StateContent, 'sky130A', 'sky130_fd_sc_ms') or ExtractJsonArrayContains(StateContent, 'sky130B', 'sky130_fd_sc_ms');
        CustomCheckListBox.Checked[IdxSkyHs] := ExtractJsonArrayContains(StateContent, 'sky130A', 'sky130_fd_sc_hs') or ExtractJsonArrayContains(StateContent, 'sky130B', 'sky130_fd_sc_hs');
        CustomCheckListBox.Checked[IdxSkyReram] := ExtractJsonArrayContains(StateContent, 'sky130B', 'sky130_fd_pr_reram');
      end
      else
        ProfileRadioRecommended.Checked := True;
    end;
  end;
  OnProfileOptionChange(nil);

  // Dedicated progress container for Preparing / Installing pages:
  ProgressContainer := TPanel.Create(WizardForm);
  ProgressContainer.Parent := WizardForm.InnerPage;
  ProgressContainer.Left := ScaleX(0);
  ProgressContainer.Top := ScaleY(70);
  ProgressContainer.Width := WizardForm.InnerPage.ClientWidth;
  ProgressContainer.Height := WizardForm.InnerPage.ClientHeight - ScaleY(72);
  ProgressContainer.BevelOuter := bvNone;
  ProgressContainer.Anchors := [akLeft, akTop, akRight, akBottom];
  ProgressContainer.Visible := False;

  ProgressPhaseLabel := TLabel.Create(WizardForm);
  ProgressPhaseLabel.Parent := ProgressContainer;
  ProgressPhaseLabel.Left := ScaleX(2);
  ProgressPhaseLabel.Top := ScaleY(2);
  ProgressPhaseLabel.Width := ProgressContainer.ClientWidth - ScaleX(4);
  ProgressPhaseLabel.Height := ScaleY(18);
  ProgressPhaseLabel.Font.Style := [fsBold];
  ProgressPhaseLabel.Caption := 'Preparing environment...';
  ProgressPhaseLabel.Anchors := [akLeft, akTop, akRight];

  LiveLogMemo := TNewMemo.Create(WizardForm);
  LiveLogMemo.Parent := ProgressContainer;
  LiveLogMemo.Left := 0;
  LiveLogMemo.Top := ScaleY(24);
  LiveLogMemo.Width := ProgressContainer.ClientWidth;
  LiveLogMemo.Height := ProgressContainer.ClientHeight - ScaleY(54);
  LiveLogMemo.ScrollBars := ssVertical;
  LiveLogMemo.ReadOnly := True;
  LiveLogMemo.Anchors := [akLeft, akTop, akRight, akBottom];

  OpenLogButton := TNewButton.Create(WizardForm);
  OpenLogButton.Parent := ProgressContainer;
  OpenLogButton.Caption := '&Open log';
  OpenLogButton.SetBounds(0, ProgressContainer.ClientHeight - ScaleY(24), ScaleX(90), ScaleY(24));
  OpenLogButton.Anchors := [akLeft, akBottom];
  OpenLogButton.OnClick := @OpenDiagnostics;

  CopyLogButton := TNewButton.Create(WizardForm);
  CopyLogButton.Parent := ProgressContainer;
  CopyLogButton.Caption := '&Copy diagnostics';
  CopyLogButton.SetBounds(ScaleX(98), ProgressContainer.ClientHeight - ScaleY(24), ScaleX(115), ScaleY(24));
  CopyLogButton.Anchors := [akLeft, akBottom];
  CopyLogButton.OnClick := @CopyDiagnostics;

  SaveLogButton := TNewButton.Create(WizardForm);
  SaveLogButton.Parent := ProgressContainer;
  SaveLogButton.Caption := '&Save log';
  SaveLogButton.SetBounds(ScaleX(221), ProgressContainer.ClientHeight - ScaleY(24), ScaleX(90), ScaleY(24));
  SaveLogButton.Anchors := [akLeft, akBottom];
  SaveLogButton.OnClick := @SaveDiagnostics;

  // Desktop shortcut checkbox on Finished page:
  DesktopShortcutCheckbox := TNewCheckBox.Create(WizardForm);
  DesktopShortcutCheckbox.Parent := WizardForm.FinishedPage;
  DesktopShortcutCheckbox.Left := WizardForm.RunList.Left;
  DesktopShortcutCheckbox.Top := WizardForm.RunList.Top + WizardForm.RunList.Height + ScaleY(8);
  DesktopShortcutCheckbox.Width := WizardForm.RunList.Width;
  DesktopShortcutCheckbox.Caption := 'Create a desktop shortcut';
  DesktopShortcutCheckbox.Checked := True;
end;

function InitializeSetup(): Boolean;
var
  Failure, Detail, SilentProfile: String;
begin
  Result := True;
  RepairExisting := False;
  UpdateExisting := False;
  WslPending := False;
  DistroNameValue := '{#PreferredDistroName}';
  InstallIdValue := '';
  ManifestHashValue := '';
  PreflightDecision := '';
  BootIdentityValue := '';
  ComputerDisplayValue := '';
  FirmwareNoticeValue := False;
  ChoicesJsonValue := '';
  ChoicesPathValue := ExpandConstant('{param:SELECTIONS|}');
  EstimateDownloadMB := 0;
  EstimateInstalledMB := 0;
  RequiredAppMB := 0;
  RequiredTempMB := 0;
  ProgressPhase := 0;
  ProgressPhaseCount := 6;
  ProgressStartedTick := 0;
  CancelRequested := False;
  BaseProvisionedForEstimate := False;
  EstimateReuseApplied := False;

  if not RunPreflight(Failure) then
  begin
    LogLine('preflight failed: ' + Failure);
    if not WizardSilent then MsgBox('LanEx could not inspect this PC''s Windows and WSL prerequisites.'
      + #13#10#13#10 + Failure + #13#10#13#10
      + 'No Windows feature, WSL distribution, or user data was changed.',
      mbError, MB_OK);
    Result := False;
    Exit;
  end;

  if PreflightDecision = 'unsupported-architecture' then
  begin
    if not WizardSilent then MsgBox('This LanEx installer contains an amd64 Linux appliance and requires '
      + 'an x64 Windows PC. ARM64 and other native architectures are not '
      + 'supported by this build.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if PreflightDecision = 'unsupported-windows' then
  begin
    if not WizardSilent then MsgBox('LanEx needs Windows build 19044 or newer so its WSLg desktop tools '
      + 'can open correctly. Windows 11 x64 is recommended.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if PreflightDecision = 'preflight-query-failed' then
  begin
    if not WizardSilent then MsgBox('Windows did not allow Setup to determine the required WSL feature '
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
    if (not WizardSilent) and (MsgBox('LanEx cannot run because your computer''s virtualization feature '
      + 'is switched off.' + #13#10#13#10
      + 'It is a one-time setting in your PC''s BIOS/UEFI screen, not something '
      + 'Windows can change. Microsoft''s instructions include manufacturer links.'
      + Detail
      + #13#10#13#10 + 'Open the instructions now?',
      mbError, MB_YESNO) = IDYES) then
      OpenHelp('#enable-virtualization');
    Result := False;
    Exit;
  end;

  // Interactive choices do not exist until InitializeWizard. Silent setup uses
  // either a named profile or a manifest-validated JSON selection file.
  if WizardSilent then
  begin
    SilentProfile := Lowercase(ExpandConstant('{param:PROFILE|recommended}'));
    if ChoicesPathValue <> '' then
      Result := PlanSelections('', ChoicesPathValue, Failure)
    else if (SilentProfile = 'recommended') or (SilentProfile = 'minimal') then
      Result := PlanSelections('{"profile":"' + SilentProfile + '"}', '', Failure)
    else
    begin
      Failure := 'Silent /PROFILE must be recommended or minimal; use /SELECTIONS=<json file> for custom choices.';
      Result := False;
    end;
    if Result then Result := CheckSelectionSpace(Failure);
    if not Result then
    begin
      LogLine('silent selection failed: ' + Failure);
      Exit;
    end;
  end;

  // Existing distro names are not ownership proof. The state worker resolves
  // and binds the exact HKCU registration/path later, before any WSL mutation.
end;

function InitializeDurableState: String;
var
  Worker, Manifest, OperationName, Output, Snippet, SetupCopy,
    StagedChoices, SourceCompanion, CachedCompanion, StateContent,
    ExistingManifestHash: String;
  RawState: AnsiString;
  HadState: Boolean;
begin
  Result := '';
  ExtractTemporaryFile('setup.ps1');
  ExtractTemporaryFile('build-manifest.json');
  ExtractTemporaryFile('install.sh');
  ExtractTemporaryFile('constraints.txt');
  ExtractTemporaryFile('{#LanexWheelFile}');
  Worker := ExpandConstant('{tmp}\setup.ps1');
  Manifest := ExpandConstant('{tmp}\build-manifest.json');
  ManifestHashValue := Lowercase(GetSHA256OfFile(Manifest));
  StagedChoices := ExpandConstant('{tmp}\choices-state.json');
  if not SaveStringToFile(StagedChoices, ChoicesJsonValue, False) then
  begin
    Result := 'LanEx could not stage its selected component choices.'
      + #13#10#13#10 + 'No WSL distribution or user data was changed.';
    Exit;
  end;

  HadState := FileExists(StateFile);
  if ExpandConstant('{param:REPAIR|0}') = '1' then
    OperationName := 'repair'
  else if IsContinuationRun then
    OperationName := 'resume'
  else if HadState then
  begin
    StateContent := '';
    if LoadStringFromFile(StateFile, RawState) then
      StateContent := String(RawState);
    ExistingManifestHash := Lowercase(ExtractJsonStringValue(StateContent, 'manifestHash'));
    if (ExistingManifestHash <> '') and (CompareText(ExistingManifestHash, ManifestHashValue) <> 0) then
      OperationName := 'update'
    else if ExtractJsonStringValue(StateContent, 'phase') = 'ready' then
      OperationName := 'modify'
    else
      OperationName := 'resume';
  end
  else
    OperationName := 'install';

  Snippet := '& ' + PSQuote(Worker) + ' -Action InitializeState -StatePath '
    + PSQuote(StateFile) + ' -ManifestPath ' + PSQuote(Manifest)
    + ' -Operation ' + OperationName
    + ' -ChoicesPath ' + PSQuote(StagedChoices)
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

  if (not WizardSilent) and (PreflightDecision = 'features-required') and FirmwareNoticeValue then
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
  if not PowerShellCapture(
      '(Get-Content -LiteralPath ' + PSQuote(StateFile)
        + ' -Raw | ConvertFrom-Json).ownerSid', OwnerSidValue) then
  begin
    Result := 'LanEx could not read the owner identity from setup state.';
    Exit;
  end;
  DistroNameValue := Trim(StripNulls(DistroNameValue));
  InstallIdValue := Trim(StripNulls(InstallIdValue));
  OwnerSidValue := Trim(StripNulls(OwnerSidValue));
  if not PowerShellCapture(
      '(Get-Content -LiteralPath ' + PSQuote(StateFile)
        + ' -Raw | ConvertFrom-Json).appliance.basePath', DistroBasePathValue) then
    DistroBasePathValue := DistroDir;
  DistroBasePathValue := Trim(StripNulls(DistroBasePathValue));
  if DistroBasePathValue = '' then
    DistroBasePathValue := DistroDir;
  ManifestHashValue := Lowercase(GetSHA256OfFile(Manifest));

  // Keep an immutable candidate copy and a manual continuation shortcut before
  // UAC. If elevation is cancelled or policy blocks it, the originating user
  // still has a recoverable setup entry independent of Downloads.
  ForceDirectories(CacheDir);
  SetupCopy := CacheDir + '\LanEx-Setup.exe';
  if CompareText(ExpandConstant('{srcexe}'), SetupCopy) <> 0 then
    if not FileCopy(ExpandConstant('{srcexe}'), SetupCopy, False) then
    begin
      // CopyFile can be rejected for a running EXE when Windows applies its
      // RedirectionGuard mitigation. The same unelevated owner may still copy
      // it normally; StageInstaller below then requires an exact SHA256 match.
      Snippet := 'Copy-Item -LiteralPath ' + PSQuote(ExpandConstant('{srcexe}'))
        + ' -Destination ' + PSQuote(SetupCopy) + ' -Force';
      if not PowerShellCapture(Snippet, Output) then
      begin
        Result := 'LanEx could not stage a durable copy of this exact installer.'
          + #13#10#13#10 + Output + #13#10#13#10
          + 'No Windows feature or WSL distribution was changed.';
        Exit;
      end;
    end;
#ifdef CompanionRootfsSha256
  // Resume runs from the immutable cache, so preserve the verified companion
  // beside the cached EXE instead of silently switching to a network fallback
  // after reboot. A missing companion remains allowed and uses the existing
  // pinned fallback path.
  SourceCompanion := ExpandConstant('{src}\{#BakedRootfsFile}');
  CachedCompanion := CacheDir + '\{#BakedRootfsFile}';
  if FileExists(SourceCompanion) and
     (CompareText(GetSHA256OfFile(SourceCompanion), '{#CompanionRootfsSha256}') = 0) and
     (CompareText(SourceCompanion, CachedCompanion) <> 0) then
  begin
    if (not FileCopy(SourceCompanion, CachedCompanion, False)) or
       (CompareText(GetSHA256OfFile(CachedCompanion), '{#CompanionRootfsSha256}') <> 0) then
    begin
      Result := 'LanEx could not preserve the verified companion appliance for restart.'
        + #13#10#13#10 + 'No Windows feature or WSL distribution was changed.';
      Exit;
    end;
  end;
#endif
  Snippet := '& ' + PSQuote(Worker) + ' -Action StageInstaller -StatePath '
    + PSQuote(StateFile) + ' -ResumeInstallerPath ' + PSQuote(SetupCopy);
  if not PowerShellCapture(Snippet, Output) then
  begin
    Result := 'LanEx could not verify its cached installer or manual Continue '
      + 'shortcut.' + #13#10#13#10 + Output
      + #13#10#13#10 + 'No Windows feature or WSL distribution was changed.';
    Exit;
  end;
  RepairExisting := (OperationName = 'repair') and HadState and DistroExists;
  UpdateExisting := False;
  if (OperationName = 'update') and HadState then
    if PowerShellCapture(
        '$s=Get-Content -LiteralPath ' + PSQuote(StateFile) + ' -Raw | ConvertFrom-Json; '
        + '[bool]$s.PSObject.Properties[''previousBuild'']', Output) then
      UpdateExisting := CompareText(Trim(Output), 'True') = 0;
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
  Params := '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'
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
    SetPhase(2, 6, Format('Downloading the LanEx environment... %d%% of %d MB', [
      Progress * 100 div ProgressMax, ProgressMax div 1048576]));
  end;
  Result := not CancelRequested;
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
    SetPhase(2, 6, 'Checking the downloaded LanEx environment...');
    if CompareText(GetSHA256OfFile(Dest), Sha256) = 0 then
    begin
      LogLine('cached rootfs verified: ' + Dest);
      Exit;
    end;
    LogLine('cached rootfs failed its checksum — downloading again: ' + Dest);
    DeleteFile(Dest);
  end;
  SetPhase(2, 6, 'Downloading the LanEx environment (about ' + SizeMB + ' MB)...');
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
var
  Companion: String;
begin
  if CancelRequested then
  begin
    Result := 'Setup was cancelled before downloading the appliance image.';
    Exit;
  end;
#ifdef EmbeddedRootfs
  SetPhase(2, 6, 'Extracting the embedded appliance image...');
  ExtractTemporaryFile('{#BakedRootfsFile}');
  ImportPath := ExpandConstant('{tmp}\{#BakedRootfsFile}');
  LogLine('using the embedded appliance image: ' + ImportPath);
  Result := '';
  Exit;
#endif
#ifdef CompanionRootfsSha256
  Companion := ExpandConstant('{src}\{#BakedRootfsFile}');
  if FileExists(Companion) then
  begin
    if CompareText(GetSHA256OfFile(Companion), '{#CompanionRootfsSha256}') = 0 then
    begin
      if (CompareText(Companion, BakedRootfsPath) = 0) or
         FileCopy(Companion, BakedRootfsPath, False) then
      begin
        ImportPath := BakedRootfsPath;
        LogLine('using the verified companion appliance image');
        Result := '';
        Exit;
      end;
      LogLine('could not cache the verified companion image; trying configured downloads');
    end
    else
      LogLine('ignored adjacent appliance image because its SHA256 does not match this Setup');
  end;
#endif
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
  if CancelRequested then
  begin
    Result := 'The environment download was cancelled. Setup did not start the fallback download.';
    Exit;
  end;
  ImportPath := RootfsPath;
  Result := FetchRootfs('{#RootfsUrl}', '{#RootfsFile}', '{#RootfsSha256}',
                        RootfsPath, '{#RootfsSizeMB}');
end;

// ProvisionDistro runs provision.sh inside the freshly imported distro.
procedure RecordSetupOutcome(const Outcome, MessageText: String);
var
  Worker, ManifestFile, Output, Snippet: String;
begin
  Worker := ExpandConstant('{tmp}\setup.ps1');
  ManifestFile := ExpandConstant('{tmp}\build-manifest.json');
  Snippet := '& ' + PSQuote(Worker) + ' -Action RecordOutcome -StatePath ' +
    PSQuote(StateFile) + ' -Outcome ' + Outcome + ' -OutcomeMessage ' + PSQuote(MessageText);
  if FileExists(ManifestFile) then
    Snippet := Snippet + ' -ManifestPath ' + PSQuote(ManifestFile);
  if not PowerShellCapture(Snippet, Output) then
    LogLine('WARNING: could not record setup outcome: ' + Output);
end;

function ProvisionDistro: String;
var
  ScriptPath, InstallPath, WheelPath, ConstraintPath, ManifestPath, LinuxPath, LinuxInstall,
  LinuxWheel, LinuxConstraint, LinuxManifest, LinuxChoices, Params, UpdateModeValue: String;
  Code, Answer: Integer;
begin
  Result := '';
  ExtractTemporaryFile('provision.sh');
  ExtractTemporaryFile('build-manifest.json');
  ScriptPath := ExpandConstant('{tmp}\provision.sh');
  InstallPath := ExpandConstant('{tmp}\install.sh');
  WheelPath := ExpandConstant('{tmp}\{#LanexWheelFile}');
  ConstraintPath := ExpandConstant('{tmp}\constraints.txt');
  ManifestPath := ExpandConstant('{tmp}\build-manifest.json');
  LinuxPath := WindowsToWslPath(ScriptPath);
  LinuxInstall := WindowsToWslPath(InstallPath);
  LinuxWheel := WindowsToWslPath(WheelPath);
  LinuxConstraint := WindowsToWslPath(ConstraintPath);
  LinuxManifest := WindowsToWslPath(ManifestPath);
  LinuxChoices := WindowsToWslPath(StateFile);
  if UpdateExisting then UpdateModeValue := '1' else UpdateModeValue := '0';
  // `tr -d '\r'` before running: if this repo is ever checked out with Windows
  // line endings (a CI runner with core.autocrlf=true), bash would fail on the
  // shebang with "bad interpreter: No such file or directory" — a bewildering
  // error for a script that is obviously present. .gitattributes pins LF too;
  // this is the belt to that braces.
  // `export`, not a `VAR=... bash script` prefix: provision.sh's own header
  // records why (a prefix applies to the one command it prefixes, so every knob
  // passed that way was silently inert).
  Params := '-d ' + DistroNameValue + ' -u root -- env '
    + 'LANEX_REPO="{#LanexSourceRepo}" LANEX_REF="{#LanexRef}" '
    + 'LANEX_SOURCE_SHA="{#LanexSourceSha}" LANEX_INSTALL_ID="' + InstallIdValue + '" '
    + 'LANEX_MANIFEST_HASH="' + ManifestHashValue + '" '
    + 'LANEX_INSTALL_SCRIPT="' + LinuxInstall + '" LANEX_FROM="' + LinuxWheel + '" '
    + 'LANEX_PIP_CONSTRAINT="' + LinuxConstraint + '" '
    + 'LANEX_BUILD_MANIFEST="' + LinuxManifest + '" LANEX_SETUP_CHOICES="' + LinuxChoices + '" '
    + 'LANEX_UPDATE_MODE="' + UpdateModeValue + '" '
    + 'bash "' + LinuxPath + '" base';
  repeat
    SetPhase(4, 6, 'Preparing the base LanEx environment...');
    if RunLogged(WslExe, Params, Code) and (Code = 0) then
      Exit;
    if CancelRequested then
    begin
      Result := 'LanEx Setup was cancelled. Completed verified downloads and project data were preserved.';
      RecordSetupOutcome('cancelled', Result);
      Exit;
    end;
    if WizardSilent then Answer := IDCANCEL
    else Answer := MsgBox('Setting up the LanEx environment did not finish.'
      + #13#10#13#10 + 'The failing component and recovery detail are shown below. '
      + 'Retry rechecks completed work and preserves verified downloads.' + #13#10#13#10
      + 'Last lines of the log:' + #13#10 + LogTail(12) + ProxyFailureHint,
      mbError, MB_RETRYCANCEL);
  until Answer <> IDRETRY;
  Result := 'The LanEx environment could not be prepared.' + #13#10#13#10
    + 'The full log is at:' + #13#10 + LogFile + #13#10#13#10
    + 'Please report it — the log tells us exactly which step failed.';
  RecordSetupOutcome('failed', Result);
end;

function VerifyRepairIdentity(var Failure: String): Boolean;
var
  WorkerOutput, Snippet: String;
begin
  Failure := '';
  if UpdateExisting then
    Snippet := '$s=Get-Content -LiteralPath ' + PSQuote(StateFile)
      + ' -Raw | ConvertFrom-Json; $e=$s.previousBuild; '
  else
    Snippet := '$e=[pscustomobject]@{manifestHash=' + PSQuote(ManifestHashValue)
      + ';source=[pscustomobject]@{sha=''{#LanexSourceSha}''}}; ';
  Snippet := Snippet + '$m = (& ' + PSQuote(WslExe) + ' -d ' + PSQuote(DistroNameValue)
    + ' -u root -- cat /etc/lanex/appliance.json) | ConvertFrom-Json; '
    + 'if ($m.schema -ne 1 -or $m.installId -ne ' + PSQuote(InstallIdValue)
    + ' -or $m.manifestHash -ne $e.manifestHash -or $m.sourceSha -ne $e.source.sha) '
    + '{ throw ''Linux appliance identity does not match the expected current build.'' }; ''identity-ok''';
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
  Result := RunLogged(WslExe, '-d ' + DistroNameValue
    + ' -u root -- env LANEX_BUILD_MANIFEST="' + LinuxManifest
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
  Params := '-d ' + DistroNameValue + ' -u root -- env '
    + 'LANEX_USER="lanex" LANEX_BUILD_MANIFEST="' + LinuxManifest + '" '
    + 'LANEX_SETUP_CHOICES="' + LinuxChoices + '" COLUMNS=120 LINES=40 TERM=dumb bash "' + LinuxScript + '" finalize';
  repeat
    SetPhase(6, 6, 'Installing and verifying the selected tools, image, and PDKs...');
    if RunLogged(WslExe, Params, Code) and (Code = 0) then
      Exit;
    if CancelRequested then
    begin
      Result := 'LanEx Setup was cancelled while stopping the current component safely. '
        + 'Finalization did not continue, and completed verified data was preserved.';
      RecordSetupOutcome('cancelled', Result);
      Exit;
    end;
    if WizardSilent then Answer := IDCANCEL
    else Answer := MsgBox('The selected LanEx components did not all become ready.'
      + #13#10#13#10 + 'Retrying preserves completed tools, image layers, PDKs, and projects.'
      + #13#10#13#10 + 'Last lines of the log:' + #13#10 + LogTail(16) + ProxyFailureHint,
      mbError, MB_RETRYCANCEL);
  until Answer <> IDRETRY;
  Result := 'LanEx base setup is intact, but selected-component readiness failed.'
    + #13#10#13#10 + 'No existing distribution or project was deleted.'
    + #13#10#13#10 + 'Full log: ' + LogFile;
  RecordSetupOutcome('failed', Result);
end;

function CompleteUpdateCheckpoint(Rollback: Boolean): Boolean;
var
  ScriptPath, LinuxScript, ModeName, ActionName, Output: String;
  Code: Integer;
begin
  Result := True;
  if not UpdateExisting then Exit;
  ExtractTemporaryFile('provision.sh');
  ScriptPath := ExpandConstant('{tmp}\provision.sh');
  LinuxScript := WindowsToWslPath(ScriptPath);
  if Rollback then
  begin
    ModeName := 'rollback-update';
    ActionName := 'RollbackUpdate';
  end else begin
    ModeName := 'commit-update';
    ActionName := 'CommitUpdate';
  end;
  Result := RunLogged(WslExe, '-d ' + DistroNameValue + ' -u root -- env '
    + 'LANEX_USER="{#AppUser}" LANEX_INSTALL_ID="' + InstallIdValue + '" '
    + 'LANEX_UPDATE_MODE="1" bash "' + LinuxScript + '" ' + ModeName, Code)
    and (Code = 0);
  if not PowerShellCapture('& ' + PSQuote(ExpandConstant('{tmp}\setup.ps1'))
      + ' -Action ' + ActionName + ' -StatePath ' + PSQuote(StateFile), Output) then
  begin
    LogLine('update checkpoint action failed: ' + Output);
    Result := False;
  end;
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
    + '-InputFingerprint $m.componentFingerprints.pdks -Phase linux-ready';
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
  RotateInstallLog;
  ForceDirectories(LogDir);
  ProgressStartedTick := GetTickCount;
  if ChoicesJsonValue = '' then ChoicesJsonValue := '{"profile":"recommended"}';
  AppendLiveLine('=== LanEx Setup {#AppVersion} started ===');
  AppendLiveLine('Initializing environment and validating prerequisites...');
  LogLine('');
  LogLine('=== LanEx Setup {#AppVersion} — ' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':')
    + ' (resume=' + ExpandConstant('{param:RESUME|0}') + ') ===');

  // Establish immutable owner/build/appliance identity before enabling WSL,
  // downloading, importing, terminating, or provisioning anything.
  Result := InitializeDurableState;
  if Result <> '' then
  begin
    LogLine('ERROR: ' + Result);
    AppendLiveLine('Error: ' + Result);
    Exit;
  end;
  if not PlanSelections('', StateFile, Output) then
  begin
    Result := 'LanEx could not revalidate the saved component choices.' + #13#10#13#10 + Output;
    Exit;
  end;
  if CancelRequested then
  begin
    Result := 'The environment download was cancelled. Setup did not start the fallback download.';
    Exit;
  end;
  if not CheckSelectionSpace(Output) then
  begin
    Result := Output + #13#10#13#10 +
      'Free space and run the same Setup again. Verified completed downloads and data are preserved.';
    Exit;
  end;
  SetPhase(1, 6, 'Checking Windows, WSL, ownership, and selected disk space...');

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

  if PreflightDecision = 'wsl-kernel-unavailable' then
  begin
    Result := 'Windows reports that WSL is installed, but the WSL 2 kernel could '
      + 'not start. If this PC is a virtual machine, its host must expose nested '
      + 'virtualization to the guest; on physical hardware, verify virtualization '
      + 'and the Windows hypervisor configuration.' + #13#10#13#10
      + 'Setup did not download or import an environment. Existing WSL '
      + 'distributions were not started, stopped, or changed.';
    RecordSetupOutcome('failed', Result);
    Exit;
  end;

  // Only the feature operation crosses UAC. A different administrator may
  // authorize it, but execution returns here before any user-owned work.
  if PreflightDecision = 'features-required' then
  begin
    SetPhase(1, 6, 'Requesting permission for two Windows features...');
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
    Result := 'Windows needs to restart to complete WSL setup.' + #13#10#13#10
      + 'Setup registered an automatic continuation. If Windows blocks it, use Continue LanEx Setup from the Start menu.' + #13#10#13#10
      + 'Your component and PDK choices are saved.';
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
    Result := 'Windows needs to restart to complete WSL setup.' + #13#10#13#10
      + 'Setup registered an automatic continuation. If Windows blocks it, use Continue LanEx Setup from the Start menu.' + #13#10#13#10
      + 'Your component and PDK choices are saved.';
    Exit;
  end;

  if PreflightDecision = 'wsl-update-required' then
  begin
    if WizardSilent and (ExpandConstant('{param:ALLOWWSLUPDATE|0}') <> '1') then
    begin
      Result := 'WSL update required. Silent setup will not change the machine-wide '
        + 'WSL runtime without /ALLOWWSLUPDATE=1.';
      Exit;
    end;
    if (not WizardSilent) and (MsgBox('LanEx needs a newer WSL runtime for systemd and desktop tools.'
      + #13#10#13#10 + 'Updating WSL is machine-wide and can briefly affect '
      + 'other WSL work. Save active WSL work before continuing. Setup will '
      + 'not shut down or convert any distribution.' + #13#10#13#10
      + 'Update WSL now?', mbConfirmation, MB_YESNO) <> IDYES) then
    begin
      Result := 'WSL update deferred. Your choices and exact installer are saved; '
        + 'choose Continue LanEx Setup from the Start menu when ready.';
      Exit;
    end;
    SetPhase(1, 6, 'Updating Windows Subsystem for Linux...');
    if not (RunLogged(WslExe, '--update --web-download', Code) and (Code = 0)) then
    begin
      if CancelRequested then
      begin
        Result := 'LanEx Setup was cancelled after the current WSL update attempt stopped.';
        RecordSetupOutcome('cancelled', Result);
        Exit;
      end;
      if not (RunLogged(WslExe, '--update', Code) and (Code = 0)) then
      begin
        Result := 'Windows could not update WSL. This may be a managed-policy or '
          + 'network restriction; the existing distributions were not stopped or '
          + 'changed.' + #13#10#13#10 + LogTail(12);
        Exit;
      end;
    end;
    if CancelRequested then
    begin
      Result := 'LanEx Setup was cancelled after the current WSL update operation finished safely. '
        + 'No distribution was stopped or converted.';
      RecordSetupOutcome('cancelled', Result);
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
      Result := 'Windows needs to restart to complete WSL setup.' + #13#10#13#10
        + 'Setup registered an automatic continuation. If Windows blocks it, use Continue LanEx Setup from the Start menu.' + #13#10#13#10
        + 'Your component and PDK choices are saved.';
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

  // Download and import — skipped when the appliance distro is already registered.
  if not DistroExists then
  begin
    Result := EnsureRootfs;
    if Result <> '' then
    begin
      if CancelRequested then
      begin
        Result := 'LanEx Setup was cancelled. A partial rootfs transfer was not cached; completed verified downloads remain reusable.';
        RecordSetupOutcome('cancelled', Result);
      end;
      Exit;
    end;
    SetPhase(3, 6, 'Creating the private LanEx environment...');
    if DistroBasePathValue = '' then DistroBasePathValue := DistroDir;
    ForceDirectories(DistroBasePathValue);
    // --version 2 explicitly: Docker and the GUI viewers need WSL 2, and the
    // user's default version is none of our business.
    // --version 2 explicitly (again): `wsl --import` reads plain tar and .tar.gz
    // alike, so the baked and the Ubuntu path use one identical command.
    if not (RunLogged(WslExe, '--import ' + DistroNameValue + ' "' + DistroBasePathValue + '" "'
        + ImportPath + '" --version 2', Code) and (Code = 0)) then
    begin
      Result := 'The LanEx environment could not be created.' + #13#10#13#10
        + 'Last lines of the log:' + #13#10 + LogTail(10) + #13#10
        + 'Full log: ' + LogFile;
      RecordSetupOutcome('failed', Result);
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
    if CancelRequested then
    begin
      Result := 'LanEx Setup was cancelled after safely finishing the environment import. '
        + 'The owner-bound environment is preserved for Continue/Retry.';
      RecordSetupOutcome('cancelled', Result);
      Exit;
    end;
  end
  else
  begin
    LogLine('distro ' + DistroNameValue + ' already exists and is adopted; skipping import');
    AppendLiveLine('Using existing LanEx environment (' + DistroNameValue + ').');
  end;

  // 5. A no-op Repair proves owner/build identity and runs the appliance
  // self-test without invoking pip or apt. Only a failed health check re-enters
  // idempotent provisioning; an identity mismatch is never overwritten.
  NeedProvision := True;
  if RepairExisting then
  begin
    if not VerifyRepairIdentity(IdentityFailure) then
    begin
      LogLine('repair identity verification failed: ' + IdentityFailure);
      Result := 'LanEx could not verify ownership of the existing appliance for repair:' + #13#10#13#10
        + IdentityFailure + #13#10#13#10
        + 'Setup stopped without changing any distribution files.';
      Exit;
    end
    else if HealthyRepairNeedsNoChanges then
    begin
      NeedProvision := False;
      LogLine('repair verified exact identity and health; no dependencies changed');
      AppendLiveLine('Existing LanEx environment is healthy. No packages need updating.');
    end;
  end;

  // 6. Provision a new or unhealthy-but-owned appliance.
  if NeedProvision then
  begin
    Result := ProvisionDistro;
    if Result <> '' then
    begin
      CompleteUpdateCheckpoint(True);
      Exit;
    end;
  end;
  MarkAppComplete;
  BaseProvisionedForEstimate := True;

  // Image and PDK extraction are the largest later phases. Recheck their
  // destination volume after base apt/pip work has consumed real space.
  if not CheckSelectionSpace(Output) then
  begin
    Result := Output + #13#10#13#10 +
      'Base setup is preserved. Free space, then choose Retry/Continue; verified caches are reused.';
    CompleteUpdateCheckpoint(True);
    Exit;
  end;

  // 7. Restart ONLY the owner-bound appliance, then run the shared strict
  //    finalizer after systemd and Docker are reachable. The finalizer executes
  //    as the appliance user and exits nonzero until every saved selection is
  //    operational; image/PDK caches and completed work survive Retry.
  SetPhase(5, 6, 'Restarting only the private LanEx environment...');
  if not (RunLogged(WslExe, '--terminate ' + DistroNameValue, Code) and (Code = 0)) then
  begin
    Result := 'Windows could not restart the owner-bound LanEx environment.'
      + #13#10#13#10 + 'No other WSL distribution was stopped.' + #13#10#13#10
      + LogTail(10);
    Exit;
  end;
  if CancelRequested then
  begin
    Result := 'LanEx Setup was cancelled after stopping only its owner-bound environment. '
      + 'Selected-component finalization did not start.';
    RecordSetupOutcome('cancelled', Result);
    CompleteUpdateCheckpoint(True);
    Exit;
  end;
  Result := FinalizeDistro;
  if Result <> '' then
  begin
    CompleteUpdateCheckpoint(True);
    Exit;
  end;
  if not MarkSelectionsComplete then
  begin
    Result := 'The selected components are ready, but Setup could not save their '
      + 'owner-bound completion checkpoint. The appliance and all data were preserved.';
    CompleteUpdateCheckpoint(True);
    Exit;
  end;
  // NOTE: Rollback checkpoint is committed in CurStepChanged(ssPostInstall) ONLY after Windows files are verified!
  LogLine('appliance provisioning and strict finalization complete; Windows files will now be installed...');
  LogLine('=== provisioning complete ===');
end;

// InstallCompleted gates the "Launch LanEx" checkbox: after a reboot-pending
// run there is no appliance yet, so offering to launch it would only produce an
// error dialog.
function InstallCompleted: Boolean;
begin
  Result := (not WslPending) and FileExists(ExpandConstant('{app}\LanEx.exe')) and FileExists(ExpandConstant('{app}\appliance.json'));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Failure: String;
begin
  Result := True;
  if WizardSilent then Exit;
  if CurPageID = ConfigurePage.ID then
  begin
    if ProfileRadioCustom.Checked and not ValidatePdkFamilies(Failure) then
    begin
      MsgBox(Failure, mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if not PlanSelections(BuildChoicesJson, '', Failure) then
    begin
      MsgBox('Those selections cannot be installed:' + #13#10#13#10 + Failure,
        mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if not CheckSelectionSpace(Failure) then
    begin
      MsgBox(Failure + #13#10#13#10 +
        'Completed verified downloads are reused. Free space, then click Install again.',
        mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  // The self-resuming run after the restart goes straight to the progress page:
  // the user already accepted the licence and chose their options.
  Result := IsContinuationRun and
            ((PageID = wpWelcome) or (PageID = wpLicense) or
             (PageID = ConfigurePage.ID));
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if ProgressContainer <> nil then
  begin
    ProgressContainer.Visible := (CurPageID = wpPreparing) or (CurPageID = wpInstalling);
  end;
  if CurPageID = ConfigurePage.ID then
  begin
    WizardForm.LicenseMemo.Visible := False;
    ConfigurePage.Surface.BringToFront;
    ConfigurePage.Surface.Repaint;
    WizardForm.NextButton.Caption := '&Install';
    UpdateEstimates;
  end
  else if CurPageID = wpLicense then
  begin
    WizardForm.LicenseMemo.Visible := True;
    WizardForm.NextButton.Caption := SetupMessage(msgButtonNext);
  end
  else if CurPageID = wpFinished then
  begin
    WizardForm.NextButton.Caption := SetupMessage(msgButtonFinish);
    if not WslPending then
      WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10
        + 'Your selected tools, container image, and PDK libraries were installed '
        + 'and passed LanEx''s setup readiness checks.';
  end
  else
  begin
    WizardForm.NextButton.Caption := SetupMessage(msgButtonNext);
  end;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
var
  Code: Integer;
begin
  if ((CurPageID = wpPreparing) or (CurPageID = wpInstalling)) and
     (DistroNameValue <> '') then
  begin
    Cancel := False;
    Confirm := False;
    if not CancelRequested then
    begin
      CancelRequested := True;
      SetStatus('Stopping safely... the current package database operation will finish first.');
      LogLine('cancellation requested by user');
      Exec(WslExe, '-d ' + DistroNameValue + ' -u root -- sh -c "mkdir -p /run/lanex; touch /run/lanex/setup.cancel"',
        '', SW_HIDE, ewNoWait, Code);
    end;
  end;
end;

// ------------------------------------------------------------------ uninstall --

procedure OpenProjectFolder;
var
  Code: Integer;
begin
  ShellExec('open', DistroProjectPath(''), '', '',
            SW_SHOWNORMAL, ewNoWait, Code);
end;

function UninstallWorker(const Snippet: String; var Output: String): Boolean;
begin
  Result := PowerShellCapture('& ' + PSQuote(ExpandConstant('{app}\setup-worker.ps1'))
    + ' ' + Snippet, Output);
end;

function InitializeUninstall(): Boolean;
var
  Choice: Integer;
  Output, ExportFile, Snippet: String;
begin
  Result := False;
  Choice := MsgBox('Keep your LanEx environment and data? (Recommended)' + #13#10#13#10
    + 'Yes keeps projects, run results, PDKs, caches, and the private WSL environment '
    + 'for a later reinstall.' + #13#10#13#10
    + 'No opens export and permanent-removal choices. Cancel stops uninstall.',
    mbConfirmation, MB_YESNOCANCEL or MB_DEFBUTTON1);
  if Choice = IDCANCEL then Exit;

  if Choice = IDYES then
  begin
    if FileExists(StateFile) then
    begin
      if not UninstallWorker('-Action ClearResume -StatePath ' + PSQuote(StateFile), Output) then
        LogLine('WARNING: could not clear continuation hook during uninstall: ' + Output);
    end;
    MsgBox('The Windows launcher and shortcuts will be removed. Your private LanEx '
      + 'environment remains at:' + #13#10 + ApplianceRoot + #13#10#13#10
      + 'Run LanEx Setup later to verify and reuse it. Other WSL distributions and '
      + 'Windows WSL features are unchanged.', mbInformation, MB_OK);
    Result := True;
    Exit;
  end;

  Choice := MsgBox('Choose what happens to the private LanEx environment.' + #13#10#13#10
    + 'Yes exports a backup, then keeps the environment.' + #13#10
    + 'No permanently removes the verified LanEx environment and its owned data.' + #13#10
    + 'Cancel stops uninstall.', mbConfirmation, MB_YESNOCANCEL or MB_DEFBUTTON1);
  if Choice = IDCANCEL then Exit;
  if Choice = IDYES then
  begin
    ExportFile := ExpandConstant('{userdocs}\LanEx-environment-backup.tar');
    if not GetSaveFileName('Export the LanEx environment before uninstalling', ExportFile,
        ExpandConstant('{userdocs}'), 'WSL tar archive (*.tar)|*.tar', 'tar') then Exit;
    if not UninstallWorker('-Action ExportAppliance -StatePath ' + PSQuote(StateFile)
        + ' -ExportPath ' + PSQuote(ExportFile), Output) then
    begin
      MsgBox('The export did not complete, so uninstall stopped and all LanEx data '
        + 'was preserved.' + #13#10#13#10 + Output, mbError, MB_OK);
      Exit;
    end;
    if not UninstallWorker('-Action ClearResume -StatePath ' + PSQuote(StateFile), Output) then
    begin
      MsgBox('The backup completed, but LanEx could not clear its continuation hook. '
        + 'Uninstall stopped; the environment and export are preserved.' + #13#10#13#10
        + Output, mbError, MB_OK);
      Exit;
    end;
    MsgBox('The verified backup was saved to:' + #13#10 + ExportFile + #13#10#13#10
      + 'The private environment is also being kept.', mbInformation, MB_OK);
    Result := True;
    Exit;
  end;

  if MsgBox('Permanently remove this LanEx environment and its projects, run results, '
      + 'PDKs, caches, and owned browser profile?' + #13#10#13#10
      + 'This cannot be undone. Other WSL distributions, the pre-existing generic '
      + 'LanEx browser profile, and Windows WSL features will not be changed.',
      mbError, MB_YESNO or MB_DEFBUTTON2) <> IDYES then Exit;
  Snippet := '-Action RemoveAppliance -StatePath ' + PSQuote(StateFile)
    + ' -OwnedDataRoot ' + PSQuote(AppDataRoot)
    + ' -ConfirmedInstallId $((Get-Content -LiteralPath ' + PSQuote(StateFile)
    + ' -Raw | ConvertFrom-Json).installId)';
  if not UninstallWorker(Snippet, Output) then
  begin
    MsgBox('Permanent removal did not complete. LanEx preserved the VHDX, state, '
      + 'caches, and logs so the problem can be diagnosed safely.' + #13#10#13#10
      + Output, mbError, MB_OK);
    Exit;
  end;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
begin
  if CurUninstallStep <> usUninstall then
    Exit;

  // Terminate any running LanEx launcher process for this specific installation
  Exec('powershell.exe', '-NoProfile -WindowStyle Hidden -Command "Get-Process -Name LanEx -ErrorAction SilentlyContinue | Where-Object { $_.Path -like ''' + ExpandConstant('{app}') + '\*'' } | Stop-Process -Force"', '', SW_HIDE, ewWaitUntilTerminated, Code);

  // Remove dynamically written launcher configuration
  DeleteFile(ExpandConstant('{app}\appliance.json'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Config, Output, Worker: String;
begin
  if CurStep <> ssPostInstall then
    Exit;

  // 1. Write the launcher appliance identity into {app}\appliance.json
  Config := '{"schema":2,"installId":"' + InstallIdValue
    + '","ownerSid":"' + OwnerSidValue
    + '","distroName":"' + DistroNameValue
    + '","sourceSha":"{#LanexSourceSha}","manifestHash":"'
    + ManifestHashValue + '"}' + #13#10;
  if not SaveStringToFile(ExpandConstant('{app}\appliance.json'), Config, False) then
  begin
    LogLine('ERROR: could not write launcher appliance identity');
    RecordSetupOutcome('failed', 'Could not write launcher appliance identity to ' + ExpandConstant('{app}\appliance.json'));
    Exit;
  end;

  // 2. Verify launcher binary exists
  if not FileExists(ExpandConstant('{app}\LanEx.exe')) then
  begin
    LogLine('ERROR: launcher binary missing from ' + ExpandConstant('{app}\LanEx.exe'));
    RecordSetupOutcome('failed', 'LanEx launcher binary was not installed correctly');
    Exit;
  end;

  // 3. Create Desktop shortcut if requested
  if (DesktopShortcutCheckbox <> nil) and DesktopShortcutCheckbox.Checked then
  begin
    CreateShellLink(
      ExpandConstant('{userdesktop}\{#AppName}.lnk'),
      '{#AppName}',
      ExpandConstant('{app}\LanEx.exe'),
      '',
      ExpandConstant('{app}'),
      ExpandConstant('{app}\lanex.ico'),
      0,
      SW_SHOWNORMAL
    );
    LogLine('created desktop shortcut');
  end;

  // 4. Commit final readiness now that Windows files, appliance.json, and Linux appliance are verified
  RecordSetupOutcome('ready', 'All selected components passed strict readiness.');

  // 5. Commit update checkpoint (clearing rollback state now that installation succeeded)
  CompleteUpdateCheckpoint(False);

  // 6. Clear continuation RunOnce / shortcut while preserving phase = ready
  Worker := ExpandConstant('{app}\setup-worker.ps1');
  if not FileExists(Worker) then
    Worker := ExpandConstant('{tmp}\setup.ps1');
  if not PowerShellCapture('& ' + PSQuote(Worker) + ' -Action ClearResume -StatePath '
      + PSQuote(StateFile), Output) then
    LogLine('WARNING: could not clear owned continuation shortcut: ' + Output);

  LogLine('=== installation successfully completed and verified ===');
end;
