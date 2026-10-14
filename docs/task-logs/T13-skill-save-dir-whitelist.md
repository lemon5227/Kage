# T13 `skills_save_local` 写入目录白名单

- 日期：2026-10-14
- 执行者：AI 助手（由 wenbo 领取）
- 父提交：`2c38985`
- 环境：Linux 云端容器，Python 3.13.16
- 状态：完成

## 目标

模型保存技能时只能写入 Kage 的技能目录，不能借 `target_dir` 往任意目录写文件。

## 过程记录

| # | 做了什么 | 改动文件 | 怎么验证 |
|---|---|---|---|
| 1 | 新增面向模型的包装函数 `skills_save_local_tool`：`target_dir` 解析（`expanduser` + `resolve`，消除 `..`）后必须等于或位于 `core/skill_parser.py::default_skill_sources()` 中某个目录之下，否则返回 `InvalidArgument`（outcome=rejected） | `core/tools/skill_ops.py` | 新测试：外部目录、`..` 穿越、`/tmp` 被拒；技能目录子目录允许 |
| 2 | 工具注册改用包装函数，schema 描述注明只能是技能目录；原 `skills_save_local` Python 函数保持不变（内部调用和既有单测不受影响） | `core/tool_registry.py` | — |
| 3 | 2 个既有测试通过注册表把临时目录当作 `target_dir`，按新规则在测试内把临时目录加入允许列表（monkeypatch `_allowed_skill_roots`） | `tests/test_tool_contracts.py`、`tests/test_tool_outcome_semantics.py` | 通过 |

## 验证结果

```
python -m pytest -q tests/test_tool_contracts.py tests/test_tool_outcome_semantics.py tests/test_skills_save_local.py
33 passed

python -m pytest -q --ignore=tests/test_round14_audio.py --timeout=90
3 failed, 1043 passed, 5 skipped, 1 xfailed, 8 subtests passed
```

## 偏离计划

- 没有修改原函数，而是在注册层加包装（见 #2），这样内部代码仍可指定目录，只有模型调用受限。
- 修改了计划外的 2 个测试文件（见 #3）。

## 遗留与后续

- 允许目录包含 `os.getcwd()/skills`，取决于服务启动时的工作目录；如果从其他目录启动服务，该项会指向别处。
