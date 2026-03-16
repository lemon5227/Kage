# Kage Agent Orchestration Playbook

本文件用于指导 Kage 在"准确度优先"前提下完成速度优化与泛化能力保留。
下一个模型/开发者无需重读全仓库，按本文件即可继续推进。

## 1. 背景与目标

### 1.1 当前痛点（基于真实 trace）
- 命令类（亮度/音量/Wi-Fi/蓝牙）常被多轮模型决策拖慢，典型 20-40s。
- 信息类（天气/视频）偶发空回复、结果不准、输出过长。
- 连续对话（"打开这个"、"第2个"）缺少统一引用机制。
- 命令场景不应做 memory recall，既增延迟也增噪声。

### 1.2 硬目标（SLO）
- 准确度优先于速度，任何提速不得降低正确率。
- `command` P95 < 2s。
- `info` P95 < 6s。
- 空回复率 < 1%。
- 高置信误路由率 < 3%。

## 2. 设计原则（Decision Rationale）

### 2.1 为什么不全走大模型
- 现场数据表明瓶颈主要在模型推理，不在工具执行。
- 确定性命令让模型反复推理会引入慢与误操作风险。
- 结论：高置信命令直达工具；低置信/复杂任务走 agent。

### 2.2 为什么 `search` 是原子操作
- YouTube/Bilibili/Web 只是检索 provider，不是能力本体。
- 能力本体是"统一检索 + 统一结果结构 + 可引用打开"。
- 结论：`search` 作为原子，provider 插件化。

### 2.3 为什么要 route + confidence
- 全直达会损伤泛化；全 agent 会慢且不稳定。
- 门控策略允许"高置信快路径 + 低置信泛化路径"并存。

### 2.4 为什么 command 禁用 memory recall
- 命令执行关注当前意图，通常不依赖长期语义记忆。
- recall 在 command 中多数是噪声与延迟来源。

### 2.5 为什么两阶段执行（planner/execute/responder）
- 拆分"工具决策"与"结果表达"可减少无效多轮。
- responder 失败时可回退结构化模板，避免 silent turn。

## 3. 目标架构

### 3.1 路由层
- 输出结构：`{route, confidence, reason, fallback_allowed}`
- route: `command | info | chat | agent`
- 策略：高置信直达；低置信回退通用 agent。

### 3.2 原子操作层（V1）

| 操作 | 用途 | 入参（核心） | 输出（核心） |
|---|---|---|---|
| `search` | 统一检索 | `query, source, sort, max_results, filters` | `items[], meta` |
| `fetch` | 抓取 URL 内容 | `url, format` | `content, status_code, final_url` |
| `extract` | 提取结构化字段 | `content, schema` | `data, confidence, missing_fields` |
| `open_url` | 打开链接 | `url` | `ok, opened_url` |
| `open_app` | 打开应用 | `app_name` | `ok, app_resolved` |
| `open_item` | 打开上一步结果项 | `index/ref_id` | `ok, target_url` |
| `system_control` | 系统控制 | `target, action, value?` | `ok, applied, message` |
| `system_status` | 系统状态读取 | `target` | `value, unit, timestamp` |
| `fs_search` | 文件检索 | `path, query, type` | `matches[]` |
| `fs_preview` | 变更预览 | `ops[]` | `diff_summary, risk` |
| `fs_apply` | 变更落地 | `ops[]` | `applied_count, details` |
| `fs_undo_last` | 最近一次回滚 | 无 | `ok, restored_items` |

### 3.3 Search Provider 插件
- `web`（必选）
- `youtube`（必选）
- `bilibili`（预留）
- `auto` 路径：意图优先 provider，失败回退 web。

### 3.4 会话层
- `last_action`: 最近可引用结果（用于"这个/第N个"）
- `pending_action`: 待澄清/待确认
- 历史窗口按 route 动态裁剪

## 4. 分阶段实施计划

### 实施状态快照（2026-02-11）
- M1: done（`search` 原子与 provider 抽象落地）。
- M2: done（route+confidence 门控、correctness 门禁、可观测性落地）。
- M3: in_progress（连续对话纠错已接入；正在补“纠错后二跳命中率”量化）。
- M4: pending（自动化回归门禁增强中）。

### M1: 能力抽象统一（先打地基）

#### 目标
- 定义 `search` 原子 schema（统一返回字段）
- 改造现有 `smart_search`/`web_fetch` 到统一结构
- 增加 provider 接口（先 web + youtube，bilibili 预留）

#### 任务清单（必须逐条记录）
- M1-1 定义 `search` 输入/输出 schema
- M1-2 定义 `items[]` 标准字段
- M1-3 适配 `smart_search` -> 统一结构
- M1-4 适配 `web_fetch` -> 统一结构
- M1-5 建立 provider 接口
- M1-6 实现 provider:web
- M1-7 实现 provider:youtube
- M1-8 预留 provider:bilibili
- M1-9 `open_item` 对接统一结果
- M1-10 单测/集成测补齐

