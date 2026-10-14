# T03 Heartbeat 主动通知真正送达用户

- 日期：2026-10-14
- 执行者：AI 助手（由 wenbo 领取）
- 父提交：`a2519b9`
- 环境：Linux 云端容器，Python 3.13.16
- 状态：完成

## 目标

Heartbeat 产生的通知能真正到达用户（WebSocket 事件 + 空闲时语音），作为"主动交互"的最小闭环。

## 计划

1. 测试先行：回调送达、用户活跃时排队、回调异常不终止循环、后台循环确实调用送达。
2. `Heartbeat` 增加 `on_notifications` 与 `_run_once()`。
3. `KageServer` 增加 `_deliver_proactive_notifications` 并在构造 Heartbeat 时传入。
4. 修正启动失败日志的格式串。

## 过程记录

| # | 做了什么 | 改动文件 | 怎么验证 |
|---|---|---|---|
| 1 | 复现：原 `_loop()` 执行 `await self.tick()` 后丢弃返回值；`get_queued_notifications()` 全仓库无调用者，因此 HEARTBEAT.md 中启用的检查项从未送达用户 | — | `grep -rn get_queued_notifications core` |
| 2 | 新增 `TestDelivery` 4 例（红：`unexpected keyword argument 'on_notifications'`） | `tests/test_heartbeat.py` | pytest |
| 3 | `__init__` 增加可选参数 `on_notifications`；新增 `_run_once()`：`tick()` 后把非空通知交给回调，回调异常写入 `heartbeat_error.log`（检查名 `deliver`），不抛出；`_loop()` 改为调用 `_run_once()` | `core/heartbeat.py` | heartbeat 测试 23 passed |
| 4 | 新增 3 个服务端测试（红） | `tests/test_server_helpers.py` | pytest |
| 5 | `KageServer._deliver_proactive_notifications`：每条通知发送 `{"type": "proactive", "event": "heartbeat", "notification": {...}}`；仅当前端已连接、UI 状态为 IDLE、非纯文本模式且内容非空时再语音播报（与后台任务完成通知的打扰规则一致）；构造 Heartbeat 时传入该方法 | `core/server.py` | 服务端测试通过 |
| 6 | `logger.warning("Heartbeat start failed: %s", exc_info=True)` 缺参数，改为 `logger.warning("Heartbeat start failed", exc_info=True)` | `core/server.py` | — |

## 送达规则

| 条件 | WebSocket `proactive` 事件 | 语音 |
|---|---|---|
| 用户 2 分钟内有输入 | 不发，进入队列，下个周期空闲时一起发 | 否 |
| 空闲 + 前端已连接 + UI=IDLE + 非纯文本模式 | 发 | 是（内容非空时） |
| 前端正在说话/思考，或纯文本模式，或未连接 | 发（未连接时 `send_message` 本身不发送） | 否 |

## 验证结果

```
python -m pytest -q tests/test_heartbeat.py tests/test_server_helpers.py
49 passed

python -m pytest -q --ignore=tests/test_round14_audio.py --timeout=90
3 failed, 997 passed, 5 skipped, 1 xfailed, 8 subtests passed
```

3 个失败为已知容器进程回收问题。

## 偏离计划

无。

## 遗留与后续

- 前端尚未处理 `proactive` 消息类型（目前只会在控制台忽略），由 T04 实现气泡与反馈。
- 通知目前没有稳定 `id`/`source` 字段，T04 加入。
- 现有心跳检查项只是把 HEARTBEAT.md 的描述原样发出，没有真正"检查"任何东西；真实触发源由 T06/T07/T11 提供，频率与免打扰由 T05 控制。
- 本次未在真机启动完整服务做端到端验证（需要 macOS 音频依赖），由作者在 Mac 上复核：在 `~/.kage/HEARTBEAT.md` 写一个 `- enabled: true` 的检查项、把 `heartbeat.interval_minutes` 设为 5，空闲 5 分钟后应听到播报。
