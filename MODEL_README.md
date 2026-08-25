# 高分段英雄行为参数模型（Riot API）

这是一条可复现的 OCE 高分段基准流水线。默认样本总体为采集时单双排 Diamond IV、III、II、I、Master、Grandmaster 和 Challenger 的全部可枚举玩家。分析单位是“某位 D4+ 玩家在一场单双排中使用某英雄/位置的表现”，不是隐藏 MMR，也不预测或替代 Riot 排位。

## 运行

PowerShell：

```powershell
$env:RIOT_API_KEY = "RGAPI-..."
python -m riot_model.cli collect --platform oc1 --population diamond-plus --players 0 --matches-per-player 20
python -m riot_model.cli model --minimum-samples 5
python -m riot_model.cli dashboard
python -m tools.build_model_extras
python -m tools.build_conditional_model
python -m tools.build_player_case --platform oc1 --riot-id "Geolonwe" --tag-line OC --matches 20
python -m tools.build_site_manifest
python -m tools.player_case_server --host 127.0.0.1 --port 8765 --refresh-on-start
```

开发 Key 通常会过期且有严格限流。采集器会缓存成功响应，遇到 429 时按 `Retry-After` 等待，因此可安全重跑。不要把 Key 写进代码或提交到 Git。

日常使用推荐直接运行 `release/LOLHighRankComparator.exe`：这是 Python/Tkinter 原生桌面程序，可在窗口顶部切换玩家和更新 Development Key，每 1 分钟检查一次新对局。每场比赛会缓存赛后 Timeline；人物位置按约一分钟采样，目标事件按毫秒，秒级时间线同时驱动小地图和图标化 TAB 面板。英雄、装备与召唤师技能图标来自随程序打包的 Riot Data Dragon 资源。兵线位置不属于 Riot API 输出，只按出生时间、标准路线和移动速度估算。Key 只保存在 `%LOCALAPPDATA%\LOLHighRankComparator\riot_api_key.txt`，不会打进 EXE。命令行与旧本地网页入口仍可用于开发和审计模型。

输出：

- `data/processed/player_matches.csv`：每行一位玩家的一局数据。
- `data/processed/player_matches.manifest.json`：样本量和口径。
- `data/models/champion_role_benchmarks.csv`：按英雄、位置、指标生成的 `n/mean/median/std/P25/P75/IQR` 参数。
- `data/cache/`：原始 Match-v5 与 Timeline-v5 JSON，便于审计和重复建模。
- `assets/model-data.js`：浏览器仪表盘使用的去标识化参数数据。
- `assets/model-extras.js`：出装、技能/符文、版本/段位枚举分布，以及从时间线派生的龙团与全场团战参数；不含 PUUID。
- `assets/conditional-model.js`：按英雄、位置、版本、段位带和阶段分层的稳健分布、相关矩阵、时间切分稳定性，以及案例所需的同英雄同位置跨版本固定基准。
- `assets/player-case.js`：本地案例最近 20 场的去标识化逐局阶段指标；只输出数据，不保存账号 PUUID 或人工评价。
- `assets/model-manifest.json`：数据内容哈希、生成时间、样本元信息和当次使用的完整参数快照；网页用它自动刷新缓存版本。
- `config/model-parameters.json`：采集、建模和展示的统一可调参数，不再把样本量、龙团窗口、分页数和置信度阈值散落写死在脚本中。
- `data/checkpoints/player_matches.jsonl`：逐局断点文件；长时间采集被中断后可直接重跑。

## 指标与可解释边界

| 阶段 | API 可复现指标 | 说明 |
|---|---|---|
| 0–15 分钟 | 金币、等级、原始经验、CS、K/D/A | 等级直接取 15 分钟时间线快照；原始经验保留在全字段浏览器中 |
| 15–25 分钟 | 金币、CS、英雄伤害、K/D/A、团队塔/龙 | 塔和龙是团队级上下文，不应误称个人控制率 |
| 25 分钟后 | 每分钟英雄伤害、每分钟承伤、K/D/A、团战参与、首个阵亡 | 以后期大龙首次刷新为阶段起点；伤害与承伤除以实际 `比赛分钟数 − 25`，并将 15 秒内连续至少 3 次击杀定义为团战 |
| 全局 | CS/分钟、伤害/分钟、视野/分钟、胜负 | 用于质量检查与描述，不作为隐藏分 |

