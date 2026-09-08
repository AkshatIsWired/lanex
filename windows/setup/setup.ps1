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
    [ValidateSet('NewManifest', 'InitializeState', 'ResolveAppliance', 'BindAppliance', 'SetComponent', 'ReadState')]
    [string]$Action,
    [string]$StatePath,
    [string]$ManifestPath,
    [ValidateSet('install', 'repair', 'update')]
    [string]$Operation = 'install',
    [string]$ChoicesJson = '{}',
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
        sizeEstimates = [ordered]@{ minimumFreeBytes = 10737418240; rootfsDownloadBytes = $RootfsSizeBytes }
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
    $choices = try { $ChoicesJson | ConvertFrom-Json } catch { throw 'ChoicesJson is malformed.' }
    if (Test-Path -LiteralPath $StatePath) {
        $state = Migrate-State (Read-JsonFile $StatePath 'Install state')
        Assert-StateOwner $state $owner
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
    'ReadState' {
        $s = Migrate-State (Read-JsonFile $StatePath 'Install state')
        Assert-StateOwner $s (Get-OwnerSid)
        $s
    }
}
$result | ConvertTo-Json -Depth 100 -Compress
