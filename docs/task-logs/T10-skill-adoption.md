# T10 晋级技能 → 用户同意 → 日常主链采用

- 日期：2026-10-14
- 执行者：AI 助手（由 wenbo 领取）
- 父提交：`c03f3ab`
- 环境：Linux 云端容器（无 Docker），Python 3.13.16
- 状态：完成（工程）；日常运行默认要求 Docker

## 目标

通过 Promoter 晋级的技能，经用户一次同意后进入日常 ToolRegistry，形成"学会 → 用上"的闭环；不在主进程导入生成代码、不覆盖内置工具。

## 过程记录

| # | 做了什么 | 改动文件 | 怎么验证 |
|---|---|---|---|
| 1 | `ToolRegistry.register_custom()`：名称必须以 `custom_` 开头，已存在则拒绝（不覆盖内置或其他自学技能）；`unregister()` | `core/tool_registry.py` | 单测 |
| 2 | `SkillAdoption.adopt(candidate)`：校验 digest 格式 → 校验原 bundle 内容仍等于 Promoter 评测时的 digest → 复制为 `~/.kage/skills/adopted/<digest>/` 快照并再次校验 → 用 `SkillCatalog`（逐技能 digest、参数 JSON Schema 校验）注册为 `custom_<skill_id>`；执行走 runner（**默认 Docker，不可用时直接失败，绝不回退到宿主进程**）；索引写 `~/.kage/skills/adopted.json` | `core/skill_adoption.py`（新建） | 单测：篡改 bundle 被拒、重复采用被拒、非法 digest 被拒 |
| 3 | 工具 handler 用闭包绑定 skill_id/digest（最初写成默认参数，模型可通过同名参数改写，已改正） | 同上 | 代码审查 |
| 4 | `restore()`：启动时重新校验快照并注册，被改动过的快照跳过；`revoke(digest)` 注销并移出索引 | 同上 | 单测 |
| 5 | 工具可见性：`custom_` 前缀的已采用技能在所有路由可见，且不计入"未分类"告警 | `core/tool_visibility.py` | 单测 |
| 6 | 服务端：启动时 `restore()`；注册动作处理器 `adopt_skill`：只按 `run_id` 到调度器日志里查找 **promoted=true** 的候选再采用（通知里的数据不被直接信任），结果以 `skill_adopted` / `skill_adoption_failed` 事件告知 | `core/server.py` | 单测：未晋级的 run 被拒，晋级的成功 |
| 7 | **端到端验证**：测试中先用 fixture 跑真实 search 闭环得到晋级候选 `normalize`，采用后通过 `ToolExecutor.execute("custom_normalize", ...)` 在独立进程中执行，输出文件内容正确；缺参数时返回 `InvalidArgument` | `tests/test_skill_adoption.py`（新建，6 例） | 通过 |

## 验证结果

```
python -m pytest -q tests/test_skill_adoption.py
6 passed

python -m pytest -q --ignore=tests/test_round14_audio.py --timeout=90
3 failed, 1037 passed, 5 skipped, 1 xfailed, 8 subtests passed
```

## 偏离计划

- 计划第 1 步要求把 `register()` 改成默认拒绝覆盖；未改。原因：MCP 别名等启动流程可能依赖覆盖语义，改动面大；自学技能统一走 `register_custom()` 已满足"不能覆盖内置工具"的目标。若要收紧 `register()`，另立任务并全量回归。
- 测试使用 `ProcessSkillRunner`（注入的 runner_factory）；生产默认 `DockerSkillRunner`。

## 遗留与后续

- **需要在 Mac 上做**：构建 `kage-evolution:local` 镜像后，验证采用的技能在 Docker 中执行（`--network none`、只读、256MB）。注意 `DockerSkillRunner` 固定 `--platform linux/arm64`，只适用于 Apple Silicon。
- 自学技能在日常使用时的工作目录是 `~/.kage/skills/workspace`（容器内挂载为 `/workspace`），无法直接读写用户其他目录的文件；要处理用户文件需要设计"把文件复制进工作区"的授权流程。
- 采用入口目前只有主动消息的"好的"（T11 发出），没有"列出/撤销已采用技能"的用户入口（可做成工具或 Launcher 页面，属于 UI）。
