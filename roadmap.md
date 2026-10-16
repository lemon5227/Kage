# Kage 总 Roadmap 与模型执行入口

更新：2026-10-14（重新规划，依据 [计划审查与修正](docs/plans/replan-2026-10-14.md) 与 [实现方案](docs/plans/self-evolving-proactive-agent-2026-10-14.md)）。**其他模型先完整读本文件再开工。** 用户最新指示优先。旧版 G1–G4 路线原文存档于 [roadmap-g1-g4-archived](docs/plans/roadmap-g1-g4-archived-2026-10-13.md)，只作历史与接口参考，其中的“下一步”已失效。

## 1. 目标

做一个**自进化、自动演化、会主动交互**的 Agent：本地小模型执行电脑任务，知道自己哪里不行就主动求教（云教师或用户演示），把学到的东西变成经过验证的技能，空闲时自己练习、修复和整理能力，并主动向用户汇报和确认。三个词的可测定义、架构和实验设计见 [实现方案](docs/plans/self-evolving-proactive-agent-2026-10-14.md)，**开工必读**。

最终交付（面试 / 博士申请）：成长曲线、消融对照表、可现场演示的闭环（求教 → 学会 → 后台自练 → 汇报 → 新题复用 → 负例不误用）、4–8 页技术报告。Live2D/语音外壳只作为交互层的显示，在核心完成前不扩展。

## 2. 当前状态（2026-10-16）

| 已有 | 应如何理解 |
|---|---|
| Runner / Evaluator / Promoter / Journal / Budget / Docker 沙箱 / 不可变 bundle / active+回退 | 可复用基础设施，不重建 |
| C4.4 文件技能：技能 3/3，原学生 0/3（单族、每臂 3 次） | 唯一的学习收益证据，规模很小 |
| G1：恢复源码 失败→生成→validation 晋级→新进程采用（n=1） | 管线工程闭环成立；不是成长曲线 |
| G2 基线：读取保留任务被 G1 策略误用技能改坏 | 根因是恢复钩子在每次正常结束时都会触发（`core/agentic_loop.py:604`），属接口缺陷；作为负发现保留，G2 学习包不再执行 |
| heartbeat 通知队列、BackgroundWorker、浏览器示范录制 | 主动交互与后台演化的现成载体 |
| TextEdit / AX / 桌面外壳扩展 | 暂停 |
| 10-14 Claude 已完成（未提交）：证据备份、钩子 `request_help`+上下文、$1 全局账本、能力自评、F3 日志族+负例生成器、stream 垂直切片（A0/A4/A5）及真实链集成测试 | 工程接通；**尚无真实模型结果**。详见 [任务书](docs/plans/tasks-2026-10-14.md) 与 [工作日志](docs/worklog/2026-10-claude.md) |
| **E-1 主实验完成（Kaggle T4，stream-v1，2 种子）** | 族内 cp60：A3 轨迹记忆 88%、A4 技能库 81%、A0 原学生 29%、A1 等预算重试≈31%；A4 vs A0 p=3.4e-5，**A4 vs A3 p=1**；跨族无迁移；负例 0 误用。**H1 部分成立**：从示范学习有效，技能库不优于轨迹记忆 → 按 M3 停止扩展，先诊断技能提取与选用。详见 [工作日志](docs/worklog/2026-10-claude.md) |
| **P3 完成（10-16，E-2/E-2b）** | 门控+自动归族消除未学族干扰、负例零误用；族内 A6-fixed 45/48、A5 43/48，与 A3/A4m 不显著；主动求教几乎不触发；L2 架构师在噪声验证下晋级了有害策略（A6 41/48）。同环境 A0 重复 4 次：族内 7–13/24。下一步：P5 报告与演示 |
| **P5 产出完成（10-16）** | 技术报告、相关工作、README 成长曲线与对照表、83 秒演示视频（离线渲染真实记录）；证据与报告全部在 `evidence/`；已合并 main |
| **与目标的差距** | ①闭环只在基准里跑，Kage 应用本身还没接上（W3-4 消息前端显示、W4-1 空闲触发自练均 🟡），演示是回放不是现场；②学到的东西不跨族迁移，技能/记忆都只帮同类题；③任务都是“改文件”的编程题，还没有真正的电脑操作族 |
| 实验运行环境 | E-1 起在 Kaggle 免费 T4 上跑（`scripts/experiments/kaggle_e1.py`），本机不再跑模型；教师总预算 $2（剩约 $1.33） |

## 3. 阶段计划（时间盒：10/15–10/29）

| 阶段 | 日期 | 交付 | 硬检查点 |
|---|---|---|---|
| **P0 清理止损** | 10/15 | 证据异地备份；钩子触发原因显式化 + `request_help` 动作；BudgetTracker 硬上限 $1 | 聚焦测试通过 |
| **P1 基准 + 能力模型** | 10/16–18 | `eval/stream-v1/` 6 族生成器 + ~20% 负例；`stream_run.py`、`stream_report.py`；`core/evolution/competence.py` | 原学生每族成功率 10–50%；报告脚本出图 |
| **P2 自进化主实验** | 10/19–21 | A0 原学生 / A1 等预算重试 / A3 轨迹记忆 / A4 技能库；流 60，检查点 0/30/60，评测 48，2 seed | **10/21 判定 H1**；A4 不优于 A0/A3 就停下诊断，不进 P3 |
| **P3 主动交互 + 自动演化** | 10/22–25 | A5 主动求教门；A6 后台演化环（选薄弱族→自练→修/合/汰→L2）+ 交互层汇报/确认；A6-fixed 对照 | 10/25 判定 H2–H4 |
| **P5 产出** | 10/26–29 | 演示、技术报告、README 曲线与对照表 | 结论与证据一致 |
| P4 条件扩展 | 10/29 后 | L3 LoRA 蒸馏 或 浏览器族接入（二选一） | 视结果 |

