# 交接给本地 Claude Code（2026-10-14）

## 用户的目的
做一个**自进化 · 自动演化 · 主动交互**的 Agent，用于大厂面试和博士申请，要做成能吸引注意力的前沿项目：
- 本地 Agents-A1-4B（llama.cpp，Mac 16GB）执行电脑任务；DeepSeek 当教练和"架构师"，负责示范、提取技能、改写 Agent 的策略代码。云费总上限 $1。
- 自进化：从失败和示范里学成经过验证的技能和策略，后续任务自动采用。
- 自动演化：学什么、练什么、淘汰什么由系统自己决定（能力自评、夜间自练、版本树）。
- 主动交互：知道自己不会时主动求教，学会后主动汇报，有副作用的能力启用前先确认。
- 最终交付（目标 10/29）：成长曲线、消融对照表、可现场演示的闭环、技术报告。

## 背景
- 之前由 Codex（Astra）推进 G1/G2 路线。基础设施和证据纪律很好，但验收方式是一个事件、一个样本，证明不了成长；能改的对象只有一个恢复函数，而且这个钩子在每次正常结束时都会触发，G2 的"误用"就是这么来的；预算 $0.03，限制太死；文档开销也过大。
- 2026-10-14，Claude（Cowork 会话）审查后重新规划，并完成了第一批工程代码。**Cowork 的终端是隔离的 Linux 虚拟机，跑不了 llama-server、Docker 和 git push，而且只读了大约 10% 的代码**（主要是 `core/evolution` 那条链和 `agentic_loop.py` 的恢复钩子附近）。所以下面所有"已完成"都只是**工程接通、单元测试通过**，没有经过真实模型运行。

## 已完成（全部未提交 main）
- 文档：`roadmap.md`（重写）、`docs/plans/replan-2026-10-14.md`（审查理由）、`docs/plans/self-evolving-proactive-agent-2026-10-14.md`（架构、实验设计、预算、前沿技术）、`docs/plans/tasks-2026-10-14.md`（任务书 v2.1：里程碑、工作流、任务）、`docs/plans/cards/`（每个任务的执行卡）、`docs/worklog/2026-10-claude.md`（逐步日志）、`CLAUDE.md`、`AGENTS.md`（加了入口）。
- 代码：
  - `core/agentic_loop.py`：恢复钩子增加上下文字段和 `request_help` 动作，旧候选的行为保持不变。
  - `core/evolution/teacher_budget.py`：$1 全局账本。
  - `core/evolution/competence.py`：能力自评。
  - `core/evolution/stream_tasks.py`：日志聚合任务族 + 只读负例生成器。
  - `core/evolution/stream.py`：学习流 A0/A4/A5、教师示范缓存、`chain_runner`。
  - `scripts/experiments/stream_run.py`。
  - `scripts/dev/push_agent.sh` 等：推送代理。你能直接推送，所以不需要它。
  - 6 个新测试文件。相关子集在虚拟机里 326 个通过；全量测试没跑过。
- 证据备份：本地孤立分支 `evidence/2026-10-14`，提交 `f7b092a`，**尚未推送**。仓库是公开的，用户已同意推送。

