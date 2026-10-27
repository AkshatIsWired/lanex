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
        'Preflight', 'EnableFeatures', 'StageInstaller', 'RegisterResume', 'ClearResume', 'PlanChoices', 'RecordOutcome',
        'ValidateUninstall', 'ExportAppliance', 'RemoveAppliance', 'CommitUpdate', 'RollbackUpdate', 'NetworkCheck')]
    [string]$Action,
    [string]$StatePath,
    [string]$ManifestPath,
    [ValidateSet('install', 'repair', 'update', 'modify', 'resume')]
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
    [ValidateSet('ready', 'failed', 'cancelled', 'restart-required')]
    [string]$Outcome,
    [string]$OutcomeMessage,
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
    [string]$LockPath,
    # How long the preflight waits for WSL to start its kernel; 0 skips that
    # test (the wizard's first look, rechecked in full before Install).
    [int]$KernelProbeSeconds = 360,
    [string]$PdkAssetsPath,
    [string]$AptSnapshot,
    [string]$RootfsUrls,
    [string]$CatalogPath,
    [string]$PdkPinsPath,
    [string]$RootfsUrl,
    [string]$RootfsSha256,
    [Int64]$RootfsSizeBytes,
    [string]$BakedRootfsUrl = '',
    [string]$BakedRootfsSha256 = '',
    [Int64]$BakedRootfsSizeBytes = 0,
    [string]$BakedRootfsFile = 'lanex-rootfs-amd64.tar.gz',
    [string]$BakedPackageInventoryPath = '',
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
    [string]$TestInstallId,
    [string]$LinuxMarkerFixturePath,
    [string]$TestWslFixturePath,
    [string]$ExportPath,
    [string]$ConfirmedInstallId,
    [string]$OwnedDataRoot,
    [ValidateSet('full', 'minimal')]
    [string]$NetworkProfile = 'full',
    [ValidateSet('0', '1')]
    [string]$NeedRootfs = '0'
)