#### 验收（DoD）
- 同一解析逻辑可消费不同 source 的结果。
- `open_item(index)` 可稳定打开目标项。
- schema/错误码统一。
- 测试通过并附 benchmark 初始基线。

### M2: 编排升级（速度 + 泛化平衡）

#### 目标
- 引入 route+confidence 门控
- command 高置信直达（禁 memory recall）
- info 两阶段（planner/execute/responder）
- 低置信任务继续走 agent

#### 任务清单
- M2-1 定义 route 输出结构
- M2-2 command 高置信直达
- M2-3 command 路径强制 recall off
- M2-4 info 两阶段执行
- M2-5 低置信 fallback agent
- M2-6 空回复兜底
- M2-7 trace 汇总字段
- M2-8 benchmark 脚本接入
- M2-9 system_status 校验命令正确性
- M2-10 指标回归对比

#### 验收（DoD）
- 命令类不再多轮模型。
- command P95 < 2s，info P95 < 6s。
- 空回复率 < 1%。
- 低置信任务仍具泛化完成能力。

### M3: 连续对话与指代
- `last_action` 标准化
- "这个/第N个"引用解析
- 歧义追问机制
- 验收：视频类连续 3 轮稳定完成

#### M3 当前实现补充
- 中置信 command 已实现“先确认再执行”（`confirm_inferred_command`）。
- 已支持纠错短语 `不是这个，是...` 并在同轮回退执行。
- 视频快路径在博主名不匹配时优先返回纠错提示。
- 下一步：把“纠错后二跳命中率”加入 benchmark 作为正式指标。

### M4: 回归与基准自动化
- benchmark 任务集（命令/天气/视频/泛化）
- 输出 route/tool_chain/耗时分解/成功率
- CI 阈值门禁
- 验收：每次改动自动产出前后对比

#### M4 近期重点
- 新增“二跳纠错任务集”（首轮给错候选 + 用户纠正 + 第二轮命中）。
- 为天气 provider 竞速增加长期统计（provider 胜率、超时率、回退率）。

#### M4 剩余实现（当前待办）
- M4-2: 连续对话状态机强类型化（pending 优先处理，去分支顺序耦合）。
- M4-3: 结果选择证据化（selection_reason）与证据不足澄清分支。
- M4-4: 将二跳纠错评测扩展到 command/info/chat，而不仅是视频。
- M4-5: 指标面板完善（second_turn_grounded_rate / fallback_rate / provider_win_rate）。

## 5. 记录与审计要求（必须遵守）

### 5.1 每条任务记录字段
- Task ID（如 M1-3）
- Date/Owner
- Change Summary
- Files Touched
- Decision Reason（为什么这么做）
- Tradeoff（牺牲了什么，换来什么）
- Risk
- Validation Commands
- Metrics Before/After
- Result
- Rollback Plan
- Next Step

### 5.2 禁止事项
- 禁止引入特定人名/口头词硬编码规则。
- 禁止无 benchmark 对比就宣称"优化完成"。
- 禁止为提速牺牲命令正确性。

## 6. 运行与验证建议
- 开启 trace: `KAGE_TRACE=1`
- 开启时间戳: `KAGE_LOG_TS=1`
- 建议在同一任务集上比较 before/after 指标。

### 6.1 标准验证命令（每次改动后）
- 语法检查：`python -m py_compile core/server.py scripts/kage_e2e_benchmark.py`
- 回归测试：`pytest -q`
- 天气 provider 基准：`python scripts/weather_provider_benchmark.py`
- E2E（text-only）：
  - `KAGE_TEXT_ONLY=1 KAGE_BENCH_TEXT_ONLY=1 uvicorn core.server:app --host 127.0.0.1 --port 12346`
  - `python scripts/kage_e2e_benchmark.py --uri ws://127.0.0.1:12346/ws --include-system`
- 结果文件检查：
  - `docs/benchmarks/latest_weather_provider_benchmark.json`
  - `docs/benchmarks/latest_kage_e2e_benchmark.json`
- 进程清理：`pgrep -fl "python -m core.server|uvicorn core.server:app"`

## 7. 参考实现启发（PicoClaw）

参考项目：`https://github.com/sipeed/picoclaw`

可借鉴的思路（保留泛化前提下提速）：
- 工具能力配置化：provider 可替换，接口保持稳定。
- 单一能力原子化：例如检索只暴露 `search`，由 provider 承担平台差异。
- 低资源优先策略：先走确定性工具链，再让模型负责表达和兜底。
- 可观测优先：每条链路都能看到耗时与结果质量。

本项目对应落地：
- `search` 统一 schema + provider 抽象（web/youtube/bilibili）。
- benchmark 持续记录 `pass_rate`、`avg_ms`，作为优化门禁。
