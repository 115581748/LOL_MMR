$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$SecretDirectory = Join-Path $ProjectRoot '.secrets'
$SecretPath = Join-Path $SecretDirectory 'riot_api_key.txt'
$StatusUrl = 'http://127.0.0.1:8765/api/player-case/status'
$RefreshUrl = 'http://127.0.0.1:8765/api/player-case/refresh'

$SecureKey = Read-Host '请粘贴新的 Riot Development API Key' -AsSecureString
$Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)
try {
    $ApiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
}

if (-not $ApiKey.StartsWith('RGAPI-') -or $ApiKey.Length -lt 20) {
    throw 'API Key 格式不正确，应以 RGAPI- 开头。'
}
New-Item -ItemType Directory -Path $SecretDirectory -Force | Out-Null
Set-Content -LiteralPath $SecretPath -Value $ApiKey -Encoding ascii
$ApiKey = $null

try {
    $Status = Invoke-RestMethod -Uri $StatusUrl -TimeoutSec 2
    if ($Status.available) {
        Write-Host 'Key 已仅保存在本机。正在立即刷新当前玩家，请稍候…'
        $Result = Invoke-RestMethod -Method Post -Uri $RefreshUrl -ContentType 'application/json' -Body '{}' -TimeoutSec 600
        Write-Host $Result.message
        Write-Host '刷新完成；已打开的页面会自动重新载入。'
        exit 0
    }
} catch {
    if ($_.Exception.Response) {
        throw "Key 已保存，但 Riot 刷新失败：$($_.ErrorDetails.Message)"
    }
}

Write-Host 'Key 已仅保存在本机。双击 Start-LOL-Model.cmd 启动程序后会自动刷新。'
