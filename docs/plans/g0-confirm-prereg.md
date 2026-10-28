# G0 确认实验：预注册（2026-10-28，跑模型之前写定）

回应审稿意见（GPT / Astra / DeepSeek）里能在本机做的两条：**全新冻结题**、**规则位置与“先写计划”分开**。LoRA 多 seed、等暴露回放、强制读回另走 Kaggle（见文末）。

## 冻结物（SHA-256，跑之前）
| 文件 | SHA-256 |
|---|---|
| `eval/desktop_v2_confirm/tasks.json`（18 题，从未给学生/老师/开发者跑过；标准解 18/18） | `57e2091fc58a8b47ce56b32deb0677d9fe153ed1432e9c199d1164eb5e4be025` |
| `evidence/reports/g0/a0-baseline-v1/lessons.json`（10-23 从 v1 训练题失败写的 4 条规则，不改） | `f121b95eb21f5645f54751da3c263522bfb71467317b1dc7dd8c7f832bf6b925` |
| `scripts/experiments/g0_confirm.py` | `f1b4a9c9d64a4f251a6357457fcb7cd327119d509cf79af54d5872d327edc87b` |
| `core/computer_use/desktop_agent.py`（新增 `adjacent` 模式，其余与论文一致） | `3fa01be788feac3b2f547573568577b5b07c028efffcaad4bf4a708784b7f3fb` |

学生 Agents-A1-4B Q4_K_M，llama-server 参数与论文相同（`local_service.server_argv`，8,192 上下文），温度 0.7（agent 循环），每格 3 次。

## 题目
- **计算器 12 题**：分组题 10 道（`(a+b)×c`×3、`(a−b)×c`×2、`(a+b)÷c`×2、`(a−b)÷c`×3，必须在第二个运算前按等号）；**优先级对照 2 道**（`8 + 7 × 6`、`12 + 9 × 3`：直接按下去就对，按规则“加完先按等号”反而错——测规则过度套用）。
- **TextEdit 6 题**：改错字 2、追加一行 2、写两行 2（文件名、内容都是新的）。

## 实验与臂（同一会话交错）
每个 (run, 题) 内，该实验的所有臂背靠背跑，臂顺序按 (run + 题序号) 轮转。
- **X1 接口确认**：TextEdit 6 题 × {v2 fill，v4 按行}，无规则。
- **X2 规则采纳拆分**：计算器 12 题，接口 v4，五个条件：
  `none`（无规则）· `system`（规则在系统提示）· `planonly`（只要求先写计划）· `adjacent`（规则在任务旁，不要求计划）· `plan`（规则在任务旁 + 先写计划，论文里的配置）。

## 假设与分析（写定，不看结果再改）
单位 = 题；每题 3 次取均值；按题配对；**精确**双侧 sign-flip（`docs/paper/v0.5-support/verify.py` 的同一实现）；p 均为 nominal，不做多重校正；另报每臂合计 k/n。

主要对比（分组题 10 道）：
1. **P1** `plan` vs `none`：论文主张在新题上是否复现。
2. **P2** `adjacent` vs `system`：不写计划时，只换规则位置有没有作用。
3. **P3** `plan` vs `planonly`：给了计划要求后，规则内容有没有额外作用。
4. **P4** `plan` vs `adjacent`：给了任务旁规则后，计划要求有没有额外作用。

次要：
5. **S1** X1 `te-v4` vs `te-v2`（6 题）：论文最强结论（按行工具）在新题上是否复现；最小可达 p = 1/32。
6. **S2** 优先级对照 2 题上各臂的成功率（过度套用；只描述，不检验）。

判读：p<0.05 且方向一致记“复现/有作用”；否则记“未复现/无证据”，不论方向都写进论文，包括与论文相反的结果。

## 运行规则
- 学生失败从不重跑。setup/应用/服务异常（记录里有 `error`）计入 `infra-errors.jsonl`，该格重跑至多 2 次；若仍异常，按失败计并单独报告。
- 运行中不改代码、规则、提示词、题目。发现脚本 bug：停止、记录、修复后**整组重跑**，两次都报告。
- 屏幕锁定时等待（`wait_until_unlocked`），`caffeinate` 保持唤醒。
- 原始结果在 `~/.kage/g0/confirm/`，跑完复制到 `evidence/reports/g0-confirm/`。

## 规模与时间
X1 36 次（约 45 s/次）+ X2 180 次（约 75 s/次）≈ 4.2 小时。

## 不在本次（另行，Kaggle）
- R3 多训练 seed（3 个）同数据重训，测学过/留出/阴性。
- 等暴露量回放对照、强制读回干预（`docs/plans/r3f-forgetting-fix.md`）。
- 第二学生（Nemotron）在同一确认集上跑 X2：视本次结果决定。

## 附录 A：第二学生（2026-10-28 08:40 追加，跑之前写定）
- Nemotron-3-Nano-4B Q4_K_M（`KAGE_MODEL_PATH`），同一冻结题、同一脚本，只跑 **X1**（TextEdit 6 题 × v2/v4 × 3）。假设 S1'：te-v4 > te-v2（题级精确 sign-flip，最小可达 1/32）。
- **不跑 X2**：该学生在计算器上此前所有条件均为 0（v2/v4/v5、有无规则、有无计划，共 0/108，`evidence/reports/g0-nemotron`），五臂会落在地板上，无法区分条件。论文照实写明这一点。
- 输出 `~/.kage/g0/confirm-nemotron/` → `evidence/reports/g0-confirm/raw-nemotron/`。