$ErrorActionPreference = 'Stop'
$StateSchema = 1
$ManifestSchema = 1
# Below this much RAM Setup stops: WSL gets half of it, which leaves too little
# for Docker and one LibreLane run. Below RecommendedMemoryBytes it warns.
# Measured on the 8 GB Ship line VM (see installer-workspace/outputs).
$MinMemoryBytes = [int64]5GB
$RecommendedMemoryBytes = [int64]7GB

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
        if ($OutputPath) { [IO.File]::WriteAllText($OutputPath + '.done', 'failed: worker integrity') }
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
    $p = [Environment]::ExpandEnvironmentVariables($Path).Trim().Trim('"')
    if ($p.StartsWith('\\?\UNC\', [StringComparison]::OrdinalIgnoreCase)) {
        $p = '\\' + $p.Substring(8)
    } elseif ($p.StartsWith('\\?\', [StringComparison]::OrdinalIgnoreCase)) {
        $p = $p.Substring(4)
    } elseif ($p.StartsWith('\\.\', [StringComparison]::OrdinalIgnoreCase)) {
        $p = $p.Substring(4)
    }
    return [IO.Path]::GetFullPath($p).TrimEnd('\').ToLowerInvariant()
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
    if ($profile -notin @('recommended', 'complete', 'maximum', 'full', 'custom', 'minimal')) {
        throw 'profile must be recommended, complete, maximum, full, custom, or minimal.'
    }
    if ($profile -eq 'recommended') {
        if ($null -eq $catalog.PSObject.Properties['sky130A']) {
            throw 'The recommended sky130A PDK is absent from the build manifest.'
        }
        $skyEntry = $catalog.PSObject.Properties['sky130A'].Value
        [string[]]$starterLibs = if ($null -ne $skyEntry.default_libraries) {
            @($skyEntry.default_libraries | ForEach-Object { [string]$_ })
        } else {
            @('sky130_fd_io', 'sky130_fd_pr', 'sky130_fd_sc_hd', 'sky130_fd_sc_hvl', 'sky130_ml_xx_hd', 'sky130_sram_macros')
        }
        $recLibs = [pscustomobject][ordered]@{
            'sky130A' = [string[]]$starterLibs
        }
        return [pscustomobject][ordered]@{
            schema = 1; profile = 'recommended'; engine = 'docker'; image = $true
            nativeTools = @('verilator', 'iverilog', 'graphviz', 'gtkwave', 'gds3d')
            pdks = @('sky130A'); libraries = $recLibs
        }
    }
    if ($profile -in @('complete', 'maximum', 'full')) {
        $resolvedProfile = if ($profile -eq 'full') { 'complete' } else { $profile }
        $maxPdks = @('sky130A', 'sky130B', 'gf180mcuD', 'ihp-sg13g2')
        $maxLibs = [pscustomobject][ordered]@{}
        foreach ($requiredPdk in $maxPdks) {
            if ($null -eq $catalog.PSObject.Properties[$requiredPdk]) {
                throw "The $resolvedProfile $requiredPdk PDK is absent from the build manifest."
            }
            $pdkEntry = $catalog.PSObject.Properties[$requiredPdk].Value
            [string[]]$libs = @($pdkEntry.libraries | ForEach-Object { [string]$_ })
            Add-OrSet $maxLibs $requiredPdk ([string[]]$libs)
        }
        return [pscustomobject][ordered]@{
            schema = 1; profile = $resolvedProfile; engine = 'docker'; image = $true
            nativeTools = @('verilator', 'iverilog', 'graphviz', 'gtkwave', 'gds3d')
            pdks = $maxPdks; libraries = $maxLibs
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
    foreach ($variantValue in @($selectedRaw)) {
        $variant = [string]$variantValue
        $entry = $catalog.PSObject.Properties[$variant]
        if (-not $variant -or $null -eq $entry) { throw "Unknown PDK variant: $variant" }
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
        $libraries = [pscustomobject][ordered]@{}
        foreach ($variant in $selected) {
            $entry = $catalog.PSObject.Properties[$variant].Value
            $allowed = @($entry.libraries | ForEach-Object { [string]$_ })
            Add-OrSet $libraries $variant ([string[]]$allowed)
        }
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
            Add-OrSet $libraries $variant ([string[]]$merged)
        }
    }
    return [pscustomobject][ordered]@{
        schema = 1; profile = 'custom'; engine = $engine; image = $image
        nativeTools = $native; pdks = $selected; libraries = $libraries
    }
}

function Get-SelectionEstimate($Manifest, $Choices, $ExistingState = $null) {
    # Planning estimates, never download promises. Base/rootfs/image values are
    # measured in the documented 2026 reference run; PDK sizes come from the
    # locked Ciel catalog and receive extraction/cache headroom.
    $gib = [int64]1073741824
    $rootfs = [int64]$Manifest.rootfs.sizeBytes
    $baseInstalled = [int64]([math]::Ceiling(1.3 * $gib))
    $baseNetwork = [int64]([math]::Ceiling(0.9 * $gib))
    $nativeInstalled = if (@($Choices.nativeTools).Count -gt 0) { [int64]([math]::Ceiling(1.2 * $gib)) } else { 0 }
    $nativeNetwork = if (@($Choices.nativeTools).Count -gt 0) { [int64]([math]::Ceiling(0.7 * $gib)) } else { 0 }
    $imageNetwork = if ($Choices.image) { [int64](3.2 * $gib) } else { 0 }
    $imageInstalled = if ($Choices.image) { [int64]7524155924 } else { 0 }
    $pdkNetwork = [int64]0
    $pdkInstalled = [int64]0
    $seenFamilies = @{}
    $isStarterSky130 = ($Choices.profile -eq 'recommended') -or
        ((@($Choices.pdks).Count -eq 1) -and (@($Choices.pdks) -contains 'sky130A') -and
         ($Choices.libraries -is [System.Management.Automation.PSCustomObject]) -and
         ($null -ne $Choices.libraries.PSObject.Properties['sky130A']) -and
         (@($Choices.libraries.PSObject.Properties['sky130A'].Value).Count -le 6))

    if ($isStarterSky130) {
        $pdkNetwork = [int64](0.35 * $gib)
        $pdkInstalled = [int64](4.0 * $gib)
    } else {
        foreach ($variant in @($Choices.pdks)) {
            $pdkProp = $Manifest.pdkCatalog.PSObject.Properties[[string]$variant]
            if ($null -ne $pdkProp) {
                $fam = [string]$pdkProp.Value.family
                if (-not $seenFamilies.ContainsKey($fam)) {
                    $seenFamilies[$fam] = $true
                    $approx = [double]$pdkProp.Value.approx_gb
                    $pdkNetwork += [int64]([math]::Ceiling($approx * $gib))
                    if ($fam -eq 'sky130') {
                        $pdkInstalled += [int64]16500000000
                    } elseif ($fam -eq 'gf180mcu') {
                        $pdkInstalled += [int64](8.5 * $gib)
                    } elseif ($fam -eq 'ihp-sg13g2') {
                        $pdkInstalled += [int64](4.0 * $gib)
                    }
                }
            }
        }
    }
    if ($pdkInstalled -eq 0 -and $pdkNetwork -gt 0) {
        $pdkInstalled = [int64]([math]::Ceiling($pdkNetwork * 1.6))
    }
    $runHeadroom = if ($Choices.image) { 4 * $gib } else { 1 * $gib }
    $extractionHeadroomBytes = [int64]([math]::Ceiling(($imageNetwork + $pdkNetwork) * 0.35))
    $isEmbedded = ($env:LANEX_EMBEDDED_ROOTFS -eq '1')
    $rootfsDownload = if ($isEmbedded) { [int64]0 } else { $rootfs }
    $download = $rootfsDownload + $baseNetwork + $nativeNetwork + $imageNetwork + $pdkNetwork
    $installed = $baseInstalled + $nativeInstalled + $imageInstalled + $pdkInstalled
    $appDataRequired = $rootfsDownload + $installed + $runHeadroom + $extractionHeadroomBytes
    $tempRequired = if ($isEmbedded) { [int64]0 } else { $rootfs }
    $reused = [int64]0
    if ($null -ne $ExistingState -and $null -ne $ExistingState.components) {
        if ([string]$ExistingState.components.app.status -eq 'complete') {
            $reused += $baseInstalled
            $appDataRequired -= $baseInstalled
            $download -= $baseNetwork
        }
        if ([string]$ExistingState.components.image.status -eq 'complete' -and $Choices.image) {
            $reused += $imageInstalled
            $appDataRequired -= $imageInstalled
            $download -= $imageNetwork
        }
        if ([string]$ExistingState.components.pdks.status -eq 'complete' -and @($Choices.pdks).Count -gt 0) {
            $reused += $pdkInstalled
            $appDataRequired -= $pdkInstalled
            $download -= $pdkNetwork
        }
    }
    if ($download -lt 0) { $download = [int64]0 }
    if ($appDataRequired -lt $runHeadroom) { $appDataRequired = [int64]$runHeadroom }
    return [pscustomobject][ordered]@{
        schema = 1
        measuredBasis = '2026 reference run plus locked catalog approximations'
        downloadBytes = [int64]$download
        installedBytes = $installed
        reusedInstalledBytes = $reused
        extractionHeadroomBytes = $extractionHeadroomBytes
        practicalRunHeadroomBytes = $runHeadroom
        volumes = [pscustomobject][ordered]@{
            appDataRequiredBytes = [int64]$appDataRequired
            tempRequiredBytes = [int64]$tempRequired
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
    $stateWrapper = $raw
    if ($raw.PSObject.Properties['choices']) { $raw = $raw.choices }
    $choices = ConvertTo-NormalizedChoices $manifest $raw
    return [pscustomobject][ordered]@{
        schema = 1; choices = $choices
        estimates = Get-SelectionEstimate $manifest $choices $stateWrapper
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

function Invoke-WslBounded([string]$WslExe, [string[]]$Arguments, [int]$TimeoutSeconds) {
    <# Runs wsl.exe with a time limit. Right after sign-in WSL can hang while
       Windows finishes registering it; an unbounded call would leave Setup
       invisible with no way out. Returns exitCode (-1 on timeout), output and
       timedOut. #>
    $result = [pscustomobject]@{ exitCode = -1; output = ''; timedOut = $false }
    $proc = $null
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $WslExe
        $psi.Arguments = (($Arguments | ForEach-Object {
            if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
        }) -join ' ')
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
        $psi.EnvironmentVariables['WSL_UTF8'] = '1'
        $proc = [System.Diagnostics.Process]::Start($psi)
        $stdout = $proc.StandardOutput.ReadToEndAsync()
        $stderr = $proc.StandardError.ReadToEndAsync()
        if ($proc.WaitForExit($TimeoutSeconds * 1000)) {
            $proc.WaitForExit()
            $result.exitCode = $proc.ExitCode
            $result.output = (($stdout.Result + $stderr.Result) -replace "`0", '').Trim()
        } else {
            $result.timedOut = $true
            & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /T /F /PID $proc.Id *> $null
        }
    } catch {
        $result.output = $_.Exception.Message
    }
    return $result
}

function Invoke-WslKernelProbe([string]$WslExe, [string[]]$Arguments) {
    <# A kernel-starting wsl.exe call. On Windows 10 the first WSL start after
       the feature restart waits minutes for Windows to set up WSL's network
       (seen: 4 min 40 s; the next start took a second), and killing or
       restarting it does not speed that up, so this waits once, long.
       error is 'timeout' or WSL's own message when it fails. #>
    $run = Invoke-WslBounded $WslExe $Arguments $KernelProbeSeconds
    $errorText = ''
    if ($run.timedOut) {
        $errorText = 'timeout'
    } elseif ($run.exitCode -ne 0) {
        $errorText = [string]$run.output
        if ($errorText.Length -gt 400) { $errorText = $errorText.Substring(0, 400) }
    }
    return [pscustomobject]@{ exitCode = $run.exitCode; error = $errorText }
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
    # The processor's own flag, before the hypervisor override below: inside a
    # virtual machine Windows always reports a hypervisor, so only this flag
    # tells whether the host passes virtualization through (nested).
    $firmwareRaw = 'unknown'
    if ($null -ne $processor -and $null -ne $processor.VirtualizationFirmwareEnabled) {
        $firmwareRaw = if ([bool]$processor.VirtualizationFirmwareEnabled) { 'enabled' } else { 'disabled' }
    }
    $isVirtualMachine = $false
    if ($null -ne $computerSystem) {
        $isVirtualMachine = ([string]$computerSystem.Model + ' ' + [string]$computerSystem.Manufacturer) -match
            'Virtual Machine|VMware|VirtualBox|KVM|QEMU|Parallels|Xen'
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
    if (-not (Test-Path -LiteralPath $wslExe -PathType Leaf) -and (Test-Path -LiteralPath (Join-Path $env:SystemRoot 'sysnative\wsl.exe') -PathType Leaf)) {
        $wslExe = Join-Path $env:SystemRoot 'sysnative\wsl.exe'
    }
    $wslPresent = Test-Path -LiteralPath $wslExe -PathType Leaf
    $wslVersion = ''
    $statusUsable = $false
    $kernelError = ''
    if ($wslPresent) {
        $versionRun = Invoke-WslBounded $wslExe @('--version') 20
        if ($versionRun.exitCode -eq 0 -and $versionRun.output -match '(?im)^WSL version:\s*([0-9]+(?:\.[0-9]+){1,3})') {
            $wslVersion = $Matches[1]
        }
        if (-not $wslVersion) {
            try {
                $package = Get-AppxPackage -Name MicrosoftCorporationII.WindowsSubsystemForLinux -ErrorAction Stop
                if ($null -ne $package) { $wslVersion = [string]$package.Version }
            } catch {}
        }
        $statusUsable = ((Invoke-WslBounded $wslExe @('--status') 30).exitCode -eq 0)
    }
    $systemdCapable = $false
    try { $systemdCapable = ([version]$wslVersion -ge [version]'0.67.6') } catch {}
    $kernelUsable = $false
    if ($wslPresent -and $statusUsable -and $systemdCapable -and $KernelProbeSeconds -le 0) {
        $kernelError = 'not-checked'
    } elseif ($wslPresent -and $statusUsable -and $systemdCapable) {
        try {
            $listRun = Invoke-WslBounded $wslExe @('--list', '--quiet') 30
            $distroList = @($listRun.output -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
            if ($listRun.exitCode -ne 0) { $distroList = @() }
            if ($distroList.Count -gt 0) {
                $kernelRun = Invoke-WslKernelProbe $wslExe @('--system', '--exec', '/bin/true')
                $kernelUsable = ($kernelRun.exitCode -eq 0)
                if (-not $kernelUsable) { $kernelError = $kernelRun.error }
            } else {
                # On a fresh installation with no Linux distributions registered yet, wsl.exe --system
                # refuses to boot the utility VM with "WSL has no installed distributions" (exit code -1).
                # Register a transient micro-distro to verify genuine kernel/VM startup.
                $probeBase = Join-Path ([System.IO.Path]::GetTempPath()) ("wsl-probe-" + [Guid]::NewGuid().ToString('N'))
                $probeContent = Join-Path $probeBase "c"
                $probeRootfs = Join-Path $probeBase "r"
                $probeTar = Join-Path $probeBase "p.tar.gz"
                $probeName = "lanex_probe_" + [Guid]::NewGuid().ToString('N').Substring(0, 8)
                try {
                    New-Item -ItemType Directory -Path "$probeContent\bin" -Force | Out-Null
                    Set-Content -Path "$probeContent\bin\sh" -Value "#!/bin/sh`nexit 0"
                    $tarExe = Join-Path $env:SystemRoot 'System32\tar.exe'
                    if (-not (Test-Path -LiteralPath $tarExe -PathType Leaf) -and (Test-Path -LiteralPath (Join-Path $env:SystemRoot 'sysnative\tar.exe') -PathType Leaf)) {
                        $tarExe = Join-Path $env:SystemRoot 'sysnative\tar.exe'
                    }
                    if (Test-Path -LiteralPath $tarExe -PathType Leaf) {
                        & $tarExe -czf $probeTar -C $probeContent . *> $null
                    }
                    if (Test-Path -LiteralPath $probeTar -PathType Leaf) {
                        $kernelRun = Invoke-WslKernelProbe $wslExe @('--import', $probeName, $probeRootfs, $probeTar, '--version', '2')
                        if ($kernelRun.exitCode -eq 0) {
                            $kernelRun = Invoke-WslKernelProbe $wslExe @('--system', '--exec', '/bin/true')
                        }
                        $kernelUsable = ($kernelRun.exitCode -eq 0)
                        if (-not $kernelUsable) { $kernelError = $kernelRun.error }
                    } else {
                        $kernelRun = Invoke-WslBounded $wslExe @('--system', '--exec', '/bin/true') 90
                        if ($kernelRun.output -match 'no installed distributions') {
                            $kernelUsable = $true
                        }
                    }
                } finally {
                    Invoke-WslBounded $wslExe @('--unregister', $probeName) 60 | Out-Null
                    Remove-Item -Recurse -Force $probeBase -ErrorAction SilentlyContinue
                }
            }
        } catch {}
    }
    # Group Policy / Intune can switch WSL off (WSL's ADMX writes these values).
    $wslPolicy = 'none'
    try {
        $pol = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Policies\WSL' -ErrorAction Stop
        if ($null -ne $pol.AllowWSL -and [int]$pol.AllowWSL -eq 0) { $wslPolicy = 'wsl-disabled' }
    } catch {}
    $memoryBytes = [int64]0
    if ($null -ne $computerSystem -and $null -ne $computerSystem.TotalPhysicalMemory) {
        $memoryBytes = [int64]$computerSystem.TotalPhysicalMemory
    }
    $ubr = 0
    try { $ubr = [int](Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -ErrorAction Stop).UBR } catch {}
    $boot = ''
    if ($null -ne $operatingSystem -and $null -ne $operatingSystem.LastBootUpTime) {
        try { $boot = $operatingSystem.LastBootUpTime.ToUniversalTime().ToString('o') } catch {}
    }
    if (-not $boot) {
        try {
            $cim = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
            if ($cim -and $cim.LastBootUpTime) {
                $boot = $cim.LastBootUpTime.ToUniversalTime().ToString('o')
            }
        } catch {}
    }
    if (-not $boot) {
        try {
            $tick = [System.Environment]::TickCount
            $boot = 'uptime-' + [string]$tick
        } catch {
            $boot = 'uptime-' + [string][DateTime]::UtcNow.Ticks
        }
    }

    return [pscustomobject][ordered]@{
        nativeArchitecture = $nativeArchitecture.ToUpperInvariant()
        windowsBuild = [Environment]::OSVersion.Version.Build
        windowsUbr = $ubr
        computer = [pscustomobject][ordered]@{
            manufacturer = if ($null -eq $computerSystem) { '' } else { [string]$computerSystem.Manufacturer }
            model = if ($null -eq $computerSystem) { '' } else { [string]$computerSystem.Model }
        }
        hypervisorPresent = $hypervisor
        firmwareVirtualization = $firmware
        firmwareVirtualizationRaw = $firmwareRaw
        virtualMachine = $isVirtualMachine
        memoryBytes = $memoryBytes
        wslPolicy = $wslPolicy
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
            kernelUsable = $kernelUsable
            kernelError = $kernelError
        }
    }
}

function Test-StoreWsl($Facts) {
    <# WSL 2.0 and later (the app from the Store or `wsl --install`) runs
       WSL 2 without the old "Windows Subsystem for Linux" optional feature:
       on Windows 11 26H2, `wsl --install` turns on only Virtual Machine
       Platform, and WSL works. Asking for the old feature there cost an
       administrator prompt and a restart for nothing. #>
    try { return ([version][string]$Facts.wsl.version -ge [version]'2.0') } catch { return $false }
}

function Get-PreflightDecision($Facts) {
    $featuresMissing = (([string]$Facts.features.wsl -ne 'enabled' -and -not (Test-StoreWsl $Facts)) -or
        [string]$Facts.features.virtualMachinePlatform -ne 'enabled') -and
        [string]$Facts.features.wsl -notmatch 'pending' -and
        [string]$Facts.features.virtualMachinePlatform -notmatch 'pending'
    $code = 'ready'
    $blocked = $false
    $needsElevation = $false
    $needsRestart = $false
    $firmwareNotice = $false
    if ([string]$Facts.nativeArchitecture -ne 'AMD64') {
        $code = 'unsupported-architecture'; $blocked = $true
    } elseif ([int]$Facts.windowsBuild -lt 19044) {
        $code = 'unsupported-windows'; $blocked = $true
    } elseif (($null -ne $Facts.windowsUbr) -and [int]$Facts.windowsUbr -gt 0 -and (
            (([int]$Facts.windowsBuild -in @(19044, 19045)) -and [int]$Facts.windowsUbr -lt 2311) -or
            (([int]$Facts.windowsBuild -eq 22000) -and [int]$Facts.windowsUbr -lt 1281))) {
        # WSL from the Microsoft Store (systemd, WSLg) needs KB5020030 on
        # Windows 10 21H2/22H2 and KB5019157 on Windows 11 21H2; older updates
        # only have the inbox WSL, which LanEx cannot use.
        $code = 'windows-update-required'; $blocked = $true
    } elseif ([string]$Facts.wslPolicy -eq 'wsl-disabled') {
        $code = 'wsl-blocked-by-policy'; $blocked = $true
    } elseif ($null -ne $Facts.memoryBytes -and [int64]$Facts.memoryBytes -gt 0 -and
            [int64]$Facts.memoryBytes -lt [int64]$MinMemoryBytes) {
        $code = 'not-enough-memory'; $blocked = $true
    } elseif ($Facts.virtualMachine -eq $true -and $Facts.wsl.kernelUsable -ne $true -and (
            ([string]$Facts.firmwareVirtualizationRaw -eq 'disabled' -and
             [string]$Facts.features.virtualMachinePlatform -ne 'enabled') -or
            [string]$Facts.wsl.kernelError -match '80370102|HCS_E_HYPERV_NOT_INSTALLED')) {
        # Windows itself runs in a VM whose host does not expose
        # virtualization: WSL 2 cannot start, and a restart will not help.
        # The processor flag only means this before Virtual Machine Platform
        # runs Windows' own hypervisor, which hides the flag either way.
        $code = 'vm-nested-virtualization-off'; $blocked = $true
    } elseif ($Facts.hypervisorPresent -ne $true -and
            [string]$Facts.firmwareVirtualization -eq 'disabled' -and
            $Facts.wsl.statusUsable -ne $true) {
        $code = 'firmware-disabled'; $blocked = $true
    } elseif ([string]$Facts.features.wsl -eq 'unknown' -or
            [string]$Facts.features.virtualMachinePlatform -eq 'unknown') {
        $code = 'preflight-query-failed'; $blocked = $true
    } elseif ([string]$Facts.features.wsl -match 'pending' -or
            [string]$Facts.features.virtualMachinePlatform -match 'pending' -or
            ($Facts.pendingReboot -eq $true -and $Facts.wsl.statusUsable -ne $true -and -not $featuresMissing)) {
        # A restart Windows Update already wants is only waited for when the
        # features are on; otherwise turning them on first lets one restart
        # do both (a VM run asked for two).
        $code = 'restart-required'; $needsRestart = $true
    } elseif ($featuresMissing) {
        $code = 'features-required'; $needsElevation = $true
        $firmwareNotice = ([string]$Facts.firmwareVirtualization -eq 'unknown')
    } elseif ($Facts.wsl.statusUsable -ne $true -or $Facts.wsl.systemdCapable -ne $true) {
        $code = 'wsl-update-required'
    } elseif ([string]$Facts.wsl.kernelError -eq 'not-checked') {
        # First look only; the full preflight before Install starts the kernel.
        $code = 'ready'
    } elseif ($Facts.wsl.kernelUsable -ne $true -and [string]$Facts.wsl.kernelError -eq 'timeout') {
        $code = 'wsl-not-responding'; $blocked = $true
    } elseif ($Facts.wsl.kernelUsable -ne $true) {
        # HypervisorPresent and firmware capability flags describe host
        # configuration, not whether WSL2 can actually launch its utility VM.
        $code = 'wsl-kernel-unavailable'; $blocked = $true
    }
    return [pscustomobject][ordered]@{
        code = $code
        blocked = $blocked
        needsElevation = $needsElevation
        needsRestart = $needsRestart
        firmwareNotice = $firmwareNotice
    }
}

function Test-RequiredHosts {
    <# One HEAD request per host Setup will download from, through the same
       Windows proxy settings the browser uses. Returns the hosts that failed. #>
    $targets = @(
        @{ name = 'Ubuntu package snapshot'; url = 'https://snapshot.ubuntu.com/' },
        @{ name = 'Python packages (pypi.org)'; url = 'https://pypi.org/simple/pip/' },
        @{ name = 'Python package files'; url = 'https://files.pythonhosted.org/' }
    )
    if ($NetworkProfile -ne 'minimal') {
        $targets += @{ name = 'LibreLane tool image (ghcr.io)'; url = 'https://ghcr.io/v2/' }
        $targets += @{ name = 'PDK downloads (github.com)'; url = 'https://github.com/fossi-foundation/ciel-releases/releases' }
    }
    if ($NeedRootfs -eq '1') {
        $targets += @{ name = 'Ubuntu image (releases.ubuntu.com)'; url = 'https://releases.ubuntu.com/24.04.4/SHA256SUMS' }
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $failed = @()
    foreach ($t in $targets) {
        $ok = $false; $why = ''
        for ($i = 0; $i -lt 2 -and -not $ok; $i++) {
            try {
                $r = Invoke-WebRequest -Uri $t.url -Method Head -UseBasicParsing -TimeoutSec 20 -MaximumRedirection 5
                $ok = ([int]$r.StatusCode -lt 500)
            } catch {
                $resp = $_.Exception.Response
                if ($null -ne $resp -and [int]$resp.StatusCode -in @(401, 403, 404, 405)) { $ok = $true }
                else { $why = $_.Exception.Message }
            }
        }
        if (-not $ok) { $failed += [pscustomobject][ordered]@{ name = $t.name; url = $t.url; error = $why } }
    }
    return [pscustomobject][ordered]@{ schema = 1; ok = ($failed.Count -eq 0); failed = $failed }
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
        windowsUbr = [int]$facts.windowsUbr
        computer = $facts.computer
        hypervisorPresent = $facts.hypervisorPresent
        firmwareVirtualization = [string]$facts.firmwareVirtualization
        firmwareVirtualizationRaw = [string]$facts.firmwareVirtualizationRaw
        virtualMachine = $facts.virtualMachine
        features = $facts.features
        pendingReboot = $facts.pendingReboot
        bootIdentity = [string]$facts.bootIdentity
        wsl = $facts.wsl
        decision = Get-PreflightDecision $facts
        memory = [pscustomobject][ordered]@{
            low = ($null -ne $facts.memoryBytes -and [int64]$facts.memoryBytes -gt 0 -and
                [int64]$facts.memoryBytes -lt [int64]$RecommendedMemoryBytes)
            gb = if ($null -ne $facts.memoryBytes) { [math]::Round([int64]$facts.memoryBytes / 1GB, 1) } else { 0 }
        }
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
    # The features alone are not WSL any more: since WSL left Windows, a clean
    # PC needs the WSL package too, and `wsl --update` refuses to run until it
    # exists ("not installed"). Installing it here keeps it to one UAC prompt.
    # A failure is not fatal: after the restart Setup installs it again.
    if ($null -eq $FeatureFixturePath -or -not $FeatureFixturePath) {
        # Setup starts this elevated helper with ShellExec, which does not turn
        # off WOW64 redirection: it runs as 32-bit PowerShell, where System32
        # is SysWOW64 and has no wsl.exe. sysnative reaches the real one.
        $wslExe = Join-Path $env:SystemRoot 'System32\wsl.exe'
        if (-not (Test-Path -LiteralPath $wslExe -PathType Leaf)) {
            $wslExe = Join-Path $env:SystemRoot 'sysnative\wsl.exe'
        }
        if ($failed.Count -eq 0 -and (Test-Path -LiteralPath $wslExe -PathType Leaf)) {
            $env:WSL_UTF8 = '1'
            # Best effort only. On Windows 10 before the restart wsl.exe writes
            # "Catastrophic failure" to stderr, which Windows PowerShell turns
            # into a terminating error under ErrorActionPreference=Stop; that
            # must not undo the two features that did turn on.
            $previousPreference = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            try {
                $text = (& $wslExe --install --no-distribution 2>&1 | ForEach-Object { [string]$_ } | Out-String) -replace "`0", ''
                $packageExit = [int]$LASTEXITCODE
            } catch {
                $text = [string]$_.Exception.Message; $packageExit = -1
            } finally {
                $ErrorActionPreference = $previousPreference
            }
            Add-OrSet $result 'wslPackage' ([pscustomobject][ordered]@{
                exitCode = $packageExit; output = $text.Trim() })
        }
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
    $folder = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\LanEx (EDA)'
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
        try {
            $actual = [string](Get-ItemPropertyValue -LiteralPath $paths.trigger -Name 'LanExSetupResume' -ErrorAction Stop)
        } catch { $actual = '' }
        if ($actual -eq $expected) {
            Remove-ItemProperty -LiteralPath $paths.trigger -Name 'LanExSetupResume' -ErrorAction SilentlyContinue
        }
    }
    if ($state.resume.manualShortcut) {
        Remove-Item -LiteralPath ([string]$state.resume.manualShortcut) -Force -ErrorAction SilentlyContinue
    }
    $state.resume.triggerRegistered = $false
    Write-AtomicJson $StatePath $state
    return $state
}

function Get-TestWslFixture {
    if (-not $TestWslFixturePath) { return $null }
    if ($env:LANEX_SETUP_TESTING -ne '1') { throw 'TestWslFixturePath is accepted only by the test harness.' }
    return Read-JsonFile $TestWslFixturePath 'WSL fixture'
}

function Read-OwnedLinuxMarker($State) {
    if ($LinuxMarkerFixturePath) {
        if ($env:LANEX_SETUP_TESTING -ne '1') { throw 'LinuxMarkerFixturePath is accepted only by the test harness.' }
        return Read-JsonFile $LinuxMarkerFixturePath 'Linux appliance marker'
    }
    $wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
    $output = @(& $wsl '-d' ([string]$State.appliance.name) '-u' 'root' '--' 'cat' ([string]$State.appliance.linuxMarker) 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not read the owned Linux appliance marker: $($output -join [Environment]::NewLine)" }
    try { return (($output -join [Environment]::NewLine) | ConvertFrom-Json) }
    catch { throw "Linux appliance marker is malformed JSON: $($_.Exception.Message)" }
}

function Validate-UninstallOwnership {
    $state = Migrate-State (Read-JsonFile $StatePath 'Install state')
    Assert-StateOwner $state (Get-OwnerSid)
    if (-not $state.appliance.registryId -or -not $state.appliance.name -or -not $state.appliance.basePath) {
        throw 'Saved appliance identity is incomplete; no distribution was changed.'
    }
    $matches = @(Get-RegistryEntries | Where-Object {
        [string]$_.registryId -eq [string]$state.appliance.registryId -and
        [string]::Equals([string]$_.name, [string]$state.appliance.name, [StringComparison]::OrdinalIgnoreCase) -and
        (Normalize-Path ([string]$_.basePath)) -eq (Normalize-Path ([string]$state.appliance.basePath))
    })
    if ($matches.Count -ne 1) { throw 'The exact saved WSL registration identity/path does not match; no distribution was changed.' }
    $marker = Read-OwnedLinuxMarker $state
    if ([int]$marker.schema -ne 1 -or [string]$marker.installId -ne [string]$state.installId -or
            [string]$marker.manifestHash -ne [string]$state.manifestHash -or
            [string]$marker.sourceSha -ne [string]$state.source.sha) {
        throw 'The Linux appliance marker does not match the saved owner/build identity; no distribution was changed.'
    }
    return $state
}

function Export-OwnedAppliance {
    $state = Validate-UninstallOwnership
    if ([string]::IsNullOrWhiteSpace($ExportPath)) { throw 'ExportAppliance requires an export path.' }
    $destination = [IO.Path]::GetFullPath($ExportPath)
    if (Test-Path -LiteralPath $destination) { throw 'The export destination already exists.' }
    $parent = Split-Path -Parent $destination
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw 'The export destination folder does not exist.' }
    $fixture = Get-TestWslFixture
    if ($null -ne $fixture) {
        $exitCode = [int]$fixture.exportExitCode
        if ($exitCode -eq 0) { [IO.File]::WriteAllBytes($destination, [byte[]](1, 2, 3, 4)) }
    } else {
        $wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
        & $wsl '--export' ([string]$state.appliance.name) $destination
        $exitCode = $LASTEXITCODE
    }
    if ($exitCode -ne 0 -or -not (Test-Path -LiteralPath $destination -PathType Leaf) -or
            (Get-Item -LiteralPath $destination).Length -le 0) {
        Remove-Item -LiteralPath $destination -Force -ErrorAction SilentlyContinue
        throw 'WSL export did not complete. The appliance and all data were preserved.'
    }
    return [pscustomobject][ordered]@{ schema = 1; exported = $true; path = $destination; installId = [string]$state.installId; distroName = [string]$state.appliance.name }
}

function Remove-OwnedAppliance {
    $state = Validate-UninstallOwnership
    $originalPhase = [string]$state.phase
    if (-not $ConfirmedInstallId -or [string]$state.installId -ne $ConfirmedInstallId) {
        throw 'Permanent removal confirmation does not match this install; no distribution was changed.'
    }
    if (-not $OwnedDataRoot) { throw 'RemoveAppliance requires the owned data root.' }
    $root = Normalize-Path $OwnedDataRoot
    $stateFull = Normalize-Path $StatePath
    $base = Normalize-Path ([string]$state.appliance.basePath)
    $separator = [IO.Path]::DirectorySeparatorChar
    $comparison = if ($env:OS -eq 'Windows_NT') {
        [StringComparison]::OrdinalIgnoreCase
    } else {
        [StringComparison]::Ordinal
    }
    if (-not $root -or
            -not $stateFull.StartsWith($root + $separator, $comparison) -or
            -not $base.StartsWith($root + $separator, $comparison)) {
        throw 'Owned paths are outside the expected LanEx data root; no distribution was changed.'
    }
    [void](Clear-OwnerResume)
    $fixture = Get-TestWslFixture
    if ($null -ne $fixture) {
        $exitCode = [int]$fixture.unregisterExitCode
    } else {
        $wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
        & $wsl '--terminate' ([string]$state.appliance.name) | Out-Null
        & $wsl '--unregister' ([string]$state.appliance.name)
        $exitCode = $LASTEXITCODE
    }
    if ($exitCode -ne 0) {
        $preserved = Migrate-State (Read-JsonFile $StatePath 'Install state')
        $preserved.phase = $originalPhase
        Write-AtomicJson $StatePath $preserved
        throw 'WSL could not unregister the verified LanEx appliance. Its VHDX, state, caches, and logs were preserved.'
    }
    if ($null -eq $fixture) {
        $remaining = @(Get-RegistryEntries | Where-Object { [string]$_.registryId -eq [string]$state.appliance.registryId })
        if ($remaining.Count -ne 0) {
            $preserved = Migrate-State (Read-JsonFile $StatePath 'Install state')
            $preserved.phase = $originalPhase
            Write-AtomicJson $StatePath $preserved
            throw 'Windows still reports the LanEx appliance as registered. Its files were preserved.'
        }
    }
    # The historical browser profile is %LOCALAPPDATA%\lanex\app-profile,
    # which aliases this root on case-insensitive Windows. Remove only paths
    # created for this install ID; never recurse over the shared root.
    foreach ($ownedPath in @(
            ([IO.Path]::GetFullPath([string]$state.appliance.basePath)),
            (Join-Path ([IO.Path]::GetFullPath($OwnedDataRoot)) 'installer-cache'),
            (Join-Path ([IO.Path]::GetFullPath($OwnedDataRoot)) 'logs'),
            (Join-Path ([IO.Path]::GetFullPath($OwnedDataRoot)) ('app-profile\' + [string]$state.installId)),
            ([IO.Path]::GetFullPath($StatePath)))) {
        Remove-Item -LiteralPath $ownedPath -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath (Join-Path ([IO.Path]::GetFullPath($OwnedDataRoot)) 'appliance') -Force -ErrorAction SilentlyContinue
    return [pscustomobject][ordered]@{ schema = 1; removed = $true; installId = [string]$state.installId; distroName = [string]$state.appliance.name }
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
            $RootfsUrl, $RootfsSha256, $ImageDigest, $Gds3dCommit, $LockPath, $PdkAssetsPath, $AptSnapshot)) {
        if ([string]::IsNullOrWhiteSpace($required)) { throw 'NewManifest is missing a required argument.' }
    }
    if ($SourceSha -notmatch '^[0-9a-fA-F]{40}$') { throw 'SourceSha must be a full commit SHA.' }
    if ($RootfsSha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'RootfsSha256 is invalid.' }
    if ($BakedRootfsSha256 -and $BakedRootfsSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw 'BakedRootfsSha256 is invalid.'
    }
    if ($ImageDigest -notmatch '^sha256:[0-9a-fA-F]{64}$') { throw 'ImageDigest must be an immutable sha256 digest.' }
    if ($Gds3dCommit -notmatch '^[0-9a-fA-F]{40}$') { throw 'Gds3dCommit must be a full commit SHA.' }
    if ($AptSnapshot -notmatch '^[0-9]{8}T[0-9]{6}Z$') { throw 'AptSnapshot must be a snapshot.ubuntu.com ID like 20261023T000000Z.' }
    $pdkAssets = Read-JsonFile $PdkAssetsPath 'PDK asset pins'
    $catalog = Read-JsonFile $CatalogPath 'Capability catalog'
    $pins = Read-JsonFile $PdkPinsPath 'PDK pins'
    $payload = [ordered]@{
        wheel = [ordered]@{ file = [IO.Path]::GetFileName($WheelPath); sha256 = Get-Sha256 $WheelPath }
        installScriptSha256 = Get-Sha256 $InstallScriptPath
        provisionScriptSha256 = Get-Sha256 $ProvisionScriptPath
        selftestSha256 = Get-Sha256 $SelftestPath
        setupWorkerSha256 = Get-Sha256 $PSCommandPath
        constraintsSha256 = Get-Sha256 $ConstraintsPath
        lockSha256 = Get-Sha256 $LockPath
        catalogSha256 = Get-Sha256 $CatalogPath
        pdkPinsSha256 = Get-Sha256 $PdkPinsPath
    }
    $bakedInventory = $null
    if ($BakedPackageInventoryPath) {
        $bakedInventory = Read-JsonFile $BakedPackageInventoryPath 'Baked package inventory'
    }
    $manifest = [ordered]@{
        schema = $ManifestSchema
        generatedUtc = [DateTime]::UtcNow.ToString('o')
        source = [ordered]@{ repository = $SourceRepository; ref = $SourceRef; sha = $SourceSha.ToLowerInvariant() }
        app = [ordered]@{ version = $AppVersion; channel = $Channel }
        target = [ordered]@{ os = 'windows'; architecture = 'amd64'; minBuild = 19044; primary = 'windows-11-x64' }
        rootfs = [ordered]@{
            url = $RootfsUrl
            urls = if ($RootfsUrls) { @($RootfsUrls -split '\|' | Where-Object { $_ }) } else { @($RootfsUrl) }
            sha256 = $RootfsSha256.ToLowerInvariant()
            # Informational only: shown in estimates, never compared to a download.
            sizeBytes = $RootfsSizeBytes
        }
        apt = [ordered]@{ snapshot = $AptSnapshot; source = 'https://snapshot.ubuntu.com/ubuntu/' + $AptSnapshot + '/' }
        bakedRootfs = if ($BakedRootfsSha256) {
            [ordered]@{
                file = $BakedRootfsFile
                url = if ($BakedRootfsUrl) { $BakedRootfsUrl } else { $null }
                sha256 = $BakedRootfsSha256.ToLowerInvariant()
                sizeBytes = $BakedRootfsSizeBytes
                packageInventory = $bakedInventory
                packageInventorySha256 = if ($BakedPackageInventoryPath) { Get-Sha256 $BakedPackageInventoryPath } else { $null }
            }
        } else { $null }
        payload = $payload
        python = [ordered]@{ supported = @('3.12'); constraintsFile = [IO.Path]::GetFileName($ConstraintsPath); lockFile = [IO.Path]::GetFileName($LockPath) }
        dependencies = [ordered]@{ librelane = '3.0.4'; ciel = '2.6.1' }
        image = [ordered]@{ reference = $ImageReference; digest = $ImageDigest.ToLowerInvariant() }
        gds3d = [ordered]@{ repository = 'trilomix/GDS3D'; commit = $Gds3dCommit.ToLowerInvariant() }
        pdkPins = $pins
        pdkCatalog = $catalog.pdk_catalog
        pdkAssets = $pdkAssets
        sizeEstimates = [ordered]@{
            rootfsDownloadBytes = $RootfsSizeBytes
            measuredBaseInstalledBytes = [int64]1395864372
            measuredBaseNetworkBytes = [int64]966367642
            estimatedNativeInstalledBytes = [int64]1288490189
            estimatedNativeNetworkBytes = [int64]751619277
            estimatedImageDownloadBytes = [int64]1589137899
            estimatedImageInstalledBytes = [int64]8074035200
            practicalRunHeadroomBytes = [int64]4294967296
        }
        componentFingerprints = [ordered]@{}
    }
    $manifest.componentFingerprints.app = Get-TextSha256 (($manifest.source | ConvertTo-Json -Compress) + ($payload | ConvertTo-Json -Compress))
    $manifest.componentFingerprints.rootfs = Get-TextSha256 ($manifest.rootfs | ConvertTo-Json -Compress)
    $manifest.componentFingerprints.image = Get-TextSha256 ($manifest.image | ConvertTo-Json -Compress)
    $manifest.componentFingerprints.pdks = Get-TextSha256 (($manifest.pdkPins | ConvertTo-Json -Depth 20 -Compress) + ($manifest.pdkCatalog | ConvertTo-Json -Depth 20 -Compress))
    $manifest.componentFingerprints.app = Get-TextSha256 ($manifest.componentFingerprints.app + ($manifest.apt | ConvertTo-Json -Compress))
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
                    $incomingSha -ne [string]$state.resume.installerSha256) {
                throw 'Automatic resume installer identity does not match saved state.'
            }
            # MSIX-packaged launchers can expose the same owner-scoped file
            # through Packages\<family>\LocalCache\Local while an unelevated
            # installer records the ordinary LocalAppData spelling. Exact
            # content identity plus the owner-bound state is authoritative;
            # requiring the alias string to match makes a valid restart fail.
            if (-not $BootIdentity -or [string]$state.boot.lastIdentity -eq $BootIdentity) {
                throw 'The required restart has not been observed; Setup will not loop in the same boot.'
            }
        }
        if ($Operation -eq 'repair' -and ([string]$state.manifestHash -ne $manifestHash -or
                [string]$state.source.sha -ne [string]$manifest.source.sha)) {
            throw 'Repair cannot change build identity. Run the matching Setup or choose an explicit Update.'
        }
        if (($Operation -eq 'update' -or [string]$state.manifestHash -ne $manifestHash) -and $Operation -ne 'repair') {
            if (-not $state.PSObject.Properties['previousBuild']) {
                $snapshot = [pscustomobject][ordered]@{
                    manifestHash = [string]$state.manifestHash
                    source = $state.source
                    choices = $state.choices
                    components = $state.components
                    phase = [string]$state.phase
                }
                $snapshot = ($snapshot | ConvertTo-Json -Depth 100 | ConvertFrom-Json)
                Add-OrSet $state 'previousBuild' $snapshot
            }
            Reset-ChangedComponents $state $manifest
            $state.manifestHash = $manifestHash
            $state.source = $manifest.source
            if ($Operation -ne 'update') {
                $Operation = 'update'
            }
        }
        Add-OrSet $state 'currentInstallerSha256' $installerSha
        $state.operation = $Operation
        # Existing choices are authoritative on resume/manual rerun. New choices
        # are accepted only for an explicit update or modify.
        if ($Operation -eq 'update' -or $Operation -eq 'modify') {
            if ($rawChoices) { $state.choices = $choices }
        } else {
            $state.choices = ConvertTo-NormalizedChoices $manifest $state.choices
        }
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
    $canonExpected = Normalize-Path $ExpectedBasePath
    if ($state.appliance.registryId) {
        $owned = @($entries | Where-Object {
            [string]$_.registryId -eq [string]$state.appliance.registryId -and
            [string]::Equals([string]$_.name, [string]$state.appliance.name, [StringComparison]::OrdinalIgnoreCase) -and
            (Normalize-Path ([string]$_.basePath)) -eq (Normalize-Path ([string]$state.appliance.basePath))
        })
        if ($owned.Count -eq 1) { return $state.appliance }
        throw 'The recorded appliance registration identity no longer matches Windows.'
    }
    $atExpected = @($entries | Where-Object { (Normalize-Path ([string]$_.basePath)) -eq $canonExpected })
    if ($atExpected.Count -eq 1) {
        $matched = $atExpected[0]
        $markerRaw = & wsl.exe -d ([string]$matched.name) -u root -- cat /etc/lanex/appliance.json 2>$null
        if ($LASTEXITCODE -eq 0 -and $markerRaw) {
            try {
                $marker = ($markerRaw | Out-String) | ConvertFrom-Json
                if ($marker.installId -and [string]$marker.installId -ne [string]$state.installId) {
                    throw "An existing distribution at $ExpectedBasePath belongs to installId $($marker.installId), not $($state.installId)."
                }
            } catch {
                if ($_.Exception.Message -match "belongs to installId") { throw $_ }
                throw "Linux ownership marker in distribution $($matched.name) is malformed."
            }
        }
        $state.appliance.name = [string]$matched.name
        $state.appliance.basePath = $ExpectedBasePath
        $state.appliance.registryId = [string]$matched.registryId
        $state.phase = 'appliance-bound'
        Write-AtomicJson $StatePath $state
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
    $targetPath = Normalize-Path ([string]$state.appliance.basePath)
    $matches = @(Get-RegistryEntries | Where-Object {
        [string]::Equals([string]$_.name, [string]$state.appliance.name, [StringComparison]::OrdinalIgnoreCase) -and
        (Normalize-Path ([string]$_.basePath)) -eq $targetPath
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

function Set-SetupOutcome {
    if (-not $Outcome) { throw 'RecordOutcome requires Outcome.' }
    $state = Migrate-State (Read-JsonFile $StatePath 'Install state')
    Assert-StateOwner $state (Get-OwnerSid)
    $state.phase = $Outcome
    if ($Outcome -eq 'ready') {
        $state.failure = $null
        if ($ManifestPath -and (Test-Path -LiteralPath $ManifestPath)) {
            $manifest = Read-JsonFile $ManifestPath 'Build manifest'
            $manifestHash = Get-Sha256 $ManifestPath
            $state.manifestHash = $manifestHash
            $state.source = $manifest.source
        }
    } else {
        $state.failure = [pscustomobject][ordered]@{
            kind = $Outcome
            message = [string]$OutcomeMessage
            recordedUtc = [DateTime]::UtcNow.ToString('o')
        }
    }
    Write-AtomicJson $StatePath $state
    return $state
}

function Complete-Update([bool]$Rollback) {
    $state = Migrate-State (Read-JsonFile $StatePath 'Install state')
    Assert-StateOwner $state (Get-OwnerSid)
    if (-not $state.PSObject.Properties['previousBuild']) {
        throw 'There is no pending update checkpoint.'
    }
    if ($Rollback) {
        $previous = $state.previousBuild
        $state.manifestHash = [string]$previous.manifestHash
        $state.source = $previous.source
        $state.choices = $previous.choices
        $state.components = $previous.components
        $state.phase = [string]$previous.phase
        $state.operation = 'repair'
        $state.failure = $null
    }
    $state.PSObject.Properties.Remove('previousBuild')
    Write-AtomicJson $StatePath $state
    return $state
}

$result = switch ($Action) {
    'NewManifest' { New-BuildManifest }
    'InitializeState' { Initialize-State }
    'ResolveAppliance' { Resolve-Appliance }
    'BindAppliance' { Bind-Appliance }
    'SetComponent' { Set-ComponentState }
    'Preflight' { Invoke-Preflight }
    'EnableFeatures' {
        # Setup waits for <OutputPath>.done instead of the process (it keeps
        # the wizard responsive), so the marker is written whatever happens.
        try {
            Enable-WindowsFeatures
            if ($OutputPath) { [IO.File]::WriteAllText($OutputPath + '.done', 'ok') }
        } catch {
            if ($OutputPath) { [IO.File]::WriteAllText($OutputPath + '.done', 'failed: ' + $_.Exception.Message) }
            throw
        }
    }
    'StageInstaller' { Stage-ResumeInstaller }
    'RegisterResume' { Register-OwnerResume }
    'ClearResume' { Clear-OwnerResume }
    'PlanChoices' { Get-PlannedChoices }
    'RecordOutcome' { Set-SetupOutcome }
    'ValidateUninstall' { Validate-UninstallOwnership }
    'ExportAppliance' { Export-OwnedAppliance }
    'RemoveAppliance' { Remove-OwnedAppliance }
    'CommitUpdate' { Complete-Update $false }
    'RollbackUpdate' { Complete-Update $true }
    'NetworkCheck' { Test-RequiredHosts }
    'ReadState' {
        $s = Migrate-State (Read-JsonFile $StatePath 'Install state')
        Assert-StateOwner $s (Get-OwnerSid)
        $s
    }
}
$result | ConvertTo-Json -Depth 100 -Compress
