# 自学习 / 自进化 Agent：独立审核交接

更新2026-10-09；整理时已完成源码HEAD为`6e687b8`。本文件是审核入口，不是新的能力证明或已经批准的实现方案。

## 用户目标与最新纠偏

项目核心是自学习、自进化Agent，用于大厂面试与可能的博士申请。桌面、Live2D等是外壳，核心功能完成后再考虑。用户明确指出：反复TextEdit文本/保存测试偏离目标。TextEdit反馈dev5及新增GUI适配已暂缓。

审核必须围绕：真实失败能否触发经验/技能/源码候选生成，候选能否被后续Agent实际采用，是否在独立新任务上同预算改善，退化时能否拒绝/回退。开发者替Agent修代码不计Agent自进化；确定性工作流复用不自动等于模型学习；工程测试数量不计能力得分。

当前队列E2.1→E3.1→E4也应接受质疑：不要为了完整档案先堆字段，优先收敛到一个真实、可复核的成长闭环。审核者应独立决定合理执行路径，不以已有编号/未勾选列表为不可变约束。

## 记录与证据入口

- [当前任务队列](task-queue-2026-10-01.md)、[roadmap](../../roadmap.md)、[总体规划](../agent-memory-evolution-master-plan-2026-09-29.md)：状态与提出的顺序。
- [执行交接](execution-handoff-2026-10-03.md)：现有接口、预算、验收及历史设计；最新用户要求优先于旧领取顺序。
- [全部实验索引](../experiments/README.md)、[问题与纠正台账](../computer-use-issues.md)：包括负结果、错误推断纠正、修复及限制。
- Git提交：源码/实验报告/状态通常分别提交；最近生产观测改动`961fb57`，真实dev4冻结的是此前`e3e7ccb`，不能混用。
- 本地过程记录：活动工作树`.superpowers/sdd/execution-handoff-2026-10-03/progress.md`与task briefs/reviews/implementation notes，均被Git忽略。旧Task完成行的“next”是当时交接，不覆盖本文件最新纠偏。

主要原始实验保存在 **`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/`**，并未全部进入Git。例：`e3-recovery-pilot-v1/`、`native-text-observed/2026-10-09-dev4/`、`native-parent-reference/2026-10-09-controls1/`、`native-lifecycle-long/2026-10-09-controls1/`。其中freeze、实际请求/响应、工具、journal/budget、workspace、独立检查和audit须按报告核对。

历史`native-inactive/2026-10-09-controls2/`在 **`/Users/wenbo/Kage/artifacts/`**。只读取主仓库或远程Git会缺少原始证据；不得据此冒认已审核全部实验。不要清理/归档活动worktree的唯一证据。提交记录不是逐token费用账单，也不是所有对话的完整逐字备份。

## 最需要核查的能力证据

| 证据 | 已报告结果 | 审核重点 |
|---|---|---|
| [文件技能迁移](../experiments/2026-10-01-c4-transfer-ablation.md) | 单家族原学生0/3、技能3/3 | 真实调用、技能/发现策略作用、任务泄漏及泛化边界 |
| [恢复源码演化](../experiments/2026-10-01-e3-recovery-self-modification.md) | 父0、生成子1、一个新变体通过 | 实际加载生成源码、依赖已有技能/关键词规则、是否只是一轮人为编排pilot |
| [浏览器45次对照](../experiments/2026-10-03-browser-transfer.md) | raw2/9、云5/9、工作流1/9，0技能调用 | 明确负结果；已生成技能为何没有被Agent采用 |
| [浏览器新留出](../experiments/2026-10-03-browser-local-transfer-v2.md) | raw3/3、search2/3、preview3/3 | 实际调用不代表完成率改善，是否存在成本收益 |
| [教学集成](../experiments/2026-10-07-browser-demonstration.md) | 录制/直接复用/本地执行各2/2，模型0新技能调用 | 工作流运行与Agent自主学习的区别 |
| [最新原生dev4](../experiments/2026-10-09-native-observed-text-dev.md) | 0/1 checker failed，实际Save但文本双重编码 | 原生回归非成长；31样本不解释旧失效；事后metrics收益未验 |

已有核心代码入口：`core/evolution/{runner,archive,mutator,recovery_mutator,bundle,promotion,skills}.py`、`core/agentic_loop.py`、`core/computer_use/{episodes,skills,skill_mutator,teacher_takeover}.py`。按实际调用链读取，不把模块存在视为机制已集成。

## 请审核者输出

1. **能力地图**：哪些机制实际运行，哪些只是接口/脚本pilot，哪些还缺失；每项附源码/实际证据。
2. **偏航与浪费**：哪里过度投入适配、诊断、档案或文档，哪些工作应停止/暂缓；指出原报告不实或证据不足处。
3. **最小成长闭环**：选择已有可靠环境和真实失败，明确改进对象、自动触发/采用、候选验证/回退与未见任务；开发、教师和学生贡献分别记账。
4. **修订执行路径**：优先级、必要依赖、每包可验收行为与成本/停止条件，避免又把支撑工程扩成主线。
5. **可声明的结论**：哪些可用于面试/研究展示，哪些仍不能声称自主持续进化；提出同预算对照与消融要求。

先只读核对并形成审核结论/修订建议，不重跑旧失败救分，也不要自行启动大批模型实验或训练。必要新实验另定协议与固定预算，原失败保留。最新源码全量结果为1138 passed/4 skipped/1 xfailed（961fb57），这是工程证据，不是成长分数。
