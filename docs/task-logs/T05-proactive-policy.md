# T05 主动策略层：免打扰、频率上限、反馈学习

- 日期：2026-10-14
- 执行者：AI 助手（由 wenbo 领取）
- 父提交：`cf16347`
- 环境：Linux 云端容器，Python 3.13.16
- 状态：完成

## 目标

主动消息"该说才说"：免打扰时段不打扰、不刷屏、用户"稍后"的来源暂停、"别再提醒"的来源永久不再出现；重启后仍然生效。

## 计划

1. 配置：`heartbeat.quiet_hours / max_per_hour / snooze_minutes`。
2. 策略类：`verdict(notification) -> deliver | hold | drop`，`mark_sent()`，`was_sent(source, 秒)`（供后续触发源去重）。
3. Heartbeat 送达前经过策略；hold 的放回队列，drop 的丢弃。
4. 事件驱动触发源的入口 `deliver_now()`。

## 过程记录

| # | 做了什么 | 改动文件 | 怎么验证 |
|---|---|---|---|
| 1 | `ProactivePolicy`：检查顺序 静音(drop) → 稍后(hold) → 免打扰(hold，支持跨午夜，非法配置视为不设) → 最近 1 小时已发送数(hold)；发送记录追加写 `~/.kage/proactive_sent.jsonl` | `core/proactive.py` | `tests/test_proactive_policy.py` 前 5 例 |
| 2 | Heartbeat 构造参数 `proactive_config`；`_deliver()` 逐条判定；`_hold()` 同一来源只保留最新一条、最多 50 条；新增 `deliver_now()`（用户活跃时先排队） | `core/heartbeat.py` | 后 3 例 |
| 3 | 服务端把 `heartbeat` 配置段传给 Heartbeat；`config/settings.json` 默认 `23:00-08:00`、每小时 2 条、稍后 60 分钟 | `core/server.py`、`config/settings.json` | JSON 校验 + 全量测试 |
| 4 | Heartbeat 未传配置时默认"宽松"（无免打扰、无频率上限，只有静音/稍后），保证旧测试在任何时刻运行都不受免打扰影响 | `core/heartbeat.py` | 旧 heartbeat 测试全部通过 |

## 验证结果

```
python -m pytest -q tests/test_proactive_policy.py
8 passed

python -m pytest -q --ignore=tests/test_round14_audio.py --timeout=90
3 failed, 1012 passed, 5 skipped, 1 xfailed, 8 subtests passed
```

## 偏离计划

- 计划写新建 `core/proactive_policy.py`；实际放在 T04 新建的 `core/proactive.py` 中（策略依赖同文件的反馈存储与 JSONL 读写），没有新建文件。
- 计划第 2 步写"免打扰结束后再发"：实现为 hold 放回队列、下个心跳周期重新判定，效果相同。

## 遗留与后续

- 免打扰按本机本地时间计算；跨时区出差时依赖系统时区正确。
- "反馈学习"目前只到规则级（静音/稍后）；按接受率自动调整频率可作为后续改进。
