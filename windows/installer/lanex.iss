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
; The data-only worker remains available to the uninstaller for owner/marker
; validation, verified export, resume cleanup, and explicit removal.
Source: "..\setup\setup.ps1"; DestDir: "{app}"; DestName: "setup-worker.ps1"; Flags: ignoreversion
Source: "..\setup\constraints.txt"; Flags: dontcopy
Source: "..\setup\build-manifest.json"; Flags: dontcopy
Source: "{#LanexWheel}"; DestName: "{#LanexWheelFile}"; Flags: dontcopy

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
  ProfilePage, EnginePage, ComponentPage, PdkPage, LibraryPage: TInputOptionWizardPage;
  EstimatePage: TOutputMsgWizardPage;
  LiveLogMemo: TNewMemo;
  OpenLogButton, CopyLogButton, SaveLogButton: TNewButton;
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
  if ProgressPhase > 0 then
    Caption := 'Phase ' + IntToStr(ProgressPhase) + ' of ' +
      IntToStr(ProgressPhaseCount) + '  |  ' + ElapsedText + '  |  ' + Caption;
  if WizardForm <> nil then
  begin
    WizardForm.PreparingLabel.Caption := Caption;
    WizardForm.PreparingLabel.Update;
    WizardForm.StatusLabel.Caption := Caption;
    WizardForm.StatusLabel.Update;
  end;
end;

procedure SetPhase(Number, Total: Integer; const S: String);
begin
  ProgressPhase := Number;
  ProgressPhaseCount := Total;
  ProgressActivity := S;
  RefreshProgressCaption;
  LogLine('--- phase ' + IntToStr(Number) + '/' + IntToStr(Total) + ': ' + S);
end;

procedure SetStatus(const S: String);
begin
  // The one progress surface the user sees during the slow parts. Without it a
  // five-minute provision looks like a hang.
  //
  // TWO labels, and PreparingLabel is the one that matters. Everything slow in
  // this installer — the rootfs download, import, and whole provisioning
  // run — happens inside PrepareToInstall, and PrepareToInstall runs while the
  // *Preparing* page is on screen. StatusLabel and ProgressGauge belong to the
  // *Installing* page, which is not reached until all of that is already over.
  // Setting only StatusLabel meant a real user sat in front of a blank white
  // page for eight minutes with no text, no bar and no way to tell a working
  // install from a hung one. StatusLabel is still set for the file-copy step
  // afterwards; writing to an off-screen control is harmless.
  ProgressActivity := S;
  RefreshProgressCaption;
  LogLine('--- ' + S);
end;

procedure ProgressTimerProc(HWnd, Msg, IdEvent, Time: LongWord);
begin
  RefreshProgressCaption;
end;

procedure AppendLiveLine(const S: String);
begin
  if (LiveLogMemo = nil) or WizardSilent then Exit;
  LiveLogMemo.Lines.Add(S);
  while LiveLogMemo.Lines.Count > 400 do
    LiveLogMemo.Lines.Delete(0);
  LiveLogMemo.SelStart := Length(LiveLogMemo.Text);
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

// Output is consumed line-by-line so the wizard stays meaningful during slow
// apt, image and PDK work. The memo is bounded; install.log rotates per run.
function RunLogged(const FileName, Params: String; var ResultCode: Integer): Boolean;
var
  PreviousWslEnv, ForwardedWslEnv: String;
