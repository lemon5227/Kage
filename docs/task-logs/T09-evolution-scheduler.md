# T09 空闲时自演化作业（EvolutionScheduler）

- 日期：2026-10-14
- 执行者：AI 助手（由 wenbo 领取）
- 父提交：`87614e4`
- 环境：Linux 云端容器（无 Docker），Python 3.13.16
- 状态：完成（工程）；真实云生成需在 Mac 上跑

## 目标

日常运行的 Kage 在用户空闲、且最近确实有失败时，自动在后台跑一轮"生成候选 → 父子对比 → 晋级判定"，不再只能手动跑脚本。只记录结果，不自动安装。

## 计划

1. 配置 `evolution` 段，**默认关闭**。
2. `EvolutionScheduler`：判定是否运行、后台子进程运行、记录结果。
3. 作为 Heartbeat 触发源接入；浏览器任务失败/未确认时记一笔"待学习失败"。

## 过程记录

| # | 做了什么 | 改动文件 | 怎么验证 |
|---|---|---|---|
| 1 | 运行条件（全部满足）：`auto=true`；没有正在跑的作业；用户空闲 ≥ `idle_minutes`；上次运行后新增失败 ≥ `min_new_failures`；今天已完成次数 < `max_runs_per_day`；今天已报告费用 < `daily_budget_usd`。`should_run()` 返回 (是否, 原因) | `core/evolution/scheduler.py`（新建） | 单测逐条覆盖 |
| 2 | 运行方式：为每次运行复制一份 search 配置到 `~/.kage/evolution/runs/<run_id>/`，改写 `output_dir`，并把 `budget.max_cost_usd` 压到"今日剩余预算"以下；用子进程执行 `kage_evolve.py search --config ... --provider ... --runner ...`（可超时杀掉，不阻塞事件循环，不新写第二套评分）；结束后读 report.json，追加写 `~/.kage/evolution/scheduler.jsonl`：`started`（含触发它的失败列表）与 `finished`（返回码、错误、停止原因、费用、是否晋级、晋级候选、报告路径） | 同上 | 单测（假 launcher）+ 1 个真实子进程端到端（fixture + process runner） |
| 3 | 失败材料：`note_failure(job)` 写入 `~/.kage/evolution/scheduler_state.json`（最多 50 条），一次运行开始时清空 | 同上 | 单测 |
| 4 | 服务端：构造 `self.evolution_scheduler` 并作为 Heartbeat 第二个触发源；浏览器实验任务以 failed/unknown 结束时调用 `note_failure` | `core/server.py` | 冒烟：构造 KageServer，触发源为 [ImportantDateSource, EvolutionScheduler]，`should_run()` = (False, 'disabled') |
| 5 | 默认配置：`auto=false`、空闲 30 分钟、每天 1 次、每天 $0.05、provider=live、runner=docker、`eval/evolution/pilot.json`、超时 1800 秒 | `config/settings.json` | JSON 校验 |

## 验证结果

```
python -m pytest -q tests/test_evolution_scheduler.py
7 passed

python -m pytest -q --ignore=tests/test_round14_audio.py --timeout=90
3 failed, 1031 passed, 5 skipped, 1 xfailed, 8 subtests passed
```

## 偏离计划

- 计划写"存在新的失败 episode（`ExperienceArchive.retrieve`）"。日常服务没有接 ExperienceArchive（它属于实验 journal），因此改为服务端在浏览器任务失败时直接记录到调度器状态文件，效果是"有真实失败才练习"。
- 通过 Heartbeat 触发源接口接入，而非在 server 里另写定时逻辑。

## 已知局限（必须如实说明）

- **练习内容与失败内容还没有对应**：触发练习的是浏览器任务失败，但练习跑的是配置的 search 套件（默认 `eval/evolution/pilot.json`，文件/代码技能任务）。"根据失败类型决定练什么、改什么"正是研究线 T17（E4/FCER）的内容，本任务只建立了"失败 → 空闲时自动练习 → 记录"的骨架。
- 浏览器工作流的生成（`core/computer_use/skill_mutator.py`）目前只在实验脚本里，没有接入调度器；可作为后续任务把 `search_config` 扩展为浏览器 transfer 协议。
- **云端做不了、需要在 Mac 上做**：真实运行需要 `evolution.auto=true`、云模型 key（`model.cloud_api`）和 Docker 镜像 `kage-evolution:local`（`docker build -t kage-evolution:local sandbox/evolution`）。在 Mac 上开启后，空闲 30 分钟且出现过浏览器任务失败时，`~/.kage/evolution/scheduler.jsonl` 应出现 started/finished 两行。
