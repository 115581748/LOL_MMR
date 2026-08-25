# OCE Diamond IV+ 常驻采集器

`oce_collector.ps1` 每轮都会枚举 OCE 单双排当前的 Diamond IV、III、II、I、Master、Grandmaster 与 Challenger 玩家。它扫描每人最近最多 100 场排位，只把未见过的玩家—对局追加到 JSONL 断点，然后重建 CSV、数值模型、出装/枚举模型、条件模型、本地玩家案例和仪表盘。

## API Key

不要把 Key 写进脚本。前台单轮运行可以使用环境变量：

```powershell
$env:RIOT_API_KEY = "RGAPI-新生成的Key"
```

常驻后台模式使用单独的、被 Git 忽略的密钥文件：

```powershell
New-Item -ItemType Directory -Force .secrets
Set-Content -LiteralPath .secrets\riot_api_key.txt -Value "RGAPI-新生成的Key" -NoNewline
```

常驻进程每轮都会重新读取该文件，因此开发 Key 过期后只需替换文件内容，不必重启采集器。长期采集建议使用 Riot Production Key。后台模式优先推荐密钥文件，这样替换过期 Key 时不需要重启进程。

## 控制命令

```powershell
# 后台启动：每轮结束六小时后再次刷新
powershell -ExecutionPolicy Bypass -File tools\oce_collector.ps1 -Action start

# 查看实际进程状态、心跳、样本行数和日志位置
powershell -ExecutionPolicy Bypass -File tools\oce_collector.ps1 -Action status

# 前台只运行一轮，适合确认新 Key
powershell -ExecutionPolicy Bypass -File tools\oce_collector.ps1 -Action once

# 请求优雅停止；当前 API 或建模步骤结束后退出
powershell -ExecutionPolicy Bypass -File tools\oce_collector.ps1 -Action stop
```

采集、建模和页面展示的易变值统一放在 `config/model-parameters.json`。默认每名玩家每轮最多追加 20 场，扫描最近 100 个 Match ID；修改配置后，下一轮采集会自动采用新参数，并把参数快照写入模型清单。Riot 返回 `429` 时采集客户端遵循 `Retry-After` 自动等待；Match 与 Timeline JSON 按比赛 ID 永久缓存，重复运行不会重复下载已有比赛。

模型重建后会生成 `assets/model-manifest.json`。网页先以 `no-store` 方式读取该清单，再按照数据文件的内容哈希加载 JS，因此样本量变化后不需要在 HTML 中手改 `?v=4078` 之类的常量。

英雄参考工作台位于 `conditional-model.html`。聚合查询按英雄、位置、补丁、段位和阶段实时重算；本地案例逐局固定对照同英雄、同位置的跨版本基准。玩家值和高分段值都使用中位数，页面不会读取或显示任何主观玩家标签。

阶段边界也在配置中参数化。当前 `conditional_model.late_phase_start_minute=25`，因此每轮采集后会从缓存 Timeline 重算 15–25 分钟中期指标和 25 分钟后指标，而不是只修改网页标签。

运行状态写在 `.collector/state.json`；日志和 PID 也位于 `.collector/`。这些文件以及 `.secrets/` 都不会进入 Git。

## 运行状态与恢复

常驻进程由独立心跳进程每 15 秒写入 `.collector/heartbeat.json`。`status` 不会只相信上一次写入的文字状态，而会同时核对 PID 和心跳：

- `collecting` / `materializing` / `modelling` / `publishing`：当前真实阶段，进程与心跳正常。
- `idle` / `retry_wait` / `waiting_for_key`：本轮结束后等待下一次刷新、失败重试或新 Key。
- `crashed`：状态文件说采集器在运行，但记录的 PID 已不存在。
- `unresponsive`：进程仍存在，但心跳超过 60 秒没有更新。

运行 `-Action start` 时会先移除已经没有对应进程的陈旧 PID，然后从稳定键去重的 JSONL 断点继续。单个采集周期内的 API 或建模步骤失败后，常驻进程会记录 `last_completed_step` 和 `next_retry_at`，等待后自动重试。如果常驻进程本身已终止，需要重新执行 `-Action start`；心跳只负责检测，不会隐式拉起新进程。
