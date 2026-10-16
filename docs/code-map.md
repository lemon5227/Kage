# Kage 代码地图（W0-8，2026-10-14）

给接手模型的导航：每个模块做什么、谁调用谁、哪些和自进化主线有关、哪些已暂停。行数为 2026-10-14 合并 origin/main 后的数字。主线 = 任务书 v2 的 stream 学习流（W1–W5）。

## 1. 两条入口

| 入口 | 走向 | 与主线关系 |
|---|---|---|
| `main.py`（85）→ `core/server.py`（2137） | 桌面陪伴产品：FastAPI + WebSocket，语音/Live2D/heartbeat/后台任务 | 交互外壳；W3-4 交互消息层接这里 |
| `scripts/experiments/stream_run.py`（185） | 实验：学生 4B（llama-server）+ DeepSeek 教师，跑 A0/A4/A5 学习流 | **主线** |
| `scripts/kage_evolve.py`（440） | EvoLab CLI：E1 技能搜索 `search`、smoke 等 | 被 T09 调度器以子进程调用 |
| `scripts/kage_recover.py`（222） | G1 持久恢复单入口 | 历史 G1；保留作回归 |

## 2. 共享执行核：AgenticLoop

`core/agentic_loop.py`（1708）是产品和实验共用的多步工具循环。

- 调用方：`core/server.py`、`core/realtime_lane.py`、`core/realtime_handlers.py`、`core/pending_handlers.py`；实验经 `core/evolution/agent_provider.KageChainProvider`。
- 依赖：`prompt_builder.PromptBuilder`（路由分类 + 工具呈现）、`tool_executor.ToolExecutor`（解析、安全分级、审计）、`tool_registry.ToolRegistry`、`model_provider`。
- 类属性是实验旋钮：`MAX_STEPS`、`TOOL_MAX_TOKENS`（产品默认 300；`stream.chain_runner` 设 1024）。
- 恢复钩子（10-14 新增上下文和 `request_help`）：每次结束时调用候选的 `core/evolvable/recovery.py` 策略。
- **陪伴产品逻辑（W0-9a 已查）**：天气兜底、info 路由 `smart_search` 兜底、command 路由推断 `system_control`、`skills_find_remote`→`skills_install`、`skills_save_local` 自动保存。实验路径 `prune_tools=False`，只注册工作区工具（read/write/list + skill_search/skill_call）；stream 任务路由只落在 command/chat，命令推断不命中，因此这些分支在实验中不会触发。唯一泄漏是 300 token 工具轮上限，已改。路由仍影响提示词中的少量提示文字，各臂一致。

## 3. 自进化核心 `core/evolution/`

调用关系（→ 表示 import/调用）：

```
stream_run.py ─→ stream.StreamLearner ─→ competence.CompetenceModel
                     │                 └→ TeacherCache（教师按题缓存）
                     └→ stream.chain_runner ─→ runner.EvolutionRunner ─→ agent_provider.KageChainProvider ─→ AgenticLoop
                                              │                       └→ skills.SkillCatalog ─→ sandbox.{Process,Docker}SkillRunner
                                              └→ runner.Evaluator（外部评分，completion.py 行为检查）
stream_run.propose ─→ mutator.Mutator（教师→不可变技能 bundle）─→ budget.BudgetTracker ← teacher_budget.global_teacher_budget（$1）
search.py（E1）─→ mutator + promotion.Promoter ─→ journal（record_lineage, T14）
recovery_loop.py（G1）─→ recovery_mutator ─→ bundle（恢复源码在沙箱执行）─→ promotion
scheduler.py（T09，空闲触发，默认关）─→ 子进程 kage_evolve.py search
```

| 模块 | 行 | 作用 | 主线状态 |
|---|---|---|---|
| `contracts.py` | 72 | `Candidate`/`RunSpec`/`RunResult`/`EvolutionEvent` | 核心 |
| `runner.py` | 671 | `EvolutionRunner` 隔离执行 + `Evaluator` 外部评分 | 核心；**评分器不可改** |
| `completion.py` | 61 | 外部完成检查 | 核心；不可改 |
| `agent_provider.py` | 615 | 真实 Kage 链（`KageChainProvider`）、工作区注册表、调用计量 | 核心 |
| `skills.py` | 105 | 候选私有技能目录，`skill_search`/`skill_call` 两个工具 | 核心 |
| `sandbox.py` | 133 | 技能在子进程/ARM64 Docker 执行 | 核心 |
| `mutator.py` | 190 | 教师提案→不可变技能 bundle，格式修复，记账 | 核心 |
| `budget.py` | 274 | 预留/结算式预算 | 核心 |
| `teacher_budget.py` | 36 | 全局 $1 教师账本（`~/.config/kage/teachers/ledger.sqlite`） | 核心；所有云调用必须走它 |
| `journal.py` | 273 | SQLite 实验日志 + T14 谱系 | 核心；W4-4 数据源 |
| `stream.py` | 560 | 学习流各臂（A0…A6）、教师缓存、`chain_runner`（含相关性门控） | **主线** |
| `relevance.py` | 220 | TF-IDF 相关性、自动归族、技能来源与 L2 选用策略 | **主线** |
| `l2_selection.py` | 150 | A6 架构师演化技能选用策略（验证晋级） | **主线** |
| `stream_tasks.py` | 157 | 任务族生成器（F3 + 只读负例），清单哈希 | **主线**；W1-2…7 在此扩充 |
| `competence.py` | 167 | 能力自评：求教决策、练习目标、技能状态 | **主线** |
| `promotion.py` | 132 | 父子配对比较、原子激活 | E1/G1 用；W4 复用 |
| `search.py` | 170 | E1 有界技能搜索 | T09 调度器调用 |
| `recovery_loop.py` / `recovery_mutator.py` / `bundle.py` | 259/57/70 | G1 恢复策略学习 | 历史 G1；W3-2 改 `core/evolvable/recovery.py` |
| `retries.py` | 54 | 等预算本地重试 | W2-3 A1 臂复用 |
| `archive.py` | 108 | 经验档案索引 | W2-4 A3 臂复用 |
| `takeover.py` | 111 | 任务级教师接管 | C4 历史 |
| `progress.py` / `artifacts.py` / `fixtures.py` | 89/19/52 | 停滞检测、原子写、合成演示 provider | 支撑 |
| `scheduler.py` | 238 | T09 空闲自演化（默认 `auto:false`） | W4-1 的触发壳；**现按自身 daily_budget 花钱，不走 $1 账本，接入前须改** |