begin
  ForceDirectories(LogDir);
  LogLine('$ ' + FileName + ' ' + Params);
  // `set WSL_UTF8=1&&` first, with no space before the &&, or the space becomes
  // part of the value. Without it wsl.exe writes UTF-16LE straight into a log
  // that is otherwise single-byte, and every WSL line comes back as
  // "T h e   o p e r a t i o n   c o m p l e t e d" — in the one file we ask
  // users to send us when an install fails.
  // WSL does not normally import arbitrary Windows environment variables.
  // WSLENV forwards only explicit proxy variables without putting their values
  // (often credentials) on the command line or in install.log. The previous
  // process-local WSLENV is restored immediately after the child exits.
  PreviousWslEnv := GetEnv('WSLENV');
  ForwardedWslEnv := 'HTTP_PROXY:HTTPS_PROXY:NO_PROXY:http_proxy:https_proxy:no_proxy';
  if PreviousWslEnv <> '' then
    ForwardedWslEnv := PreviousWslEnv + ':' + ForwardedWslEnv;
  SetProcessEnvironmentVariable('WSLENV', ForwardedWslEnv);
  try
    SetProcessEnvironmentVariable('WSL_UTF8', '1');
    ProgressTimer := SetTimer(0, 0, 1000, CreateCallback(@ProgressTimerProc));
    try
      Result := ExecAndLogOutput(FileName, Params, '', SW_HIDE,
        ewWaitUntilTerminated, ResultCode, @CommandOutput);
    finally
      if ProgressTimer <> 0 then KillTimer(0, ProgressTimer);
      ProgressTimer := 0;
      SetProcessEnvironmentVariable('WSL_UTF8', '');
    end;
  finally
    SetProcessEnvironmentVariable('WSLENV', PreviousWslEnv);
  end;
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

function SelectedPdkList: String;
var
  I: Integer;
begin
  Result := '';
  for I := 0 to 6 do
    if PdkPage.Values[I] then AddJsonString(Result, PdkName(I));
end;

function SelectedVariant(StartIndex, EndIndex: Integer): String;
var
  I: Integer;
begin
  Result := '';
  for I := StartIndex to EndIndex do
    if PdkPage.Values[I] then Result := PdkName(I);
end;

function LibraryName(Index: Integer): String;
begin
  case Index of
    0: Result := 'sky130_fd_sc_hdll';
    1: Result := 'sky130_fd_sc_lp';
    2: Result := 'sky130_fd_sc_ls';
    3: Result := 'sky130_fd_sc_ms';
    4: Result := 'sky130_fd_sc_hs';
    5: Result := 'sky130_fd_pr_reram';
    6: Result := 'gf180mcu_osu_sc_gp12t3v3';
    7: Result := 'gf180mcu_osu_sc_gp9t3v3';
    8: Result := 'gf180mcu_as_sc_mcu7t3v3';
    9: Result := 'gf180mcu_re_efuse';
    10: Result := 'gf180mcu_ocd_io';
    11: Result := 'gf180mcu_ocd_ip_sram';
    12: Result := 'gf180mcu_ocd_alpha_small';
    13: Result := 'gf180mcu_ocd_alpha_large';
    14: Result := 'gf180mcu_ocd_alpha_misc';
  else
    Result := '';
  end;
end;

function LibraryArray(StartIndex, EndIndex: Integer): String;
var
  I: Integer;
begin
  Result := '';
  for I := StartIndex to EndIndex do
    if LibraryPage.Values[I] then AddJsonString(Result, LibraryName(I));
  Result := '[' + Result + ']';
end;

function BuildChoicesJson: String;
var
  Native, Libraries, Variant: String;
begin
  if ProfilePage.SelectedValueIndex = 0 then
  begin
    Result := '{"profile":"recommended"}';
    Exit;
  end;
  if ProfilePage.SelectedValueIndex = 2 then
  begin
    Result := '{"profile":"minimal"}';
    Exit;
  end;
  Native := '';
  if ComponentPage.Values[1] then
  begin
    AddJsonString(Native, 'verilator');
    AddJsonString(Native, 'iverilog');
    AddJsonString(Native, 'graphviz');
    AddJsonString(Native, 'gtkwave');
  end;
  if ComponentPage.Values[2] then AddJsonString(Native, 'gds3d');
  if SelectedPdkList <> '' then ComponentPage.Values[0] := True;
  Libraries := '';
  Variant := SelectedVariant(0, 1);
  if Variant <> '' then
    Libraries := '"' + Variant + '":' + LibraryArray(0, 5);
  Variant := SelectedVariant(2, 5);
  if Variant <> '' then
  begin
    if Libraries <> '' then Libraries := Libraries + ',';
    Libraries := Libraries + '"' + Variant + '":' + LibraryArray(6, 14);
  end;
  if PdkPage.Values[6] then
  begin
    if Libraries <> '' then Libraries := Libraries + ',';
    Libraries := Libraries + '"ihp-sg13g2":[]';
  end;
  Result := '{"schema":1,"profile":"custom","engine":"';
  if EnginePage.SelectedValueIndex = 1 then Result := Result + 'podman'
  else Result := Result + 'docker';
  Result := Result + '","image":';
  if ComponentPage.Values[0] then Result := Result + 'true' else Result := Result + 'false';
  Result := Result + ',"nativeTools":[' + Native + '],"pdks":[' +
    SelectedPdkList + '],"libraries":{' + Libraries + '}}';