## 4. 现在领取（2026-10-16）

P0–P3、P5 已完成，比时间盒（10/29）提前约两周。**顺序（用户 10-16 定）：A → C → B**——先让应用和浏览器任务产生更多、更多样的数据，再做蒸馏。B 的管线已写好并存档（`scripts/experiments/distill_data.py`、`lora_train.py`、Kaggle `lora-smoke`/`lora` 阶段，未验证），已收 204 条教师示范（`evidence/distill/`）。
1. **A 闭环接进应用（现场演示）**：W3-4 消息在 Launcher 显示 + 用户回复；W4-1 空闲触发自练（EvolutionScheduler 走 $2 账本）；真实任务进入学习流。
2. **B P4-L3 蒸馏（最后做）**：用已缓存的教师示范在 Kaggle T4 上对 4B 学生做 LoRA，检验能否带来跨族收益（技能/记忆做不到的部分）。
3. **C P4 浏览器族（第二个做）**：把浏览器任务接入 stream 基准，让“电脑任务”名副其实。

### 原 P0/P1 清单（保留作核对）

**P0**
1. 将 `/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/` 打包到 Git 之外的第二位置，sha256 记入 `docs/experiments/README.md`；不删除原目录。
2. 修改 `AgenticLoop` 恢复钩子：触发原因显式化（`finish_attempt` / `tool_error` / `no_progress` / `self_reported_failure`），向策略提供模型最终文本与已写文件；动作空间加入 `request_help`；bootstrap 策略对 `finish_attempt` 返回 stop。这是宿主改动，所有臂一致，单独说明。
3. BudgetTracker 设全局教师硬上限 $1.00（先预留后执行，超限即停）。不重跑、不改写 G1/G2 历史成绩。

**P1**：按 [实现方案](docs/plans/self-evolving-proactive-agent-2026-10-14.md) §3、§6 实现基准、stream runner、报告脚本和能力模型。族：F1 子集选择（含旧 knapsack 回归）、F2 区间/排期、F3 日志聚合、F4 CSV 变换进入学习流；F5 文本规范化、F6 配置迁移只用于评测。指令每族 ≥3 种句式；标定实例不进正式评测；冻结清单哈希。

## 5. 预算

- 每次任务运行：最多 6 本地请求 / 5 循环步 / 12 工具派发 / 150 秒（沿用）。
- **教师总预算 $2.00（DeepSeek；用户 2026-10-14 确认 $1，2026-10-15 追加 $1）**，分配见实现方案 §4；单次 ≤24000 字节输入 / 3000 输出 token（2026-10-14 用户同意由 12000 放宽：格式修复要带回上一条回复，12000 会被拦）。闲时自演化调度器（T09）的花费也计入这 $1 账本。
- 教师从干净初始状态解题并**按任务实例缓存**，跨臂、跨 seed 共享，云费不随臂数增加。练习、评测和学生执行全部在本地。
- 预算写入实验 config，中途不加样本、不改上限。

## 6. 执行纪律（精简版）

保留：
- 运行前冻结 config（任务清单哈希、模型、预算、臂定义）；全部运行保留，不挑样本，不重跑救分。
- 隐藏评分不进入教师和学生；评测实例不参与学习或晋级。
- 开发模型修宿主代码 ≠ Agent 学习；人工改动单独记录。
- 不打印密钥；教师配置见 [凭据规范](docs/development/teacher-credentials.md)。

精简：
- 每个实验只交付：config + 原始结果 + 自动生成报告 + 不超过一页的人写结论。不再为每个微步骤写计划、审计 json 和 ledger。
- 全量测试只在实验冻结前跑一次；平时跑相关聚焦测试。
- 本文件保持在 150 行以内；只记录目标、状态、当前任务、预算，不写账务细节。
- 开包前回答：改变哪种 Agent 行为？会落在曲线/对照表的哪个格子里？答不出就不做。

## 7. 暂缓事项

TextEdit/AX/OCR/跨应用适配、完整谱系与多岛搜索、E4 复杂演化路由、换模型或推理引擎、Live2D/UI/语音、发布包装。恢复条件：P2/P3 结果证明需要它们，或用户另有明确独立任务（单独记账，不计作成长）。

## 8. 工作区与证据位置

- 主目录 `/Users/wenbo/Kage`；活动 worktree `/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage`（分支 `codex/c2-learning-loop`）。开工先查两处 HEAD 与 `git status`，不覆盖其他模型的修改。
- G1 原始证据：worktree `artifacts/g1-persistent-recovery/`；G2 基线：worktree `artifacts/g2-applicability/2026-10-12-baseline/`。被 Git 忽略，P0 备份完成前不得清理。
- 实验 Python：worktree `.venv-computer-use/bin/python`；模型服务与 Docker 使用前核实在线。
- 历史报告：[实验索引](docs/experiments/README.md)、[G1 报告](docs/experiments/2026-10-11-g1-persistent-recovery.md)、[G2 基线](docs/experiments/2026-10-13-g2-applicability-baseline.md)、[C4.4 五臂对照](docs/experiments/2026-10-01-c4-transfer-ablation.md)、[2026-10-09 纠偏](docs/plans/agent-evolution-execution-correction-2026-10-09.md)。
