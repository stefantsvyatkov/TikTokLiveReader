<#
.SYNOPSIS
    Runs a scenario of the add-on in real NVDA inside a Windows Sandbox that stays open between runs.

.DESCRIPTION
    Adapted from BST Radio's Windows\sandbox\Run-Sandbox.ps1. The first run starts Windows Sandbox
    minimised without taking the focus, with SandboxAgent.ps1 as its logon command; later runs reuse
    it. Every run stages the add-on, the driver and the fixtures to artifacts\sandbox, sends one
    request per NVDA version and prints each run's results (artifacts\sandbox-runs\<id>).
    The agent mutes every sound device of the sandbox before each run.

.PARAMETER Scenario
    A scenario of driver.py (default "smoke").

.PARAMETER Nvda
    NVDA versions to run on; each needs artifacts\sandbox\nvda\nvda_<version>.exe.

.PARAMETER Recording
    The recording the replaying TikTok client plays (a file in artifacts\sandbox\fixtures).

.PARAMETER Pace
    Scales the recording's pauses (1 = as recorded).

.PARAMETER Stop
    Close the sandbox.

.EXAMPLE
    .\sandbox\Run-Sandbox.ps1
    .\sandbox\Run-Sandbox.ps1 -Nvda 2026.2 -Scenario smoke
    .\sandbox\Run-Sandbox.ps1 -Stop
#>
[CmdletBinding()]
param(
    [string]$Scenario = "smoke",
    [string[]]$Nvda = @("2026.1.1", "2026.2", "2026.3"),
    [string]$Recording = "smoke.jsonl",
    [string]$Pace = "1",
    [switch]$Stop,
    [int]$TimeoutMinutes = 10
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$stage = Join-Path $repo "artifacts\sandbox"
$runs = Join-Path $repo "artifacts\sandbox-runs"
$heartbeat = Join-Path $runs "heartbeat.txt"
$sandboxExe = Join-Path $env:windir "System32\WindowsSandbox.exe"

function Test-AgentAlive {
    if (-not (Get-Process -Name "vmmemWindowsSandbox" -ErrorAction SilentlyContinue)) { return $false }
    if (-not (Test-Path $heartbeat)) { return $false }
    return ((Get-Date) - (Get-Item $heartbeat).LastWriteTime).TotalSeconds -lt 20
}

if ($Stop) {
    Get-Process -Name "WindowsSandboxRemoteSession", "WindowsSandboxClient" -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Host "Windows Sandbox closed."
    return
}

if (-not (Test-Path $sandboxExe)) { throw "Windows Sandbox is not turned on (Windows Features)." }
New-Item -ItemType Directory -Force -Path $stage, $runs, (Join-Path $stage "fixtures") | Out-Null

# ---- Stage ------------------------------------------------------------------------

$addon = Join-Path $stage "addon"
if (Test-Path $addon) { Remove-Item $addon -Recurse -Force }
robocopy (Join-Path $repo "addon") $addon /E /NFL /NDL /NJH /NJS /NP `
    /XD "__pycache__" "bin" /XF "*.pyc" "config.ini" "positions.json" "speechbuffer.json" | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Staging the add-on failed (robocopy $LASTEXITCODE)." }

$driver = Join-Path $stage "driver"
New-Item -ItemType Directory -Force -Path $driver | Out-Null
Copy-Item (Join-Path $PSScriptRoot "driver.py"), (Join-Path $PSScriptRoot "replay_client.py") $driver -Force
Copy-Item (Join-Path $PSScriptRoot "SandboxAgent.ps1") $stage -Force
$probe = Join-Path $stage "probe"
if (Test-Path $probe) { Remove-Item $probe -Recurse -Force }
Copy-Item (Join-Path $PSScriptRoot "probe") $probe -Recurse
# FFmpeg serving the recording scenario's stream inside the sandbox (the add-on downloads its own).
$ffmpeg = Join-Path $repo "artifacts\tools\ffmpeg\ffmpeg.exe"
if ((Test-Path $ffmpeg) -and -not (Test-Path (Join-Path $stage "tools\ffmpeg.exe"))) {
    New-Item -ItemType Directory -Force -Path (Join-Path $stage "tools") | Out-Null
    Copy-Item $ffmpeg (Join-Path $stage "tools\ffmpeg.exe")
}
if (-not (Test-Path (Join-Path $stage "python313\python.exe"))) {
    Copy-Item (Join-Path $repo "artifacts\tools\python313") (Join-Path $stage "python313") -Recurse
}
if ($Recording -and -not (Test-Path (Join-Path $stage "fixtures\$Recording"))) {
    throw "No recording $Recording in $stage\fixtures (tools\make_fixtures.py writes the synthetic ones)."
}
foreach ($version in $Nvda) {
    if (-not (Test-Path (Join-Path $stage "nvda\nvda_$version.exe"))) { throw "No installer for NVDA $version in $stage\nvda." }
}

# ---- Start the sandbox once ----------------------------------------------------------

if (-not (Test-AgentAlive)) {
    if (Get-Process -Name "vmmemWindowsSandbox" -ErrorAction SilentlyContinue) {
        throw "A Windows Sandbox without this agent is running (another project's?). Close it first."
    }

    Remove-Item $heartbeat -Force -ErrorAction SilentlyContinue
    $configuration = @"
<Configuration>
  <VGpu>Disable</VGpu>
  <Networking>Enable</Networking>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <AudioInput>Disable</AudioInput>
  <VideoInput>Disable</VideoInput>
  <MemoryInMB>4096</MemoryInMB>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>$stage</HostFolder>
      <SandboxFolder>C:\Stage</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>$runs</HostFolder>
      <SandboxFolder>C:\Runs</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\Stage\SandboxAgent.ps1</Command>
  </LogonCommand>
</Configuration>
"@
    $configurationPath = Join-Path $stage "TikTokLiveReader.wsb"
    Set-Content -Path $configurationPath -Value $configuration -Encoding UTF8

    Add-Type -Namespace TikTokSandbox -Name Native -MemberDefinition @"
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool ShowWindowAsync(System.IntPtr window, int command);
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool IsIconic(System.IntPtr window);
"@

    function Hide-SandboxWindow {
        foreach ($session in Get-Process -Name "WindowsSandboxRemoteSession", "WindowsSandboxClient" -ErrorAction SilentlyContinue) {
            $window = $session.MainWindowHandle
            if ($window -ne [IntPtr]::Zero -and -not [TikTokSandbox.Native]::IsIconic($window)) {
                # 7 is SW_SHOWMINNOACTIVE: minimised, and the focus stays where it was.
                [TikTokSandbox.Native]::ShowWindowAsync($window, 7) | Out-Null
            }
        }
    }

    Write-Host "Starting Windows Sandbox (minimised; it stays open for later runs)..."
    Start-Process -FilePath $sandboxExe -ArgumentList "`"$configurationPath`""
    $deadline = (Get-Date).AddMinutes(4)
    while (-not (Test-AgentAlive)) {
        if ((Get-Date) -gt $deadline) { throw "The sandbox agent did not start." }
        Hide-SandboxWindow
        Start-Sleep -Milliseconds 300
    }
    for ($i = 0; $i -lt 20; $i++) {
        Hide-SandboxWindow
        Start-Sleep -Milliseconds 300
    }
}

