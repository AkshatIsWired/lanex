# Copyright 2026 LanEx Contributors
# Licensed under the Apache License, Version 2.0.

<#
LanEx Setup's narrow, versioned state worker. It deliberately accepts data, not
arbitrary command text. Inno owns the UI; this file owns immutable build
identity, atomic owner-scoped state, and exact WSL registration binding.

Windows PowerShell 5.1 is the compatibility floor.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('NewManifest', 'InitializeState', 'ResolveAppliance', 'BindAppliance', 'SetComponent', 'ReadState',
        'Preflight', 'EnableFeatures', 'StageInstaller', 'RegisterResume', 'ClearResume', 'PlanChoices')]
    [string]$Action,
    [string]$StatePath,
    [string]$ManifestPath,
    [ValidateSet('install', 'repair', 'update')]
    [string]$Operation = 'install',
    [string]$ChoicesJson = '{}',
    [string]$ChoicesPath,
    [string]$InstallerPath,
    [string]$PreferredDistroName = 'lanex',
    [string]$ExpectedBasePath,
    [string]$RegistrySnapshotPath,
    [string]$Component,
    [ValidateSet('pending', 'running', 'complete', 'failed', 'cancelled')]
    [string]$ComponentStatus = 'pending',
    [string]$InputFingerprint,
    [string]$Phase,
    [string]$OutputPath,
    [string]$SourceRepository = 'AkshatIsWired/lanex',
    [string]$SourceRef = 'main',
    [string]$SourceSha,
    [string]$AppVersion = '0.0.0',
    [string]$Channel = 'candidate',
    [string]$WheelPath,
    [string]$InstallScriptPath,
    [string]$ProvisionScriptPath,
    [string]$SelftestPath,
    [string]$ConstraintsPath,
    [string]$CatalogPath,
    [string]$PdkPinsPath,
    [string]$RootfsUrl,
    [string]$RootfsSha256,
    [Int64]$RootfsSizeBytes,
    [string]$BakedRootfsUrl = '',
    [string]$BakedRootfsSha256 = '',
    [Int64]$BakedRootfsSizeBytes = 0,
    [string]$ImageReference = 'ghcr.io/librelane/librelane:3.0.4',
    [string]$ImageDigest,
    [string]$Gds3dCommit,
    [string]$PreflightFixturePath,
    [string]$FeatureFixturePath,
    [string]$ResumeInstallerPath,
    [string]$BootIdentity,
    [ValidateSet('0', '1')]
    [string]$ResumeMode = '0',
    [string]$TestResumeRoot,
    [string]$ExpectedSelfSha256,
    [string]$TestOwnerSid,
    [string]$TestInstallId
)

$ErrorActionPreference = 'Stop'
$StateSchema = 1
$ManifestSchema = 1

function Get-Sha256([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required payload is missing: $Path"
    }
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

if ($ExpectedSelfSha256) {
    if ($ExpectedSelfSha256 -notmatch '^[0-9a-fA-F]{64}$' -or
            (Get-Sha256 $PSCommandPath) -ne $ExpectedSelfSha256.ToLowerInvariant()) {
        throw 'Elevated setup worker integrity check failed before any feature operation.'
    }
}

function Get-TextSha256([string]$Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
}

function Read-JsonFile([string]$Path, [string]$Kind) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Kind is missing: $Path" }
    try { return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json) }
    catch { throw "$Kind is malformed JSON: $($_.Exception.Message)" }
}

