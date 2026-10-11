# G1：持久恢复学习闭环验收

2026-10-11。结论：一个任务家族内，真实失败自动触发教师生成恢复源码，经验证晋级后，新 CLI 进程自动采用该版本并完成新输入任务。G1 的窄域闭环成立；G2 第二次学习与旧能力保留、G3 独立对照尚未完成。

## 实际行为与数据边界

`scripts/kage_recover.py` 接入现有 AgenticLoop、RecoveryMutator、Promoter、Journal 与 BudgetTracker。外部 checker 失败后，由机器反馈生成 recovery 候选，在隔离 validation 上比较；通过才保存 active。下一进程按同一 root 自动加载，不传入新 candidate 路径。源码由 DeepSeek 生成，DockerSkillRunner 实际执行；技能目录、学生模型和任务预算冻结。

开发模型完成接线、分类器及预算修复，选择 recovery 为修改对象，并准备任务协议；这些是人工设计贡献。教师收到公开目标、实际可见工具轨迹和通用失败反馈，没有手写的本次修复诊断、指定技能 ID 或隐藏评分用例。生成的 recovery 源码没有人工修补。教师自行选择已有 `repair_knapsack_selection` 技能；该技能已会解题，本轮学习的是失败后的发现与调用策略，不是新算法或模型权重。

source 是旧 knapsack 开发任务。validation 使用历史 E3 已暴露的新变体，明确改为验证数据，不能叫盲测。重启应用任务 `allocation.py/pick_projects` 在首次生成前冻结、两轮之间内容不变，未用于晋级；它仍属于同一任务家族，不证明第二类能力或通用泛化。没有执行 G3 最终评测。

## 两轮结果（原记录均保留）

| 冻结版本 / 阶段 | 来源任务 | 验证父 / 子 | 决策 | 新进程应用 | 实际本地请求 |
|---|---|---|---|---|---|
| `6a7018f` / 10-09 run1 | 失败 0 | 0 / 1 | 拒绝：已恢复的参数解析错误被误判为基础设施失败 | 未执行 | 2 + 2 + 4 = 8 |
| `a7440f3` / 10-11 run2 | 失败 0 | 0 / 1 | 自动晋级 | 通过 1，实际 recovery → skill_call | 2 + 2 + 4 + 5 = 13 |

run1 为 73.814 秒，run2 为 116.353 秒。分数是对应独立 checker 的单任务结果，不是总体成功率估计。两轮共 2 个候选、7 次任务运行，其中 6 次开发/验证、1 次重启应用；达到了候选限额，停止生成。

run2 父 bundle：`3963d3f2a0611705b65c7b401b5420b191772ed44b0e5726369702e069260569`。

晋级并重启采用的子 bundle：`a88ddfde9d39d2093e6e436bcc85388c9ada98e496d30a8180e0dd07a1f39e77`；实际 recovery 源码 SHA256：`0b3fd2a2d5a5e3d7c360a6e8e74237334cdad3e34b36409619e40747211ed790`。应用 trace 记录源码、Docker image、决策、真实工具执行和完成检查，active 指向同一 digest。

## 问题、修复与工程验收

G2准备时补充的边界（2026-10-11）：教师生成的G1源码固定查找 `repair_knapsack_selection` ID，并没有按目标做适用性匹配。提示中的“不硬编码ID”要求未被语义验收保证。通过Docker执行原源码的两项受控策略输入（无关折扣函数、日志文件）均选择了该技能；没有执行返回动作或调用模型，不能冒充真实任务失败。G1同族采用结论保持，但不得由此声称安全的跨族匹配。见 [G2准备协议](../plans/g2-applicability-protocol-2026-10-11.md)。

- `4d322d5`：只把本地解析器的已知 `InvalidToolArguments: ` 前缀判作能力问题；网络、权限、未知及混合错误仍停止。原拒绝不回写、不重评分。第二候选在新失败任务上重新生成。
- `a78f607`、`3fec271`、`a7440f3`：修复后续轮不能共用原限额的问题。延续 root 先扣除已用候选/运行，共用原教师和本地 SQLite 账本；独占 claim，原 root 退休，避免新建目录重置额度。仅支持顺序单 worker，不宣称并发协调已完成。
- `acc055c`、`7ec480a`：两轮共享账本但验证父 run_id 相同，run2 原始 `RunResult.usage` 累计了 run1 消耗；直接相加会误报 23 次。实际 chain 请求及共享账本都是 21 次。未来 root 使用稳定 namespace 隔离归因，原 DB、成绩和报告不修改，不重跑模型。修复后的代码并非本次真实实验冻结版本。
- 持久 active 校验、禁用坏 digest、未验证版本拒绝、运行时故障下一任务回退、无祖先时停止、同任务幂等、费用先预留和硬动作上限有工程回归。故障注入与确定性退化候选拒绝仅证明保护机制，不能当自然学习成果。真实 run1 拒绝属于分类缺陷，不能冒充真实退化实验。

最终源码 `7ec480a` 全量：1198 passed、1 skipped、1 xfailed、1 warning，235.97 秒、exit 0，原始日志 `artifacts/g1-persistent-recovery/final-pytest-7ec480a.txt`。warning 是 pygame 对 pkg_resources 的弃用提示。此前冻结 `a7440f3` 全量为 1189 passed、1 skipped、1 xfailed、1 warning，247.75 秒、exit 0。代码及最终证据审查通过；工程测试数不计作成长收益。

## 成本、授权与停止

用户授权总教师最多 6 请求 / $0.03，两轮共用，没有重新申请或重置。实际 2 请求，1446 输入、1093 输出 tokens。按冻结的缓存未命中峰值价格输入 $0.30 / 输出 $1.20 每百万 tokens，保守估计 **$0.0017454**，不是供应商账单。价格依据：[DeepSeek 官方定价](https://api-docs.deepseek.com/quick_start/pricing/)。实际本地 21 请求，30077 输入、3416 输出 tokens；全部预留已结算。

每次任务硬上限：6 本地请求、5 循环步、12 工具派发、150 秒；教师单次 ≤12000 字节输入、3000 输出 tokens、60 秒 HTTP 超时。总候选 2、开发/验证上限 12；实际每轮都在限额内。模型服务由实验拥有并停止，Docker 原始环境保留。教师凭据位置与兼容旧路径见 [凭据规范](../development/teacher-credentials.md)，不在报告保存密钥。

## 证据与下一项

原始数据唯一保留在活动 worktree：`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/g1-persistent-recovery/`。两个日期目录各有 `freeze.json`、输入、driver、report、teacher/student 请求轨迹、task trace、比较与 active/state；run1 的原失败、拒绝及独占延续 claim 保留。run2 `audit.py` / `audit.json` 核对 21 项冻结哈希、状态、晋级、源码执行及实际消耗。ignored `.superpowers/sdd/roadmap/progress.md` 保存过程；不能只复制 Git 仓库后宣称原始证据也在。

下一项是 G2：先寻找另一类现有文件/代码失败，冻结基线与第一能力回归，再只改变一个学习层。必须包含不适用/没有相关技能的负例，不能继续换文件名证明成长。先准备协议和预算，不自动沿用已耗尽的 G1 候选额度或追加付费调用。
