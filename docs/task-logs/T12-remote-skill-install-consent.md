# T12 远程技能自动安装加同意门

- 日期：2026-10-14
- 执行者：AI 助手（由 wenbo 领取）
- 父提交：`6797239`
- 环境：Linux 云端容器，Python 3.13.16
- 状态：完成

## 目标

Agent 循环不再在无人确认的情况下自动 `npx skills install` 第三方技能（第 7 章评审 B6）。

## 过程记录

| # | 做了什么 | 改动文件 | 怎么验证 |
|---|---|---|---|
| 1 | `AgenticLoop` 新增参数 `auto_install_remote_skills=False`；两处自动安装（搜索到远程技能后自动装第一个；技能卡住后自动装备选）都只在该开关为真时执行；`create_isolated_runner` 透传 | `core/agentic_loop.py` | 新测试：默认只搜索不安装 |
| 2 | `skills_install` 安全等级 `SAFE` → `DANGEROUS`：模型显式调用时返回 `NeedConfirmation`，服务端已有的确认流程会问用户"确认/取消"，确认后由 `pending_handlers` 执行（T02 后模型无法自签确认） | `core/tool_registry.py` | 新测试 |
| 3 | 服务端读取配置 `skills.auto_install_remote`（默认 false）传给 AgenticLoop；确认提示文案原为"要执行删除类操作"，现在确认不只用于删除，改为"这个操作需要你确认" | `core/server.py`、`config/settings.json` | 全量测试 |
| 4 | 4 个旧测试的场景本身就是"自动安装后的行为"（自动安装、备选技能回退、技能引导、技能卡住后回退到基础工具），在构造 AgenticLoop 时显式开启开关，断言不变 | `tests/test_agentic_loop_auto_install.py`、`tests/test_agentic_loop_skill_fallback.py`、`tests/test_agentic_loop_skill_guidance.py`、`tests/test_agentic_loop_primitive_fallback.py` | 通过 |

## 验证结果

```
python -m pytest -q tests/test_agentic_loop_auto_install.py tests/test_agentic_loop_skill_fallback.py \
  tests/test_agentic_loop_skill_guidance.py tests/test_agentic_loop_primitive_fallback.py tests/test_registry_defaults.py
全部通过

python -m pytest -q --ignore=tests/test_round14_audio.py --timeout=90
3 failed, 1042 passed, 5 skipped, 1 xfailed, 8 subtests passed
```

## 偏离计划

- 计划第 2 步"关闭时在结果中追加提示"未做：关闭后模型照常看到搜索结果，若它决定安装会触发确认流程，用户自然得到提示，不需要另加文案。
- 额外修改了确认提示文案（见 #3）。

## 遗留与后续

- 行为变化：以前"找技能 → 自动装 → 照着做"一步完成，现在需要用户说"确认"。如果你更想保留以前的体验，在 `~/.kage/config.json` 设 `"skills": {"auto_install_remote": true}`（风险自负：安装过程会执行第三方代码）。
