$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$DashboardUrl = 'http://127.0.0.1:8765/conditional-model.html'
$StatusUrl = 'http://127.0.0.1:8765/api/player-case/status'
$RuntimeRoot = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
$BundledPython = Join-Path $RuntimeRoot 'python\python.exe'
$StateDirectory = Join-Path $ProjectRoot '.collector'
$PidPath = Join-Path $StateDirectory 'player-case-server.pid'
$LogPath = Join-Path $StateDirectory 'player-case-server.log'
$ErrorLogPath = Join-Path $StateDirectory 'player-case-server.error.log'
$SecretDirectory = Join-Path $ProjectRoot '.secrets'
$SecretPath = Join-Path $SecretDirectory 'riot_api_key.txt'

try {
    $Existing = Invoke-RestMethod -Uri $StatusUrl -TimeoutSec 2
    if ($Existing.available) {
        Start-Process $DashboardUrl
        Write-Host 'LOL 高分段对比助手已经在运行，已打开仪表盘。'
        exit 0
    }
} catch {
    # No local instance is listening yet.
}

if (-not (Test-Path -LiteralPath $SecretPath)) {
    $ApiKey = Read-Host '首次启动：请粘贴 Riot Development API Key（输入不会写入网页或 Git）'
    if (-not $ApiKey.StartsWith('RGAPI-')) {
        throw 'API Key 格式不正确，应以 RGAPI- 开头。'
    }
    New-Item -ItemType Directory -Path $SecretDirectory -Force | Out-Null
    Set-Content -LiteralPath $SecretPath -Value $ApiKey -Encoding ascii
}

$PythonPath = $null
if (Test-Path -LiteralPath $BundledPython) {
    $PythonPath = $BundledPython
} else {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($PythonCommand -and $PythonCommand.Source -notlike '*WindowsApps*') {
        $PythonPath = $PythonCommand.Source
    } else {
        $PyCommand = Get-Command py -ErrorAction SilentlyContinue
        if ($PyCommand) { $PythonPath = $PyCommand.Source }
    }
}
if (-not $PythonPath) {
    throw '没有找到可用的 Python。请安装 Python 3.10+，或从 Codex 工作区运行本程序。'
}

New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null
$Arguments = @(
    '-m', 'tools.player_case_server',
    '--host', '127.0.0.1',
    '--port', '8765',
    '--refresh-on-start'
)
$ServerProcess = Start-Process -FilePath $PythonPath -ArgumentList $Arguments -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $LogPath -RedirectStandardError $ErrorLogPath -PassThru
Set-Content -LiteralPath $PidPath -Value $ServerProcess.Id -Encoding ascii

$Ready = $false
for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
    Start-Sleep -Milliseconds 500
    if ($ServerProcess.HasExited) { break }
    try {
        $Status = Invoke-RestMethod -Uri $StatusUrl -TimeoutSec 2
        if ($Status.available) { $Ready = $true; break }
    } catch {
        # Keep waiting while the local HTTP server starts.
    }
}

if (-not $Ready) {
    $Detail = if (Test-Path -LiteralPath $ErrorLogPath) { (Get-Content -LiteralPath $ErrorLogPath -Tail 8) -join "`n" } else { '没有错误日志。' }
    throw "本地服务未能启动。`n$Detail"
}

Start-Process $DashboardUrl
Write-Host 'LOL 高分段对比助手已启动。关闭这个窗口不会停止后台监测。'
Write-Host '双击 Stop-LOL-Model.cmd 可以停止。'
