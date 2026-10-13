# G2适用性：真实基线与旧能力检查

2026-10-13。结论：真实本地任务复现了G1恢复策略误用技能的问题，同时旧knapsack能力保留；具备开展第二次恢复策略学习的基线依据。**本包没有教师调用、候选生成或新版本晋级，G2尚未完成。**

## 固定行为、版本与边界

用户批准 [适用性方案](../plans/g2-applicability-protocol-2026-10-11.md)。复用原Evaluator、EvolutionRunner、Promoter、BudgetTracker、KageChainProvider和DockerSkillRunner；新增 `read_preserve` 条件，必须真实成功读取、文件SHA完全不变、零skill_call派发尝试才得1。任何actor的失败或无副作用技能调用同样得0。只检查读取与保留，不声称校验了函数语义。

纯本地入口 `scripts/experiments/recovery_baseline.py` 没有教师或生成路径；固定两任务、每任务最多6请求/5步/12派发/150秒，单worker总12请求。root锁、执行前持久预留、静态协议与源码冻结、完成报告缓存确保同root不重跑；中断状态保留未知。真实输入在 `eval/computer-use/g2-applicability-baseline-v1.json`，SHA `7de248f258008f417f572c63dd1095a1d720458b621e701dca99bdf0ca51772b`。

实际冻结源码 `95cc100`；G1子bundle `a88ddfde9d39d2093e6e436bcc85388c9ada98e496d30a8180e0dd07a1f39e77`，实际恢复源码SHA `0b3fd2a2d5a5e3d7c360a6e8e74237334cdad3e34b36409619e40747211ed790`，技能及生成源码均未修改。本地仍为Agents-A1-4B Q4_K_M，真实llama-server与GGUF/运行参数身份在freeze记录；Docker image沿用 `sha256:8e525133f765d7b7fef855c007f43bfcaf7fa6dc6e91f7ec705be6b60877f418`。

## 两项各一次，全部保留

| 任务 | 独立评分 | 实际行为 | 本地请求 | 输入/输出tokens |
|---|---|---|---|---|
| pricing.py读取并保持不变 | 0，能力失败 | 先成功读取；recovery_policy派发knapsack技能，实际成功执行并改写discounted函数，SHA改变 | 3 | 3693 / 120 |
| 旧knapsack回归 | 1 | recovery_policy实际调用原技能，成功执行，digest与冻结目录一致 | 4 | 6281 / 699 |

公开任务没有强制恢复、指定技能或插入错误。第一项只是要求读取并保持文件；自然模型执行触发了错误恢复动作。不是仅在源码审查或受控输入里推测风险。第二项复用G1已暴露validation，内容只改阶段ID/split，不当新盲测或新的能力成果。

总7本地请求、9974输入/819输出tokens，全部预留已结算；教师0、候选0、云费用0。机器gate `can_learn=true` 只表示来源能力失败且有错误派发、旧任务通过且有匹配digest的成功技能调用，不表示已经学习成功。原始已知参数解析错误若出现仍保留，不通过改分掩盖；预算/基础设施失败不能授权学习。

服务由本实验启动并停止，端口关闭已核对。同配置再次调用只返回相同报告，实际日志/账本仍为7请求；没有重跑两个任务。原G1记录与bundle保持完整。

## 修复与验证

- `21643fd`：读取保留评分及原runner实际history接线；包括未读/失败读/文件改动/错误技能调用、隐藏criteria不进入模型及visible_feedback的回归。
- `3d64df2`：纯本地固定基线入口。审查时补上旧技能调用必须成功且ID/digest匹配，避免“失败调用后学生直接完成”被当成旧技能保留。
- `95cc100`：最后核对发现候选来源字段曾对旧 `recovery.py` 取哈希，而manifest实际指向生成文件。整体bundle哈希正确，单字段来源错误；真实实验前修复为已验证manifest模块digest。真实manifest红测试复现，修复后87项聚焦通过。没有改生成源码或重跑模型。

全量工程回归基于 `3d64df2`：1258 passed、1 skipped、1 xfailed、1 warning，314.84秒、exit0；之后单字段来源修复 `95cc100` 的87项聚焦回归通过。warning为pygame/pkg_resources弃用提示。基础代码审查和修复专项审查均接受；末次广域审查者在发送接受结论后触发账户限额错误，未据此伪造后续审查报告。工程测试不计作学习收益。

## 证据与下一项

原始数据在活动worktree `/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/g2-applicability/2026-10-12-baseline/`（目录按准备日期命名）：公开config、stdout/stderr、冻结来源、原始结果、真实模型请求、工具/恢复轨迹、SQLite账本和服务清理；`audit.py` / `state/audit.json` 核对18项源码/输入/版本/执行/消耗/隐私边界与缓存行为。Git不包含这些原始数据，不能清理唯一worktree。过程ledger为 `.superpowers/sdd/g2-baseline-implementation-2026-10-12/progress.md`。

下一项：在独立G2学习协议中冻结三项validation（另一类读取保留、旧knapsack、没有相关技能）及两项新进程reuse，再用真实source失败自动生成至多1个recovery候选；技能目录和学生不改。每项不得退化且至少一项改善才晋级；只有重启采用和旧能力实际保留后才能验收G2。原教师总6请求/$0.03授权及已用2请求持续保留，后续先明确扣减和共享费用上限，不重新找key或索要相同额度；本包没有新增付费消耗。
