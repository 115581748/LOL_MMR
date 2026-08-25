[CmdletBinding()]
param(
    [ValidateSet('start', 'run', 'once', 'stop', 'status', 'heartbeat')]
    [string]$Action = 'status',
    [ValidateRange(0, 10080)]
    [int]$IntervalMinutes = 0,
    [ValidateRange(0, 100)]
    [int]$MatchesPerPlayer = 0,
    [ValidateRange(0, 100)]
    [int]$MatchHistoryCount = 0,
    [ValidateRange(0, 1000)]
    [int]$MinimumSamples = 0,
    [ValidateRange(0, 10080)]
    [int]$LeagueCacheMaxAgeMinutes = 0,
    [string]$Platform = '',
    [string]$Population = '',
    [string]$ConfigPath = 'config\model-parameters.json',
    [string]$ApiKeyFile = '.secrets\riot_api_key.txt',
    [string]$PythonPath = '',
    [string]$StateDirectory = '',
    [ValidateRange(5, 300)]
    [int]$HeartbeatSeconds = 15,
    [ValidateRange(15, 900)]
    [int]$HeartbeatStaleSeconds = 60,
    [int]$ParentPid = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$resolvedConfigPath = if ([IO.Path]::IsPathRooted($ConfigPath)) { $ConfigPath } else { Join-Path $repoRoot $ConfigPath }
$parameters = Get-Content -LiteralPath $resolvedConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($IntervalMinutes -eq 0) { $IntervalMinutes = [int]$parameters.collection.interval_minutes }
if ($MatchesPerPlayer -eq 0) { $MatchesPerPlayer = [int]$parameters.collection.matches_per_player }
if ($MatchHistoryCount -eq 0) { $MatchHistoryCount = [int]$parameters.collection.match_history_count }
if ($MinimumSamples -eq 0) { $MinimumSamples = [int]$parameters.model.minimum_samples }
if ($LeagueCacheMaxAgeMinutes -eq 0) { $LeagueCacheMaxAgeMinutes = [int]$parameters.collection.league_cache_max_age_minutes }
if (-not $Platform) { $Platform = [string]$parameters.collection.platform }
if (-not $Population) { $Population = [string]$parameters.collection.population }
$outlierIqrMultiplier = [double]$parameters.model.outlier_iqr_multiplier
$stateDirectory = if ($StateDirectory) {
    if ([IO.Path]::IsPathRooted($StateDirectory)) { $StateDirectory } else { Join-Path $repoRoot $StateDirectory }
}
else {
    Join-Path $repoRoot '.collector'
}
$statePath = Join-Path $stateDirectory 'state.json'
$pidPath = Join-Path $stateDirectory 'collector.pid'
$heartbeatPath = Join-Path $stateDirectory 'heartbeat.json'
$heartbeatPidPath = Join-Path $stateDirectory 'heartbeat.pid'
$stopPath = Join-Path $stateDirectory 'STOP'
$stdoutPath = Join-Path $stateDirectory 'collector.out.log'
$stderrPath = Join-Path $stateDirectory 'collector.err.log'
$checkpointPath = Join-Path $repoRoot 'data\checkpoints\player_matches.jsonl'
$processedPath = Join-Path $repoRoot 'data\processed\player_matches.csv'
$modelPath = Join-Path $repoRoot 'data\models\champion_role_benchmarks.csv'
$dashboardPath = Join-Path $repoRoot 'assets\model-data.js'
$extrasPath = Join-Path $repoRoot 'assets\model-extras.js'

New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null

$script:collectorMode = if ($Action -eq 'once') { 'once' } else { 'resident' }
$script:cycleId = $null
$script:cycleStartedAt = [datetime]::MinValue
$script:lastCompletedStep = $null
$script:nextRetryAt = $null
$script:checkpointRows = 0
if (Test-Path -LiteralPath $statePath) {
    try {
        $previousState = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $script:checkpointRows = [int]($previousState.checkpoint_rows)
    }
    catch {
        $script:checkpointRows = 0
    }
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $temporaryPath = "$Path.$PID.next"
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
}

function Get-OptionalProperty {
    param($Object, [string]$Name, $Default = $null)
    if ($null -eq $Object) { return $Default }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}

function Resolve-PythonExecutable {
    if ($PythonPath) {
        $resolved = Resolve-Path -LiteralPath $PythonPath -ErrorAction Stop
        return $resolved.Path
    }
    $bundled = 'C:\Users\92920\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundled) {
        return $bundled
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    throw 'Python was not found. Pass -PythonPath with a valid Python executable.'
}

function Resolve-ApiKeyPath {
    if ([IO.Path]::IsPathRooted($ApiKeyFile)) {
        return $ApiKeyFile
    }
    return Join-Path $repoRoot $ApiKeyFile
}

function Read-RiotApiKey {
    if ($env:RIOT_API_KEY) {
        return $env:RIOT_API_KEY.Trim()
    }
    $keyPath = Resolve-ApiKeyPath
    if (Test-Path -LiteralPath $keyPath) {
        return (Get-Content -LiteralPath $keyPath -Raw -Encoding UTF8).Trim()
    }
    return ''
}

function Write-CollectorState {
    param(
        [string]$Status,
        [string]$Message,
        [datetime]$CycleStarted = [datetime]::MinValue,
        [int]$CollectorPid = $PID
    )
    $checkpointBytes = if (Test-Path -LiteralPath $checkpointPath) {
        (Get-Item -LiteralPath $checkpointPath).Length
    }
    else { 0 }
    $effectiveCycleStarted = if ($CycleStarted -ne [datetime]::MinValue) { $CycleStarted } else { $script:cycleStartedAt }
    $state = [ordered]@{
        status = $Status
        effective_status = $Status
        message = $Message
        pid = $CollectorPid
        mode = $script:collectorMode
        cycle_id = $script:cycleId
        last_completed_step = $script:lastCompletedStep
        next_retry_at = $script:nextRetryAt
        updated_at = (Get-Date).ToString('o')
        cycle_started_at = if ($effectiveCycleStarted -eq [datetime]::MinValue) { $null } else { $effectiveCycleStarted.ToString('o') }
        platform = $Platform
        population = $Population
        checkpoint_rows = $script:checkpointRows
        checkpoint_bytes = $checkpointBytes
        interval_minutes = $IntervalMinutes
        new_matches_per_player_per_cycle = $MatchesPerPlayer
        recent_match_ids_scanned = $MatchHistoryCount
    }
    Write-JsonAtomic -Value $state -Path $statePath
}

function Refresh-CheckpointRowCount {
    if (-not (Test-Path -LiteralPath $checkpointPath)) {
        $script:checkpointRows = 0
        return
    }
    $count = & $script:pythonExecutable -c @'
import sys
from pathlib import Path

with Path(sys.argv[1]).open("rb") as source:
    print(sum(chunk.count(b"\n") for chunk in iter(lambda: source.read(8 * 1024 * 1024), b"")))
'@ $checkpointPath
    if ($LASTEXITCODE -eq 0 -and "$count" -match '^\d+$') {
        $script:checkpointRows = [int64]$count
    }
}

function Invoke-PythonStep {
    param(
        [string]$Label,
        [string[]]$Arguments,
        [string]$Status,
        [string]$Message,
        [datetime]$CycleStarted
    )
    Write-CollectorState -Status $Status -Message $Message -CycleStarted $CycleStarted
    Write-Host "[$((Get-Date).ToString('s'))] $Label"
    & $script:pythonExecutable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
    $script:lastCompletedStep = $Label
    if ($Label -eq 'collect') {
        Refresh-CheckpointRowCount
    }
    Write-CollectorState -Status $Status -Message "$Label completed successfully." -CycleStarted $CycleStarted
}

function Invoke-CollectionCycle {
    $cycleStarted = Get-Date
    $script:cycleStartedAt = $cycleStarted
    $script:cycleId = [guid]::NewGuid().ToString('n')
    $script:lastCompletedStep = $null
    $script:nextRetryAt = $null
    $apiKey = Read-RiotApiKey
    if (-not $apiKey) {
        Write-CollectorState -Status 'waiting_for_key' -Message "Set RIOT_API_KEY or write a fresh key to $(Resolve-ApiKeyPath)." -CycleStarted $cycleStarted
        return 2
    }
    $originalApiKey = $env:RIOT_API_KEY
    $env:RIOT_API_KEY = $apiKey
    try {
        Invoke-PythonStep -Label 'collect' -Arguments @(
            '-m', 'riot_model.cli', 'collect',
            '--config', $resolvedConfigPath,
            '--platform', $Platform, '--population', $Population,
            '--players', '0', '--max-diamond-pages', '0',
            '--incremental', '--matches-per-player', "$MatchesPerPlayer",
            '--match-history-count', "$MatchHistoryCount",
            '--league-cache-max-age-minutes', "$LeagueCacheMaxAgeMinutes",
            '--cache-dir', 'data\cache',
            '--checkpoint', 'data\checkpoints\player_matches.jsonl',
            '--replay-dir', 'data\replays',
            '--output', 'data\processed\player_matches.csv'
        ) -Status 'collecting' -Message 'Refreshing the complete OCE Diamond IV+ ladder and appending unseen matches.' -CycleStarted $cycleStarted
        Invoke-PythonStep -Label 'phase rebuild' -Arguments @('-m', 'tools.rephase_player_rows', '--config', $resolvedConfigPath, '--input', 'data\processed\player_matches.csv', '--output', 'data\processed\player_matches.csv', '--manifest', 'data\processed\player_matches.manifest.json', '--data-root', 'data') -Status 'materializing' -Message 'Rebuilding phase columns and the processed-data manifest.' -CycleStarted $cycleStarted
        Invoke-PythonStep -Label 'model' -Arguments @('-m', 'riot_model.cli', 'model', '--config', $resolvedConfigPath, '--input', 'data\processed\player_matches.csv', '--output', 'data\models\champion_role_benchmarks.csv', '--minimum-samples', "$MinimumSamples", '--outlier-iqr-multiplier', "$outlierIqrMultiplier") -Status 'modelling' -Message 'Rebuilding numeric champion and role benchmarks.' -CycleStarted $cycleStarted
        Invoke-PythonStep -Label 'dashboard' -Arguments @('-m', 'riot_model.cli', 'dashboard', '--config', $resolvedConfigPath, '--input', 'data\models\champion_role_benchmarks.csv', '--output', 'assets\model-data.js') -Status 'modelling' -Message 'Rebuilding dashboard model assets.' -CycleStarted $cycleStarted
        Invoke-PythonStep -Label 'extras' -Arguments @('-m', 'tools.build_model_extras', '--config', $resolvedConfigPath, '--minimum-samples', "$MinimumSamples") -Status 'modelling' -Message 'Rebuilding categorical, item-order and objective models.' -CycleStarted $cycleStarted
        if ($parameters.player_case.enabled) {
            Invoke-PythonStep -Label 'player case' -Arguments @('-m', 'tools.build_player_case', '--config', $resolvedConfigPath, '--platform', $Platform, '--riot-id', "$($parameters.player_case.riot_id)", '--tag-line', "$($parameters.player_case.tag_line)", '--matches', "$($parameters.player_case.matches)", '--cache-dir', 'data\cache', '--output', 'assets\player-case.js') -Status 'publishing' -Message 'Refreshing the configured local player case.' -CycleStarted $cycleStarted
        }
        Invoke-PythonStep -Label 'conditional model' -Arguments @('-m', 'tools.build_conditional_model', '--config', $resolvedConfigPath, '--player-csv', 'data\processed\player_matches.csv', '--data-root', 'data', '--player-case', 'assets\player-case.js', '--output', 'assets\conditional-model.js') -Status 'publishing' -Message 'Rebuilding patch-aware conditional comparison profiles.' -CycleStarted $cycleStarted
        Invoke-PythonStep -Label 'site manifest' -Arguments @('-m', 'tools.build_site_manifest', '--config', $resolvedConfigPath) -Status 'publishing' -Message 'Publishing the content-hashed site manifest.' -CycleStarted $cycleStarted
        Write-CollectorState -Status 'idle' -Message 'Cycle completed successfully; waiting for the next scheduled refresh.' -CycleStarted $cycleStarted
        return 0
    }
    catch {
        Write-CollectorState -Status 'error' -Message $_.Exception.Message -CycleStarted $cycleStarted
        [Console]::Error.WriteLine("Collection cycle failed: $($_.Exception.Message)")
        return 1
    }
    finally {
        if ($null -eq $originalApiKey) {
            Remove-Item Env:RIOT_API_KEY -ErrorAction SilentlyContinue
        }
        else {
            $env:RIOT_API_KEY = $originalApiKey
        }
    }
}

function Get-RecordedProcess {
    if (-not (Test-Path -LiteralPath $pidPath)) {
        return $null
    }
    try {
        $recordedPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    }
    catch {
        return $null
    }
    return Get-Process -Id $recordedPid -ErrorAction SilentlyContinue
}

function Start-HeartbeatProcess {
    $windowsPowerShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"",
        '-Action', 'heartbeat', '-ParentPid', "$PID",
        '-StateDirectory', "`"$stateDirectory`"",
        '-HeartbeatSeconds', "$HeartbeatSeconds",
        '-HeartbeatStaleSeconds', "$HeartbeatStaleSeconds",
        '-ConfigPath', "`"$resolvedConfigPath`""
    )
    $originalApiKey = $env:RIOT_API_KEY
    Remove-Item Env:RIOT_API_KEY -ErrorAction SilentlyContinue
    try {
        $heartbeatProcess = Start-Process -FilePath $windowsPowerShell -ArgumentList $arguments -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
        $heartbeatProcess.Id | Set-Content -LiteralPath $heartbeatPidPath -Encoding ASCII
        return $heartbeatProcess
    }
    finally {
        if ($null -ne $originalApiKey) {
            $env:RIOT_API_KEY = $originalApiKey
        }
    }
}