## 4. 主动交互（T03–T11，origin/main 合入）

| 模块 | 作用 |
|---|---|
| `core/heartbeat.py`（268） | 周期 tick，`on_notifications` 回调送达（T03） |
| `core/proactive.py`（163） | 通知 id/来源、反馈、免打扰/频率上限/静音（T04/T05） |
| `core/proactive_sources.py`（140） | 触发源：重要日期（T06）等 |
| `core/skill_adoption.py`（146） | 晋级技能经用户同意进入日常 ToolRegistry（T10） |
| `core/server.py` | `_deliver_proactive_notifications`、`proactive_feedback` 消息、调度器汇报（T11） |

W3-4 交互消息层应直接复用这些，不另建队列。

## 5. 电脑操作 `core/computer_use/`

浏览器（DOM 适配器、示范录制/编译、任务服务与 worker、迁移协议）：C1.1/C4.5 历史实验，P4 才可能接入学习流。`native_ax.py`（438）/`native_model.py`（388）：macOS AX/TextEdit，**暂停**（roadmap §7）。

## 6. 产品外围（与主线无关）

记忆：`memory.py`（1082）、`memory_extractor.py`、`memory_llm_extractor.py`、`memory_profile.py`、`identity_store.py`。
语音/外观：`ears.py`、`mouth.py`、`speech_engine.py`、`audio_orchestrator.py`、`avatar_animation.py`、`kage-avatar/`（Tauri+Live2D）。
路由与对话：`route_classifier.py`、`router.py`、`intent_router.py`、`dialog_state_machine.py`、`chat_polisher.py`、`response_sanitizer.py`、`pending_handlers.py`、`realtime_*`。
模型：`model_provider.py`、`anthropic_provider.py`、`hybrid_model_provider.py`、`model_broker.py`、`local_model_runtime.py`、`credential_helpers.py`、`provider_test.py`。
工具：`tool_registry.py`（784）、`tool_executor.py`（769）、`tool_visibility.py`、`tools/*`（文件、网页、技能、快捷指令、记忆）、`system_control.py`、`media_controller.py`、`weather_service.py`、`mcp_client.py`、`undo_log.py`。
后台：`background_lane.py`、`background_worker.py`、`job_*`、`session_*`、`tray.py`、`routes/*`（HTTP API）。

## 7. 脚本与数据

- `scripts/experiments/`：主线只用 `stream_run.py` 和它导入的 `task_suite.RecordedLocalProvider`、`native_model_pilot.LocalService`（W0-10 要把后者抽到 `local_service.py`）。其余为历史实验：C2 `task_suite.py`、C4 `learning_ablation.py`/`skill_learning.py`、E3 `recovery_evolution.py`、G2 `recovery_baseline.py`、浏览器 `browser_*.py`（10 个）、原生 `native_*.py`（9 个，约 1900 行，暂停）。`flexible_output_probe.py` 是 C4 当年对 300 token 上限的补充对照。
- `scripts/` 根目录：产品基准与冒烟脚本（ASR、路由、天气、搜索、e2e），与主线无关。
- `eval/computer-use/*.json`：历史冻结套件（files-v1、learning-*、recovery-*、browser-*、g2）。stream 清单将冻结在 `eval/stream_v1/`（W1-9）。
- `tests/`：160 个文件；stream 相关 `test_stream_{tasks,learner,chain_integration,run_cap}.py`、`test_competence.py`、`test_teacher_budget.py`、`test_recovery_context.py`。
- `artifacts/`（Git 忽略）：原始实验证据。G1/G2 在 c2-learning-loop worktree；E-0 在主目录 `artifacts/stream-slice/`。

## 8. 10/29 后精简候选（现在不做）

1. 从 `agentic_loop.py` 拆出陪伴产品逻辑（天气、info/command 兜底、远程技能安装、autosave）到产品层策略对象，循环只保留通用执行与恢复钩子。
2. `core/server.py`（2137 行）按领域拆分：WebSocket 会话、语音、主动交互、后台任务。
3. 归档历史实验脚本：`native_*`（W0-10 先做）、`browser_*` 中已结题的诊断脚本；`task_suite.RecordedLocalProvider` 移到 `core/evolution/`。
4. 路由三处重复（`route_classifier.py`、`router.py`、`intent_router.py`）合并。
5. `docs/` 根目录 40+ 历史日志/优化轮次文件移入 `docs/archive/`（与 T22 合并）。
6. 产品默认 `TOOL_MAX_TOKENS=300` 是否仍合适（陪伴回复短，但工具写文件会被截断）。
