$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$StateDirectory = Join-Path $ProjectRoot '.collector'
$PidPath = Join-Path $StateDirectory 'player-case-server.pid'
$StatusUrl = 'http://127.0.0.1:8765/api/player-case/status'

if (-not (Test-Path -LiteralPath $PidPath)) {
    Write-Host '没有记录到正在运行的 LOL 高分段对比助手。'
    exit 0
}

$ServerPid = [int](Get-Content -LiteralPath $PidPath -Raw)
$ServerProcess = Get-Process -Id $ServerPid -ErrorAction SilentlyContinue
if ($ServerProcess) {
    if ($ServerProcess.ProcessName -notmatch 'python|py') {
        throw "PID $ServerPid 当前不是 Python 进程；为避免误停其他程序，已取消操作。"
    }
    try {
        $Status = Invoke-RestMethod -Uri $StatusUrl -TimeoutSec 2
        if (-not $Status.available) { throw '本地端点不是 LOL 对比助手。' }
    } catch {
        throw "PID $ServerPid 仍存在，但无法验证为 LOL 对比助手；为避免误停其他程序，已取消操作。"
    }
    Stop-Process -Id $ServerPid
    Wait-Process -Id $ServerPid -Timeout 10 -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $PidPath -Force
Write-Host 'LOL 高分段对比助手已停止。'