function Get-CollectorHealth {
    $state = $null
    if (Test-Path -LiteralPath $statePath) {
        try { $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $state = $null }
    }
    $heartbeat = $null
    if (Test-Path -LiteralPath $heartbeatPath) {
        try { $heartbeat = Get-Content -LiteralPath $heartbeatPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $heartbeat = $null }
    }
    $existing = Get-RecordedProcess
    $processRunning = $null -ne $existing
    $heartbeatAge = $null
    $heartbeatUpdatedAt = Get-OptionalProperty -Object $heartbeat -Name 'updated_at'
    if ($heartbeatUpdatedAt) {
        try { $heartbeatAge = [Math]::Max(0, ((Get-Date) - [datetime]$heartbeatUpdatedAt).TotalSeconds) } catch { $heartbeatAge = $null }
    }
    $reportedStatus = [string](Get-OptionalProperty -Object $state -Name 'status' -Default 'not_started')
    $effectiveStatus = $reportedStatus
    $diagnosis = 'State and process health agree.'
    $stateMode = Get-OptionalProperty -Object $state -Name 'mode'
    $statePid = Get-OptionalProperty -Object $state -Name 'pid'
    $residentExpected = $state -and (($stateMode -eq 'resident') -or ($statePid -and $reportedStatus -notin @('stopped', 'not_started')))
    if (-not $processRunning -and $residentExpected -and $reportedStatus -notin @('stopped', 'not_started')) {
        $effectiveStatus = 'crashed'
        $diagnosis = 'State claimed an active resident collector, but its recorded PID is not running.'
    }
    elseif ($processRunning -and (-not $heartbeat -or $null -eq $heartbeatAge)) {
        $effectiveStatus = 'starting'
        $diagnosis = 'Collector process exists; waiting for its first heartbeat.'
    }
    elseif ($processRunning -and $heartbeatAge -gt $HeartbeatStaleSeconds) {
        $effectiveStatus = 'unresponsive'
        $diagnosis = "Collector heartbeat is older than $HeartbeatStaleSeconds seconds."
    }
    $output = [ordered]@{}
    if ($state) {
        foreach ($property in $state.PSObject.Properties) {
            $output[$property.Name] = $property.Value
        }
    }
    $output['effective_status'] = $effectiveStatus
    $output['diagnosis'] = $diagnosis
    $output['process_running'] = $processRunning
    $output['heartbeat_age_seconds'] = if ($null -eq $heartbeatAge) { $null } else { [Math]::Round($heartbeatAge, 1) }
    $output['heartbeat_stale_after_seconds'] = $HeartbeatStaleSeconds
    $output['stdout'] = $stdoutPath
    $output['stderr'] = $stderrPath
    return $output
}

