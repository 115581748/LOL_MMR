[CmdletBinding()]
param(
    [ValidateSet('start', 'run', 'once', 'stop', 'status')]
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
    [string]$PythonPath = ''
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
$stateDirectory = Join-Path $repoRoot '.collector'
$statePath = Join-Path $stateDirectory 'state.json'
$pidPath = Join-Path $stateDirectory 'collector.pid'
$stopPath = Join-Path $stateDirectory 'STOP'
$stdoutPath = Join-Path $stateDirectory 'collector.out.log'
$stderrPath = Join-Path $stateDirectory 'collector.err.log'
$checkpointPath = Join-Path $repoRoot 'data\checkpoints\player_matches.jsonl'
$processedPath = Join-Path $repoRoot 'data\processed\player_matches.csv'
$modelPath = Join-Path $repoRoot 'data\models\champion_role_benchmarks.csv'
$dashboardPath = Join-Path $repoRoot 'assets\model-data.js'
$extrasPath = Join-Path $repoRoot 'assets\model-extras.js'

New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null

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
    $checkpointRows = 0
    if (Test-Path -LiteralPath $checkpointPath) {
        $checkpointRows = (Get-Content -LiteralPath $checkpointPath | Measure-Object -Line).Lines
    }
    $state = [ordered]@{
        status = $Status
        message = $Message
        pid = $CollectorPid
        updated_at = (Get-Date).ToString('o')
        cycle_started_at = if ($CycleStarted -eq [datetime]::MinValue) { $null } else { $CycleStarted.ToString('o') }
        platform = $Platform
        population = $Population
        checkpoint_rows = $checkpointRows
        interval_minutes = $IntervalMinutes
        new_matches_per_player_per_cycle = $MatchesPerPlayer
        recent_match_ids_scanned = $MatchHistoryCount
    }
    $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Invoke-PythonStep {
    param(
        [string]$Label,
        [string[]]$Arguments
    )
    Write-Host "[$((Get-Date).ToString('s'))] $Label"
    & $script:pythonExecutable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Invoke-CollectionCycle {
    $cycleStarted = Get-Date
    $apiKey = Read-RiotApiKey
    if (-not $apiKey) {
        Write-CollectorState -Status 'waiting_for_key' -Message "Set RIOT_API_KEY or write a fresh key to $(Resolve-ApiKeyPath)." -CycleStarted $cycleStarted
        return 2
    }
    $originalApiKey = $env:RIOT_API_KEY
    $env:RIOT_API_KEY = $apiKey
    try {
        Write-CollectorState -Status 'collecting' -Message 'Refreshing the complete OCE Diamond IV+ ladder and appending unseen matches.' -CycleStarted $cycleStarted
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
        )
        Invoke-PythonStep -Label 'phase rebuild' -Arguments @('-m', 'tools.rephase_player_rows', '--config', $resolvedConfigPath, '--input', 'data\processed\player_matches.csv', '--output', 'data\processed\player_matches.csv', '--manifest', 'data\processed\player_matches.manifest.json', '--data-root', 'data')
        Write-CollectorState -Status 'modelling' -Message 'Rebuilding numeric, categorical, item-order and dragon-fight models.' -CycleStarted $cycleStarted
        Invoke-PythonStep -Label 'model' -Arguments @('-m', 'riot_model.cli', 'model', '--config', $resolvedConfigPath, '--input', 'data\processed\player_matches.csv', '--output', 'data\models\champion_role_benchmarks.csv', '--minimum-samples', "$MinimumSamples", '--outlier-iqr-multiplier', "$outlierIqrMultiplier")
        Invoke-PythonStep -Label 'dashboard' -Arguments @('-m', 'riot_model.cli', 'dashboard', '--config', $resolvedConfigPath, '--input', 'data\models\champion_role_benchmarks.csv', '--output', 'assets\model-data.js')
        Invoke-PythonStep -Label 'extras' -Arguments @('-m', 'tools.build_model_extras', '--config', $resolvedConfigPath, '--minimum-samples', "$MinimumSamples")
        if ($parameters.player_case.enabled) {
            Invoke-PythonStep -Label 'player case' -Arguments @('-m', 'tools.build_player_case', '--config', $resolvedConfigPath, '--platform', $Platform, '--riot-id', "$($parameters.player_case.riot_id)", '--tag-line', "$($parameters.player_case.tag_line)", '--matches', "$($parameters.player_case.matches)", '--cache-dir', 'data\cache', '--output', 'assets\player-case.js')
        }
        Invoke-PythonStep -Label 'conditional model' -Arguments @('-m', 'tools.build_conditional_model', '--config', $resolvedConfigPath, '--player-csv', 'data\processed\player_matches.csv', '--data-root', 'data', '--player-case', 'assets\player-case.js', '--output', 'assets\conditional-model.js')
        Invoke-PythonStep -Label 'site manifest' -Arguments @('-m', 'tools.build_site_manifest', '--config', $resolvedConfigPath)
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
    $recordedPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    return Get-Process -Id $recordedPid -ErrorAction SilentlyContinue
}

$pythonExecutable = Resolve-PythonExecutable
Set-Location -LiteralPath $repoRoot

switch ($Action) {
    'start' {
        $existing = Get-RecordedProcess
        if ($existing) {
            Write-Host "Collector is already running (PID $($existing.Id))."
            break
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
            '-ApiKeyFile', "`"$ApiKeyFile`""
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
        $mutex = [Threading.Mutex]::new($false, 'Local\LOL_OCE_D4PLUS_COLLECTOR')
        if (-not $mutex.WaitOne(0)) {
            throw 'Another OCE collector process already owns the resident lock.'
        }
        try {
            $PID | Set-Content -LiteralPath $pidPath -Encoding ASCII
            while (-not (Test-Path -LiteralPath $stopPath)) {
                $result = Invoke-CollectionCycle
                $sleepSeconds = if ($result -eq 0) { $IntervalMinutes * 60 } else { 300 }
                for ($remaining = $sleepSeconds; $remaining -gt 0 -and -not (Test-Path -LiteralPath $stopPath); $remaining -= 10) {
                    Start-Sleep -Seconds ([Math]::Min(10, $remaining))
                }
            }
            Write-CollectorState -Status 'stopped' -Message 'Collector stopped through the STOP signal.'
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
        $existing = Get-RecordedProcess
        if (Test-Path -LiteralPath $statePath) {
            Get-Content -LiteralPath $statePath -Raw -Encoding UTF8
        }
        else {
            Write-Host 'No collector state has been written yet.'
        }
        if ($existing) {
            Write-Host "Process: running (PID $($existing.Id))"
        }
        else {
            Write-Host 'Process: not running'
        }
        Write-Host "stdout: $stdoutPath"
        Write-Host "stderr: $stderrPath"
    }
}