function Write-AtomicJson([string]$Path, $Value) {
    $parent = Split-Path -Parent $Path
    if (-not $parent) { throw "State path must have a parent directory." }
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $temp = Join-Path $parent ('.state-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    $backup = Join-Path $parent ('.state-' + [Guid]::NewGuid().ToString('N') + '.bak')
    try {
        $json = $Value | ConvertTo-Json -Depth 100
        $utf8 = New-Object Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($temp, $json + [Environment]::NewLine, $utf8)
        $stream = [IO.File]::Open($temp, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        try { $stream.Flush($true) } finally { $stream.Dispose() }
        if ($env:LANEX_SETUP_TEST_FAIL_BEFORE_REPLACE -eq '1') {
            throw 'Injected interruption before atomic replace.'
        }
        if (Test-Path -LiteralPath $Path) {
            [IO.File]::Replace($temp, $Path, $backup, $true)
            Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
        } else {
            [IO.File]::Move($temp, $Path)
        }
    } finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
    }
}

function Get-OwnerSid {
    if ($TestOwnerSid) {
        if ($env:LANEX_SETUP_TESTING -ne '1') { throw 'TestOwnerSid is accepted only by the test harness.' }
        return $TestOwnerSid
    }
    return [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
}

function Get-NewInstallId {
    if ($TestInstallId) {
        if ($env:LANEX_SETUP_TESTING -ne '1') { throw 'TestInstallId is accepted only by the test harness.' }
        return ([Guid]$TestInstallId).ToString()
    }
    return [Guid]::NewGuid().ToString()
}

function Assert-Manifest($Manifest) {
    if ($null -eq $Manifest.schema -or [int]$Manifest.schema -ne $ManifestSchema) {
        throw "Unsupported build manifest schema '$($Manifest.schema)'; expected $ManifestSchema."
    }
    if ([string]$Manifest.source.sha -notmatch '^[0-9a-fA-F]{40}$') { throw 'Manifest source SHA is invalid.' }
    if ([string]$Manifest.source.repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'Manifest source repository is invalid.' }
}

function Migrate-State($State) {
    if ($null -eq $State.schema) { throw 'Install state has no schema.' }
    $schema = [int]$State.schema
    if ($schema -gt $StateSchema) { throw "Install state schema $schema is newer than this Setup supports." }
    if ($schema -lt 1) {
        # No schema-0 state was ever released. Refuse it explicitly rather than
        # guessing ownership from a historical, unversioned file.
        throw "Install state schema $schema has no safe migration path."
    }
    return $State
}

function Assert-StateOwner($State, [string]$OwnerSid) {
    if ([string]::IsNullOrWhiteSpace([string]$State.installId)) { throw 'Install state has no install ID.' }
    try { [void][Guid]([string]$State.installId) } catch { throw 'Install state install ID is invalid.' }
    if ([string]$State.ownerSid -ne $OwnerSid) { throw 'Install state belongs to a different Windows user.' }
}

function Get-RegistryEntries {
    if ($RegistrySnapshotPath) {
        $snapshot = Read-JsonFile $RegistrySnapshotPath 'Registry snapshot'
        return @($snapshot)
    }
    $root = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
    if (-not (Test-Path $root)) { return @() }
    $entries = @()
    foreach ($key in Get-ChildItem -LiteralPath $root) {
        $p = Get-ItemProperty -LiteralPath $key.PSPath
        $entries += [pscustomobject]@{
            registryId = $key.PSChildName
            name = [string]$p.DistributionName
            basePath = [string]$p.BasePath
        }
    }
    return $entries
}

function Normalize-Path([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return '' }
    return [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($Path)).TrimEnd('\').ToLowerInvariant()
}

function Add-OrSet($Object, [string]$Name, $Value) {
    if ($Object.PSObject.Properties[$Name]) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

function Get-ChoiceProperty($Object, [string]$Name, $Default) {
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}

function ConvertTo-NormalizedChoices($Manifest, $RawChoices) {
    <# Interactive and unattended setup meet at this strict boundary. Nothing
       selected here may become a Linux argument unless it occurs in the
       hash-bound manifest. A missing profile is the compatible M3/M4 shape. #>
    if ($null -eq $RawChoices -or $RawChoices -isnot [psobject]) {
        throw 'Selections must contain a JSON object.'
    }
    $catalog = $Manifest.pdkCatalog
    if ($null -eq $catalog) { throw 'Build manifest has no PDK catalog.' }
    $profile = [string](Get-ChoiceProperty $RawChoices 'profile' 'custom')
    if ($profile -notin @('recommended', 'custom', 'minimal')) {
        throw 'profile must be recommended, custom, or minimal.'
    }
    if ($profile -eq 'recommended') {
        if ($null -eq $catalog.PSObject.Properties['sky130A']) {
            throw 'The recommended sky130A PDK is absent from the build manifest.'
        }
        return [pscustomobject][ordered]@{
            schema = 1; profile = 'recommended'; engine = 'docker'; image = $true
            nativeTools = @('verilator', 'iverilog', 'graphviz', 'gtkwave', 'gds3d')
            pdks = @('sky130A'); libraries = 'all'
        }
    }
    if ($profile -eq 'minimal') {
        return [pscustomobject][ordered]@{
            schema = 1; profile = 'minimal'; engine = 'none'; image = $false
            nativeTools = @(); pdks = @(); libraries = [pscustomobject][ordered]@{}
        }
    }

    $engine = [string](Get-ChoiceProperty $RawChoices 'engine' 'docker')
    if ($engine -notin @('docker', 'podman', 'none')) {
        throw 'engine must be docker, podman, or none.'
    }
    $imageValue = Get-ChoiceProperty $RawChoices 'image' $true
    if ($imageValue -isnot [bool]) { throw 'image must be true or false.' }
    $image = [bool]$imageValue
    $allowedTools = @('verilator', 'iverilog', 'graphviz', 'gtkwave', 'gds3d')
    $nativeProperty = $RawChoices.PSObject.Properties['nativeTools']
    if ($null -ne $nativeProperty -and $nativeProperty.Value -isnot [array]) {
        throw 'nativeTools must be an array.'
    }
    $nativeRaw = if ($null -eq $nativeProperty) { $allowedTools } else { @($nativeProperty.Value) }
    $native = @()
    foreach ($tool in @($nativeRaw)) {
        if ($tool -isnot [string] -or $tool -notin $allowedTools) {
            throw "Unsupported native tool selection: $tool"
        }
        if ($native -notcontains [string]$tool) { $native += [string]$tool }
    }

    $selectedProperty = $RawChoices.PSObject.Properties['pdks']
    if ($null -ne $selectedProperty -and $selectedProperty.Value -isnot [array]) {
        throw 'pdks must be an array.'
    }
    $selectedRaw = if ($null -eq $selectedProperty) { @('sky130A') } else { @($selectedProperty.Value) }
    $selected = @()
    $families = @{}
    foreach ($variantValue in @($selectedRaw)) {
        $variant = [string]$variantValue
        $entry = $catalog.PSObject.Properties[$variant]
        if (-not $variant -or $null -eq $entry) { throw "Unknown PDK variant: $variant" }
        $family = [string]$entry.Value.family
        if ($families.ContainsKey($family) -and $families[$family] -ne $variant) {
            throw "Select only one $family variant at a time ($($families[$family]), $variant)."
        }
        $families[$family] = $variant
        if ($selected -notcontains $variant) { $selected += $variant }
    }
    if (($image -or $selected.Count -gt 0) -and $engine -eq 'none') {
        throw 'A selected flow image or PDK requires Docker or Podman.'
    }
    if ($selected.Count -gt 0 -and -not $image) {
        throw 'Selected PDKs require the matched flow image.'
    }

    $libraryRaw = Get-ChoiceProperty $RawChoices 'libraries' 'all'
    if ($libraryRaw -is [string]) {
        if ([string]$libraryRaw -ne 'all') {
            throw "libraries must be 'all' or an object keyed by selected PDK."
        }
        $libraries = 'all'
    } else {
        if ($libraryRaw -isnot [System.Management.Automation.PSCustomObject]) {
            throw "libraries must be 'all' or an object keyed by selected PDK."
        }
        $libraries = [pscustomobject][ordered]@{}
        foreach ($property in @($libraryRaw.PSObject.Properties)) {
            if ($selected -notcontains $property.Name) {
                throw "Libraries were supplied for an unselected PDK: $($property.Name)"
            }
        }
        foreach ($variant in $selected) {
            $entry = $catalog.PSObject.Properties[$variant].Value
            $allowed = @($entry.libraries | ForEach-Object { [string]$_ })
            $required = @($entry.default_libraries | ForEach-Object { [string]$_ })
            $requestedProperty = $libraryRaw.PSObject.Properties[$variant]
            if ($null -ne $requestedProperty -and
                    $requestedProperty.Value -isnot [array]) {
                throw "Libraries for $variant must be an array."
            }
            $requested = if ($null -eq $requestedProperty) { @() } else { @($requestedProperty.Value) }
            $merged = @()
            foreach ($libraryValue in @($required) + @($requested)) {
                $library = [string]$libraryValue
                if (-not $library -or $allowed -notcontains $library) {
                    throw "Unknown library for ${variant}: $library"
                }
                if ($merged -notcontains $library) { $merged += $library }
            }
            Add-OrSet $libraries $variant $merged
        }
    }
    return [pscustomobject][ordered]@{
        schema = 1; profile = 'custom'; engine = $engine; image = $image
        nativeTools = $native; pdks = $selected; libraries = $libraries
    }
}

function Get-SelectionEstimate($Manifest, $Choices) {
    # Planning estimates, never download promises. Base/rootfs/image values are
    # measured in the documented 2026 reference run; PDK sizes come from the
    # locked Ciel catalog and receive extraction/cache headroom.
    $gib = [int64]1073741824
    $rootfs = [int64]$Manifest.rootfs.sizeBytes
    $baseInstalled = [int64]([math]::Ceiling(1.3 * $gib))
    $baseNetwork = [int64]([math]::Ceiling(0.9 * $gib))
    $nativeInstalled = if (@($Choices.nativeTools).Count -gt 0) { [int64]([math]::Ceiling(1.2 * $gib)) } else { 0 }
    $nativeNetwork = if (@($Choices.nativeTools).Count -gt 0) { [int64]([math]::Ceiling(0.7 * $gib)) } else { 0 }
    $imageNetwork = if ($Choices.image) { 3 * $gib } else { 0 }
    $imageInstalled = if ($Choices.image) { 4 * $gib } else { 0 }
    $pdkNetwork = [int64]0
    foreach ($variant in @($Choices.pdks)) {
        $approx = [double]$Manifest.pdkCatalog.PSObject.Properties[[string]$variant].Value.approx_gb
        $pdkNetwork += [int64]([math]::Ceiling($approx * $gib))
    }
    $pdkInstalled = [int64]([math]::Ceiling($pdkNetwork * 1.6))
    $runHeadroom = if ($Choices.image) { 4 * $gib } else { 1 * $gib }
    return [pscustomobject][ordered]@{
        schema = 1
        measuredBasis = '2026 reference run plus locked catalog approximations'
        downloadBytes = $rootfs + $baseNetwork + $nativeNetwork + $imageNetwork + $pdkNetwork
        installedBytes = $baseInstalled + $nativeInstalled + $imageInstalled + $pdkInstalled
        extractionHeadroomBytes = [int64]([math]::Ceiling(($imageNetwork + $pdkNetwork) * 0.35))
        practicalRunHeadroomBytes = $runHeadroom
        volumes = [pscustomobject][ordered]@{
            appDataRequiredBytes = $rootfs + $baseInstalled + $nativeInstalled + $imageInstalled + $pdkInstalled + $runHeadroom
            tempRequiredBytes = $rootfs
        }
        notes = @(
            'Completed rootfs, image layers and validated PDK data are reusable.',
            'An interrupted rootfs transfer restarts; partial-range resume is not claimed.',
            'Actual registry compression, selected libraries and future design runs can vary.'
        )
    }
}

function Get-PlannedChoices {
    $manifest = Read-JsonFile $ManifestPath 'Build manifest'
    Assert-Manifest $manifest
    $raw = if ($ChoicesPath) {
        Read-JsonFile $ChoicesPath 'Selection file'
    } else {
        try { $ChoicesJson | ConvertFrom-Json } catch { throw 'ChoicesJson is malformed.' }
    }
    if ($raw.PSObject.Properties['choices']) { $raw = $raw.choices }
    $choices = ConvertTo-NormalizedChoices $manifest $raw
    return [pscustomobject][ordered]@{
        schema = 1; choices = $choices; estimates = Get-SelectionEstimate $manifest $choices
    }
}

function Get-FeatureState([string]$Name) {
    try {
        $feature = Get-CimInstance Win32_OptionalFeature -Filter ("Name='" + $Name + "'") -ErrorAction Stop
        if ($null -eq $feature) { return 'unknown' }
        switch ([int]$feature.InstallState) {
            1 { return 'enabled' }
            2 { return 'disabled' }
            3 { return 'absent' }
            default { return 'unknown' }
        }
    } catch { return 'unknown' }
}

function Get-LivePreflightFacts {
    $nativeArchitecture = ''
    try {
        $nativeArchitecture = [string](Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment' -ErrorAction Stop).PROCESSOR_ARCHITECTURE
    } catch { $nativeArchitecture = [string]$env:PROCESSOR_ARCHITEW6432 }
    if ([string]::IsNullOrWhiteSpace($nativeArchitecture)) {
        $nativeArchitecture = [string]$env:PROCESSOR_ARCHITECTURE
    }

    $computerSystem = $null
    $processor = $null
    $operatingSystem = $null
    try { $computerSystem = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop } catch {}
    try { $processor = @(Get-CimInstance Win32_Processor -ErrorAction Stop)[0] } catch {}
    try { $operatingSystem = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop } catch {}

    $hypervisor = $null
    if ($null -ne $computerSystem -and $null -ne $computerSystem.HypervisorPresent) {
        $hypervisor = [bool]$computerSystem.HypervisorPresent
    }
    $firmware = 'unknown'
    if ($hypervisor -eq $true) {
        $firmware = 'enabled'
    } elseif ($null -ne $processor -and $null -ne $processor.VirtualizationFirmwareEnabled) {
        $firmware = if ([bool]$processor.VirtualizationFirmwareEnabled) { 'enabled' } else { 'disabled' }
    }

    $pending = $false
    try {
        $pending = (Test-Path -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') -or
            (Test-Path -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired')
        $sessionManager = Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -ErrorAction SilentlyContinue
        if ($null -ne $sessionManager.PendingFileRenameOperations) { $pending = $true }
    } catch { $pending = $null }

    $wslExe = Join-Path $env:SystemRoot 'System32\wsl.exe'
    $wslPresent = Test-Path -LiteralPath $wslExe -PathType Leaf
    $wslVersion = ''
    $statusUsable = $false
    if ($wslPresent) {
        try {
            $versionText = (& $wslExe --version 2>&1 | Out-String)
            if ($LASTEXITCODE -eq 0 -and $versionText -match '(?im)^WSL version:\s*([0-9]+(?:\.[0-9]+){1,3})') {
                $wslVersion = $Matches[1]
            }
        } catch {}
        if (-not $wslVersion) {
            try {
                $package = Get-AppxPackage -Name MicrosoftCorporationII.WindowsSubsystemForLinux -ErrorAction Stop
                if ($null -ne $package) { $wslVersion = [string]$package.Version }
            } catch {}
        }
        try { & $wslExe --status *> $null; $statusUsable = ($LASTEXITCODE -eq 0) } catch {}
    }
    $systemdCapable = $false
    try { $systemdCapable = ([version]$wslVersion -ge [version]'0.67.6') } catch {}
    $boot = ''
    if ($null -ne $operatingSystem -and $null -ne $operatingSystem.LastBootUpTime) {
        try { $boot = $operatingSystem.LastBootUpTime.ToUniversalTime().ToString('o') } catch {}
    }
    if (-not $boot) { $boot = 'uptime-' + [string][Environment]::TickCount64 }

    return [pscustomobject][ordered]@{
        nativeArchitecture = $nativeArchitecture.ToUpperInvariant()
        windowsBuild = [Environment]::OSVersion.Version.Build
        computer = [pscustomobject][ordered]@{
            manufacturer = if ($null -eq $computerSystem) { '' } else { [string]$computerSystem.Manufacturer }
            model = if ($null -eq $computerSystem) { '' } else { [string]$computerSystem.Model }
        }
        hypervisorPresent = $hypervisor
        firmwareVirtualization = $firmware
        features = [pscustomobject][ordered]@{
            wsl = Get-FeatureState 'Microsoft-Windows-Subsystem-Linux'
            virtualMachinePlatform = Get-FeatureState 'VirtualMachinePlatform'
        }
        pendingReboot = $pending
        bootIdentity = $boot
        wsl = [pscustomobject][ordered]@{
            present = $wslPresent
            statusUsable = $statusUsable
            version = $wslVersion
            systemdCapable = $systemdCapable
        }
    }
}

function Get-PreflightDecision($Facts) {
    $code = 'ready'
    $blocked = $false
    $needsElevation = $false
    $needsRestart = $false
    $firmwareNotice = $false
    if ([string]$Facts.nativeArchitecture -ne 'AMD64') {
        $code = 'unsupported-architecture'; $blocked = $true
    } elseif ([int]$Facts.windowsBuild -lt 19044) {
        $code = 'unsupported-windows'; $blocked = $true
    } elseif ($Facts.hypervisorPresent -ne $true -and
            [string]$Facts.firmwareVirtualization -eq 'disabled' -and
            $Facts.wsl.statusUsable -ne $true) {
        $code = 'firmware-disabled'; $blocked = $true
    } elseif ([string]$Facts.features.wsl -eq 'unknown' -or
            [string]$Facts.features.virtualMachinePlatform -eq 'unknown') {
        $code = 'preflight-query-failed'; $blocked = $true
    } elseif ([string]$Facts.features.wsl -match 'pending' -or
            [string]$Facts.features.virtualMachinePlatform -match 'pending' -or
            ($Facts.pendingReboot -eq $true -and $Facts.wsl.statusUsable -ne $true)) {
        $code = 'restart-required'; $needsRestart = $true
    } elseif ([string]$Facts.features.wsl -ne 'enabled' -or
            [string]$Facts.features.virtualMachinePlatform -ne 'enabled') {
        $code = 'features-required'; $needsElevation = $true
        $firmwareNotice = ([string]$Facts.firmwareVirtualization -eq 'unknown')
    } elseif ($Facts.wsl.statusUsable -ne $true -or $Facts.wsl.systemdCapable -ne $true) {
        $code = 'wsl-update-required'
    }
    return [pscustomobject][ordered]@{
        code = $code
        blocked = $blocked
        needsElevation = $needsElevation
        needsRestart = $needsRestart
        firmwareNotice = $firmwareNotice
    }
}

function Invoke-Preflight {
    if ($PreflightFixturePath) {
        if ($env:LANEX_SETUP_TESTING -ne '1') { throw 'Preflight fixtures are accepted only by the test harness.' }
        $facts = Read-JsonFile $PreflightFixturePath 'Preflight fixture'
    } else { $facts = Get-LivePreflightFacts }
    return [pscustomobject][ordered]@{
        schema = 1
        nativeArchitecture = [string]$facts.nativeArchitecture
        windowsBuild = [int]$facts.windowsBuild
        computer = $facts.computer
        hypervisorPresent = $facts.hypervisorPresent
        firmwareVirtualization = [string]$facts.firmwareVirtualization
        features = $facts.features
        pendingReboot = $facts.pendingReboot
        bootIdentity = [string]$facts.bootIdentity
        wsl = $facts.wsl
        decision = Get-PreflightDecision $facts
    }
}

function Invoke-FeatureCommand([string]$FeatureName) {
    $arguments = @('/online', '/enable-feature', "/featurename:$FeatureName", '/all', '/norestart')
    $text = (& (Join-Path $env:SystemRoot 'System32\dism.exe') $arguments 2>&1 | Out-String).Trim()
    return [pscustomobject][ordered]@{ exitCode = [int]$LASTEXITCODE; output = $text }
}

function Enable-WindowsFeatures {
    if ($FeatureFixturePath) {
        if ($env:LANEX_SETUP_TESTING -ne '1') { throw 'Feature fixtures are accepted only by the test harness.' }
        $raw = Read-JsonFile $FeatureFixturePath 'Feature fixture'
    } else {
        $raw = [pscustomobject][ordered]@{
            wsl = Invoke-FeatureCommand 'Microsoft-Windows-Subsystem-Linux'
            virtualMachinePlatform = Invoke-FeatureCommand 'VirtualMachinePlatform'
        }
    }
    $result = [pscustomobject][ordered]@{}
    $failed = @()
    foreach ($item in @(@('wsl', 'Microsoft-Windows-Subsystem-Linux'),
                         @('virtualMachinePlatform', 'VirtualMachinePlatform'))) {
        $value = $raw.($item[0])
        $success = ([int]$value.exitCode -eq 0 -or [int]$value.exitCode -eq 3010)
        Add-OrSet $result $item[0] ([pscustomobject][ordered]@{
            feature = $item[1]; exitCode = [int]$value.exitCode; success = $success
            restartRequired = ([int]$value.exitCode -eq 3010); output = [string]$value.output
        })
        if (-not $success) { $failed += $item[1] }
    }
    if ($OutputPath) { Write-AtomicJson $OutputPath $result }
    if ($failed.Count -gt 0) { throw ('Feature enable failed: ' + ($failed -join ', ')) }
    return $result
}

function Ensure-M2State($State) {
    if ($null -eq $State.boot) {
        Add-OrSet $State 'boot' ([pscustomobject][ordered]@{ lastIdentity = ''; restartAttempts = 0 })
    }
    if ($null -eq $State.resume) {
        Add-OrSet $State 'resume' ([pscustomobject][ordered]@{
            installerPath = ''; installerSha256 = ''; triggerRegistered = $false
            manualShortcut = ''; registeredUtc = $null
        })
    }
}

function Get-ResumePaths {
    if ($TestResumeRoot) {
        if ($env:LANEX_SETUP_TESTING -ne '1') { throw 'TestResumeRoot is accepted only by the test harness.' }
        [IO.Directory]::CreateDirectory($TestResumeRoot) | Out-Null
        return [pscustomobject]@{
            shortcut = Join-Path $TestResumeRoot 'Continue LanEx Setup.lnk.json'
            trigger = Join-Path $TestResumeRoot 'runonce.txt'
        }
    }
    $folder = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\LanEx'
    [IO.Directory]::CreateDirectory($folder) | Out-Null
    return [pscustomobject]@{
        shortcut = Join-Path $folder 'Continue LanEx Setup.lnk'
        trigger = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce'
    }
}

function Write-ManualShortcut([string]$Path, [string]$Installer) {
    if ($TestResumeRoot) {
        Write-AtomicJson $Path ([ordered]@{ target = $Installer; arguments = '/CONTINUE=1 /SP-' })
        return
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $Installer
    $shortcut.Arguments = '/CONTINUE=1 /SP-'
    $shortcut.WorkingDirectory = Split-Path -Parent $Installer
    $shortcut.Description = 'Continue LanEx Setup for this Windows account'
    $shortcut.Save()
}

function Stage-ResumeInstaller {
    $state = Migrate-State (Read-JsonFile $StatePath 'Install state')
    Assert-StateOwner $state (Get-OwnerSid)
    Ensure-M2State $state
    $sha = Get-Sha256 $ResumeInstallerPath
    if ($sha -ne [string]$state.currentInstallerSha256) {
        throw 'Staged installer does not match the initialized Setup identity.'
    }
    $paths = Get-ResumePaths
    Write-ManualShortcut $paths.shortcut $ResumeInstallerPath
    if (-not (Test-Path -LiteralPath $paths.shortcut -PathType Leaf)) {
        throw 'Could not verify the manual Continue LanEx Setup shortcut.'
    }
    if (-not $TestResumeRoot) {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($paths.shortcut)
        if ((Normalize-Path ([string]$shortcut.TargetPath)) -ne (Normalize-Path $ResumeInstallerPath) -or
                [string]$shortcut.Arguments -ne '/CONTINUE=1 /SP-') {
            throw 'Could not verify the manual Continue LanEx Setup shortcut identity.'
        }
    }
    $state.resume.installerPath = [IO.Path]::GetFullPath($ResumeInstallerPath)
    $state.resume.installerSha256 = $sha
    $state.resume.manualShortcut = [string]$paths.shortcut
    $state.phase = 'installer-staged'
    Write-AtomicJson $StatePath $state
    return $state
}

function Register-OwnerResume {
    $state = Migrate-State (Read-JsonFile $StatePath 'Install state')
    Assert-StateOwner $state (Get-OwnerSid)
    Ensure-M2State $state
    if (-not $BootIdentity) { throw 'RegisterResume requires a boot identity.' }
    if (-not $state.resume.installerPath -or
            (Get-Sha256 ([string]$state.resume.installerPath)) -ne [string]$state.resume.installerSha256) {
        throw 'The staged resume installer is missing or has changed.'
    }
    if ([string]$state.boot.lastIdentity -eq $BootIdentity) {
        throw 'An automatic restart was already requested during this boot.'
    }
    if ([int]$state.boot.restartAttempts -ge 2) {
        throw 'The automatic restart limit has been reached; use diagnostics instead of restarting again.'
    }
    $paths = Get-ResumePaths
    $command = '"' + [string]$state.resume.installerPath + '" /RESUME=1 /SP-'
    # Record the bounded attempt before exposing the trigger. A power loss in
    # the small window that follows can consume an attempt, but can never create
    # an unrecorded reboot loop; the manual shortcut remains available.
    $state.boot.lastIdentity = $BootIdentity
    $state.boot.restartAttempts = [int]$state.boot.restartAttempts + 1
    $state.resume.triggerRegistered = $false
    $state.phase = 'restart-registering'
    Write-AtomicJson $StatePath $state
    if ($TestResumeRoot) {
        [IO.File]::WriteAllText($paths.trigger, $command, (New-Object Text.UTF8Encoding($false)))
    } else {
        New-Item -Path $paths.trigger -Force | Out-Null
        New-ItemProperty -LiteralPath $paths.trigger -Name 'LanExSetupResume' -Value $command -PropertyType String -Force | Out-Null
    }
    if ($env:LANEX_SETUP_TEST_TRIGGER_FAIL -eq '1' -and $TestResumeRoot) {
        Remove-Item -LiteralPath $paths.trigger -Force -ErrorAction SilentlyContinue
    }
    $verified = if ($TestResumeRoot) {
        (Test-Path -LiteralPath $paths.trigger -PathType Leaf) -and
            ([IO.File]::ReadAllText($paths.trigger) -eq $command)
    } else {
        ([string](Get-ItemPropertyValue -LiteralPath $paths.trigger -Name 'LanExSetupResume' -ErrorAction SilentlyContinue) -eq $command)
    }
    if (-not $verified) { throw 'Could not verify the owner-bound automatic resume trigger.' }
    $state.resume.triggerRegistered = $true
    $state.resume.registeredUtc = [DateTime]::UtcNow.ToString('o')
    $state.phase = 'restart-required'
    Write-AtomicJson $StatePath $state
    return $state
}

function Clear-OwnerResume {
    $state = Migrate-State (Read-JsonFile $StatePath 'Install state')
    Assert-StateOwner $state (Get-OwnerSid)
    Ensure-M2State $state
    $paths = Get-ResumePaths
    if ($TestResumeRoot) {
        Remove-Item -LiteralPath $paths.trigger -Force -ErrorAction SilentlyContinue
    } else {
        $expected = '"' + [string]$state.resume.installerPath + '" /RESUME=1 /SP-'
        $actual = [string](Get-ItemPropertyValue -LiteralPath $paths.trigger -Name 'LanExSetupResume' -ErrorAction SilentlyContinue)
        if ($actual -eq $expected) {
            Remove-ItemProperty -LiteralPath $paths.trigger -Name 'LanExSetupResume' -ErrorAction SilentlyContinue
        }
    }
    if ($state.resume.manualShortcut) {
        Remove-Item -LiteralPath ([string]$state.resume.manualShortcut) -Force -ErrorAction SilentlyContinue
    }
    $state.resume.triggerRegistered = $false
    $state.phase = 'resume-cleared'
    Write-AtomicJson $StatePath $state
    return $state
}

function Reset-ChangedComponents($State, $Manifest) {
    if ($null -eq $State.components) { return }
    foreach ($property in @($State.components.PSObject.Properties)) {
        $next = $Manifest.componentFingerprints.PSObject.Properties[$property.Name]
        if ($null -eq $next -or [string]$property.Value.inputFingerprint -ne [string]$next.Value) {
            $property.Value.status = 'pending'
            $property.Value.inputFingerprint = if ($null -eq $next) { '' } else { [string]$next.Value }
            Add-OrSet $property.Value 'completedUtc' $null
        }
    }
}

function New-BuildManifest {
    foreach ($required in @($OutputPath, $SourceSha, $WheelPath, $InstallScriptPath,
            $ProvisionScriptPath, $SelftestPath, $ConstraintsPath, $CatalogPath, $PdkPinsPath,
            $RootfsUrl, $RootfsSha256, $ImageDigest, $Gds3dCommit)) {
        if ([string]::IsNullOrWhiteSpace($required)) { throw 'NewManifest is missing a required argument.' }
    }
    if ($SourceSha -notmatch '^[0-9a-fA-F]{40}$') { throw 'SourceSha must be a full commit SHA.' }
    if ($RootfsSha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'RootfsSha256 is invalid.' }
    if ($ImageDigest -notmatch '^sha256:[0-9a-fA-F]{64}$') { throw 'ImageDigest must be an immutable sha256 digest.' }
    if ($Gds3dCommit -notmatch '^[0-9a-fA-F]{40}$') { throw 'Gds3dCommit must be a full commit SHA.' }
    $catalog = Read-JsonFile $CatalogPath 'Capability catalog'
    $pins = Read-JsonFile $PdkPinsPath 'PDK pins'
    $payload = [ordered]@{
        wheel = [ordered]@{ file = [IO.Path]::GetFileName($WheelPath); sha256 = Get-Sha256 $WheelPath }
        installScriptSha256 = Get-Sha256 $InstallScriptPath
        provisionScriptSha256 = Get-Sha256 $ProvisionScriptPath
        selftestSha256 = Get-Sha256 $SelftestPath
        setupWorkerSha256 = Get-Sha256 $PSCommandPath
        constraintsSha256 = Get-Sha256 $ConstraintsPath
        catalogSha256 = Get-Sha256 $CatalogPath
        pdkPinsSha256 = Get-Sha256 $PdkPinsPath
    }
    $manifest = [ordered]@{
        schema = $ManifestSchema
        generatedUtc = [DateTime]::UtcNow.ToString('o')
        source = [ordered]@{ repository = $SourceRepository; ref = $SourceRef; sha = $SourceSha.ToLowerInvariant() }
        app = [ordered]@{ version = $AppVersion; channel = $Channel }
        target = [ordered]@{ os = 'windows'; architecture = 'amd64'; minBuild = 19044; primary = 'windows-11-x64' }
        rootfs = [ordered]@{ url = $RootfsUrl; sha256 = $RootfsSha256.ToLowerInvariant(); sizeBytes = $RootfsSizeBytes }
        bakedRootfs = if ($BakedRootfsUrl) { [ordered]@{ url = $BakedRootfsUrl; sha256 = $BakedRootfsSha256.ToLowerInvariant(); sizeBytes = $BakedRootfsSizeBytes } } else { $null }
        payload = $payload
        python = [ordered]@{ supported = @('3.10', '3.11', '3.12', '3.13'); constraintsFile = [IO.Path]::GetFileName($ConstraintsPath) }
        dependencies = [ordered]@{ librelane = '3.0.4'; ciel = '2.6.1' }
        image = [ordered]@{ reference = $ImageReference; digest = $ImageDigest.ToLowerInvariant() }
        gds3d = [ordered]@{ repository = 'trilomix/GDS3D'; commit = $Gds3dCommit.ToLowerInvariant() }
        pdkPins = $pins
        pdkCatalog = $catalog.pdk_catalog
        sizeEstimates = [ordered]@{
            rootfsDownloadBytes = $RootfsSizeBytes
            measuredBaseInstalledBytes = [int64]1395864372
            measuredBaseNetworkBytes = [int64]966367642
            estimatedNativeInstalledBytes = [int64]1288490189
            estimatedNativeNetworkBytes = [int64]751619277
            estimatedImageDownloadBytes = [int64]3221225472
            estimatedImageInstalledBytes = [int64]4294967296
            practicalRunHeadroomBytes = [int64]4294967296
        }
        componentFingerprints = [ordered]@{}
    }
    $manifest.componentFingerprints.app = Get-TextSha256 (($manifest.source | ConvertTo-Json -Compress) + ($payload | ConvertTo-Json -Compress))
    $manifest.componentFingerprints.rootfs = Get-TextSha256 ($manifest.rootfs | ConvertTo-Json -Compress)
    $manifest.componentFingerprints.image = Get-TextSha256 ($manifest.image | ConvertTo-Json -Compress)
    $manifest.componentFingerprints.pdks = Get-TextSha256 (($manifest.pdkPins | ConvertTo-Json -Depth 20 -Compress) + ($manifest.pdkCatalog | ConvertTo-Json -Depth 20 -Compress))
    Write-AtomicJson $OutputPath $manifest
    return $manifest
}

function Initialize-State {
    $manifest = Read-JsonFile $ManifestPath 'Build manifest'
    Assert-Manifest $manifest
    $manifestHash = Get-Sha256 $ManifestPath
    $owner = Get-OwnerSid
    $installerSha = Get-Sha256 $InstallerPath
    $rawChoices = if ($ChoicesPath) {
        Read-JsonFile $ChoicesPath 'Selection file'
    } else {
        try { $ChoicesJson | ConvertFrom-Json } catch { throw 'ChoicesJson is malformed.' }
    }
    if ($rawChoices.PSObject.Properties['choices']) { $rawChoices = $rawChoices.choices }
    $choices = ConvertTo-NormalizedChoices $manifest $rawChoices
    if (Test-Path -LiteralPath $StatePath) {
        $state = Migrate-State (Read-JsonFile $StatePath 'Install state')
        Assert-StateOwner $state $owner
        Ensure-M2State $state
        if ($ResumeMode -eq '1') {
            $incomingSha = Get-Sha256 $InstallerPath
            if (-not $state.resume.installerSha256 -or
                    $incomingSha -ne [string]$state.resume.installerSha256 -or
                    (Normalize-Path $InstallerPath) -ne (Normalize-Path ([string]$state.resume.installerPath))) {
                throw 'Automatic resume installer identity does not match saved state.'
            }
            if (-not $BootIdentity -or [string]$state.boot.lastIdentity -eq $BootIdentity) {
                throw 'The required restart has not been observed; Setup will not loop in the same boot.'
            }
        }
        if ($Operation -eq 'repair' -and ([string]$state.manifestHash -ne $manifestHash -or
                [string]$state.source.sha -ne [string]$manifest.source.sha)) {
            throw 'Repair cannot change build identity. Run the matching Setup or choose an explicit Update.'
        }
        if ($Operation -eq 'update' -and [string]$state.manifestHash -ne $manifestHash) {
            Reset-ChangedComponents $state $manifest
            $state.manifestHash = $manifestHash
            $state.source = $manifest.source
        }
        Add-OrSet $state 'currentInstallerSha256' $installerSha
        $state.operation = $Operation
        # Existing choices are authoritative on resume/manual rerun. New choices
        # are accepted only for an explicit update.
        if ($Operation -eq 'update') { $state.choices = $choices }
        else { $state.choices = ConvertTo-NormalizedChoices $manifest $state.choices }
    } else {
        if ($Operation -eq 'repair') { throw 'Repair requires an existing owner-scoped install state.' }
        $state = [pscustomobject][ordered]@{
            schema = $StateSchema
            installId = Get-NewInstallId
            ownerSid = $owner
            manifestHash = $manifestHash
            source = $manifest.source
            installerSha256 = $installerSha
            currentInstallerSha256 = $installerSha
            operation = $Operation
            choices = $choices
            appliance = [pscustomobject][ordered]@{ name = ''; registryId = ''; basePath = ''; linuxMarker = '/etc/lanex/appliance.json' }
            phase = 'initialized'
            components = [pscustomobject][ordered]@{}
            boot = [pscustomobject][ordered]@{ lastIdentity = ''; restartAttempts = 0 }
            resume = [pscustomobject][ordered]@{
                installerPath = ''; installerSha256 = ''; triggerRegistered = $false
                manualShortcut = ''; registeredUtc = $null
            }
            failure = $null
            lastEventCursor = 0
        }
    }
    Write-AtomicJson $StatePath $state
    return $state
}

function Resolve-Appliance {
    $state = Migrate-State (Read-JsonFile $StatePath 'Install state')
    Assert-StateOwner $state (Get-OwnerSid)
    $entries = @(Get-RegistryEntries)
    if ($state.appliance.registryId) {
        $owned = @($entries | Where-Object {
            [string]$_.registryId -eq [string]$state.appliance.registryId -and
            [string]::Equals([string]$_.name, [string]$state.appliance.name, [StringComparison]::OrdinalIgnoreCase) -and
            (Normalize-Path ([string]$_.basePath)) -eq (Normalize-Path ([string]$state.appliance.basePath))
        })
        if ($owned.Count -ne 1) { throw 'The recorded appliance registration identity no longer matches Windows.' }
        return $state.appliance
    }
    $collision = @($entries | Where-Object { [string]::Equals([string]$_.name, $PreferredDistroName, [StringComparison]::OrdinalIgnoreCase) })
    $name = $PreferredDistroName
    if ($collision.Count -gt 0) { $name = $PreferredDistroName + '-' + ([string]$state.installId).Substring(0, 8) }
    $secondary = @($entries | Where-Object { [string]::Equals([string]$_.name, $name, [StringComparison]::OrdinalIgnoreCase) })
    if ($secondary.Count -gt 0) { throw "Both the preferred and owner-derived appliance names are already registered; no distribution was changed." }
    $state.appliance.name = $name
    $state.appliance.basePath = $ExpectedBasePath
    Write-AtomicJson $StatePath $state
    return $state.appliance
}

function Bind-Appliance {
    $state = Migrate-State (Read-JsonFile $StatePath 'Install state')
    Assert-StateOwner $state (Get-OwnerSid)
    $matches = @(Get-RegistryEntries | Where-Object {
        [string]::Equals([string]$_.name, [string]$state.appliance.name, [StringComparison]::OrdinalIgnoreCase) -and
        (Normalize-Path ([string]$_.basePath)) -eq (Normalize-Path ([string]$state.appliance.basePath))
    })
    if ($matches.Count -ne 1) { throw 'Imported appliance registration did not match its expected name and path.' }
    $state.appliance.registryId = [string]$matches[0].registryId
    $state.phase = 'appliance-bound'
    Write-AtomicJson $StatePath $state
    return $state.appliance
}

function Set-ComponentState {
    if ([string]::IsNullOrWhiteSpace($Component) -or [string]::IsNullOrWhiteSpace($InputFingerprint)) {
        throw 'SetComponent requires Component and InputFingerprint.'
    }
    $state = Migrate-State (Read-JsonFile $StatePath 'Install state')
    Assert-StateOwner $state (Get-OwnerSid)
    $record = [pscustomobject][ordered]@{
        status = $ComponentStatus
        inputFingerprint = $InputFingerprint
        completedUtc = if ($ComponentStatus -eq 'complete') { [DateTime]::UtcNow.ToString('o') } else { $null }
    }
    Add-OrSet $state.components $Component $record
    if ($Phase) { $state.phase = $Phase }
    Write-AtomicJson $StatePath $state
    return $record
}

$result = switch ($Action) {
    'NewManifest' { New-BuildManifest }
    'InitializeState' { Initialize-State }
    'ResolveAppliance' { Resolve-Appliance }
    'BindAppliance' { Bind-Appliance }
    'SetComponent' { Set-ComponentState }
    'Preflight' { Invoke-Preflight }
    'EnableFeatures' { Enable-WindowsFeatures }
    'StageInstaller' { Stage-ResumeInstaller }
    'RegisterResume' { Register-OwnerResume }
    'ClearResume' { Clear-OwnerResume }
    'PlanChoices' { Get-PlannedChoices }
    'ReadState' {
        $s = Migrate-State (Read-JsonFile $StatePath 'Install state')
        Assert-StateOwner $s (Get-OwnerSid)
        $s
    }
}
$result | ConvertTo-Json -Depth 100 -Compress
