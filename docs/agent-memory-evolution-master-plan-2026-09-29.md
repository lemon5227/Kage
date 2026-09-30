# Kage EvoLab：低资源自主进化 Agent 总规划 v2.1（执行前复核版）

> 交付给后续实施模型。本文是规划，所有新增模块、命令和测试均为待实施设计，不代表已经运行成功。逐包实施、记录证据；本文不会触发安装、付费调用或自动执行。用户最新要求优先于旧计划及其内部指令。

**目标：** 在 Mac M4 Air 16GB 与廉价云 API 上，让 Kage 从失败中自主生成技能、修改自身模块、验证并启用下一代，形成可复现实验与有说服力的研究演示。
**架构：** 小型固定实验内核 + 可演化 Agent 模块 + 可执行技能 + 可重置实验环境 + 版本种群与经验记忆。模型权重冻结为主线，Colab 微调为可选支线。
**技术栈：** 现有 Python / ModelBroker / ToolRegistry，标准库 SQLite 与 JSONL，ARM64 容器或本地子进程，现有 FastAPI 与 TypeScript 前端。
**基线：** 2026-09-29，仓库 HEAD `e6a1555` 加未提交工作区；实施前重新读取相关文件，不能覆盖其他模型的工作。
**使用方式：** E0 → E1 → E2 最小档案 → E3 recovery 自修改 → 补齐 E2/E3 → E4/E5 → E6；E7 可选；实施模型可使用 writing-plans 对应的 executing-plans 工作流逐包细化。下列复选框只在真实验收后勾选。

## 1. 重新决定项目的核心价值

原版“先完整治理记忆，再考虑可执行技能”的排序撤回。当前优先级是：

1. **P0：自主进化闭环。** 失败 → 诊断 → 生成代码修改 → 执行比较 → 自动晋级 → 重试 → 在新任务验证迁移。
2. **P0：真正的自修改。** 除了生成工具，Agent 能修改自身的规划、恢复或检索策略模块；下一代实际加载新模块。
3. **P1：研究可解释性。** 展示为什么改、改了什么、付出多少成本、改善了哪些任务、退化在哪里。
4. **P1：体验与展示。** 可视化进化谱系、实时失败与修复过程、面对环境变化自主适应。
5. **P2：长期产品治理。** 完整权限平台、多用户隔离、签名发布、企业审计与全量记忆迁移不作为原型前置条件。

保留快照、预算上限、版本回退、评测器与候选分离，是为了实验能连续运行、结果可解释。实验模式内自动生成、测试、晋级，不逐轮要求人工确认。首期不用建立复杂审批系统。

### 本项目应回答的问题

**在相同模型与有限推理预算下，根据失败证据自适应选择“修改技能、工作流还是 Agent 核心策略”，能否比固定修改单一层次更快获得可迁移的能力，并减少遗忘？**

暂称 **Failure-Conditioned Evolution Routing（FCER，失败条件化演化路由）**。这是待验证的设计假设，不是已经确立的原创算法。AgentSquare 已研究模块搜索，GEPA 已研究反思进化，DGM 已研究代码自修改；不能把这些已有机制的拼装宣称为首创。

预期研究贡献是：低预算下的修改对象选择方法、带环境变化的任务流、完整成本归因、跨任务迁移与退化分析。参考论文的机制需与本项目改造区分，贡献由独立实验确定，不以机构名称或论文数量作为创新证据。若学习型路由不胜过简单规则，应如实报告，保留有价值的负结果。

### 三条路线比较

| 路线 | 优点 | 主要限制 | 决定 |
| --- | --- | --- | --- |
| 全力做记忆产品工程 | 日常助手可靠性提升 | 难突出自主能力成长 | 保留必要修复，降为支撑项 |
| 冻结模型、进化可执行系统 | 成本可控，代码差异可观察，能直接形成实验 | 需要可靠任务评价与防止过拟合 | **主线** |
| 持续训练大模型权重 | 可研究参数层适应 | 算力、训练数据与可重复性成本高 | E7 小规模对照，不阻塞主线 |

## 2. 文献依据：发表状态与项目采用方式

检索截至 2026-09-29。优先使用期刊、会议正式论文页面和作者论文。AI 领域的 ICLR、ICML、NeurIPS 是顶级会议，与 Nature 期刊分别标注。下表不是穷尽文献综述；未核实录用的论文不算已发表顶会成果。表中 Kage 方案均为设计推论，不能借用原论文成绩作为本项目成绩。

