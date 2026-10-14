# T06 触发源①：重要日期与提醒

- 日期：2026-10-14
- 执行者：AI 助手（由 wenbo 领取）
- 父提交：`ecda4b2`
- 环境：Linux 云端容器，Python 3.13.16
- 状态：完成

## 目标

用户告诉过 Kage 的重要日期（生日、纪念日、截止日期）在前一天和当天被主动提醒。

## 计划

1. 触发源接口 `async collect(now) -> list[通知]`，实现 `ImportantDateSource`。
2. Heartbeat 支持 `sources`，并按 `dedup_seconds` 去重。
3. 服务端接入 MemoryProfile。

## 过程记录

| # | 做了什么 | 改动文件 | 怎么验证 |
|---|---|---|---|
| 1 | **发现计划外缺口**：`MemoryProfile.add_important_date()` 在全仓库没有任何调用者（记忆抽取只写饮食/音乐/作息偏好），即 `important_dates` 永远为空，只做读取侧的提醒没有意义 | — | `grep -rn important_dates core` |
| 2 | 新增模型工具 `remember_date(date, event, reminder?, repeat_yearly?)`：校验 `YYYY-MM-DD` / `MM-DD`（含闰日、非法日期）后写入 MemoryProfile；由服务端在拿到 MemoryProfile 后注册（安全等级 SAFE，只写用户档案） | `core/proactive_sources.py`（新建）、`core/server.py` | 工具单测 |
| 3 | 工具可见性：新增 `reminders` 分组，关键词"提醒/生日/纪念日/记得/别忘/截止/deadline/remind"命中时可见；新增 `SERVER_SLOTS`（服务端运行时注册的工具），审计测试据此不把它当"幽灵工具" | `core/tool_visibility.py`、`tests/test_tool_visibility.py` | 可见性测试 |
| 4 | `ImportantDateSource`：一次性日期只在当天或之前生效；`MM-DD` 每年重复（跨年、闰日在非闰年跳过）；同一次发生最多提醒两次（前一天、当天），`source` 形如 `date:<事件>:<日期>:tomorrow`，`dedup_seconds`=2 天 | `core/proactive_sources.py` | 日期单测 |
| 5 | Heartbeat `sources` 参数：`tick()` 合并各触发源结果；单个触发源异常写错误日志不影响其他；带 `dedup_seconds` 的通知若同来源已在窗口内送达则跳过 | `core/heartbeat.py` | 重复运行只送达一次 |
| 6 | 服务端构造 Heartbeat 时 `sources=[ImportantDateSource(lambda: memory_profile)]` | `core/server.py` | 冒烟：桩掉 pyaudio/funasr 等 macOS 依赖后构造 `KageServer`，确认工具已注册、1 个触发源、策略 2 条/小时、免打扰 23:00–08:00 |

## 验证结果

```
python -m pytest -q tests/test_proactive_sources.py tests/test_tool_visibility.py tests/test_heartbeat.py tests/test_prompt_builder.py
66 passed

python -m pytest -q --ignore=tests/test_round14_audio.py --timeout=90
3 failed, 1018 passed, 5 skipped, 1 xfailed, 8 subtests passed
```

## 偏离计划

- 增加了计划外的 `remember_date` 工具与可见性分组（见过程 #1，否则功能不可用）。
- 计划写在 `core/server.py` 把 profile 传给 Heartbeat；实际通过触发源闭包传入，Heartbeat 本身不依赖 MemoryProfile。

## 遗留与后续

- 需要在 Mac 上用真实本地模型验证：说"下周三是我妈生日，记得提醒我"时模型是否会调用 `remember_date` 并换算出正确日期（相对日期换算依赖模型知道今天日期，`get_time` 在 CORE 中可用）。
- 记忆抽取器（`core/memory_extractor.py`）也可以自动识别日期，目前未做。
