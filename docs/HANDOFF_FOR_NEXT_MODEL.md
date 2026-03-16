# Handoff For Next Model

本文件给下一个模型/开发者快速接手使用。

## 0. 先读顺序（必须）
1. `docs/HANDOFF_FOR_NEXT_MODEL.md`（本文件）
2. `docs/agent_orchestration_playbook.md`
3. `docs/agent_progress_log.md`

## 1. 本项目当前核心目标
- 准确度优先于速度。
- command 高置信任务要快、要准，不走多轮模型。
- info 任务要稳定输出，不允许空回复。
- 低置信任务仍走 agent，保留泛化能力。

## 2. 当前执行策略（摘要）
- 原子能力方向：`search` 是原子，YouTube/Bilibili/Web 是 provider。
- 路由方向：`route + confidence` 门控（高置信直达，低置信回退 agent）。
- 编排方向：info 走两阶段（planner/execute/responder）。
- 记录方向：所有任务必须写入 progress log 并附指标前后对比。

## 3. M1/M2 的硬验收标准
- command P95 < 2s
- info P95 < 6s
- 空回复率 < 1%
- 高置信误路由率 < 3%
- 任何提速不得降低正确率

## 4. 禁止事项（必须遵守）
- 禁止写特定人名/口头词硬编码规则。
- 禁止无 benchmark 对比就宣称优化完成。
- 禁止把所有任务都硬编码直达（会破坏泛化）。
- 禁止在 command 路径开启 memory recall。

## 5. 开始工作前的最小检查
- 查看当前状态：`docs/agent_progress_log.md`
- 确认待办起点：M4-1（纠错后二跳命中率基准）
- 运行基础回归：`pytest -q`
- 运行检索基准：`python scripts/search_quality_benchmark.py --mock`
- 运行天气 provider 基准：`python scripts/weather_provider_benchmark.py`

## 6. 推荐运行参数（调试）
- `KAGE_LOG_TS=1`：每行日志带时间
- `KAGE_TRACE=1`：输出阶段耗时与工具链路

## 7. 本轮已达成共识（不可反转）
- `search` 是原子操作；平台检索是 provider。
- "能原子就原子，能流程就流程，剩余不确定性才交给 agent"。
- 文档化与进度记录是一等公民，必须持续更新。

## 8. 当前实现快照（2026-02-11）
- 路由策略：三层门控已落地（高置信直达 / 中置信确认 / 低置信回退 agent）。
- 连续对话：支持 `不是这个，是...` 的纠错闭环；视频候选未命中时优先提示纠错而非硬返回。
- 性能门禁：E2E 已采用 correctness + latency 双门禁（weather/video/system 各自 SLO）。
- 天气链路：默认并发双源 `open_meteo + metno`，谁先返回用谁；`wttr` 仅作为末级兜底；含天气缓存与坐标缓存。
- 视频链路：快路径保留用户原句检索，支持 5 分钟 query 级缓存，返回包含频道提示。
- 基准结果（最近一次）：`weather=534ms`，`video=854ms`，`system=54.6ms`，双门禁 100%。

## 9. 现阶段思路（继续推进）
- 先保证首轮高概率命中；不确定时用确认机制减少误操作，不强行猜测。
- 把“纠错后的二跳命中率”变成正式指标（而不只看单轮命中率）。
- 保持泛化：禁止按具体人名/口误做硬编码；规则只抽象到意图层。

## 10. 剩余任务（按优先级）
1) M4-2 - 连续对话状态机收敛（高优）
- 将 `pending_action` 升级为强类型状态：`confirm_command` / `video_disambiguation` / `correction_retry`。
- 统一顺序：每轮先处理 pending，再做 route；避免纠错句被当普通查询。

2) M4-3 - 结果“有证据再回复”机制（高优）
- 在视频/信息检索回复前生成 `selection_reason`（实体命中、频道命中、来源命中）。
- 证据不足时走澄清，不直接报单候选。

3) M4-4 - 二跳纠错样本扩展（中优）
- 不只视频：扩展到 command/info/chat 的“首轮失败 -> 纠错 -> 二跳命中”任务集。

4) M4-5 - 观测与告警（中优）
- 输出 `second_turn_grounded_rate`、`fallback_rate`、`provider_win_rate`。
- 为天气 provider 长期波动增加周级统计。

## 11. 标准测试流程（必须执行）
1. 语法与回归
- `python -m py_compile core/server.py scripts/kage_e2e_benchmark.py`
- `pytest -q`

2. Provider 基准（天气）
- `python scripts/weather_provider_benchmark.py`
- 检查 `docs/benchmarks/latest_weather_provider_benchmark.json`

3. E2E 双门禁 + 二跳纠错
- 启动（text-only，避免语音监听）：
  - `KAGE_TEXT_ONLY=1 KAGE_BENCH_TEXT_ONLY=1 uvicorn core.server:app --host 127.0.0.1 --port 12346`
- 跑基准：
  - `python scripts/kage_e2e_benchmark.py --uri ws://127.0.0.1:12346/ws --include-system`
- 检查输出文件：
  - `docs/benchmarks/latest_kage_e2e_benchmark.json`
  - 重点看：`pass_rate`、`slo_rate`、`correction_success_rate`

4. 进程清理校验（必须）
- `pgrep -fl "python -m core.server|uvicorn core.server:app"`
- 若有残留：`pkill -f "python -m core.server|uvicorn core.server:app"`