# ---- Run, one NVDA version after the other ----------------------------------------------

# Only the latest call's results are kept.
Get-ChildItem $runs -Directory | Remove-Item -Recurse -Force
$failed = 0
foreach ($version in $Nvda) {
    $id = (Get-Date -Format "yyyyMMdd-HHmmss") + "-$version"
    $temporary = Join-Path $runs "request.tmp"
    Set-Content -Path $temporary -Value @($id, $version, $Scenario, $Recording, $Pace) -Encoding Ascii
    Move-Item $temporary (Join-Path $runs "request.txt") -Force

    $results = Join-Path $runs $id
    $done = Join-Path $results "done.txt"
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    Write-Host "NVDA $version, scenario $Scenario ($id)..."
    while (-not (Test-Path $done)) {
        if ((Get-Date) -gt $deadline) { Write-Warning "Timed out. Partial results: $results"; $failed++; break }
        Start-Sleep -Seconds 2
    }
    if (-not (Test-Path $done)) { continue }

    $code = [int]((Get-Content $done -Raw).Trim())
    if ($code -ne 0) { $failed++ }
    $summary = Join-Path $results "results.txt"
    if (Test-Path $summary) { Get-Content $summary -Encoding UTF8 | Write-Host }
    else { Get-Content (Join-Path $results "console.txt"), (Join-Path $results "console.err.txt") -ErrorAction SilentlyContinue | Write-Host }
    Write-Host ""
}

Write-Host "Results: $runs"
exit $failed
