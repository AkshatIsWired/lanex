# Copyright 2026 LanEx Contributors
# Licensed under the Apache License, Version 2.0
#
# run-streamed.ps1 -- runs one long Setup command (wsl.exe ...) and hands its
# output to the Inno Setup wizard in small numbered files.
#
# Why this exists: the wizard used to redirect the command into ONE log file and
# re-read that whole file every 50 ms. Over an hour-long PDK/image download the
# file grows to megabytes, every poll re-parses all of it, and the wizard slows
# to a crawl at "80%" while the work itself is fine. Here every line is written
# once, into chunk-NNNNNN.txt files the wizard reads and deletes, so the cost
# stays flat however long the step runs.
#
# It is also the wizard's reliable way out. Cancel used to only drop a flag file
# for the Linux side and then keep waiting; if the step was hung on a dead
# network connection the wizard waited forever and had to be killed from Task
# Manager. The wizard writes kill.request here when a graceful stop has not
# worked, and this runner kills the whole process tree and reports exit 130.
#
# Contract with lanex.iss (RunLogged):
#   <ChunkDir>\command.txt   line 1: program, line 2: argument string (input)
#   <ChunkDir>\chunk-*.txt   UTF-8 (BOM) output lines, renamed into place whole
#   <ChunkDir>\alive.txt     a counter rewritten every ~2 s while running
#   <ChunkDir>\kill.request  created by the wizard: stop now
#   <ChunkDir>\exit.code     written last: the command's exit code
param(
    [Parameter(Mandatory = $true)][string]$ChunkDir
)

$ErrorActionPreference = 'Stop'
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
$utf8 = New-Object System.Text.UTF8Encoding($false)
$killFile = Join-Path $ChunkDir 'kill.request'
$doneFile = Join-Path $ChunkDir 'exit.code'
$aliveFile = Join-Path $ChunkDir 'alive.txt'
$script:seq = 0
$script:buffer = New-Object System.Collections.Generic.List[string]

function Write-Atomic([string]$Path, [string]$Text, $Encoding) {
    $tmp = $Path + '.tmp'
    [IO.File]::WriteAllText($tmp, $Text, $Encoding)
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Flush-Chunk {
    if ($script:buffer.Count -eq 0) { return }
    $name = Join-Path $ChunkDir ('chunk-{0:D6}.txt' -f $script:seq)
    Write-Atomic $name (($script:buffer -join "`r`n") + "`r`n") $utf8Bom
    $script:seq++
    $script:buffer.Clear()
}

$code = 1
$aliveCount = 0
try {
    $command = [IO.File]::ReadAllLines((Join-Path $ChunkDir 'command.txt'), $utf8)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $command[0]
    $psi.Arguments = if ($command.Count -gt 1) { $command[1] } else { '' }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = $utf8
    $psi.StandardErrorEncoding = $utf8
    $proc = [System.Diagnostics.Process]::Start($psi)
    $outTask = $proc.StandardOutput.ReadLineAsync()
    $errTask = $proc.StandardError.ReadLineAsync()
    $outOpen = $true
    $errOpen = $true
    $lastFlush = [Environment]::TickCount
    $lastAlive = 0
    $killed = $false
    while ($outOpen -or $errOpen) {
        $busy = $false
        if ($outOpen -and $outTask.IsCompleted) {
            $line = $outTask.Result
            if ($null -eq $line) { $outOpen = $false }
            else { $script:buffer.Add($line); $outTask = $proc.StandardOutput.ReadLineAsync() }
            $busy = $true
        }
        if ($errOpen -and $errTask.IsCompleted) {
            $line = $errTask.Result
            if ($null -eq $line) { $errOpen = $false }
            else { $script:buffer.Add($line); $errTask = $proc.StandardError.ReadLineAsync() }
            $busy = $true
        }
        $now = [Environment]::TickCount
        if ($script:buffer.Count -ge 200 -or ($script:buffer.Count -gt 0 -and ($now - $lastFlush) -ge 250)) {
            Flush-Chunk
            $lastFlush = $now
        }
        if (($now - $lastAlive) -ge 2000) {
            $aliveCount++
            Write-Atomic $aliveFile ([string]$aliveCount) $utf8
            $lastAlive = $now
        }
        if (Test-Path -LiteralPath $killFile) {
            $script:buffer.Add('Setup is force-stopping this step.')
            & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $proc.Id /T /F *> $null
            $killed = $true
            break
        }
        if (-not $busy) { Start-Sleep -Milliseconds 80 }
    }
    if ($killed) {
        $code = 130
    } else {
        $proc.WaitForExit()
        $code = $proc.ExitCode
    }
} catch {
    $script:buffer.Add('Setup could not run this step: ' + $_.Exception.Message)
    $code = 1
}
try { Flush-Chunk } catch {}
Write-Atomic $doneFile ([string]$code) $utf8
exit 0
