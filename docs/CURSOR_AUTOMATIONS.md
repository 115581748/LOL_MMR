# Cursor 自主维护配置

仓库侧规则已放在根目录 `AGENTS.md` 和 `.cursor/rules/autonomous-improvement.mdc`。Cursor 账号中的 Automation 仍需在其控制台创建；建议先运行一周，只使用一个每日维护任务和一个每周审计任务，不允许自动合并。

## 每日维护

- 名称：`LOL High Rank Model Daily Maintenance`
- 计划：每天一次，建议本地时间 03:00
- 结果：独立分支或可 review 的 PR，不合并 `main`

提示词：

```text
Act as the autonomous maintenance engineer for this repository.

Read AGENTS.md and all applicable Cursor project rules first. Inspect the
repository and select the single highest-value small improvement that can be
safely completed during this run.

Check available evidence including failing tests or CI, runtime errors, stale
or duplicate Riot data, incomplete Timeline replays, API rate-limit and retry
failures, baseline sample health, TODO/FIXME items, weak error handling,
important missing tests, measurable performance bottlenecks, recent
regressions, obvious player-facing usability problems, issues and PR feedback.

Rank candidates by player impact, correctness/reliability impact, evidence
strength, regression risk and implementation cost. Implement only one item
unless multiple changes are inseparable.

Preserve the repository's metric definitions and evidence labels. Never expose
secrets, modify production credentials, delete production data, weaken tests,
change success metrics, merge main, or perform a speculative rewrite.

Run all relevant tests, compile checks and build checks. Add or update tests
where appropriate. If no change is clearly justified, make no code changes and
produce an inspection report.

End with: problem, evidence, change, tests/results, risk, and follow-up. Record
only durable non-secret lessons useful to future runs.
```

## 每周产品与工程审计

- 名称：`LOL High Rank Model Weekly Review`
- 计划：每周一次，建议周日 04:00
- 默认行为：只审计和提议，不直接写代码

提示词：

```text
Perform a weekly product, data and engineering review of this repository.
Read AGENTS.md and all applicable project rules. Do not immediately write code.

Review the last seven days of changes and available issues, PRs, CI, tests,
logs and data outputs. Assess data freshness, duplicate rate, Riot API success
rate, Timeline coverage, baseline sample health, detector explainability,
desktop runtime errors, EXE build reliability, UI clarity, recurring failures,
technical debt and unnecessary complexity.

Propose the five highest-value improvements for the next week. For each give:
problem, evidence, expected player value, engineering effort, risk, and a
measurable success criterion.

Only implement an item when it is both clearly small enough to finish safely
and obviously more valuable than a proposal. Otherwise leave the repository
unchanged and produce the review.
```

## 建议追踪的目标指标

- 最近一次成功采集距当前的时间
- Riot 请求成功率、429 次数和重试后成功率
- matchId 重复率与去重后样本数
- 拥有有效 Timeline 的本地玩家比赛比例
- 英雄 × 位置 × 阶段基准的样本覆盖率
- 原因分析中“证据不足”的比例及误报复核结果
- 单元测试通过率、EXE 构建成功率和启动失败次数
- 刷新耗时、复盘切换耗时和用户报告问题数

在这些指标没有可靠采集方式之前，Automation 不应声称自己优化了它们。
