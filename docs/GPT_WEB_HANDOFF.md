# 给 GPT 网页版的项目交接说明

`LOLHighRankComparator-GPT-source.zip` 是与 Windows EXE 同版本的可读源码包。GPT 网页版不能运行或反编译本项目的 `.exe`，因此应上传这个 ZIP，而不是上传 EXE。

## 建议提问方式

上传 ZIP 后可以直接说：

```text
这是“峡谷天平”Windows 赛后复盘程序的可读源码包。请先阅读
GPT_WEB_HANDOFF.md、AGENTS.md、README.md 和 desktop/lol_high_rank_comparator.py，
再根据我的要求分析或修改。保持 Riot Timeline 精度标签、英雄×位置基准匹配、
25 分钟指标口径，以及“事实/估计/候选因果”的边界。不要索要或输出 Riot API Key。
```

## 关键入口

- `desktop/lol_high_rank_comparator.py`：Tkinter 桌面应用、复盘、原因证据图与 API 自动刷新。
- `riot_model/`：Riot 数据采集、特征、建模与命令行代码。
- `tests/`：关键口径与桌面辅助函数测试。
- `config/model-parameters.json`：参数化模型定义。
- `desktop/LOLHighRankComparator.spec`：Windows EXE 打包配置。
- `AGENTS.md`：项目不变量、安全规则与验证要求。
- `docs/CURSOR_AUTOMATIONS.md`：保守的每日维护和每周审计配置。

## 当前原因分析模型

“原因”图层以一次己方丢龙或先锋为结果，回溯 90 秒并生成：

1. 可验证事实：目标归属、阵亡、购买、视野动作与跨图资源事件。
2. 分钟快照估计：目标区人数、玩家距离与团队经济。
3. 候选原因：只使用 `MAY_CONTRIBUTE_TO`，同时保留证据 ID、来源和置信度。
4. 替代解释：例如丢目标后 60 秒内取得塔或其他史诗资源。
5. 证据不足：没有足够上游证据时明确拒绝生成主要原因。

该结构可在后续作为大模型的输入，但大模型只能解释已有证据，不能补造 Riot API 没有提供的事件。

团战同样不是 Riot 原始事件。程序将至少三次英雄击杀、相邻间隔不超过 15 秒的序列聚类为 `DERIVED_TEAMFIGHT`，保留原始击杀时间戳、参与者、双方击杀比、位置、置信度和规则来源，并可作为丢龙/先锋的上游证据。

地图死亡态由精确的 `CHAMPION_KILL` 时间戳和地点触发，地图与 TAB 头像都会灰化并打叉。普通 Timeline 没有精确复活事件，`estimated_respawn_seconds` 只生成明确标注为“预计”的界面倒计时，不得作为观测事实或模型特征。

## 不包含的内容

交接包故意排除：

- Riot API Key、GitHub token 和其他凭据；
- `%LOCALAPPDATA%` 下的本地玩家缓存与完整比赛 Timeline；
- 大型原始 CSV、缓存、构建目录和已有 EXE；
- `.git`、虚拟环境及临时文件。

需要复现玩家案例时，应由用户在本地 EXE 中输入自己的 Riot ID 与有效 Development Key，不应把密钥放进对话或源码包。