end;

function ValidatePdkFamilies(var Failure: String): Boolean;
var
  Sky, Gf, I: Integer;
begin
  Sky := 0; Gf := 0;
  for I := 0 to 1 do if PdkPage.Values[I] then Sky := Sky + 1;
  for I := 2 to 5 do if PdkPage.Values[I] then Gf := Gf + 1;
  Result := (Sky <= 1) and (Gf <= 1);
  if not Result then
    Failure := 'Choose only one variant from each PDK family. You may combine one SkyWater, one GlobalFoundries, and IHP.';
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
  else if FileExists(RootfsPath) and
     (CompareText(GetSHA256OfFile(RootfsPath), '{#RootfsSha256}') = 0) then
  begin
    AppNeed := AppNeed - {#RootfsSizeMB};
    TempNeed := 0;
  end;
  if CompareText(ExtractFileDrive(AppDataRoot), ExtractFileDrive(ExpandConstant('{tmp}'))) = 0 then
  begin
    if GetSpaceOnDisk(AppDataRoot, True, AppFree, AppTotal) and
       (Int64(AppFree) < AppNeed + TempNeed) then
    begin
      Failure := 'The selected setup needs about ' + IntToStr(AppNeed + TempNeed) +
        ' MB free on ' + ExtractFileDrive(AppDataRoot) + ', but only ' +
        IntToStr(AppFree) + ' MB is available.';
      Result := False;
    end;
  end
  else
  begin
    if GetSpaceOnDisk(AppDataRoot, True, AppFree, AppTotal) and (Int64(AppFree) < AppNeed) then
    begin
      Failure := 'The selected setup needs about ' + IntToStr(AppNeed) +
        ' MB free for the LanEx environment, but only ' + IntToStr(AppFree) + ' MB is available.';
      Result := False;
      Exit;
    end;
    if GetSpaceOnDisk(ExpandConstant('{tmp}'), True, TempFree, TempTotal) and
       (Int64(TempFree) < TempNeed) then
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

procedure InitializeWizard;
var
  I: Integer;
begin
  ProfilePage := CreateInputOptionPage(wpLicense, 'Choose your LanEx setup',
    'Recommended installs everything needed for a first RTL-to-GDS run.',
    'Choose a setup profile. Custom exposes engines, tools, PDKs and advanced libraries.', True, False);
  ProfilePage.Add('&Recommended — Docker, all supported tools, GDS3D, sky130A and all sky130 libraries');
  ProfilePage.Add('&Custom — choose engine, tools, PDK variants and advanced libraries');
  ProfilePage.Add('&Minimal — LanEx application only; the Tools page will show what remains');
  ProfilePage.SelectedValueIndex := 0;

  EnginePage := CreateInputOptionPage(ProfilePage.ID, 'Container engine',
    'Docker and Podman are alternatives.', 'Choose one engine for container flows.', True, False);
  EnginePage.Add('&Docker CE (recommended)');
  EnginePage.Add('&Podman');
  EnginePage.SelectedValueIndex := 0;

  ComponentPage := CreateInputOptionPage(EnginePage.ID, 'Tools and flow support',
    'Choose the capabilities Setup should make ready now.',
    'PDKs automatically require the matched LibreLane image.', False, False);
  ComponentPage.Add('Matched &LibreLane container image');
  ComponentPage.Add('&Simulation/report/viewer tools — Verilator, Icarus, Graphviz, GTKWave');
  ComponentPage.Add('&GDS3D layout viewer and build/runtime support');
  for I := 0 to 2 do ComponentPage.Values[I] := True;

  PdkPage := CreateInputOptionPage(ComponentPage.ID, 'Process design kits',
    'Choose any supported families; choose only one variant within a family.',
    'sky130A is the recommended default. Approximate full-family sizes are shown.', False, True);
  PdkPage.Add('&sky130A — SkyWater 130 nm, ~2.5 GB (recommended)');
  PdkPage.Add('sky130&B — SkyWater 130 nm with ReRAM/SONOS models, ~2.5 GB');
  PdkPage.Add('gf180mcu&A — GlobalFoundries 180 nm, ~1.8 GB');
  PdkPage.Add('gf180mcu&B — GlobalFoundries 180 nm, ~1.8 GB');
  PdkPage.Add('gf180mcu&C — GlobalFoundries 180 nm, ~1.8 GB');
  PdkPage.Add('gf180mcu&D — GlobalFoundries 180 nm, ~1.8 GB');
  PdkPage.Add('&IHP SG13G2 — 130 nm SiGe BiCMOS, ~1.9 GB');
  PdkPage.Values[0] := True;

  LibraryPage := CreateInputOptionPage(PdkPage.ID, 'Advanced PDK libraries',
    'Required libraries are always included. These are additional supported libraries.',
    'Selections apply only to the chosen variant in that family.', False, True);
  LibraryPage.Add('Sky130: sky130_fd_sc_hdll');
  LibraryPage.Add('Sky130: sky130_fd_sc_lp');
  LibraryPage.Add('Sky130: sky130_fd_sc_ls');
  LibraryPage.Add('Sky130: sky130_fd_sc_ms');
  LibraryPage.Add('Sky130: sky130_fd_sc_hs');
  LibraryPage.Add('Sky130: sky130_fd_pr_reram');
  LibraryPage.Add('GF180: gf180mcu_osu_sc_gp12t3v3');
  LibraryPage.Add('GF180: gf180mcu_osu_sc_gp9t3v3');
  LibraryPage.Add('GF180: gf180mcu_as_sc_mcu7t3v3');
  LibraryPage.Add('GF180: gf180mcu_re_efuse');
  LibraryPage.Add('GF180: gf180mcu_ocd_io');
  LibraryPage.Add('GF180: gf180mcu_ocd_ip_sram');
  LibraryPage.Add('GF180: gf180mcu_ocd_alpha_small');
  LibraryPage.Add('GF180: gf180mcu_ocd_alpha_large');
  LibraryPage.Add('GF180: gf180mcu_ocd_alpha_misc');
  for I := 0 to 5 do LibraryPage.Values[I] := True;

  EstimatePage := CreateOutputMsgPage(LibraryPage.ID, 'Review download and space',
    'Measured estimates', 'Setup will calculate this from your choices.');

  LiveLogMemo := TNewMemo.Create(WizardForm);
  LiveLogMemo.Parent := WizardForm.InnerPage;
  LiveLogMemo.Left := ScaleX(0);
  LiveLogMemo.Top := ScaleY(78);
  LiveLogMemo.Width := WizardForm.InnerPage.ClientWidth;
  LiveLogMemo.Height := ScaleY(185);
  LiveLogMemo.ScrollBars := ssVertical;
  LiveLogMemo.ReadOnly := True;
  LiveLogMemo.Anchors := [akLeft, akTop, akRight, akBottom];
  LiveLogMemo.Visible := False;

  OpenLogButton := TNewButton.Create(WizardForm);
  OpenLogButton.Parent := WizardForm.InnerPage;
  OpenLogButton.Caption := '&Open log';
  OpenLogButton.SetBounds(ScaleX(0), ScaleY(270), ScaleX(90), ScaleY(24));
  OpenLogButton.OnClick := @OpenDiagnostics;
  OpenLogButton.Visible := False;
  CopyLogButton := TNewButton.Create(WizardForm);
  CopyLogButton.Parent := WizardForm.InnerPage;
  CopyLogButton.Caption := '&Copy diagnostics';
  CopyLogButton.SetBounds(ScaleX(98), ScaleY(270), ScaleX(115), ScaleY(24));
  CopyLogButton.OnClick := @CopyDiagnostics;
  CopyLogButton.Visible := False;
  SaveLogButton := TNewButton.Create(WizardForm);
  SaveLogButton.Parent := WizardForm.InnerPage;
  SaveLogButton.Caption := '&Save log';
  SaveLogButton.SetBounds(ScaleX(221), ScaleY(270), ScaleX(90), ScaleY(24));
  SaveLogButton.OnClick := @SaveDiagnostics;
  SaveLogButton.Visible := False;
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
    StagedChoices, SourceCompanion, CachedCompanion: String;
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
  HadState := FileExists(StateFile);
  if ExpandConstant('{param:UPDATE|0}') = '1' then
    OperationName := 'update'
  else if HadState then
    OperationName := 'repair'
  else
    OperationName := 'install';

  StagedChoices := ExpandConstant('{tmp}\choices-state.json');
  if not SaveStringToFile(StagedChoices, ChoicesJsonValue, False) then
  begin
    Result := 'LanEx could not stage its selected component choices.'
      + #13#10#13#10 + 'No WSL distribution or user data was changed.';
    Exit;
  end;

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
  RepairExisting := HadState and DistroExists;
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
  ImportPath := RootfsPath;
  Result := FetchRootfs('{#RootfsUrl}', '{#RootfsFile}', '{#RootfsSha256}',
                        RootfsPath, '{#RootfsSizeMB}');
end;

// ProvisionDistro runs provision.sh inside the freshly imported distro.
procedure RecordSetupOutcome(const Outcome, MessageText: String);
var
  Worker, Output, Snippet: String;
begin
  Worker := ExpandConstant('{tmp}\setup.ps1');
  Snippet := '& ' + PSQuote(Worker) + ' -Action RecordOutcome -StatePath ' +
    PSQuote(StateFile) + ' -Outcome ' + Outcome + ' -OutcomeMessage ' + PSQuote(MessageText);
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
  Params := '-d "' + DistroNameValue + '" -u root -- env '
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
  Result := RunLogged(WslExe, '-d "' + DistroNameValue + '" -u root -- env '
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
  RotateInstallLog;
  ForceDirectories(LogDir);
  ProgressStartedTick := GetTickCount;
  if ChoicesJsonValue = '' then ChoicesJsonValue := '{"profile":"recommended"}';
  LogLine('');
  LogLine('=== LanEx Setup {#AppVersion} — ' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':')
    + ' (resume=' + ExpandConstant('{param:RESUME|0}') + ') ===');

  // Establish immutable owner/build/appliance identity before enabling WSL,
  // downloading, importing, terminating, or provisioning anything.
  Result := InitializeDurableState;
  if Result <> '' then
    Exit;
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
    if not WizardSilent then MsgBox('Windows needs to restart to finish switching on the Linux subsystem.'
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
    begin
      if CancelRequested then
      begin
        Result := 'LanEx Setup was cancelled. A partial rootfs transfer was not cached; completed verified downloads remain reusable.';
        RecordSetupOutcome('cancelled', Result);
      end;
      Exit;
    end;
    SetPhase(3, 6, 'Creating the private LanEx environment...');
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
  if not (RunLogged(WslExe, '--terminate "' + DistroNameValue + '"', Code) and (Code = 0)) then
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
  if not CompleteUpdateCheckpoint(False) then
  begin
    Result := 'The update became ready, but Setup could not close its rollback checkpoint. '
      + 'The environment and rollback data were preserved for Repair.';
    Exit;
  end;
  RecordSetupOutcome('ready', 'All selected components passed strict readiness.');
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

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Failure: String;
begin
  Result := True;
  if WizardSilent then Exit;
  if (CurPageID = PdkPage.ID) and not ValidatePdkFamilies(Failure) then
  begin
    MsgBox(Failure, mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if ((CurPageID = ProfilePage.ID) and (ProfilePage.SelectedValueIndex <> 1)) or
     (CurPageID = LibraryPage.ID) then
  begin
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
        'Completed verified downloads are reused. Free space, then click Next again.',
        mbError, MB_OK);
      Result := False;
      Exit;
    end;
    EstimatePage.MsgLabel.Caption :=
      'Estimated network download: about ' + IntToStr(EstimateDownloadMB div 1024) + ' GB' + #13#10 +
      'Estimated installed components: about ' + IntToStr(EstimateInstalledMB div 1024) + ' GB' + #13#10 +
      'Recommended free space on the LanEx data drive: about ' + IntToStr(RequiredAppMB div 1024) + ' GB' + #13#10 +
      'Temporary space while the rootfs is copied: about ' + IntToStr(RequiredTempMB) + ' MB' + #13#10#13#10 +
      'The estimate includes extraction space and practical design-run headroom. '
      + 'Completed rootfs files, image layers and validated PDK data are reused. '
      + 'A partial rootfs download restarts from the beginning; Setup does not claim range resume.';
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  // The self-resuming run after the restart goes straight to the progress page:
  // the user already accepted the licence and chose their options.
  Result := (IsContinuationRun and
            ((PageID = wpWelcome) or (PageID = wpLicense) or
             (PageID = wpSelectTasks) or (PageID = ProfilePage.ID) or
             (PageID = EnginePage.ID) or (PageID = ComponentPage.ID) or
             (PageID = PdkPage.ID) or (PageID = LibraryPage.ID) or
             (PageID = EstimatePage.ID))) or
            ((PageID = EnginePage.ID) or (PageID = ComponentPage.ID) or
             (PageID = PdkPage.ID) or (PageID = LibraryPage.ID)) and
             (ProfilePage.SelectedValueIndex <> 1);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if LiveLogMemo <> nil then
  begin
    LiveLogMemo.Visible := CurPageID = wpPreparing;
    OpenLogButton.Visible := CurPageID = wpPreparing;
    CopyLogButton.Visible := CurPageID = wpPreparing;
    SaveLogButton.Visible := CurPageID = wpPreparing;
  end;
  if (CurPageID = wpFinished) and not WslPending then
    // Setup now closes selected readiness before presenting Finish; the Tools
    // page remains available for later additions/removal and diagnostics.
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10
      + 'Your selected tools, container image, and PDK libraries were installed '
      + 'and passed LanEx''s setup readiness checks.';
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
var
  Code: Integer;
begin
  if ((CurPageID = wpPreparing) or (CurPageID = wpInstalling)) and
     (DistroNameValue <> '') and not CancelRequested then
  begin
    CancelRequested := True;
    Cancel := False;
    Confirm := False;
    SetStatus('Stopping safely... the current package database operation will finish first.');
    LogLine('cancellation requested by user');
    Exec(WslExe, '-d "' + DistroNameValue + '" -u root -- sh -c "mkdir -p /run/lanex; touch /run/lanex/setup.cancel"',
      '', SW_HIDE, ewWaitUntilTerminated, Code);
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
    if not UninstallWorker('-Action ClearResume -StatePath ' + PSQuote(StateFile), Output) then
    begin
      MsgBox('LanEx could not remove its owner-bound continuation hook, so uninstall '
        + 'was stopped safely.' + #13#10#13#10 + Output, mbError, MB_OK);
      Exit;
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
begin
  if CurUninstallStep <> usUninstall then
    Exit;

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
  Config := '{"schema":2,"installId":"' + InstallIdValue
    + '","ownerSid":"' + OwnerSidValue
    + '","distroName":"' + DistroNameValue
    + '","sourceSha":"{#LanexSourceSha}","manifestHash":"'
    + ManifestHashValue + '"}' + #13#10;
  if not SaveStringToFile(ExpandConstant('{app}\appliance.json'), Config, False) then
    LogLine('WARNING: could not write launcher appliance identity');
end;