| 研究及核验来源 | 状态 | 可采用的机制 | 在 Kage 的落点与边界 |
| --- | --- | --- | --- |
| [ADAS: Automated Design of Agentic Systems](https://proceedings.iclr.cc/paper_files/paper/2025/hash/36b7acf6f6010652b3f2a433774a66fe-Abstract-Conference.html) | ICLR 2025 | 用代码表达 Agent，元 Agent 根据历史发现继续搜索 | E3 的模块代码搜索；不照搬大规模搜索预算 |
| [AgentSquare](https://proceedings.iclr.cc/paper_files/paper/2025/hash/0ae94013da7cd459402fd77874e09ee3-Abstract-Conference.html) | ICLR 2025 | 统一接口下组合规划、推理、工具使用与记忆模块 | E3 的模块契约；E4 比较均匀模块搜索与失败路由 |
| [AFlow](https://proceedings.iclr.cc/paper_files/paper/2025/hash/5492ecbce4439401798dcd2c90be94cd-Abstract-Conference.html) | ICLR 2025 | 代码化工作流，利用执行反馈搜索结构 | E3 增加有限步骤与分支；首期不用完整 MCTS |
| [GEPA](https://proceedings.iclr.cc/paper_files/paper/2026/hash/0e9e708b6f48e14fd0ac29e167413f76-Abstract-Conference.html) | ICLR 2026 | 阅读执行轨迹、反思修改提示、保留互补候选 | E2 的反馈包与候选保留；GEPA-lite 仅为本项目简化基线 |
| [Darwin Gödel Machine](https://arxiv.org/abs/2505.22954) | ICLR 2026 主会；[作者所在 UBC 官方录用清单](https://www.cs.ubc.ca/news/2026/04/iclr) 确认 | 修改 Agent 自身代码，以经验评价与多样化档案推进搜索 | E3 真正自修改；不等同于修改底层模型权重 |
| [FunSearch](https://www.nature.com/articles/s41586-023-06924-6) | Nature，2023 在线、2024 卷期 | 固定评价器、程序演化与分岛档案 | E2 默认单档案；双岛仅作为后续消融，不预设小预算下更优 |
| [Co-Scientist](https://www.nature.com/articles/s41586-026-10644-y) | Nature 2026-05 | 科学假说生成、评价与迭代，结合领域实验验证 | 借鉴可检验假说；不等同于通用代码沙箱或因果识别算法 |
| [Dynamo: Dynamic Skill-Tool Evolution for Vision-Language Agents](https://arxiv.org/abs/2606.30185) | 2026-06-29 预印本 | 从正确与错误尝试中演化推理技能及可执行视觉工具，积累持久库 | E1 借鉴技能与工具配对；桌面 Python 技能是跨领域改造，不是论文原场景 |
| [QwenGyre](https://arxiv.org/abs/2609.33848) | 2026-09-27 预印本 | 超长程在线 RL 的弹性 GPU 调度与分支轨迹处理 | 作为资源尺度与轨迹处理参考；不采用其训练框架，不作为本地进程隔离的依据 |
| [WebCoT](https://aclanthology.org/2025.findings-emnlp.276/) | Findings of EMNLP 2025 | 将反思、分支与回溯模式重构为训练轨迹并微调 | E3 可借鉴恢复决策；文件/记忆快照协议是 Kage 自行设计，不是论文提供的通用回滚器 |
| [WebEvolver](https://aclanthology.org/2025.emnlp-main.454/) | EMNLP 2025 | 策略与世界模型协同训练，利用预测观察生成数据及前瞻决策 | 留作后续扩展；首期不添加未经验证的 LLM 语义淘汰器，模拟不能替代实际评测 |
| [Aime](https://arxiv.org/abs/2507.11988) | 2025-07 预印本 | 动态规划、按需 Actor 与集中进度管理 | E0 借鉴进度观察；“连续两步无变化”不是论文证明的通用停机条件 |
| [Repo2Run](https://papers.nips.cc/paper_files/paper/2025/hash/2f2b1d6bbd50865eca40e2774a057eef-Abstract-Conference.html) | NeurIPS 2025 主会；此处不宣称 Spotlight | 迭代生成 Dockerfile、构建镜像并运行仓库测试 | 后续扩展仓库任务时参考；不提供本项目的 ARM64 无残留或原子重置保证 |
| [TextGrad](https://www.nature.com/articles/s41586-025-08661-4) | Nature 2025 | 用自然语言反馈优化复合系统 | E4 的失败定位与修改建议；语言反馈不是数值梯度 |
| [ERA: An AI system to help scientists write expert-level empirical software](https://www.nature.com/articles/s41586-026-10658-6) | Nature，2026-05-19 | 搜索、程序执行与经验评分结合 | E1 可重置执行实验；科学代码搜索本身不等于递归自改 Agent |
| [OpenHands](https://proceedings.iclr.cc/paper_files/paper/2025/hash/a4b6ad6b48850c0c331d1259fc66a69c-Abstract-Conference.html) | ICLR 2025 | Agent 与运行环境分离，动作与观察抽象 | E0/E1 的运行协议；不整体引入重型平台 |
| [CodeAct](https://proceedings.mlr.press/v235/wang24h.html) | ICML 2024 | 可执行代码作为可组合、可修正的动作 | E1 的代码技能；一次执行修复还不是持久进化 |
| [SEAL: Self-Adapting Language Models](https://papers.neurips.cc/paper_files/paper/2025/hash/6b41e04c41726e2a60e456d0a2b961ab-Abstract-Conference.html) | NeurIPS 2025 | 生成自适应训练材料与更新指令，涉及参数更新 | E7 的研究参照；小规模蒸馏不能称为复现 SEAL |
| [Hyperagents](https://arxiv.org/abs/2603.19461) | 2026-03 预印本，本轮未确认正式发表 | 任务 Agent 与元 Agent 同处可编辑程序，改进机制本身也可被修改 | L4 的直接相关工作；研究跨任务的改进效率，避免将普通代码搜索误称元进化 |
| [AIDE²: Recursive self-improvement of AI research agents](https://arxiv.org/abs/2609.26457) | 2026-09-22 新预印本，未在此确认同行评审 | 将改进后的 Agent 用作后续改进者 | 后续元进化实验；必须证明“改进者的能力”提升 |

记忆方向的更详细文献和原有故障证据保存在 [v1 历史稿](agent-memory-evolution-master-plan-2026-09-29-v1-memory-foundation.md)。本轮采用“经验检索服务于变异选择”的窄接口，暂不要求 Hindsight、Mem0、图数据库或记忆强化学习整套迁入。

### 2.1 采用机制与资源取舍

保留 Gemini 补充中有价值的方向，但将“论文机制”“Kage 的工程改造”“尚待验证的收益”分开：

- **假说驱动：首期保留。** `hypothesis` 说明失败证据、拟修改点、预期结果与反例。通过任务不等于证明因果；要归因需同条件 parent/child 比较与模块消融。
- **持久技能：首期保留。** 生成时就提供 schema，先进入候选私有技能映射，通过评测后随 bundle 晋级。多个成功案例有助于泛化，但不能代替外部测试。
- **进度观察：E0 保留，默认不提前熔断。** 记录新观察、子目标完成与重复动作；读文件/检索不改变文件系统仍可能是进展。具体接口见 4.5。
- **状态回溯：E3 限定在可快照夹具。** 保留失败证据与计费，只恢复任务环境和任务局部上下文；不能宣称回滚真实网络副作用。
- **分岛搜索：可选消融。** 8 个候选、单 worker 的默认方案仍是单档案。基础闭环之后再比较 2 岛 × 4 候选，不能预先承诺提高全局搜索能力。
- **世界模型预检、超长程 RL、自动构建任意仓库：后续研究。** 不放入 E0–E4 的必做依赖；先完成冻结模型下的真实代码自修改。

**实施前阅读顺序：** AgentSquare → DGM → GEPA → Dynamo → OpenHands/CodeAct → ERA；涉及回溯再读 WebCoT，E7 再读 SEAL。正式投稿前补一次系统查新，核查 FCER 与模块选择、信用分配、预算约束搜索的已有差异。

## 3. 演示必须真的发生什么

首个演示：让 Kage 整理一批格式不一致的实验记录，输出统一 CSV 和摘要。环境提供可评分的文件与模拟 API。

1. 基线 Agent 因字段变更或分页遗漏失败，界面展示失败的真实最终状态。
2. Agent 读取错误和轨迹，生成字段归一化/分页技能，自动在新环境中测试。
3. 新技能晋级，原任务重试成功；展示代码差异、版本和 API 成本。
4. 给一个未见过的同类输入，验证不是硬编码原答案。
5. 再遇到工具响应缺字段，Agent 修改自己的恢复策略模块，从盲目重试变成检查响应、重新规划。
6. 下一任务的新进程加载新版本；关闭再打开实验，能力仍存在。

展示分两层：确定性夹具上的可重复实验、真实桌面测试目录中的体验演示。真实 macOS 自动化单独报告，不能拿模拟 API 的分数冒充桌面 benchmark 成绩。

### 能力层次与用词

| 层次 | 被修改的对象 | 能否算持久进化 | 计划 |
| --- | --- | --- | --- |
| L0 | 当前对话内重新尝试 | 否 | 基线已有能力 |
| L1 | 可执行技能代码与 manifest | 验证、保存且后续复用才算 | E1 首期 |
| L2 | 提示模板、规划工作流 | 跨任务保留后算系统进化 | E3 |
| L3 | Agent 自身恢复/检索/规划模块代码 | 算 scaffold 自修改 | E3 核心验收 |
| L4 | 产生下一代的诊断/变异控制器 | 需单独证明改进者变强 | E6 后研究扩展 |
| L5 | 模型参数或适配器 | 算参数层适应 | E7 可选 |

## 4. 架构：实验内核小，演化空间明确

```mermaid
flowchart LR
    T[任务与环境快照] --> A[当前 Agent 版本]
    A --> R[执行轨迹与外部评分]
    R --> D[失败诊断与经验检索]
    D --> V[选择修改层次并生成候选]
    V --> S[新进程或容器执行]
    S --> E[开发集比较与预算记录]
    E --> P[自动晋级或保留多样候选]
    P --> A
    E --> M[经验与版本谱系]
    M --> D
```

### 4.1 固定实验内核

负责启动、环境重置、评分、预算、事件记录、版本哈希和激活指针。内核只负责调度和实验约束，通过动作/观察协议与可演化逻辑分离。候选不能修改自己的评价器与成绩文件；这是科学实验的对照条件。先用目录 + SQLite 索引，不引入集群调度器、向量数据库或插件市场。

### 4.2 可演化区域

新建 `core/evolvable/`，用接口把现有执行策略逐步抽出来：

- `recovery.py`：错误分类、重试/切换工具/重新规划决策，以及可快照夹具内的状态回溯；不支持快照的环境回退为 replan/stop。
- `planner.py`：计划结构、步骤分解与分支选择，读取固定内核的进度观察；不修改内核的计步与预算。
- `retrieval_policy.py`：从经验中选哪些记录、何时不用记忆。
- `workflow.py`：组合现有模块；限制最大步数由固定内核执行。

以上文件先建立行为保持不变的基线实现，再允许候选改副本。运行中的主服务不做猴子补丁；候选以完整 bundle 在新进程启动，验证通过后原子更新实验 `active.json`。下次任务使用新版本，当前任务留在原版本，避免难以解释的混合状态。

提示变异只修改 bundle 内 `prompts.json` 的命名模板；固定内核仍控制步数、预算与评价。E3 创建基线模板及加载适配器，B3 与其他方法共享同一执行入口。

L1 技能借鉴 Dynamo 的技能/工具持久化思路：保存在实验目录 `skills/<skill_id>/<digest>/`，包括 `manifest.json`（含完整输入/输出 JSON Schema 与语义描述）、`skill.py`、由生成者提供的局部测试。独立评测器提供的任务评分不能由这些局部测试替代。

### 4.3 最小接口契约

以下结构在 E0 落地；JSON 中不放任意 Python 对象。`dict` 内容通过 schema 校验。

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    parent_ids: tuple[str, ...]
    target: Literal['skill', 'prompt', 'workflow', 'recovery', 'retrieval', 'planner']
    bundle_path: str
    digest: str
    hypothesis: str  # 失败证据、预期效果和反例；不是已证实的因果结论
    island_id: str = "island-0"  # 默认单档案；可选实验归属以 archive membership 为准

@dataclass(frozen=True)
class RunSpec:
    run_id: str
    candidate_id: str
    task_id: str
    seed: int
    max_steps: int
    timeout_s: int

@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: Literal['passed', 'failed', 'timeout', 'budget_exhausted', 'crashed']
    score: float
    trace_path: str
    usage: dict
    final_state_path: str
    progress_stagnant: bool = False  # 观察标记，不直接决定评分
    rollback_count: int = 0  # 实际执行的夹具回溯次数

# 环境和候选执行协议
# Runner.run(candidate: Candidate, spec: RunSpec) -> RunResult
# Evaluator.score(task_id: str, final_state_path: str) -> float
# Mutator.propose(parent: Candidate, feedback: dict, target: str) -> Candidate
# Archive.select_parent(seed: int, island_id: str | None = None) -> Candidate  # 默认单档案
# Promoter.compare(parent: Candidate, child: Candidate, task_ids: list[str]) -> dict
# Budget.reserve(input_cap: int, output_cap: int) -> str
# Budget.settle(reservation_id: str, actual_usage: dict) -> None
```

模块接口：`plan(context: dict) -> dict`；`recover(error: dict, history: list[dict], checkpoints: list[dict]) -> dict`；`retrieve(query: str, records: list[dict], limit: int) -> list[str]`。恢复动作枚举为 `retry / replan / switch_tool / rollback_and_branch / stop`（只有环境声明支持快照时才允许回溯）。生成技能入口 `run(arguments: dict, context: dict) -> dict`，通过 runner 的 JSON 协议调用。

统一事件：`run_id/candidate_id/task_id/step/event_type/payload/usage/timestamp`。事件类型至少包含 `action/observation/diagnosis/mutation/evaluation/promotion/budget_stop/rollback/stagnation`。实验索引 SQLite，逐步轨迹 JSONL，代码按 digest 存储；重启读取 journal，已完成 run 不重复收费。

### 4.4 实际调用链需要打通

只保存 `SKILL.md` 不算新增能力。`skill_search` 返回描述、输入 schema 与 digest；`skill_call` 接收 `skill_id/digest/arguments`，通过 runner 调用实际 Python 入口。两者需要同时注册 ToolRegistry 并进入 PromptBuilder 可见工具集合。

动态技能通过这两个稳定入口发现，不向系统提示塞入所有技能源码。执行日志必须能追到具体 digest。实验先用专用注册表实例；后续桌面演示接入已验证版本。

### 4.5 新增机制的执行边界

**进度：** E0 新建 `core/evolution/progress.py`。`ProgressTracker.observe(action: dict, observation: dict, state_digest: str) -> dict` 返回 `new_evidence/repeated_cycle/stagnant`。只使用 Agent 可见信息，不读取隐藏评分器的答案或里程碑。默认检测到连续 3 个相同规范化动作、参数、观察且无新证据时记 stagnation；该阈值是可配置工程初值。先只记录，E3 可以据此 replan，最终仍受统一步数和超时控制。不同方法共享观察机制；策略如何响应才是可演化部分。

**回溯：** E3 新建 `core/evolution/checkpoints.py`，定义 `snapshot(run_id: str) -> str` 与 `restore(run_id: str, checkpoint_id: str) -> None`。只支持测试目录、模拟 API 数据、任务局部会话状态；最近一个 checkpoint 足够。先停止任务子进程，再恢复至新工作目录并重建进程。失败 trace、预算账本、已产生的 token、全局经验与候选档案均不可回滚。恢复上下文附上失败摘要，避免丢失教训。`recover` 返回回溯动作时必须带 `checkpoint_id` 和替代动作；无效 checkpoint 返回可观察错误并转 replan。每个 task 最多回溯 1 次，回溯和分支均消耗原有步骤预算，不重置计数。真实网络/桌面外部状态不能用文件快照撤销。

**版本隔离：** bundle manifest 必须锁定全部模块、提示与 `skill_id -> digest` 映射，并对规范化 manifest 和文件字节计算摘要。`skill_search/call` 仅看到该 run 绑定 bundle 的技能；不能把尚未晋级工具注入共享全局注册表。`active.json` 按 `experiment_id/method/seed` 分开，test 运行固定 candidate digest，不在中途跟随活跃指针。每种子/方法从相同空经验、初始技能和基线开始；不同候选的可见经验规则一致，禁止跨方法共享进化成果。

**异步与评分：** 仓库 `AgenticLoop.run` 是 async；E0 runner 的同步 CLI 外壳在单个事件循环中 await 执行，FastAPI 接入时不得在已有循环嵌套 `asyncio.run`。内部适配器可采用 async 方法，但需统一调用方。评分发生在外部父进程；`score` 限定为 [0,1]，passed 的阈值由任务协议冻结，不能由候选自报。固定内核持有评分器与答案，候选环境仅挂载任务输入及自身代码；测试阶段禁止把完整仓库（含 test 答案）挂给候选。

## 5. 沙箱是实验设施：针对 M4 的选择

| 模式 | 用途 | 实现与限制 |
| --- | --- | --- |
| `process` | 开发契约、可信夹具、快速迭代 | 子进程 + 临时目录 + 超时 + 固定环境变量；不称为安全沙箱 |
| `container` | 正式代码候选比较 | ARM64 Linux 镜像、每任务新目录/容器、固定依赖、资源限制；不导入音频和 MLX 桌面启动链 |
| `native-fixture` | macOS 文件与应用体验演示 | 独立测试目录，能重置的适配器；与 Linux 分数分开 |

Mac 上 Docker 容器运行于 Linux VM，不能据此声称隔离或复现了原生 macOS GUI。参见 [Docker Mac 文档](https://docs.docker.com/desktop/setup/install/mac-permission-requirements/)。只有原生适配器实际执行过的行为才算桌面能力。

建议初值：1 个候选 worker，容器 2 CPU / 2GB，VM 3–4GB，先测实占与系统内存压力再调整；这些是待测配置，不是 M4 性能保证。演化期间暂停大型本地模型，生成与诊断走云 API。容器只包含最小 Python 执行依赖，模型请求通过宿主 broker 统一计费；容器内不另起本地 LLM。

最小镜像固定 Python 版本与依赖锁；固定 runner 记录镜像 digest。模型生成代码的语法失败、超时、进程崩溃均是正常实验结果，记录后尝试下一候选。失败任务的环境必须重置，不让上一候选留下的文件帮助下一候选过关。

## 6. 如何演化：先做可解释的小算法

### 6.1 第一版循环

1. 从单档案中选 parent，全档案最多 8 个候选；保留最优和覆盖不同失败模式的候选，不要求首期分岛。
2. 在 search 任务取失败轨迹与进度事件，诊断失败类别、修改层次和支持证据。
3. 检索最多 3 条相似经验；生成单一目标的 patch/技能与 `hypothesis`。技能 schema 在试跑前生成并验证。
4. 每候选最多 2 次语法/接口修复，所有调用计费；跑 2 个 search smoke task，失败则结束该候选。
5. 在固定 dev 与锚点任务上配对评测 parent/child，重置夹具，使用相同步数和模型配置；锚点属于 dev，不能借用 test。
6. 严格提高 dev 均分且每个锚点分数不低于 parent 时自动晋级；均分相同、锚点不退化且实测成本下降也可晋级。比较键与容差写入协议。未晋级但覆盖不同能力的候选可仅保留档案。
7. 原子激活包含技能映射的完整 bundle，记录谱系与证据；重试原任务并继续，直到预算用尽。

上面是工程晋级规则，不是统计显著性检验。少量 dev 上的提升必须经 E6 独立测试验证。成本比较使用配对任务的实测均值，评分相等才比较成本，避免用任意加权系数掩盖能力退化。

### 6.2 修改层次路由

最初先实现固定规则：
- **参数/格式错或缺少领域工具** → **L1 skill**：生成可执行的专用数据清洗或 API 适配工具；
- **重复失败、环境进入脏死胡同或同类报错循环** → **L3 recovery**：自修改恢复策略，选择切换工具、重新规划或在支持快照时回溯；
- **任务里程碑停滞、步骤反复震荡或分解不当** → **L3 planner / workflow**：利用进度观察自修改规划器，调整子目标；
- **旧经验误导或上下文负迁移** → **L3 retrieval**：自修改经验检索策略，加强环境版本与失败模式过滤；
- **指令理解偏差与格式遵循不力** → **L2 prompt**：变异优化提示模板。

诊断允许 `unknown`，回退均匀选择，不伪造确定的归因。

E4 增加预算化路由：按失败类别统计各变异算子的历史有效晋级率、分数增量与成本，用带探索的选择策略决定目标；起步可用 epsilon-greedy，epsilon=0.2 是初始实验参数。只使用当轮之前的 search/dev 历史，不能读取 test 结果。冷启动回退规则路由。

必须比较：均匀选择、固定规则、历史收益路由。若诊断本身增加大量 token 却没有收益，删除这层复杂度。交叉重组、完整树搜索、学习型性能预测器都等基础循环证实后再加。

### 6.3 记忆如何为进化服务

保留三类记录：原始 episode；压缩的失败模式与修复适用条件；通过评测的可执行程序版本。反思文本不是事实真值，必须链接 episode 和被验证的 patch。

经验字段：`task_family/error_category/environment_version/parent_digest/patch_digest/evidence_run_ids/observed_gain/cost/known_failures`。已验证工具的 schema 与调用契约也是经验记忆的关键组成。先用 SQLite 条件过滤 + BM25；没有证据支持时不引入图数据库。记忆以启用/禁用、原始轨迹/摘要经验做消融。

旧版提到的向量检索异常仅在实际复用该路径时修复。完整用户事实治理、跨档案同步、全量删除迁移不阻塞实验；实验经验使用新的独立目录，避免把个人聊天记忆混进研究数据。

## 7. 预算：廉价 API 也需要可算清楚

复用现有 OpenAI-compatible provider，通过配置指定 DeepSeek endpoint、模型 ID 与参数。官方价格与别名会变化，实验开始记录完整模型 ID、日期、thinking 参数、定价快照与返回 usage；参见 [DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing)。不把今天的低价或模型别名写死到实验结论。

### 起步配置

```json
{
  "workers": 1,
  "archive_size": 8,
  "max_candidates": 8,
  "max_repair_attempts": 2,
  "max_steps_per_task": 5,
  "smoke_tasks": 2,
  "dev_tasks": 6,
  "max_api_calls": 500,
  "max_input_tokens_total": 1000000,
  "max_output_tokens_total": 200000,
  "max_input_tokens_per_call": 12000,
  "max_output_tokens_per_call": 2000,
  "task_timeout_s": 120
}
```

以上是同时生效的上限，先触及任一项即保存状态停止，不保证足够跑完 8 个候选。8 候选 × 8 任务 × 5 步已经可能产生 320 次执行模型调用，加诊断、变异、修复、parent 比较仍可能达到上限。优化器调用与执行器调用分别记账，总费用合并。

每次请求前按输入估算上界与输出上限预留额度；未知 usage 的中断请求按预留上界保守结算，不重试到重复扣费。输入超过上限先压缩轨迹或拒绝该轮。已有完成的固定 parent 运行可以缓存，但必须匹配模型配置、环境、任务、种子和版本；另报告调用随机性。

崩溃恢复必须区分“已完成”“已预留但结果未知”“未发送”：预留在发送请求前持久化；未知请求保留保守费用且不自动重发，记录为 incomplete。恢复只重做确定尚未发送的调用，不能承诺远端请求的 exactly-once。每个 run 的费用是其全部实际调用/未知预留之和；缓存命中不再次扣真实费用。正式方法比较默认不跨方法/种子共享模型调用缓存，避免不公平折扣。

费用公式：`缓存命中输入 × 对应单价 + 未命中输入 × 对应单价 + 全部计费输出 × 对应单价`。按每百万 token 换算；思考 token 按 provider 实际计费口径纳入，不仅数可见答案。初次真实调用前由使用者配置 `max_cost_usd`；本次规划不产生 API 费用。

**启动顺序：** 假模型跑契约 → 2 候选真实调用测成本 → 8 候选小实验 → 再决定完整对照规模。不要上来执行“数十轮 × 多基线 × 多随机种子”。

## 8. 实验设计：证明能力成长而非更多重试

### 8.1 数据与拆分

先做 24 个演示/开发任务；这些任务永久标为开发，不进入最终 test。研究版新建 120 个任务：文件/表格处理、模拟 API 集成、工具故障恢复三类，各 40 个。

每类按生成模板/任务家族分组切为 search 16、dev 8、test 8、drift 8，合计 48/24/24/24。不能仅替换文件名就随机划分，训练与测试共享同一解题模板会夸大迁移。子集筛选规则在运行前写入 manifest；小实验的 6 个 dev 任务从 dev 固定抽取。

search 可向进化器暴露详细反馈；dev 只用于选择版本并控制反馈粒度；test 在版本、方法与超参数冻结后评测，失败不能回流继续调同一次实验。drift 是额外任务流：先改变字段/分页/错误语义，允许在线适应，然后在独立 post-drift 测试任务上打分。每类 8 个 drift 任务再按模板分为 4 个 adaptation + 4 个 post-drift test，合计各 12 个；后半部分不用于在线更新。复用 test 调方法后必须另建新测试集。

最终评分尽量是程序可验证的结果：文件内容、表格数值、遗漏条数、API 最终状态；不能主要由同一个生成模型自评成功。

### 8.2 分阶段基线，控制成本

| 编号 | 方法 | 作用 |
| --- | --- | --- |
| B0 | 冻结 Agent | 原始能力下限；如实报告较少花费 |
| B1 | 冻结 Agent + 同预算重复尝试/best-of-N | 排除“只是多花了推理预算” |
| B2 | 仅保留反思经验，不修改程序 | 区分记忆收益与代码进化收益 |
| B3 | 仅提示反思进化 GEPA-lite | 与低成本提示优化比较，不冒充官方复现 |
| B4 | 仅可执行 skill 进化 | 检验自改核心模块是否必要 |
| B5 | 多模块均匀搜索 | 与 FCER 使用同一搜索空间和变异器 |
| B6 | 多模块固定规则路由 | 检验历史收益学习是否必要 |
| Ours | 多模块历史收益路由 | 待验证方案 |

第一阶段只跑 B0/B1/B4/Ours 的小样本排错；第二阶段核心比较 B1/B4/B5/B6/Ours，至少 3 个随机种子；资源足够再补 B2/B3。每个方法相同总预算上限、backbone、模型参数、任务流与环境；diagnoser 等额外调用计入预算。B1 的 best-of-N 在开发阶段可用开发反馈选择策略，在最终 test 不能用隐藏真值挑选最佳答案；可报告有真值选择的 oracle 上界，但必须单独标注。

预算以美元与 token 双轴报告，使用不超出已花预算的阶梯曲线对齐共同预算点，不线性插值虚构中间能力；不能让 Ours 的搜索开销消失，也不能仅比较最终单次执行的费用。测试推理费用独立列出，避免搜索与部署成本混淆。

方法归因要求：B4/B5/B6/Ours 共享进度观察、回溯执行能力和档案配置；只改变允许修改的对象或路由器。不能只有 Ours 获得回溯、分岛或额外诊断预算。B0/B1 的初始版本也拥有相同环境接口，避免人为削弱基线。正式评分不得故意删除现有恢复能力以制造提升；专门构造的故障演示需单独标为演示任务。

曲线主要在 dev 上用于在线诊断。若要报告 test 预算曲线，先冻结所有算法和各预算 checkpoint，再一次性离线测试这些版本；测试反馈不回流。B1 与进化方法另外报告“搜索费用 + 固定数量部署任务的推理费用”的总成本，统一每个测试任务最大推理预算，不能将 B1 的反复推理费用与 Ours 的单次推理费用错位比较。

### 8.3 指标与消融

主要指标：预算—成功率曲线、曲线面积、独立 test 成功率、drift 后恢复所需成本。辅助指标：跨任务迁移、旧锚点退化率、有效候选比例、每次晋级成本、端到端延迟与本机峰值内存。

核心消融：去掉经验检索；去掉多样档案只留最佳；固定 skill 修改；均匀/规则/历史收益路由。按任务家族做配对 bootstrap 或报告逐种子差异与区间，避免把同模板变体当成完全独立样本。3 个种子的宽区间也要保留。

递归自改另立实验：让旧控制器与演化后的控制器在新的任务族、相同预算下分别培养下一代，比较其改进效率。仅有任务执行分数提高不能声称已经证明递归自我改进。

可后接 [OSWorld（NeurIPS 2024 Datasets & Benchmarks）](https://proceedings.neurips.cc/paper_files/paper/2024/hash/5d413e48f84dc61244b6be550f1cd8f5-Abstract-Datasets_and_Benchmarks_Track.html) 的小规模适配实验。首期不用运行全部环境；自选子集、修改任务或运行环境都明确标注，不能作为官方榜单结果。

## 9. 对现有代码的具体判断

| 当前代码 | 本轮检查所得 | 实施动作 |
| --- | --- | --- |
| `core/skill_parser.py` | 解析 SKILL.md 描述，不是代码技能执行器 | 保留文本技能；E1 增加独立 executable manifest |
| `core/tools/skill_ops.py` | 保存本地 Markdown，不能完成代码能力加载 | E1 新增 search/call 适配，不把保存文字当成安装能力 |
| `core/tool_registry.py` | 注册 handler/schema，存在缓存 | E1 验证注册与可见 schema 同步 |
| `core/prompt_builder.py` | 工具可见性受裁剪影响 | 加入稳定 skill 入口，检查实际模型请求 |
| `core/tool_executor.py` | 已有 ToolResult、耗时和日志 | E0 导出统一事件，实验路径不混入用户日志 |
| `core/agentic_loop.py` | 最大步数 5；isolated runner 是会话上下文隔离 | E3 抽策略接口；进程/文件环境隔离由实验 runner 实现 |
| `core/model_broker.py` | 已有兼容 provider 与后台路径 | E0 接计费包装器，不另写一套云 SDK |
| `core/background_worker.py` | 当前适合后台任务，不是持久实验调度器 | 首期用独立 CLI+journal，避免先重写后台系统 |
| `scripts/kage_eval_runner.py` | 现有评测重心是路由 | 保留；新 runner 专门评测进化和最终状态 |
| `core/memory.py` | 历史稿记录已有检索/持久化问题 | E2 新实验经验库；按实际依赖修复，不全盘先迁移 |
| `kage-avatar/src/main.ts` | 现有 TypeScript 前端入口 | E5 接 evolution-panel，保持现有前端技术栈 |

## 10. 实施包：其他模型可直接领取

以下路径均相对仓库根目录 `/Users/wenbo/Kage`。每包先写行为测试，再实现与运行验收；不要求现在提交现有脏工作区。改动小步可审查，交付实际日志与文件列表。不得把计划中的预期输出填写成已经通过。

### E0 — 固定实验内核与一个冻结基线（P0，约 2–3 天）

**新增：** `core/evolution/contracts.py`、`runner.py`、`budget.py`、`journal.py`、`agent_provider.py`、`scripts/kage_evolve.py`、`eval/evolution/smoke.json`、`tests/test_evolution_kernel.py`、`tests/test_evolution_agent_chain.py`。
**接入：** `core/model_broker.py`、`core/model_provider.py`、`core/anthropic_provider.py`、`core/tool_executor.py`，尽量使用包装器而非大改主服务。
**接口：** 实现第 4.3 节 RunSpec/RunResult、Runner.run、Budget.reserve/settle；journal 按 run_id 幂等写完成状态；按 4.5 节新增 `progress.py`，进度默认仅观察。

**当前状态（E0 接入完成后复核）：** 真实 Kage 执行链已接入并通过验收。`core/evolution/agent_provider.py` 提供 `KageChainProvider`：每个 kernel step 调用一次冻结的 `AgenticLoop.run()`，其内部使用真实 `PromptBuilder`（冻结实验身份、关闭 memory 召回、`prune_tools=False`）、真实 `ToolExecutor` 与工作区受限的 `ToolRegistry`（`read_file`/`write_file`/`list_files`，拒绝绝对路径与越界路径）；provider 由 `ModelBroker` 按角色构建，token 用量来自 provider 上报值（新增 `ModelResponse.usage`，OpenAI/Anthropic 两条路径均已接线），工具调用与版本随 `RunResult.metadata` 落库。`--provider live` 已可运行：无凭据时以退出码 2 明确拒绝且不执行任何 run，传输/模型不可用时以退出码 3 记为 `infrastructure_failure`，两种情况下都不会静默退回假 provider；`fake` 与 `live` 使用不同输出目录与不同 `provider_mode` 标记。**尚未完成的部分：** 本机没有可用的云凭据（`config/settings.json` 的 `cloud_api.api_key` 与相关环境变量均为空），因此 live 路径是用本地 OpenAI 兼容 stub 端点（真实 HTTP、真实 provider 类、真实上报 usage）验证的，尚未对付费端点做过一次真实小试验；这一步需要用户提供凭据后再执行。本地 `fork` 步骤进程仅供可信 E0 CLI 使用（macOS 上存在活跃 Objective-C/线程运行时时 fork 不安全，已提供 `--step-isolation inline` 逃生阀）；E1 的生成代码须在独立容器/执行环境运行。

- [x] 建立 2 个确定性任务：字段归一化成功；缺字段返回可评分失败。假 provider 验证不调用真实 API。
- [x] 实现临时工作目录、进程超时、事件记录与评分；验证相同夹具重置后不得继承上次输出；超时需清理整个任务进程组，退出后确认没有残留子进程。
- [x] 实现 4.5 节进度观察：不同只读结果算新证据，相同动作/结果循环记 `stagnation`；不得仅因文件没变化就熔断。
- [x] 实现预算预留与断点恢复；预算耗尽返回明确状态，重启不重复已完成 run。
- [x] 通过 `python -m pytest tests/test_evolution_kernel.py -q`；CLI `python scripts/kage_evolve.py baseline --suite eval/evolution/smoke.json --provider fake` 生成可读 report。
- [x] 接入真实 Kage 执行链：在相同夹具中以冻结的 `AgenticLoop`、`ModelBroker` 和 `ToolExecutor` 运行，记录模型实际 usage、工具调用与版本；与假 provider 报表分别标记。增加网络/模型不可用时的可观察失败测试，禁止静默退回假 provider。

**E0 验收记录（新增 `tests/test_evolution_agent_chain.py`，11 个用例）：**

| 验收点 | 证据 |
| :--- | :--- |
| 真实链条跑通两个 smoke 任务 | `--provider live` + 本地 OpenAI 兼容 stub：`Outcome: pass | 2/2 passed`，每任务 `read_file,write_file`（真实 `ToolExecutor` 执行），`chain_steps=3` |
| 记录模型实际 usage | stub 上报 831/47 tokens/次 × 3 次 → 报表 `in=2493, out=141`（与上报值精确一致，非预留上限） |
| 记录工具调用与版本 | `RunResult.metadata`：`provider_mode`、`model`、`provider_class`、`agentic_loop=AgenticLoop`、`tool_executor=ToolExecutor`、`environment.kage_revision/python/platform`；journal 中 `action(source=kage_chain)` + `observation` + `diagnosis` 事件 |
| 假/live 报表分别标记 | `provider_mode=fake`（`chain=bypassed`，仍为 1/2 的夹具基线）与 `provider_mode=live`（`chain=AgenticLoop + PromptBuilder + ToolExecutor (frozen)`）写入不同目录与不同字段 |
| 网络/模型不可用可观察 | 无凭据 → 退出码 2 且 journal 无任何完成 run（不退回假 provider）；端点不可达 → 退出码 3、`outcome=infrastructure_failure`、按预留上限保守入账 |
| 答案不外泄 | 用例断言进入模型的 prompt 中不含 `scoring_criteria`/`initial_files`/答案内容 |
| 工作区限制 | `read_file`/`write_file` 拒绝 `../`、绝对路径与越界写入 |
| 基础设施失败可重试 | 崩溃/超时/预算耗尽会被 journal 幂等缓存（防重复花钱），`--retry-crashed` 显式清掉这些 run 与其保守预算记账后重新执行；已在 CLI 上实测「先死端点失败 → 再补跑成功 2/2」 |

回归结果：`python -m pytest -q` → **714 passed, 1 skipped, 1 xfailed**（新增 11 个用例；`test_cli_live_mode_is_explicitly_unavailable` 已按新语义改写为「无凭据必须显式失败且不执行」）。

关键测试示意（配套 fixture 在本包实现）：

```python
def test_budget_refuses_overcommit(budget):
    budget.reserve(input_cap=800, output_cap=100)
    assert budget.can_reserve(input_cap=800, output_cap=100) is False


def test_resume_skips_finished_run(experiment, fake_provider):
    experiment.run_once()
    calls = fake_provider.calls
    experiment.resume()
    assert fake_provider.calls == calls
```

测试 fixture 的总额度设 input=1000/output=200；`can_reserve` 是本包预算查询辅助方法，不产生预留。

### E1 — 沙箱与自动技能生成闭环（P0，约 4–6 天）

**新增：** `core/evolution/sandbox.py`、`skills.py`、`mutator.py`、`promotion.py`、`sandbox/evolution/Dockerfile`、`tests/test_evolution_skills.py`。
**修改：** `core/tools/skill_ops.py`、`core/tool_registry.py`、`core/prompt_builder.py`；CLI 增加 `search`。
**消费：** E0 runner、budget、journal；**产出：** Mutator.propose、Promoter.compare、skill_search/skill_call；新技能先绑定候选私有 manifest，不修改其他运行的工具集合。

- [x] 用预制候选验证 manifest → 注册入口 → 模型可见 schema → 子进程调用 → 真实输出完整链路（2026-09-30，见 §16–17）。
- [x] 实现技能生成器：根据失败轨迹与重试逻辑，自动合成具名 Python Tool，生成独立 `manifest.json`（含 JSON Schema）并绑定该候选的技能映射；注册表只暴露稳定 search/call 入口（fixture 与真实 HTTP provider 接口已验收，付费云端试验仍待完成）。
- [x] 实现 ARM64 容器 runner 与环境重置；process 模式仍可用于可信本地夹具测试。
- [x] 加入云模型生成 patch 接口、附带可检验的修改假说（`hypothesis`）、2 次修复上限、配对 dev 比较和原子激活指针。
- [x] 验证失败 → 新技能结晶晋级 → 原任务重试 → 未见输入复用；重启后 digest 相同且可调用（确定性 fixture 驱动，真实执行与外部评分）。
- [ ] 运行 `python -m pytest tests/test_evolution_skills.py -q`，再用 `search --config eval/evolution/pilot.json` 做 2 候选真实试验；先在本包创建该配置并填费用上限。

验收必须覆盖：评分退化不激活、超时后下一任务正常、两个候选环境互不污染、生成局部测试通过但外部评分失败时不晋级、parent 看不到 child 新技能、方法/种子之间技能库独立。

### E2 — 经验记忆与版本档案（P1，约 2–3 天）

**新增：** `core/evolution/archive.py`、`experience.py`、`tests/test_evolution_archive.py`。
**消费：** E0 轨迹与 E1 比较结果；**产出：** Archive.select_parent、经验过滤检索、谱系查询；默认单档案，分岛是独立可选实验。

- [ ] 先实现单档案、digest 去重与最优/多样候选保留。可选双岛实验每岛上限 4，每完成 4 个候选评价，交替复制一侧在共同 dev 上得分最高的候选到另一侧、替换最低分成员；不足 4 次不迁移，同 digest 不重复占本岛槽位，迁移不生成新代码、不触发额外评测。只改变 membership，不改候选身份或谱系。
- [ ] 写入 parent/patch/evidence/cost 与修改假说；不能用无 evidence 的总结制造“已验证经验”。
- [ ] 维护已结晶工具的版本和调用契约经验。
- [ ] 实现按环境版本/失败类别过滤，再做 BM25；空命中返回空，不硬塞无关记忆。
- [ ] `python -m pytest tests/test_evolution_archive.py -q`：覆盖过期经验过滤、digest 去重、失败候选保留原因、重启谱系一致；启用双岛才增加迁移测试。

### E3 — 修改 Agent 自身模块（P0 核心，约 4–7 天）

**新增：** `core/evolvable/recovery.py`、`planner.py`、`retrieval_policy.py`、`workflow.py`、`core/evolution/bundle.py`、`tests/test_evolution_self_modify.py`。
**修改：** `core/agentic_loop.py`，通过默认策略适配器保持正常路径行为。
**消费：** Candidate bundle 与 runner；**产出：** 第 4.3 节模块接口、可版本化完整 Agent bundle；按 4.5 节新增 `checkpoints.py` 与夹具恢复协议。

- [ ] 先抽出 recovery 默认实现，验证未启用实验时与原行为一致。
- [ ] 构造重复工具故障任务，使基线盲目重试失败；先让候选修改 recovery，采用 replan/switch_tool 获得改进；再增加可快照夹具的 `rollback_and_branch`，验证恢复后失败证据与计费仍保留、不可回溯环境正确回退。
- [ ] 验证子版本代码哈希改变、事件记录实际加载路径、下一任务使用新策略，而不是仅提示声称策略改变。
- [ ] 逐步开放 planner（消费固定进度观察）、retrieval、workflow，统一输入输出；契约破坏直接记失败。
- [ ] `python -m pytest tests/test_evolution_self_modify.py -q`；产出至少一个由模型生成且外部评分改进的核心模块 patch，同时记录失败 patch。

若只做到 skill.py 新增，本包不得验收为 L3 自修改。

### E4 — FCER 研究方法与消融（P1，约 3–5 天）

**新增：** `core/evolution/router.py`、`eval/evolution/methods.json`、`tests/test_evolution_routing.py`。
**消费：** E2 历史、E3 变异目标；**产出：** `select_target(feedback: dict, history: list[dict], seed: int) -> str`。

- [ ] 用同一套候选生成器实现均匀、固定规则、epsilon-greedy 历史收益路由。
- [ ] 历史收益按失败类别维护成功次数、尝试次数、分数增量与实耗；冷启动回退规则。
- [ ] 记录每次选择依据，禁止使用未来/test 结果；三个路由共享候选数和总费用上限。
- [ ] `python -m pytest tests/test_evolution_routing.py -q`：同 seed 可复现选择，unknown 可探索，未来结果不可见，预算计入诊断调用。

本包先证明比较公正；是否提升留给 E6 数据回答。

### E5 — 进化过程可视化与真实体验（P1，约 3–4 天）

**新增：** `core/routes/evolution.py`、`kage-avatar/src/evolution-panel.ts`、`kage-avatar/src/evolution-panel.css`、`tests/test_evolution_routes.py`。
**修改：** `core/server.py` 路由注册、`kage-avatar/src/main.ts`。
**消费：** journal/archive 只读投影；**产出：** `GET /evolution/runs`、`GET /evolution/runs/{run_id}`、`POST /evolution/stop`。

- [ ] 展示任务、失败证据、候选代码差异、parent/child、评分与累计费用；可展开完整 trace。
- [ ] 支持按游标轮询新事件；停止按钮停止后续调用并保存恢复点，当前请求费用仍结算。
- [ ] 执行第 3 节演示；终端与界面均能从 run_id 找到相同结果。
- [ ] API 测试通过；人工验证空状态、超时、预算停止与无晋级结果。失败候选不伪装为成功动画。

不先引入图形编辑器或复杂拓扑编排；用简单谱系列表与 diff 已能展示核心能力。

### E6 — 可复现实验与研究报告（P1，约 2–3 周，可缩小规模）

**新增：** `eval/evolution/{search,dev,test,drift}.json`、`scripts/kage_evolve_benchmark.py`、`scripts/kage_evolve_report.py`、`tests/test_evolution_eval.py`、`docs/research/kage-evolab-report.md`。
**消费：** 全部候选与评测协议；**产出：** 逐 run 数据、汇总 CSV、成本曲线、英文研究报告。

- [ ] 按第 8 节创建并冻结分组 manifest、评分器和环境版本；核查模板泄漏。
- [ ] 先小样本确认预算，再运行核心方法的 3 种子实验；资源不足报告缩减，不虚填缺失实验。
- [ ] 使用 `python scripts/kage_evolve_benchmark.py --protocol eval/evolution/protocol.json`；本包先创建含 splits/methods/seeds/budgets 的协议。
- [ ] `python scripts/kage_evolve_report.py --runs runs/evolution --output artifacts/evolution` 生成曲线与统计；失败、超时和停止均进入分母或明确报告未完成。
- [ ] `python -m pytest tests/test_evolution_eval.py -q` 验证分组无重叠、候选无法读取测试答案、计算费用含优化器、报表可从原始日志重算。
- [ ] 写清相关工作、假设、方法、资源、结果、消融、失败案例与局限。没有跑的实验写“未运行”，不写预期数字。

### E7 — Colab 小模型蒸馏支线（P2，可选 1–2 周）

**新增：** `scripts/export_evolution_traces.py`、`notebooks/evolution_distill.ipynb`、`eval/evolution/distill_protocol.json`。
**前提：** 至少积累 100–500 条有独立验证证据的训练轨迹，并有按任务族隔离的留出集；这些数量只是启动目标。

- [ ] 导出诊断→变异目标或错误→修复的窄任务样本，去重并保留来源，不把全部聊天日志当训练集。
- [ ] 先训小型开源模型的 LoRA/QLoRA 适配器，优先从约 1.5B–3B 量级试起；具体模型与训练库在实施时再核验许可、版本与显存。
- [ ] Colab 启动时测可用 GPU/显存，做小 batch 显存试跑、断点保存；资源不足缩模型/长度，不把 7B 当必能运行。
- [ ] 比较未微调小模型、微调后小模型、云模型在同一留出任务上的成功率、时延和调用费用；推理成本包含本地运行成本说明。

[Colab 官方说明](https://research.google.com/colaboratory/faq.html) 明确资源与 GPU 可用性不保证。此支线研究能否把昂贵进化经验蒸馏为廉价策略，不能仅凭训练 loss 降低宣称自适应有效，也不等同于完整 SEAL 复现。

## 11. 里程碑与收缩规则

个人兼职预计 8–12 周，按实际完成时间调整：第 1–2 周 E0/E1 出可执行演化；第 3–4 周 E2/E3 出核心模块自改；第 5–6 周 E4/E5 出方法与演示；第 7–9 周 E6 出实验报告。E7 不占主线交付门槛。

必须尽早停止低收益扩张：2 候选试跑费用过高先缩任务步数与轨迹；L1 都没有稳定迁移时先修评价/任务，不继续搭复杂搜索器；E4 不胜过规则路由时保留简单方法并分析原因；没有 GPU 时主线照常结束。

一个有力的最终交付应包含：

- 3–5 分钟真实演示：失败、修改、自动验证、能力迁移、环境变化后再次适应。
- 公开可复现的小型任务集、评分器、依赖锁与单命令实验入口。
- 完整候选谱系和成本曲线，包含失败与负结果。
- 英文论文式技术报告，明确自己的贡献与已有方法的边界。
- 简洁架构说明，能解释为什么选小模块演化、如何公平比较、为什么在少资源下仍有价值。

这比声称“做了一个无限自进化系统”更能支持博士申请与专家面试，但项目本身不能保证录取、发表或职位。研究说服力来自可检验的问题、严谨的证据和对失败的解释。

## 12. 与旧文档的关系及交接说明

本文件是当前主规划，覆盖 [原架构提案](self-evolving-skill-architecture-proposal.md) 和 [第七章评审](self-evolving-skill-architecture-proposal-ch7-peer-review.md) 中与当前优先级冲突的排序；两份原文保留为讨论材料。旧 [v1 记忆规划](agent-memory-evolution-master-plan-2026-09-29-v1-memory-foundation.md) 的可靠性证据可以复用，但不再要求先完成 T0–T7 才开始执行代码进化。

交给实施模型的首条任务：**只做 E0 与 E1 的最小纵向闭环，默认假 provider，用户配置真实预算后再执行小试验。交付真实可运行命令、失败与成功日志以及实际代码 diff；然后完成 E2 所需最小档案，立即推进 E3 recovery 模块自修改。** E4 的研究结果必须等实验，不能在实现时预先宣布有效。

本次完成的是文献核验、仓库衔接分析和规划改写；没有安装容器环境、调用付费模型、微调或跑上述 benchmark。

## 13. Gemini 修改后的执行前复核记录（2026-09-29）

结论：修正后可开始 E0/E1；本次只改规划，没有验证新功能已经实现。

- 修正 7 项新增文献入口：Co-Scientist、Dynamo、QwenGyre、WebCoT、WebEvolver、Aime、Repo2Run。原链接中五项可访问但对应其他论文，两项未能解析为所称论文；现以正式论文页或作者预印本替换。
- 修正机制归因：WebCoT 涉及轨迹训练，QwenGyre 是大规模在线 RL，Repo2Run 是 Dockerfile 构建，不把它们写成本地快照或原子清理保证；移除未经核验的 Spotlight 与机构背书。
- 保留假说、技能持久化、进度观察与夹具回溯；取消首期强制分岛和两步无文件变化熔断。复杂搜索与世界模型预检不阻塞核心自修改。
- 补齐 checkpoint 恢复范围、计费不回退、bundle 技能锁定、方法间隔离、异步接入、崩溃恢复、drift 拆分及基线公平性。
- 验收应以行为测试和真实轨迹为准；不要把“采用某论文机制”作为测试通过条件。

## 14. 基础设施修复记录：测试卫生与工具契约（2026-09-29，E0 复核期间）

E0 接入真实执行链、复跑全量回归时发现两类与演化主线无关、但会污染实验结论的基础设施缺陷（测试会真实操作桌面；工具 schema 与实现签名不符导致模型调用必失败）。均已修复并验证，记录如下，避免后续把“测试通过”当作能力可用。

### 14.1 测试真实操作桌面（浏览器 / 捷径 / 空应用名）

症状：每轮 `pytest` 会真实打开 YouTube、Bilibili、一个示例网址、快捷键 App，并执行 `open -a ""`。定位方法：用 PATH 垫片（假 `open`/`osascript`/`shortcuts`/`screencapture` 记录调用）跑全量，实测每轮 5 次真实副作用。

| 触发点 | 根因 | 修复 |
| :--- | :--- | :--- |
| `tests/test_open_website.py`（3 例） | `patch.object(tools_impl, "open_url")` 打错模块：`open_website` 定义在 `core.tools.web_ops`，调用的是该模块自己的 `open_url`，补丁完全未生效；测试还因真实函数返回同值而“通过” | 改为 patch 定义模块并断言构造出的命令 |
| `tests/test_round5_cleanup.py::test_shortcuts_create_*` | `shortcuts_create()` 的实现就是 `open -a Shortcuts` 打开 GUI，测试未 mock | mock `shortcuts_ops.subprocess.run` 并断言 `[["open","-a","Shortcuts"]]` |
| `tests/test_tools_impl_primitives.py::test_open_app_returns_json` | `open_app("")` 直接发出 `open -a ""` 且返回 `success: true`（生产 bug） | 生产侧对空输入返回 `InvalidArgument`；测试侧 mock 并断言“不发命令” |
| 全仓兜底 | —— | `tests/conftest.py` 新增 autouse 夹具：拦截 `subprocess.run/Popen/check_output/check_call` 中的桌面类命令（`open/osascript/shortcuts/screencapture/networksetup/pmset/brightness/displayplacer/caffeinate`），**记录后在 teardown 断言失败**（不用抛异常，因为工具函数里广泛的 `except Exception` 会吞掉）；显式人工测试可用 `@pytest.mark.allow_desktop_side_effects` |

验证：全量跑完后垫片日志为空（零真实副作用）；反向探针（真的调用 `open_url`/`open_app`）能稳定失败并打印具体命令，证明兜底非空转。

### 14.2 工具 schema 与实现签名不一致（模型的动作空间失效）

实测（`create_default_registry()` 34 个工具，1 个检查脚本发现 2 处）：

| 工具 | schema 宣传 | 实现签名 | 实测后果 |
| :--- | :--- | :--- | :--- |
| `search` | `query / source(auto\|web\|youtube\|bilibili) / sort / max_results / filters` | `search(query, max_results, strategy, sort)` | 模型按 schema 传 `source="youtube"` → `TypeError: unexpected keyword argument 'source'`。视频检索能力对 agent 完全不可用；`filters` 是纯属虚构的字段 |
| `skills_save_local` | `name / description / body / target_dir / overwrite` | `skills_save_local(skill_name, content, workspace_dir)` | 模型一调用必 `TypeError`。而这是 agent 自动沉淀技能的唯一入口（`core/agentic_loop.py:567`），意味着**自我沉淀技能一直静默失败**；另外名称未消毒，`../../x` 可越界写入 |

修复：
- `core/tools/web_ops.py::search` 接受 `source`（含 enum 校验，非法值返回 `InvalidArgument` 而非静默回退），保留 `strategy` 作为 `smart_search` 的旧内部别名，`max_results` 归一到 1–10；从 schema 移除不存在的 `filters`。
- `core/tools/skill_ops.py::skills_save_local` 改为与 schema 一致的 `(name, description, body, target_dir="~/.kage/skills", overwrite=False)`，写 frontmatter + 正文（JSON 引号标量，合法 YAML，不引入 PyYAML 依赖），技能名白名单校验（封堵路径穿越），`overwrite=False` 时拒绝覆盖已存在技能。
- `core/tool_registry.py` 同步两个 schema（`source` 加 enum、去掉 `filters`、更新 `skills_save_local` 描述）；`core/prompt_builder.py` 行为准则里“保存 SKILL.md”的措辞改为“保存为本地技能文件”。

### 14.3 新增元测试（替代逐个工具的重复用例）

- 新增 `tests/test_tool_contracts.py`：对**注册表里全部工具**（含以后新增的）检查 ① 名字可用于 function calling ② `parameters` 为 object schema 且 `required ⊆ properties` ③ description 非空且 ≤200 字符（会进入每次请求）④ **schema 声明的参数 ⊆ handler 形参** ⑤ **handler 无默认值的形参必须在 schema 中声明为 required**。每条检查一次性列出所有违规工具名，不做按工具的参数化堆量；另附两个 bug 的显式回归钉子（`search` 的 `source` 真的到达实现；`skills_save_local` 接受模型侧参数名、拒绝覆盖与穿越）。
- 删除了低价值的“查字典”用例（`b站 → bilibili` 之类），只保留有安全含义的断言（坏输入不发命令 / 只发一条 argv 列表）。判断依据：宿主适配层的字符串映射坏了用户一眼可见，而 schema↔实现一致性才是 agent 能力是否可用的判据。
- `tests/test_skills_save_local.py` 按新契约重写（含 frontmatter、覆盖语义、穿越拒绝、以及 `agentic_loop` 实际传参形状）。

### 14.4 状态

- [x] 测试不再真实操作桌面；全量跑完垫片日志为空
- [x] `search` / `skills_save_local` 契约缺陷修复，模型侧调用可用
- [x] 新增全注册表契约元测试；两个历史 bug 有显式回归钉子
- [x] 回归：`python -m pytest -q` → **734 passed, 1 skipped, 1 xfailed**（含纵向 Agent 工具链测试；E0 期间为 703 passed）
- [x] `skills_save_local` 的平铺 `.md` 格式已由现有 `skill_parser` 支持；注册工具现在能完成“保存 → 本地发现 → 本地读取”，不再把这项能力误记为未接入
- [ ] 已知偏差（未做）：本次只修了 `search`/`skills_save_local` 两处**签名级**不一致；`filters` 之外未审计各工具 description 的语义准确性（元测试只保证非空与长度上限）

### 14.5 Agent 能力纵向验证（本轮补充）

契约测试只能说明 schema 与函数签名一致，不能证明模型真的能使用能力。本轮增加了从 PromptBuilder 到 ToolExecutor 再到真实 handler 的纵向回归：

- 普通信息请求的生产裁剪路径现在能暴露 `search`；模型发出的 `source="youtube"` 会穿过 AgenticLoop 和 ToolExecutor 到达 YouTube 后端，测试断言真实参数为 query/sort/limit，而不是只检查注册表字典。
- handler 返回 `{"success": false}` 时，ToolExecutor 会把失败传回 Agent（`ToolResult.success=False` 与错误类型），避免模型把结构化失败误判成成功。
- 重复任务触发自动沉淀时，测试经过真实 PromptBuilder/AgenticLoop，并验证 `skills_save_local` 实际落盘；同时覆盖 info/command 路由的提前返回分支。
- 保存后的技能通过注册工具 `find_skills` 本地发现，再通过 `skills_read` 本地读取正文，形成最小可验证的复用闭环。

这些测试仍不等同于真实云模型质量评估：模型决策由确定性 fake provider 驱动，网络搜索后端在测试中只替换为参数捕获函数。它们验证的是 Agent 执行链和能力接口确实连通，真实模型的选择质量需要后续离线评测集单独衡量。

## 15. 工具可见性策略与执行结果语义（2026-09-29，结构性修复）

§14 修了 `search` 被裁剪与执行器误报成功；本轮把这两点从"逐个打补丁"升级为**有不变量的策略**，因为同类缺陷是成批存在的。

### 15.1 发现：可见性缺陷不是一处，而是六处

对 34 个注册工具做覆盖审计（`registered − 所有路由可达集合`），结果是 **6 个工具在任何路由都不可见**：

```
fetch_content、memory_search、proactive_agent、search_and_open、tavily_search、tinyfish_search
```

其中 `memory_search` 是本项目（agent-memory）的记忆检索工具——模型从来没机会调用它；`tinyfish_search`/`tavily_search` 的描述却写着"首选使用"。根因是所有可见性都写死在 `PromptBuilder._select_tool_names` 的名字字面量里，新增/遗漏都无提示。

### 15.2 修复：可见性策略成为单一事实来源

新增 `core/tool_visibility.py`：`CORE`（每路由可见，含 `memory_search`）+ `BASE`（会话基线，含本地技能复用三件套）+ 能力组 `GROUPS`（web/browse/files/system/skills，按意图关键词激活）+ `CMD_BASE`/`INFO_DEFAULT`/`INFO_WEATHER`。`PromptBuilder._select_tool_names` 退化为策略调用，路由关键词与策略关键词合并为同一来源（消除此前两处关键词表漂移）。

三条结构性保证：

1. **全量分类**：`CLASSIFIED ⊇ 注册表`，未分类即测试失败；
2. **可达性**：每个注册工具都能被某个 (路由, 意图) 看到，不可达即测试失败；
3. **fail-open**：真的出现未分类工具时，仍然提供给模型（并 `logger.warning` + 在返回值里报告），使"漏登记"退化为多给一个工具，而不是静默删除能力。

结果：可达 34/34（修复前 28/34）；常驻面 `BASE` 15 个工具、`CMD_BASE` 22 个、info 面 5 个，均远低于工具选择准确率劣化的 30–50 区间。

### 15.3 修复：执行结果语义（ok / no_results / rejected / error）

§14.5 的第一版修复把所有 `success: false` 载荷一律记为调用失败，这会误伤**领域负结果**（`NoResults`/`NotFound`/`AlreadyExists`）：它们不是执行失败，不该把 Agent 推向重试/降级。现在 `ToolResult` 携带：

| 字段 | 含义 |
| :--- | :--- |
| `success` | 工具是否给出了可信答案（`ok`/`no_results` 为 True） |
| `outcome` | `ok` / `no_results` / `rejected` / `error` / `denied` / `needs_confirmation` |
| `tool_reported_success` | 载荷自身的 `success`，信息不丢失 |
| `error_type` | 工具错误码或异常类名 |

渲染统一收敛到 `render_history_line()`（串行路径与并行批次共用）：`no_results` → `[Tool: x] （无结果）…`；`rejected` → `[Tool Error: x] …（调用被拒绝：请修正参数或改用其他方式）`；`error` → 保留"请尝试替代方案"；`denied`/`needs_confirmation` 单独措辞。JSON 解析改为仅当结果以 `{` 开头时才尝试（工具结果可能是大文档）。

### 15.4 有意的行为反转（已在测试中标注理由）

- **command 路由现在包含 `search`/`smart_search`/`web_fetch`**。旧测试 `test_command_route_excludes_search_tools` 明确断言"命令路由不该有搜索工具"，导致"查一下资料并整理成文件"这类被分类为 command 的请求完全无法检索。该测试已改名为 `test_command_route_keeps_lookup_tools_available` 并写明反转理由；浏览器类工具仍由意图关键词控制，不会随命令路由静默放开。
- **纯 info 请求保持最小面**（5 个工具，且永不包含 `open_*`）；但**特定意图**（技能/文件/系统）不会再被一个"搜索"关键词吞掉——"帮我搜索并安装一个技能"会带上技能工具。
- `tinyfish_search`/`tavily_search` 的描述不再自称"首选"，改为说明它们是 `search`/`smart_search` 的后端，模型侧入口与 `BEHAVIOR_RULE` 一致。

### 15.5 新增测试与状态

- [x] `tests/test_tool_visibility.py`（17 项）：分类完整性、可达性、fail-open、日志、常驻面预算、route×tool 矩阵（search 三路由可见 / memory_search 可见 / 本地技能三件套可见 / 远程安装与截图仅特定意图 / 天气不给浏览器 / command 能搜索）、经真实 `PromptBuilder.build()` 的端到端可见性
- [x] `tests/test_tool_outcome_semantics.py`（16 项）：载荷分类表、真实工具经执行器的语义（拒绝 / 无结果 / 异常 / 保存→已存在）、渲染措辞、以及经真实 `AgenticLoop` 断言**模型实际读到的文本**（拒绝是错误、无结果是正常答复）
- [x] 回归：`python -m pytest -q` → **770 passed, 1 skipped, 1 xfailed**；PATH 垫片日志为空（零真实桌面副作用）

### 15.6 对 §15 修复本身的自审（对抗性复核）

本轮改动完成后又做了一次针对自己产出的审计，发现并关闭 6 个问题：

| # | 自审发现 | 性质 | 处置 |
| :--- | :--- | :--- | :--- |
| 1 | 可达性测试对每条语料硬算 info/command/chat 三条路由，可能"自证"（某工具只在 `classify_route` 永不产生的路由下可达） | 测试有效性 | 改为用真实 `classify_route` 计算；复算仍 34/34，且确认无"仅假路由可达"的工具 |
| 2 | `CLASSIFIED` 含未注册的 `web_search`（幽灵项） | 策略卫生 | 显式声明 `ALIAS_SLOTS`（MCP 别名槽）并加断言：`CLASSIFIED − 注册表 ⊆ ALIAS_SLOTS` |
| 3 | `_REJECTED_OUTCOME_CODES` 定义后从未使用 | 死代码 | 让其生效：已知拒绝码 → `rejected`，未知失败码 → 新增 `tool_error`（渲染措辞不同，便于监控区分"可修正"与"工具坏了"） |
| 4 | 未分类工具的 fail-open 告警每次请求都打一次 | 运行期噪声 | 改为每个工具名告警一次，并加测试断言 5 次调用只出 1 条 |
| 5 | `prompt_builder` 里 `_TOOLS_CMD/_TOOLS_BASE/_TOOLS_WEB/_TOOLS_OPEN/_TOOLS_FILE/_TOOLS_SYSTEM` 已成死常量（仅测试引用） | 死代码 + 漂移风险 | 删除，测试改从 `core.tool_visibility` 断言策略常量（兼容别名本身就是上次漂移的温床） |
| 6 | `history_line()` 定义了但 loop 未用；另有三处特化分支（weather/web_fetch、info/smart_search、fs_apply 预览）仍手写 `[Tool: …]`/`[Tool Error: …]` | 语义分叉 | 三处统一走共享渲染器；`history_line()` 保留为 ToolResult 的公开 API 并注明 loop 为何用模块级函数（需兼容 duck-typed 结果）；现"直写工具行"残留为 0 |

复审计结果：真实路由可达 34/34、幽灵项 0、死常量 0、告警 1 次/5 次调用、分类表 `rejected|no_results|tool_error` 三态齐备、渲染分叉已消除、直写工具行 0。

同时确认影响面受限：当前只有 2 个工具会发出"良性码"（`search_and_open` → `NoResults`，`skills_save_local` → `AlreadyExists`），其余良性码是预留词汇；info 回退路径调用的是 `smart_search`，其失败码属 `rejected`，语义未变。

- [ ] 已知偏差（本轮发现，未做）：**回合内工具观察不会跨回合留存**。实际 `SessionManager.get_history()` 返回新列表，不论会话是否为空，循环内追加的工具观察都不会自动写回 session；`core/server.py` 只在回合结束后记录最终 user/assistant。此前 `_RecordingSession` 返回共享列表，不能代表实际会话行为；§16 已把结果语义测试改为检查模型下一次调用收到的 messages。跨回合持久化属于独立的 transcript 语义变更，尚未实现。
- [ ] 已知偏差（沿用）：元测试只保证 description 非空与长度上限，未审计其**语义准确性**（本轮顺手修正了两个搜索后端的描述，其余未逐一核对）

## 16. DeepSeek 改动复核与 E1 首个验收点（2026-09-30）

### 16.1 复核发现与修复

§15 的可见性策略和结果渲染统一可以保留，但针对性测试通过并不代表所有具体任务可用。本轮先写回归，观察到 4 项失败，再修正：

- `CORE` 宣称每条路由都可见，但 info/weather 分支没有使用它，`查一下我之前提过的研究方向` 看不到 `memory_search`。现在信息路由也保留记忆入口。
- `搜索视频处理技能` 会被分类为 info，只暴露远程安装工具，没有本地 `find_skills/skills_read/skills_save_local`。技能意图组现在包含这三个本地入口。
- `skills_save_local` 拒绝覆盖时返回 `AlreadyExists`；原分类却把它改成 `success=True`。这是一次没有完成的写操作，应为 `rejected/success=False`，模型可读取既有内容或明确请求覆盖。`NoResults` 的正常空查询语义保留。
- 原结果语义测试读取特制 session 的共享列表，未验证模型真正收到观察。现使用真实 `SessionState`，检查下一次 `generate(messages=...)` 中的工具结果，不依赖 session 被循环直接修改。

§15 中 info 面“5 个工具”、`AlreadyExists` 属于成功、`_RecordingSession` 能代表真实会话的说法均由本节修正。桌面默认注册表的普通 info 面现在为 6 个有效工具；候选注册表若绑定可执行技能，还可提供两个稳定执行入口。

### 16.2 E1 已交付：候选绑定的可执行技能

新增 `core/evolution/skills.py`、`sandbox.py`、`tests/test_evolution_skills.py`；`requirements.txt` 显式声明 JSON Schema 校验依赖 `jsonschema>=4.18,<5`。

manifest v1 格式：

```json
{
  "version": 1,
  "skills": [{
    "skill_id": "normalize",
    "description": "normalize record fields",
    "parameters": {"type": "object", "properties": {}, "required": []},
    "entrypoint": "normalize.py:run",
    "digest": "<sha256>"
  }]
}
```

`digest` 算法：对 `skill_id/description/parameters/entrypoint` 四项按 `sort_keys=True, separators=(',', ':')` 规范化 JSON 编码，接一个换行和入口 Python 文件原始字节，再算 SHA-256。当前支持单文件、标准库技能；其他文件与依赖封装留给后续 bundle/container 实现。

`SkillCatalog.from_bundle()` 校验 manifest、schema 与 digest，并快照代码字节。每个候选注册表只注册 `skill_search/skill_call`；搜索返回描述、参数 schema 和 digest，调用必须指定同一 digest，参数先经 JSON Schema 验证。目录后续被修改不会改变已加载的技能；重新加载则拒绝摘要不匹配。

`ProcessSkillRunner` 使用独立 Python 子进程和 JSON 文件协议，任务工作目录作为 context；结果与 stdout/stderr 分离，限定墙钟时间和结果读取大小，完成或超时后清理子进程组。这是可信预制技能的 process 模式，**容器模式尚未实现，不能把它记为生成代码的 OS 沙箱**。

`KageChainProvider(..., skill_catalog=catalog)` 将候选私有技能加入每次任务的注册表。记录实际 `skill_id/digest`，metadata 保留完整技能映射。E0 resume fingerprint 现在包含模型、模式、调用限额及实际技能映射；换技能代码后复用同一 run_id 会被拒绝，不返回其他版本的旧评分。

### 16.3 验收证据与下一执行包

6 个 E1 行为用例覆盖：manifest → 模型读到发现结果 → 子进程实际写文件；重载后在未见输入复用；父候选不可见子技能；代码篡改与运行快照；参数与 digest 错误不执行；超时后下一调用正常；真实 KageChainProvider 接入；外部评分为 1.0；相同 run 不重复执行；换实际技能版本拒绝缓存命中。模型由确定性 fixture 驱动，Python 技能执行、文件输出、执行器、评分器与 journal 均使用真实实现。

验证：`python -m pytest -q` → **778 passed, 1 skipped, 1 xfailed**，54.25 秒；结果语义测试随后再跑 **17 passed**；`git diff --check` 无错误。没有运行付费 API，也没有宣称完成自动进化。

下一包继续 E1：实现模型生成器 `mutator.py`、失败轨迹 → 修改假说 → Python/manifest 候选；接 ARM64 容器执行；再做配对 dev 评分与 `promotion.py` 原子激活。必须保留本轮已打通的真实执行与外部评分链，不用模型总结或文件落盘代替能力晋级证据。

## 17. E1 生成、容器执行、评分晋级与 CLI（2026-09-30）

### 17.1 当前交付状态

E1 代码链路已完成，§16 的下一执行包现由本节交付。**付费云端的两候选试验尚未通过**：本机现有配置指向不可达的测试端点，实测连接拒绝；已记录为基础设施失败，CLI 返回退出码 3，不切换到 fixture。不将本节的演示结果作为真实模型自主发现技能的研究证据。

新增 `core/evolution/mutator.py`、`promotion.py`、`artifacts.py`、`search.py`、`fixtures.py`、`sandbox/evolution/Dockerfile`、`eval/evolution/pilot.json` 和对应行为测试；CLI 已支持 `search`。

### 17.2 实现机制

- `Mutator.propose(parent, feedback)` 调用项目现有 ModelProvider。只发送用户指令、Agent 可见的 action/observation 与失败摘要，剔除隐藏评分字段；输出必须包含修改假说、技能名、描述、参数 schema 和 Python 源码。先校验语法、manifest 与 schema，再生成内容摘要绑定的候选目录。父候选文件不被改写。
- 初始生成后最多修复两次；无效响应、校验错误、usage 和修改事件都保留。optimizer 与 execution 共用预算，分账户记录。每个生成槽位保留请求摘要、尝试日志与已完成候选；恢复不重生成已完成候选，修复次数也不会因重启归零。
- `DockerSkillRunner` 每次调用创建一个独立 ARM64 容器；任务目录与临时运行协议目录作为挂载。容器禁止网络、根文件系统只读、限制 CPU/内存/进程数。按实际 image ID 执行，超时会停止容器而不仅是 Docker CLI；下次调用创建新容器。generated live 模式不回退到宿主 process。
- `Promoter.compare` 只接受显式 `split=dev` 的任务，父子使用同一任务、seed、步骤和超时配置，由 E0 评分器检查真实文件。只有平均分严格提高、每项任务不退化、且不存在超时/崩溃/预算中断，才原子更新活跃指针。比较记录持久化；外部评分失败的候选不会因 Python 能运行或局部示例成功而晋级。
- `search` 先运行基线，选择失败 dev 任务生成候选，再配对比较、激活与原任务重试；`reuse` 任务只在候选搜索结束后评价，不进入优化器或晋级判据。报告、日志、预算和 active 指针按 provider/experiment/seed 隔离。
- 恢复检查锁定任务协议、有效模型配置摘要、技能 digest、执行后端/超时/结果限制与容器 image ID。凭据不写入协议。基础设施失败退出码为 3，任务评分失败仍是实验数据。更换实验条件须使用新的 experiment_id/输出目录，保留原始失败记录。

本轮同时修复两处预算问题：一条 Agent 链包含多次模型调用时，之前只记一次；缺失 provider usage 时，之前聚合为零 token。现预留链的调用上限、结算实际调用数，并持久化；缺失用量按 token 预留上限结算，保留实际调用次数。旧数据库兼容迁移中已有记录只能保留原有单次计数假设，不能据此声称重建了历史实际调用数；研究测量使用新实验目录重跑。

### 17.3 实际验证与报告

本机 OrbStack 已启动，`docker info` 确认 `linux aarch64`。实际构建并执行 `kage-evolution:local`，image ID 为 `sha256:8e525133f765d7b7fef855c007f43bfcaf7fa6dc6e91f7ec705be6b60877f418`。容器测试验证真实文件输出、两个工作区隔离、每次调用模块状态重置、超时清理和下一次调用正常；验证结束无残留 `kage-skill-*` 容器。

真实命令：

```bash
docker build --platform linux/arm64 -t kage-evolution:local sandbox/evolution
python scripts/kage_evolve.py search --config eval/evolution/pilot.json --provider fixture
```

报告：`runs/evolution/search/fixture/pilot/seed-42/report.json`。测得 dev 平均分 **0.5 → 1.0**；一项未见输入 reuse 分数 **1.0**；实际执行链共 **17 次模型 fixture 调用 + 1 次 optimizer fixture 调用**。达到 dev 全通过后提前停止，没有为了凑“两候选”再生成无必要候选。活跃技能重启后 digest 一致；再次执行同命令不增加预算调用数。

最终回归：`python -m pytest -q` → **790 passed, 1 skipped, 1 xfailed**，59.98 秒；真实 Docker 集成用例本次实际执行，未被跳过。`git diff --check` 无错误。

这里的模型决策和生成代码由明确命名的 fixture 提供，Python、容器、Kage AgenticLoop、文件副作用、外部评分、晋级与恢复均真实执行。另有真实 `OpenAICompatibleProvider` + 本地 HTTP 端点的优化器测试：API 响应生成可执行候选，provider 上报 113/71 tokens，账本精确记录为 optimizer 账户，实际技能处理未见输入成功。

`pilot.json` 设置 max_candidates=2、max_api_calls=50、input=150000/output=30000、费用规划上限 $0.25。其输入/输出费率是规划系数，非官方报价；fixture 报告金额没有真实 API 支出。live 连接拒绝记录中的保守预算金额也不是已确认的账单。

### 17.4 后续执行顺序

1. 将现有不可达测试端点替换为可用云模型配置，核对计价并用新的 experiment_id 跑小规模 live 试验；如果基线本来就全部通过，报告“无需生成”，不人为降级基线制造成长。
2. E2 建立候选/失败经验档案与按环境版本过滤的检索，保留本轮完整谱系、假说、费用和外部评分证据。
3. E3 抽出可修改 recovery 模块，让能力成长从“新增技能”进一步进入 Agent 自身策略演化；真实外部评分改进后才激活。

E1 已验证单文件标准库技能；依赖安装、多文件模块、并发搜索和跨回合工具观察持久化未实现。当前恢复和原子指针按单搜索 worker 设计，未宣称多进程并发更新安全。

## 18. E0/E1 提交前复审与状态语义修复（2026-09-30）

### 18.1 评审结论与范围

DeepSeek 提出的死分支、测试 docstring 漂移、本地技能重复定义成立；已删除旧的 `no_results+AlreadyExists` 渲染与手工断言，修正文档并抽出 `LOCAL_SKILL_TOOLS`。info 路由仅在技能意图下开放本地三件套，chat/command 常驻，原因已写入策略注释。`len(INFO_DEFAULT)<=8` 原本已有断言，不新增重复测试。

当前 E1 得分由外部评测器检查输出文件决定，晋级不按工具错误次数扣分，且执行技能使用 `skill_search/skill_call`；“AlreadyExists 系统性低估 E1 得分”已撤回。修复解决的是诊断证据丢失，不声称提高外部分数。

### 18.2 状态语义端到端

工具载荷可显式声明 `outcome`，分类器优先采纳已知且与 success 一致的值，否则返回可观察的 `InvalidOutcome/tool_error`；没有显式值的旧载荷仍使用错误码表。`ok` 已允许附加载荷字段，`err` 新增可选 outcome。

`skills_save_local` 将现有文件字节与待写入的完整 frontmatter/正文比较：相同返回 `unchanged/success=True`，文件内容与修改时间不变；不同且未允许覆盖返回 `not_applied/success=False`，提示 overwrite=true。它不会将任意重复保存自动判为成功。

Agent 串行、并行与自动技能操作保留 outcome 和 tool_reported_success；`KageChainProvider` 归一化不再丢弃这些字段，runner 的 observation/journal 保留明确状态、success 与载荷原始 verdict，ToolExecutor 的 JSONL 日志同样记录。外部评分方法保持原样。E1 的 `UnknownSkill/DigestMismatch/InvalidArgument` 显式声明 rejected，旧错误码表兼容这些代码。

`tests/test_tool_state_outcomes.py` 使用真实保存、AgenticLoop、ToolExecutor、KageChainProvider 和 journal，断言模型实际读到状态、磁盘未重写与落库字段一致；在修复前的独立 E0 快照三个用例均失败，修复后通过。

### 18.3 E1 独立审查发现与修复

独立审查复现：模型响应已保存但 proposal.json 尚未发布时中断，原 Mutator 重启把有效响应误当失败，可能再次付费；若是第三次响应则直接丢弃有效候选。尝试记录更新也原本使用非原子写入。

现尝试记录均原子写入；重启先重新校验尚未完成发布的已保存响应，再决定是否进行下一次模型调用。首次和第三次有效响应均可恢复，保留原预算与修复次数上限。四个回归覆盖“响应保存后中断”和“发布前中断”，恢复后实际执行技能处理未见输入成功，调用次数不增加。独立复审另注入比较记录、激活指针及搜索进度之间的中断，恢复后活跃候选与报告一致，未重复调用模型。

E1 的真实 Docker 隔离、外部配对评分、拒绝退化、未见输入复用与显式 fixture/live 区分保持验收；付费云端试验仍未完成，不能将工程闭环或 fixture 成绩作为模型自主进化有效的研究结论。

### 18.4 最终验收与提交边界

不含 E1 的语义修复暂存快照全量回归：**777 passed, 1 skipped, 1 xfailed**，63.22 秒。技能执行/ARM64 容器子提交的独立快照：**22 passed**。完整 E1 暂存快照全量回归：**799 passed, 1 skipped, 1 xfailed**，83.32 秒；包含真实 Docker 用例，本次未跳过。现有 pygame/pkg_resources 弃用告警不影响测试结果。

本轮另在新实验目录实际复跑 Docker fixture CLI，报告位于 `runs/evolution/search/fixture/e1-prepush-2026-09-30/seed-42/report.json`。配对 dev 平均分 0.5→1.0，未见输入 reuse=1.0，模型 fixture 调用 17 次、optimizer fixture 调用 1 次。新目录的这些结果来自本轮执行，不是旧报告缓存；金额为合成用量与规划费率的估算，没有付费 API 支出。

提交分成：状态语义修复；候选技能与容器执行；生成/评分晋级/断点恢复/CLI；规划与复审记录。E0 既有五个提交保持独立，便于按依赖顺序回退。实际实验报告是本机产物，不提交 journal、私有设置或凭据。
