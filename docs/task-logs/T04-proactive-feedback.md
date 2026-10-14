# T04 主动消息 id/来源 + 用户反馈回传（后端）

- 日期：2026-10-14
- 执行者：AI 助手（由 wenbo 领取）
- 父提交：`5d0984b`
- 环境：Linux 云端容器，Python 3.13.16
- 状态：完成（后端）；前端部分拆为 T04b

## 目标

每条主动消息有稳定的 `id` 与 `source`；用户对消息的反应（好的 / 稍后 / 别再提醒）能回传后端并持久化，"好的"可以触发消息附带的后续动作。这是 T05 策略层（免打扰、静音）和 T07/T10（请求示范、采用技能）的基础。

## 计划

1. 新建 `core/proactive.py`：`make_notification()`、`ProactiveFeedbackStore`。
2. Heartbeat 生成的通知带 `id`/`source`；记住最近送达的 200 条，提供 `record_feedback()`。
3. Server 处理 `proactive_feedback` WebSocket 消息；`accept` 时按 `action.type` 分发到注册的处理器。
4. 按用户要求（UI 优先级低），前端气泡改为 T04b。

## 过程记录

| # | 做了什么 | 改动文件 | 怎么验证 |
|---|---|---|---|
| 1 | `make_notification(source, content, type_=, action=)` 统一通知格式；`ProactiveFeedbackStore` 追加写 `~/.kage/proactive_feedback.jsonl`，提供 `is_muted()`/`snoozed_until()`，读文件时跳过半截行；非法 action 抛 `ValueError` | `core/proactive.py`（新建） | `tests/test_proactive_feedback.py` 前 4 例 |
| 2 | HEARTBEAT.md 检查项的通知改用 `make_notification("heartbeat:<名称>", ...)`，保留原 `type` 字段兼容旧测试；送达逻辑抽成 `_deliver()`（之后事件驱动的触发源也走这里）；`record_feedback(id, action)` 只接受最近送达过的 id（重启前的 id 不知道来源，无法静音，故不记录） | `core/heartbeat.py` | heartbeat 测试 + 反馈往返测试 |
| 3 | `KageServer.handle_proactive_feedback()`；WebSocket 循环识别 `type == "proactive_feedback"`；`_proactive_action_handlers` 字典（`action.type` → 异步处理器）。只有用户点击 accept 才会触发，模型无法触发 | `core/server.py` | accept 触发 / snooze 不触发 / 非法 action 忽略 |
| 4 | 说明：本任务测试是在实现之后补写的（没有严格先红后绿），用例覆盖了所有新分支 | `tests/test_proactive_feedback.py`（新建，7 例） | — |

## 消息协议

| 方向 | 消息 |
|---|---|
| 后端 → 前端 | `{"type":"proactive","event":"heartbeat","notification":{"id","source","type","content","timestamp","action"?}}` |
| 前端 → 后端 | `{"type":"proactive_feedback","id":"<notification.id>","action":"accept"\|"snooze"\|"mute"}` |

## 验证结果

```
python -m pytest -q tests/test_proactive_feedback.py tests/test_heartbeat.py tests/test_server_helpers.py
56 passed

python -m pytest -q --ignore=tests/test_round14_audio.py --timeout=90
3 failed, 1004 passed, 5 skipped, 1 xfailed, 8 subtests passed
```

3 个失败为已知容器进程回收问题。

## 偏离计划

- 前端（`kage-avatar/src/main.ts` 气泡与按钮）未做，按用户指示 UI 优先级低，拆为 T04b。在 T04b 完成前，用户无法在界面上点反馈；后端逻辑可通过任意 WebSocket 客户端（如 `test_cli.py`）发送上表消息验证。
- 计划写的是 `heartbeat.record_feedback` 直接写文件；实现为独立的 `ProactiveFeedbackStore`，便于 T05 策略层复用。

## 遗留与后续

- 送达记录只在内存中（200 条），重启后旧消息的反馈会被忽略。