此外，程序会自动保留 ParticipantDto 中所有数值型结算指标（`end_*`）和 Challenges 数值指标（`challenge_*`）。这能先完成“全指标统计”，同时避免 Riot 随版本新增字段时必须改代码。嵌套对象、文本标签和无法跨版本比较的非数值字段不会直接进入参数模型。

本地仪表盘将连续/计数/布尔字段放入“全部可用数值字段”浏览器；物品 ID、召唤师技能、基石符文、版本、段位与胜负等离散值按出现频率展示，不对 ID 求均值。物品名称、符文和召唤师技能名称来自样本最新补丁对应的 Riot Data Dragon `16.15.1` 静态数据。

“龙团”采用可审计的代理口径：每次小龙击杀事件前后 45 秒内、龙坑中心 3400 坐标单位范围内发生的英雄击杀组成一个龙团窗口。由此计算参团次数、击杀/死亡/助攻、己方控龙结果、到场控龙率和存活率。这个口径不能观察没有人头发生的拉扯、完整视野与语音决策，所以网页会始终显示方法边界。

`conditional-model.html` 是英雄参考模型工作台。聚合区同时显示玩家样本中位数、高分段条件中位数、绝对差、相对差、经验分位和双方样本量。逐局区为双方分别提取同位置玩家数据，固定展示“你的本局值 / 对手本局值 / 你的英雄 D4+ 基准 / 对手英雄 D4+ 基准”，并计算“你 − 对手”以及双方各自的“本局 − 英雄基准”。双方基准都固定为“该英雄＋该位置”的 D4+ 跨版本分布，不按该局补丁或经济领先/落后切换，也绝不回退到其他英雄。逐局比较会先按“比赛 ID + PUUID”去重，独立最低样本参数默认为 3，主聚合模型仍为 20，并在表内明示实际 n。后期起点由 `late_phase_start_minute` 控制，当前为 25；后期统计只纳入实际达到该分钟的比赛，伤害和承伤以实际 25+ 分钟数归一化。

公开时间线没有完整坐标轨迹，不能可靠还原持续站位；“目标选择”也只能用团战首个阵亡、击杀/助攻关系等代理变量表示。版本号保留在每一行，正式研究应按大版本或补丁分层，避免版本变化污染英雄基准。

## 研究口径建议

当前 `collect` 使用 League-EXP 分页枚举 Diamond 四个小段，再合并 Master/Grandmaster/Challenger 梯队，每人默认最近 20 场单双排。这里的总体定义是“采样时 D4+ 的玩家”，不是“十名参与者平均段位 D4+ 的对局”。后者需要补查每局十人的当前段位，既会显著放大请求量，也无法还原历史比赛当时段位。研究报告应明确段位是采样时快照。

完整总体可能产生数万至数十万次请求。个人开发 Key 的限流和过期时间通常不足以一次跑完；建议先用 `--max-diamond-pages 1 --players 50` 做试采，再用 Production Key 跑完整总体。缓存和 JSONL 断点可避免重复请求与数据丢失。

采集器会复用同一场比赛：一次取得 Match-v5 与 Timeline-v5 后，同时为其中所有已枚举的 D4+ 参与者生成记录；当某位玩家已有 20 条记录后自动跳过。这不会改变“玩家—单局”的分析单位，但能显著减少高分段玩家互相匹配造成的重复 API 请求。

## 分钟级地图复盘

每次采集还会在 `data/replays/` 生成匿名 replay JSON。它包含从第 0 分钟到比赛结束的每个整数分钟槽位，并保证每个槽位固定列出 10 名参与者；坐标来自该分钟最新的 Riot Timeline 帧，不做插值。记录同时包括等级、金币、补刀以及该分钟的击杀、史诗资源、建筑和视野事件。

网页中的“单局复盘”模块使用同一数据结构，支持十人动态地图、时间轴播放、玩家选择、事件提示和基于队友距离/持有金币/资源事件的规则型诊断。`assets/demo-replay.js` 是从缓存的真实 OCE 排位比赛生成并去除账号标识的演示数据；可运行 `python tools/build_demo_replay.py` 重新生成。

每个英雄-位置-指标独立应用 Tukey `1.5 × IQR` 规则，再输出稳健中位数与分位区间。小样本模型仅用于管线验证；正式报告建议每个英雄-位置至少 30–50 局，并同时报告 `n_raw` 与 `n_clean`。
