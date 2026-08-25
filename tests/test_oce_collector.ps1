[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$collector = Join-Path $repoRoot 'tools\oce_collector.ps1'
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("lol-oce-collector-test-{0}" -f [guid]::NewGuid().ToString('n'))

function Assert-Equal {
    param($Actual, $Expected, [string]$Message)
    if ($Actual -ne $Expected) {
        throw "$Message Expected '$Expected', got '$Actual'."
    }
}

function Write-TestJson {
    param([string]$Name, $Value)
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $testRoot $Name) -Encoding UTF8
}

function Get-Status {
    $json = & $collector -Action status -StateDirectory $testRoot -HeartbeatStaleSeconds 30
    return ($json | Out-String | ConvertFrom-Json)
}

try {
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null

    Write-TestJson -Name 'state.json' -Value ([ordered]@{
        status = 'collecting'
        pid = 999999999
        mode = 'resident'
        updated_at = (Get-Date).AddMinutes(-5).ToString('o')
        checkpoint_rows = 125183
    })
    '999999999' | Set-Content -LiteralPath (Join-Path $testRoot 'collector.pid') -Encoding ASCII
    $status = Get-Status
    Assert-Equal $status.effective_status 'crashed' 'A missing resident process must not be reported as collecting.'
    Assert-Equal $status.process_running $false 'A missing PID must be reported as not running.'

    Write-TestJson -Name 'state.json' -Value ([ordered]@{
        status = 'collecting'
        pid = $PID
        mode = 'resident'
        updated_at = (Get-Date).ToString('o')
        checkpoint_rows = 125183
    })
    "$PID" | Set-Content -LiteralPath (Join-Path $testRoot 'collector.pid') -Encoding ASCII
    Write-TestJson -Name 'heartbeat.json' -Value ([ordered]@{
        pid = $PID
        updated_at = (Get-Date).ToString('o')
        status = 'collecting'
    })
    $status = Get-Status
    Assert-Equal $status.effective_status 'collecting' 'A live process with a fresh heartbeat must preserve its reported phase.'
    Assert-Equal $status.process_running $true 'The current PowerShell process must be detected as running.'

    Write-TestJson -Name 'heartbeat.json' -Value ([ordered]@{
        pid = $PID
        updated_at = (Get-Date).AddMinutes(-5).ToString('o')
        status = 'collecting'
    })
    $status = Get-Status
    Assert-Equal $status.effective_status 'unresponsive' 'A stale heartbeat must override an apparently live process.'
    Assert-Equal $status.process_running $true 'An unresponsive process can still exist.'

    Write-Host 'OCE collector health integration tests: OK'
}
finally {
    if (Test-Path -LiteralPath $testRoot) {
        $resolvedTestRoot = (Resolve-Path -LiteralPath $testRoot).Path
        $resolvedTempRoot = (Resolve-Path -LiteralPath ([IO.Path]::GetTempPath())).Path.TrimEnd([IO.Path]::DirectorySeparatorChar)
        if (-not $resolvedTestRoot.StartsWith($resolvedTempRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean a test path outside the system temp directory: $resolvedTestRoot"
        }
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
