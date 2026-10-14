# T02 危险操作确认闸门与技能写入路径修复

- 日期：2026-10-14
- 执行者：AI 助手（由 wenbo 领取）
- 父提交：`ba9655f`
- 环境：Linux 云端容器，Python 3.13.16
- 状态：完成

## 目标

危险操作只能由用户确认放行；模型不能自己放行；确认流程出错时默认拒绝；技能文件不能写到技能目录以外。

## 计划

1. 先写 6 个测试（4 个应先失败）。
2. 删除 `confirmed` 参数旁路；回调异常按拒绝处理。
3. 未知工具安全等级改为 `DANGEROUS`。
4. `proactive_agent` 校验技能名。

## 过程记录

| # | 做了什么 | 改动文件 | 怎么验证 |
|---|---|---|---|
| 1 | 新增 `TestConfirmationGate`（4 例）与 `TestProactiveAgentSkillName`（2 例）；运行结果 4 failed / 2 passed（红） | `tests/test_security_hardening.py` | pytest |
| 2 | 原代码 `if arguments.get("confirmed") is True: pass` 直接放行模型参数中的确认标志，已删除；现在只有调用方传入的 `require_confirmation` 回调能放行 | `core/tool_executor.py`（`execute` 安全检查段） | `test_model_supplied_confirmed_flag_does_not_bypass` |
| 3 | 原代码回调抛异常时 `logger.warning` 后**继续执行**危险操作；改为 `confirmed = False`，返回 `UserDenied` 并写审计日志 | `core/tool_executor.py` | `test_confirmation_callback_error_fails_closed` |
| 4 | `get_security_level` 未知工具由 `SAFE` 改为 `DANGEROUS`；同步把旧测试 `test_unknown_tool_defaults_safe` 改为 `test_unknown_tool_defaults_dangerous`（旧测试固化了 fail-open 行为） | `core/tool_registry.py`、`tests/test_tool_executor.py` | 两个测试通过 |
| 5 | `proactive_agent` 复用 `SKILL_NAME_RE` 校验 `skill_name`，非法返回 `InvalidArgument` | `core/tools/agent_ops.py` | `test_rejects_path_traversal`、`test_accepts_valid_name` |
| 6 | 确认用户口头确认路径不受影响：`core/pending_handlers.py` 传入 `require_confirmation=_always_yes`（用户已说"确认"后），仍可执行；它额外设置的 `confirmed=True` 参数现在无作用但无害，未改动 | — | `tests/test_pending_handlers.py` 全部通过 |

## 验证结果

```
python -m pytest -q tests/test_security_hardening.py tests/test_pending_handlers.py tests/test_tool_executor.py \
    tests/test_tool_executor_arg_normalize.py tests/test_tool_executor_fuzzy.py tests/test_dialog_state_machine.py
63 passed

python -m pytest -q --ignore=tests/test_round14_audio.py --timeout=90
3 failed, 990 passed, 5 skipped, 1 xfailed, 8 subtests passed
```

3 个失败为已知容器进程回收问题（总任务规划 2.3 节）。

## 偏离计划

修改了一个计划外文件 `tests/test_tool_executor.py`：其中一条旧测试断言"未知工具为 SAFE"，与本任务的目标行为相反，必须同步更新。

## 遗留与后续

- 评审 B2 建议的"服务端签发、带过期时间的确认令牌"尚未实现；当前依赖调用方是否传回调。如果将来有新的入口在无人值守时传入"总是同意"的回调，仍会绕过——新增入口时必须审查。
- `core/pending_handlers.py` 里 `args["confirmed"] = True` 已无意义，可在后续清理中删除。
- 远程技能自动安装（B6）与 `skills_save_local` 的 `target_dir` 仍待 T12、T13。