## 你要做的事（按顺序）
1. **推送证据分支**：`git push origin evidence/2026-10-14`。推完把任务书里 W0-3 标为完成，W0-7 标为"不再需要"，删掉 `.kage-push/requests/` 里排队的那个请求。
2. **全量测试**（卡片 W0-6）。失败项要分清是 10-14 的新改动引起的，还是以前就有的；新改动引起的直接修。
3. **代码地图**（新任务 W0-8）：通读仓库，重点读 `core/`、`scripts/`、`tests/` 的结构，写 `docs/code-map.md`：每个模块做什么、谁调用谁、哪些已过时、哪些和自进化主线有关。控制在 300 行以内。
4. **复核 Claude 10-14 写的新模块**（新任务 W0-9）：有没有和已有功能重复，有没有违反现有约定，接口有没有用错（尤其是 `stream.py` 里对 EvolutionRunner、KageChainProvider、Mutator、SkillCatalog、DockerSkillRunner 的用法，以及 `stream_run.py` 复用的 `native_model_pilot.LocalService`）。发现问题直接修，并写进日志。
   - **重点加查（W0-9a）：`core/agentic_loop.py` 里混着陪伴助手的产品逻辑**（天气兜底、info/command 路由推断、`skills_install`、autosave 等，搜 `weather`、`route ==`、`info_tc`、`skills_install`、`autosave`，约 73 处）。查清在实验路径（`KageChainProvider` 驱动的运行）里它们会不会被触发：读代码，再看已有实验的 trace（`artifacts/` 下 G1/C4 的 trace.jsonl 里有没有 weather/info 类动作）。会触发的话，给 AgenticLoop 加一个显式的实验模式开关（例如 `product_heuristics=False`），由 `KageChainProvider` 传入，**对所有对照组一致**；默认值保持原样，不影响桌面产品。写测试证明关掉后这些分支不执行，并在日志里说明这是宿主改动。
6. **W0-10 归档暂停的原生/TextEdit 实验脚本**：把 `scripts/experiments/native_*.py`（9 个，约 1900 行）用 `git mv` 移到 `scripts/experiments/archive/`，并在该目录放一个 README，说明暂停原因（见 roadmap §7）和恢复条件。只移动不删除；`core/computer_use/native_*.py` 先不动（可能被测试或服务引用）。移动后跑相关测试，有导入路径失败就修测试里的路径。`stream_run.py` 引用的 `native_model_pilot.LocalService` 要一起处理：把 `LocalService` 抽到 `scripts/experiments/local_service.py`，`stream_run.py` 改为从那里导入。
7. **真实跑 E-0 切片**（卡片 W5-experiments.md 的 W5-1）：先 `--plan-only`，再依次跑 A0、A4、A5，每个臂大约 30–60 分钟，A4/A5 会花少量云费。跑完分析：
   - 学生在有技能时，是否**真实调用**了技能（`skill_calls`）；
   - A4/A5 在检查点 cp10/cp20 上是否高于 A0；
   - 负例有没有误用；
   - 账本余额。
8. **修订计划**：根据第 3–7 步的结果更新任务书和卡片。

## 关于代码精简
现阶段**不做大重构**：现有基础设施能跑、测试能过，大改有风险，又不产生成长证据。只做上面的 W0-9a 和 W0-10。把产品逻辑从 Agent 核心拆出去、合并重复实验脚本等精简工作，放到 10/29 之后，依据代码地图和实验结果再做；可以在 `docs/code-map.md` 末尾列一个「10/29 后精简候选」清单。

## 关于是否重写计划
**不要从零重写。** 目标、实验设计和预算是用户已经确认过的，保持不变。但任务书和执行卡是在只读了约 10% 代码、没跑过真实模型的情况下写的，**凡是和代码实际情况或 E-0 真实结果冲突的地方，都应该改**：任务拆分、接口、文件位置、步骤、估时都可以改。改动写进任务书的变更记录和日志，说明原因。如果 E-0 显示整个方向有问题（比如 4B 学生根本用不了技能，且修不好），先停下来向用户报告，不要自行换方向。

## 规则
- 每一步追加到 `docs/worklog/2026-10-claude.md`（模板见 `docs/plans/cards/README.md` §4），并更新任务书状态。
- 先不提交 main。需要保存进度时，建 `claude/<任务ID>` 分支提交并推送；不要 force push，不要推 main，除非用户明确要求。
- 云模型调用只能走 `core/evolution/teacher_budget.py` 的账本；不要打印密钥（教师配置在 `~/.config/kage/teachers/deepseek.json`）。
- 不要改评分器，不要改已冻结的数据；负结果照实保留。