if ($Action -in @('run', 'once')) {
    $pythonExecutable = Resolve-PythonExecutable
}
Set-Location -LiteralPath $repoRoot

switch ($Action) {
    'start' {
        $existing = Get-RecordedProcess
        if ($existing) {
            Write-Host "Collector is already running (PID $($existing.Id))."
            break
        }
        if (Test-Path -LiteralPath $pidPath) {
            Remove-Item -LiteralPath $pidPath -Force
        }
        if (Test-Path -LiteralPath $heartbeatPidPath) {
            Remove-Item -LiteralPath $heartbeatPidPath -Force
        }
        if (Test-Path -LiteralPath $stopPath) {
            Remove-Item -LiteralPath $stopPath -Force
        }
        $scriptPath = $MyInvocation.MyCommand.Path
        $childArguments = @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$scriptPath`"",
            '-Action', 'run', '-IntervalMinutes', "$IntervalMinutes",
            '-MatchesPerPlayer', "$MatchesPerPlayer", '-MatchHistoryCount', "$MatchHistoryCount",
            '-MinimumSamples', "$MinimumSamples", '-LeagueCacheMaxAgeMinutes', "$LeagueCacheMaxAgeMinutes",
            '-Platform', "$Platform", '-Population', "$Population", '-ConfigPath', "`"$resolvedConfigPath`"",
            '-ApiKeyFile', "`"$ApiKeyFile`"", '-StateDirectory', "`"$stateDirectory`"",
            '-HeartbeatSeconds', "$HeartbeatSeconds", '-HeartbeatStaleSeconds', "$HeartbeatStaleSeconds"
        )
        # Some managed hosts inject both Path and PATH. Windows PowerShell's
        # Start-Process treats them as duplicate dictionary keys. Removing the
        # uppercase process-local copy is safe here and does not modify user or
        # machine environment variables.
        [Environment]::SetEnvironmentVariable('PATH', $null, 'Process')
        $windowsPowerShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
        $process = Start-Process -FilePath $windowsPowerShell -ArgumentList $childArguments -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
        $process.Id | Set-Content -LiteralPath $pidPath -Encoding ASCII
        Write-CollectorState -Status 'starting' -Message "Background collector started with PID $($process.Id)." -CollectorPid $process.Id
        Write-Host "Started OCE D4+ collector (PID $($process.Id))."
        Write-Host "Status: powershell -File tools\oce_collector.ps1 -Action status"
    }
    'run' {
        $script:collectorMode = 'resident'
        $mutex = [Threading.Mutex]::new($false, 'Local\LOL_OCE_D4PLUS_COLLECTOR')
        if (-not $mutex.WaitOne(0)) {
            throw 'Another OCE collector process already owns the resident lock.'
        }
        try {
            $PID | Set-Content -LiteralPath $pidPath -Encoding ASCII
            $heartbeatProcess = Start-HeartbeatProcess
            while (-not (Test-Path -LiteralPath $stopPath)) {
                $result = Invoke-CollectionCycle
                $sleepSeconds = if ($result -eq 0) { $IntervalMinutes * 60 } else { 300 }
                $script:nextRetryAt = (Get-Date).AddSeconds($sleepSeconds).ToString('o')
                if ($result -eq 0) {
                    Write-CollectorState -Status 'idle' -Message 'Cycle completed successfully; waiting for the next scheduled refresh.'
                }
                elseif ($result -eq 2) {
                    Write-CollectorState -Status 'waiting_for_key' -Message 'No in-memory Riot API Key is available; retry is scheduled.'
                }
                else {
                    Write-CollectorState -Status 'retry_wait' -Message 'The previous cycle failed; the resident collector will retry automatically.'
                }
                for ($remaining = $sleepSeconds; $remaining -gt 0 -and -not (Test-Path -LiteralPath $stopPath); $remaining -= 10) {
                    Start-Sleep -Seconds ([Math]::Min(10, $remaining))
                }
            }
            $script:nextRetryAt = $null
            Write-CollectorState -Status 'stopped' -Message 'Collector stopped through the STOP signal.'
        }
        catch {
            $script:nextRetryAt = $null
            Write-CollectorState -Status 'error' -Message "Resident collector failed: $($_.Exception.Message)"
            throw
        }
        finally {
            if ($mutex) {
                $mutex.ReleaseMutex()
                $mutex.Dispose()
            }
            if (Test-Path -LiteralPath $pidPath) {
                Remove-Item -LiteralPath $pidPath -Force
            }
        }
    }
    'once' {
        $script:collectorMode = 'once'
        $result = Invoke-CollectionCycle
        if ($result -ne 0) {
            throw "Collection cycle did not complete (result $result)."
        }
    }
    'stop' {
        New-Item -ItemType File -Path $stopPath -Force | Out-Null
        $existing = Get-RecordedProcess
        if ($existing) {
            Write-Host "Stop requested for PID $($existing.Id). It will exit after the active API/model step finishes."
        }
        else {
            Write-Host 'Stop signal written; no active process was found.'
        }
    }
    'status' {
        Get-CollectorHealth | ConvertTo-Json -Depth 8
    }
    'heartbeat' {
        if ($ParentPid -le 0) {
            throw 'heartbeat requires -ParentPid with the resident collector PID.'
        }
        while (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) {
            $state = $null
            if (Test-Path -LiteralPath $statePath) {
                try { $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $state = $null }
            }
            $heartbeat = [ordered]@{
                pid = $ParentPid
                updated_at = (Get-Date).ToString('o')
                status = Get-OptionalProperty -Object $state -Name 'status' -Default 'starting'
                cycle_id = Get-OptionalProperty -Object $state -Name 'cycle_id'
                state_updated_at = Get-OptionalProperty -Object $state -Name 'updated_at'
            }
            Write-JsonAtomic -Value $heartbeat -Path $heartbeatPath
            Start-Sleep -Seconds $HeartbeatSeconds
        }
        $heartbeat = [ordered]@{
            pid = $ParentPid
            updated_at = (Get-Date).ToString('o')
            status = 'process_exited'
            process_running = $false
        }
        Write-JsonAtomic -Value $heartbeat -Path $heartbeatPath
    }
}
