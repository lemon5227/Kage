# Kage 论文 v0.4 独立数值审计（2026-10-27）

审计对象：`docs/paper/draft.md`（v0.4，218 行，当前稿）、`docs/paper/versions/draft-v0.3.md`（前稿，369 行）、
`docs/paper/review-codex-2026-10-27.md`（前审）。本报告不修改论文，只做独立复核。

- 复核脚本：`docs/paper/deepseek-support/audit.py`（python3 + 标准库；无网络/模型/教师/GPU 调用；不 import、不运行前审的
  `docs/paper/v0.4-support/recompute.py`，只把它产出的 `audit.json` 当作对照物）。
- 机器可读结果：`docs/paper/deepseek-support/audit.json`（本次运行全部断言通过）。
- 原始证据：`eval/stream_v1/eval.json`、`eval/stream_web_v1/eval.json`、`eval/desktop_v1/tasks.json`、
  `evidence/reports/{e1,e2,e2b,c2,c3,c4,d7,g0,r2,r3,r3b,r3c,r3d,r3e,...}`、`evidence/kaggle/v{5,6,7,11,17,19,26,27,28,29,30,31,32,33}-results.tar.gz`
  内的 `checkpoints.jsonl`（用 `tarfile` 在内存里读，未解包、未改动）、`docs/paper/v0.4-support/SHA256SUMS`、`evidence/SHA256SUMS`。
- v0.4 正文行号均指 `docs/paper/draft.md`；前审行号指 v0.3，已按内容而非行号对齐。

**一句话结论**：v0.4 的表 1–7 与正文绝大多数数字都能由仓库公开证据复算（`audit.json` 的 45 条数值声明中
44 条相符、1 条无法核验），没有发现抄错或编造的主结果；问题集中在**口径披露、跨会话比较、任务级显著性**和
少数出处/范围表述（§7 列出）。唯一无法独立核对的是 `US$1.83`（私有账本）。

---

## 0. 结论摘要

1. **主表全部相符**：表 2（C4 第一轮）、表 3（TextEdit 工具）、表 4（G0 规则迁移）、表 5（R3 系列）、表 6（训练/回放）、
   表 7（D7 路由）逐格与 `evidence/kaggle/*` 的 `checkpoints.jsonl`、`evidence/reports/g0/*/results.jsonl`、
   `evidence/reports/d7/*.json` 一致（§2.2–§2.7）。表 5 的旧基线 30/15/10 与 64/34/34/62/65 等全部复算命中。
2. **E-1 的 /48 分母证实是“24 题 × 2 条流”与“单次评测复制”混用**：A3=42/48、A4=39/48 是两条真实学习流；
   A0=14/48 实际是 7/24 复制两次；**A1=12/48 实际是 6/24 复制两次**，但论文只说明了“raw baseline is duplicated”，
   没有说明 budget-matched retry 也是复制（§6(iii)，风险项 R4）。
3. **任务级（簇级）统计**：`1/18→14/18`（6 题）与 `4/18→17/18`（6 题）在任务级恰好落在最小可达 p=0.03125；
   E-1 A3/A4 vs A0（24 题）p<2e-4、R3 族内（24 题）p=3.4e-4、R3 迁移族（12 题）p=0.047 站得住；
   但 C4“全部 30 题 29→41/90”任务级 p=0.080、C4 打包/状态表 p=0.19/0.75、C4 第二轮“R3e 发票 7/18 vs 0/18”任务级 p=0.25
   （3 个有信息任务，已到最粗粒度）**不显著**（§5）。
4. **发现一处论文内部数字不一致**：§4.1 “Later raw evaluations ranged from 7 to 13” 与同仓库 v31 锚点 `A0=6/24` 不符，
   全部可复算的原始评测范围是 **6–13/24**（7,10,13,7 为 E-2b/v6 四次重复，6 为 v31 锚点，见 §6(ix)）。
5. **R3e 3251 vs 3257 已解释**：`data-stats.json` 的 3257 是预处理后行数，`train-config.json` 记录 `skipped_too_long=6`，
   3257−6=3251；R3b 同理 2787−6=2781。Table 6 用 3251/2781 是“实际训练条数”，正确，但论文没有注这一点（风险项 R5）。
6. **前审 P1-1…P1-7、P2-1…P2-3 的事实判断基本全部成立**，仅个别例子不够精确：P1-6 的“原始结果也有 15 步”实际最大 20 步
   （15 步确实存在，但最大值是 20，v0.4 的“6–20”正确）；P2-3 只点了 v32/v33/G0/D7 漏检，实际 `evidence/SHA256SUMS`
   还漏 r3e、C4 round2、eval 清单等；P1-3 引用的“303 条写文件步骤”在原始数据里是 304 条 `write_file` 目标
   （202 条无推理 + 102 条有推理；303=排除 1 条负例族），前审照抄报告，不能算错但值得注明（§4）。
7. **唯一无法核验**：`US$1.83`。论文说 “preceding project report records US$1.83”，但仓库内技术报告
   `docs/report/kage-tech-report.md` §7 写的是 “US$1.12 was spent over all experiments”（截至 10-16，总预算 US$2.00）；
   `US$1.83` 只出现在 `docs/worklog/2026-10-claude.md:652`；用报告里残留的账本余额（d7/README.md、g0 的 demo teach-log 为 2.2145，
   r3d rationalize-stats 为 2.2196，cap=US$4）反推总花费约 US$1.78–1.79。故 1.83 无法从公开证据独立重建，
   且“出处=前项目报告”与仓库内报告不符（§2.9，风险项 R6）。

---

## 1. 审计方法与复现

```sh
# 在 worktree 根目录执行（不需要网络、模型或教师 key）
python3 docs/paper/deepseek-support/audit.py     # 写出 docs/paper/deepseek-support/audit.json
```

`audit.py` 独立实现：`tarfile` 内存读取 Kaggle 归档的 `checkpoints.jsonl`；精确任务级符号翻转检验用
子集和 DP（枚举 2^m 种符号，m=非零配对差；m≤24 时精确、秒级）；任务级配对 bootstrap 用 20,000 次重采样（seed=20261027）；
执行层 Fisher 只作为对照量，不作为本报告的证据标准。

对照前审复算：前审 `docs/paper/v0.4-support/recompute.py` 只算 R2/G0/D7/压缩包计数，未做任务级统计、未区分 E-1 的
`/48` 口径、未核对 `evidence/SHA256SUMS` 覆盖。本审计在**表 2、表 3、表 4、表 5、表 6、表 7 的数值上与论文及前审 audit.json 一致**，
新增了任务级统计、E-1/A1 复制分母、C3 原始归档复核、校验清单覆盖和 R3e 3251/3257 解释。

数据口径说明（全部由脚本从清单/配置直接读出，不取自报告文字）：

| 清单 | 任务数 | 族 | 来源 |
|---|---:|---|---|
| Kage-Stream `eval/stream_v1/eval.json` | 48 | 4 个 learned（各 6）+ text_normalize 6 + config_migrate 6 + 3 个负例族（4+4+4） | 文件 |
| Kage-Web `eval/stream_web_v1/eval.json` | 30 | web_invoice/web_prefs/web_catalog/web_form/web_lookup 各 6 | 文件 |
| Desktop-v1 `eval/desktop_v1/tasks.json` | 15 | calculator 6、textedit 6、settings_read 3；split=train 10 / test 5；max_steps 6–20 | 文件 |
| D7 `eval/intent_v1/*.jsonl` | 30/30/40/… | 每套一题一预测 | 文件 |

---

## 2. v0.4 逐条数值核对

判定：**相符**＝可用仓库证据复算并一致；**不符**＝复算不一致；**无法核验**＝证据不在仓库或私有；
**单位问题**＝数值一致但分母/口径需更正或说明。备注列写清差异。

### 2.1 表 1（单位与范围，draft.md:39–46）

| 论文章节/行 | 论文中的数字 | 你重算的数字 | 证据路径 | 判定 |
|---|---|---|---|---|
| 表 1 行 1（E-1/E-2 文件） | 24 in-family、12 held-out、12 negative / 次评测；两条学习流；原始基线被复用 | 清单 48=24+12+12；v6/v7 每条学习臂 2 个 seed（seed1/seed2）；v6/A0、v5/A1 各只有 1 次评测（被复制成 /48） | `eval/stream_v1/eval.json`；`evidence/kaggle/v{5,6,7}-results.tar.gz` | 相符（口径见 §6(iii)） |
| 表 1 行 2（C4 浏览器） | 30 tasks：每族 6；每臂 3 次推理重复 | 5 族 × 6 = 30；v28 每臂 r1–r3 三份结果；30×3=90 | `eval/stream_web_v1/eval.json`；`evidence/kaggle/v28-results.tar.gz` | 相符 |
| 表 1 行 3（G0） | 10 训练题 + 5 变体；每题 3 次重复 | 15 题，split train=10/test=5；每臂每题 3 条 results | `eval/desktop_v1/tasks.json`；`evidence/reports/g0/*/results.jsonl` | 相符 |
| 表 1 行 4（R3 系列） | 24 learned-file、12 held-out-file、18 learned-web；每 adapter 3 次推理；1 个训练 seed | 24/12/18 均从清单核出；v26/v29–v32 每臂 r1–r3；5 份 train-config 均 seed=0 | `eval/stream_v1/eval.json`、`eval/stream_web_v1/eval.json`、`evidence/reports/r3*/train-config.json` | 相符 |
| 表 1 脚注（D7） | 每套 30 条，评测一次 | 每套 30 行、一题一预测；`day` 字段的评测在 intent_eval.py 里只对 calendar 行另算 | `evidence/reports/d7/{heldout,v2-heldout2}.json`；`scripts/experiments/intent_eval.py` | 相符 |

### 2.2 表 2（C4 第一轮，draft.md:66–73）— 全部相符

| 论文章节/行 | 论文中的数字 | 你重算的数字 | 证据路径 | 判定 |
|---|---|---|---|---|
| 表 2 V1 | 设置 1/18；全部 29/90 | 设置 1/18；全部 29/90（invoice 0、prefs 1、catalog 9、form 1、lookup 18） | `evidence/kaggle/v28-results.tar.gz`（V1-r1..r3） | 相符 |
| 表 2 V2 | 设置 14/18；全部 41/90 | 14/18；41/90（prefs 5,5,4；catalog 4,2,1；form 0,1,1；lookup 18） | 同上（V2-r1..r3） | 相符 |
| 表 2 V2PK | 设置 14/18；全部 36/90 | 14/18；36/90（prefs 4,5,5；catalog 1,1,2；form 0） | 同上（V2PK-r1..r3） | 相符 |
| 表 2 V2PKST | 设置 17/18；全部 39/90 | 17/18；39/90（prefs 6,6,5；catalog 2,1,1；form 0） | 同上（V2PKST-r1..r3） | 相符 |
| 表 2 脚注 | 单字段变化=14/18；17/18 含额外干预 | 14/18 只来自 checked 字段（V2）；17/18 需 + 打包 + 状态表（V2PKST） | `evidence/reports/c4/analysis.md` | 相符 |

### 2.3 表 3（TextEdit 工具，draft.md:83–89）— 全部相符

| 论文章节/行 | 论文中的数字 | 你重算的数字 | 证据路径 | 判定 |
|---|---|---|---|---|
| 表 3 整段 fill | 0 / 3 / 1 / 4（18） | typo 0/6（te_fix+te_fix2）、append 3/6（te_append 1 + te_append2 2）、write 1/6（te_write 1 + te_write2 0）→ 4/18 | `evidence/reports/g0/a0-baseline-v1/results.jsonl`（3 训练题）+ `a0-test-v2/results.jsonl`（3 测试题） | 相符（该行为两臂拼接，建议脚注说明） |
| 表 3 v3 | 6 / 2 / 0 / 8（18） | typo 6/6、append 2/6、write 0/6 → 8/18 | `evidence/reports/g0/a0-te-v3/results.jsonl`（6 题） | 相符 |
| 表 3 v4 | 6 / 5 / 6 / 17（18） | typo 6/6、append 5/6、write 6/6 → 17/18 | `evidence/reports/g0/a0-te-v4/results.jsonl` | 相符 |
| 脚注 | 6 个不同 TextEdit 题、各 3 次；非新的后选择测试 | 6 题 × 3 = 18；15 题全部是开发用题 | `eval/desktop_v1/tasks.json`；`evidence/reports/g0/analysis.md` | 相符 |
| 正文 4/18→17/18 | 同上；p=2e-5（v0.3 引用） | 17/18 vs 4/18 执行层 Fisher p=2.008e-5 | 同上 | 相符 |

### 2.4 表 4（G0 规则迁移，draft.md:97–104）— 全部相符

5 个测试变体（calc_chain2、calc_chain3、te_fix2、te_append2、te_write2），每题 3 次：

| 论文章节/行 | 论文中的数字 | 你重算的数字 | 证据路径 | 判定 |
|---|---|---|---|---|
| 表 4 无规则 | Calculator 1、TextEdit 2、合计 3 | 1 + 2 = 3/15 | `evidence/reports/g0/a0-test-v2/results.jsonl` | 相符 |
| 表 4 系统提示 | 1 / 2 / 3 | 1 + 2 = 3/15 | `a0-test-v2-lessons/results.jsonl` | 相符 |
| 表 4 仅计划 | 4 / 2 / 6 | 4 + 2 = 6/15 | `a0-test-v2-planonly/results.jsonl` | 相符 |
| 表 4 规则在任务旁+计划 | 5 / 5 / 10 | 5 + 5 = 10/15 | `a0-test-v2-plan/results.jsonl` | 相符 |
| 正文 “2 Calculator + 3 TextEdit 变体、各 3 次” | 5 题 ×3 | 5 题 ×3 | `eval/desktop_v1/tasks.json`（split=test） | 相符 |

### 2.5 表 5（R3 系列，draft.md:122–131）— 全部相符

| 版本 | 论文 learned files /72 | 重算 | 论文 held-out /36 | 重算 | 论文 learned web /54 | 重算 | 判定 |
|---|---:|---:|---:|---:|---:|---:|---|
| Base v26 | 30 | 30（9+12+9） | 15 | 15（5+5+5） | 10 | 10（invoice 0 / prefs 2 / catalog 8） | 相符 |
| R3 | 64 | 64（22+22+20） | 1 | 1（1+0+0） | 21 | 21（8+4+9） | 相符 |
| R3b | 34 | 34（11+11+12） | 15 | 15（5+5+5） | 31 | 31（invoice 13 / prefs 6 / catalog 12） | 相符 |
| R3c | 34 | 34（10+10+14） | 2 | 2（1+0+1） | 22 | 22（invoice 10 / prefs 3 / catalog 9） | 相符 |
| R3d | 62 | 62（20+21+21） | 6 | 6（1+2+3） | 20 | 20（invoice 4 / prefs 5 / catalog 11） | 相符 |
| R3e | 65 | 65（22+21+22） | 1 | 1（1+0+0） | 22 | 22（invoice 7 / prefs 2 / catalog 13） | 相符 |

证据：`evidence/kaggle/v26-results.tar.gz`（A0-r1..r3、L3-r1..r3）、`v29/v30/v31/v32`（对应 r3b/r3c/r3d/r3e 的 r1..r3 与单次 A0 锚点）；
每格 = 24（或 12/18）题 × 3 次推理。脚注“R3 与显示的 base 在 v26；R3b–R3e 来自各自会话”也已核对（v26 同会话，v29–v32 各 1 次锚点）。

### 2.6 表 6（训练/回放/步数，draft.md:143–151）— 数值相符，需补 3251/3257 注

| 版本 | 论文 examples | 重算 train-config `examples` | 论文 replay | 重算 replay | 论文 steps | 重算 `steps` | 判定 |
|---|---:|---:|---:|---:|---:|---:|---|
| R3 | 1,677 | 1,677（val 223） | 0 | 0 | 420 | 420 | 相符 |
| R3b | 2,781 | 2,781 | 1,400 | 1,400（agentnet 800 + toucan 600） | 696 | 696 | 相符 |
| R3c | 2,266 | 2,266 | 879 | 879（agentnet 123 + toucan 756） | 567 | 567 | 相符 |
| R3d | 2,736 | 2,736 | 879 | 879 | 684 | 684 | 相符 |
| R3e | 3,251 | **3,251（data-stats 写 3,257，差 6 = skipped_too_long）** | 1,400 | 1,400 | 813 | 813 | 相符（建议注脚） |

证据：`evidence/reports/r{3,3b,3c,3d,3e}/train-config.json`、`.../data-stats.json`、`.../replay-stats.json`。
所有 5 份配置均 `epochs=2.0`、`seed=0`、`lr=1e-4`、`rank=16`、`max_tokens=8192`、`dtype=bf16`（论文 §6.1 的“两个 epoch / 1e-4 / rank 16 / 8192”相符）。
五份 `wall_seconds` 合计 20,748.2 s = 5.7634 h（论文“约 5.8 小时”相符；不含采集/评测/其他运行）。

### 2.7 表 7（D7 路由，draft.md:159–164）— 全部相符

| 论文章节/行 | 论文中的数字 | 你重算的数字 | 证据路径 | 判定 |
|---|---|---|---|---|
| 表 7 第一行 | 10 类；15/30、30/30、30/30 | legacy 15/30、clef 30/30、combined 30/30 | `evidence/reports/d7/heldout.json` | 相符 |
| 表 7 第二行 | 12 类；16/30、30/30、28/30 | legacy 16/30、clef 30/30、combined 28/30；低于 0.8 阈值 2 条 | `evidence/reports/d7/v2-heldout2.json` | 相符 |
| 脚注 | 2 条正确但在阈值下；fallback 完成度未按该指标评测 | 阈值下正好 2 条，且都是 clef 判对、combined 变 'other' 而错 | `scripts/experiments/intent_eval.py`（combined=阈值后标签） | 相符（“fallback”列语义建议说明，见风险 R11） |

### 2.8 正文数字（按章节，draft.md 行号）

| 论文章节/行 | 论文中的数字 | 你重算的数字 | 证据路径 | 判定 |
|---|---|---|---|---|
| 摘要:9 | 1/18 → 14/18 | V1 1/18、V2 14/18 | `evidence/kaggle/v28-results.tar.gz` | 相符 |
| 摘要:9 | 4/18 → 17/18 | 4/18、17/18 | `evidence/reports/g0/{a0-baseline-v1,a0-test-v2,a0-te-v4}` | 相符 |
| 摘要:9 | 10/15 vs 3/15 vs 6/15；仅 5 个不同任务 | 10/15、3/15、6/15；5 题 | `evidence/reports/g0/{a0-test-v2-plan,a0-test-v2,a0-test-v2-planonly}` | 相符 |
| 摘要:9 | 1,900 条、151 个唯一任务 | 1,900 行、151 个 task_id（446 个 task/source/attempt 组合） | `evidence/reports/r2/sft-v21.jsonl.gz` | 相符 |
| 摘要:9 | 30/72 → 64/72；15/36 → 1/36 | 30/72、64/72；15/36、1/36 | `evidence/kaggle/v26-results.tar.gz` | 相符 |
| 摘要:9 | 41/45，15 题，开发期复用 | 41/45（29/30 + 12/15） | `evidence/reports/g0/a0-final-v4-plan/results.jsonl` | 相符 |
| §2:23 | 5 loop steps / 6 model requests / 12 tool dispatches / 150 s | max_steps=5、max_model_calls=6、max_tool_actions=12、timeout_s=150 | `evidence/kaggle/v26-results.tar.gz:e1/r3/file/A0-r1/config.json` | 相符 |
| §2:23 | 浏览器 8 步 / 10 次模型请求 | browser.max_steps=8、max_model_calls=10、timeout 360 s | `evidence/kaggle/v28-results.tar.gz:e1/c4/V1-r1/config.json` | 相符 |
| §2:23 | 桌面 6–20 步（manifest） | tasks.json 的 max_steps 取值 {6,8,10,14,16,20}，范围 6–20 | `eval/desktop_v1/tasks.json` | 相符 |
| §2:23 | 文件基线与桌面循环 temperature 0.7 | 代码默认 0.7（`core/model_provider.py:116`；`core/computer_use/desktop_agent.py:178`），`scripts/experiments/kaggle_e1.py:395` 注释亦写 0.7 | 代码文件；归档 config 未记录 temperature（见 §6(viii)） | 相符（推断级） |
| §2:25 | G0 生成 4 条 lesson 并复用 | lessons.json：calculator 1 + textedit 3 = 4 条 | `evidence/reports/g0/a0-baseline-v1/lessons.json` | 相符 |
| §2:29 | LoRA rank 16、response-only、attention-output+MLP | train-config rank=16、targets=safe；`lora_train.py` 的目标正则 `self_attn.o_proj` + `mlp.(gate/up/down)_proj`、loss 只对 response token（labels=-100 屏蔽 prompt）；r3/analysis.md 记录 104 个模块/1894 万参数 | `evidence/reports/r3/train-config.json`、`scripts/experiments/lora_train.py:28-29,45-50,176`、`r3/analysis.md` | 相符 |
| §2:31 | 教师预算上限 US$4 | `GLOBAL_TEACHER_CAP_USD = 4.00` | `core/evolution/teacher_budget.py:15` | 相符 |
| §2:31 | 前项目报告记录 US$1.83 | 仓库技术报告写 US$1.12（10-16）；1.83 只在 10-26 工作日志；账本余额反推约 1.78–1.79 | `docs/report/kage-tech-report.md` §7；`docs/worklog/2026-10-claude.md:652`；`evidence/reports/d7/README.md`、`g0/demo/teach-log.json`、`r3d/rationalize-stats.json` | **无法核验**（且出处表述不符） |
| §2:31 | 5 份 R3 配置合计约 5.8 小时 | 20,748.2 s = 5.7634 h | `evidence/reports/r3*/train-config.json` | 相符 |
| §3:35 | 4 learned + 2 held-out + 3 negative 文件族 | 清单 9 族 = 4+2+3 | `eval/stream_v1/eval.json` | 相符 |
| §3:35 | Web：invoice/settings/hotel 3 个 fixture + held-out form + lookup | 清单 5 族各 6 题 | `eval/stream_web_v1/eval.json` | 相符 |
| §3:35 | Desktop 15 题：6 Calculator、6 TextEdit、3 Settings | 6/6/3 | `eval/desktop_v1/tasks.json` | 相符 |
| §4.1:56 | 42/48、39/48、14/48、12/48 | A3 42/48、A4 39/48；A0=7/24×2=14/48；A1=6/24×2=12/48 | `evidence/kaggle/v{5,6,7}-results.tar.gz` | 相符（口径见 §6(iii)） |
| §4.1:56 | Later raw 7–13/24 | 可复算：v6=7、v11=10/13/7，另 v29–v32 锚点 10/11/**6**/11 → 实际 6–13 | 同上 + `v29..v32` | **单位/范围问题**（若指 E-2b 四次重复则 7–13 正确；若指全部后验评测应为 6–13） |
| §4.1:58 | C3 发票规则 0/24 → 14/24 | 4 次原学生评测 0/24；AGL+A4mGL 的 cp44 合计 14/24（1+3+4+6） | `evidence/kaggle/v{17,19}-results.tar.gz` | 相符 |
| §4.1:60 | 主动求助 120 个流任务只触发 1 次 | A5 `before_attempt=1`（2 seed × 60 = 120） | `evidence/reports/e2b-report/summary.json` | 相符 |
| §4.1:60 | 固定选择 45/48；架构师 41/48 | A6-fixed cp60 45/48；A6 cp60 41/48 | `evidence/reports/e2b-report/report.md` | 相符 |
| §4.2:75 | 第二轮 18/18 设置、41/90 | v33 V2PKST：settings 18/18、总 41/90（13+14+14） | `evidence/kaggle/v33-results.tar.gz` | 相符 |
| §4.2:75 | 保存前 checker 59 次 0 拦截 | 59 个 `checker.jsonl`、59 条记录、blocked 全 false、wrong 全空 | 同上 | 相符 |
| §5:108 | 题均差 2/3,2/3,1,0,0；32 种符号；0.25；执行层 Fisher 0.025 | 逐题均值差 [2/3,2/3,1,0,0]；2^5=32；双侧精确 p=**0.25**（3 个非零题即最小可达 2/2^3）；执行层 Fisher=0.02533 | `evidence/reports/g0/{a0-test-v2,a0-test-v2-plan}/results.jsonl` | 相符 |
| §5:110 | 41/45；29/30、12/15；17/18、15/18、9/9；基线 19/30、3/15 | 41/45；29/30、12/15；calculator 17/18、textedit 15/18、settings 9/9；19/30、3/15 | `evidence/reports/g0/{a0-final-v4-plan,a0-baseline-v1,a0-test-v2}` | 相符 |
| §6.1:116 | 四个采集报告 704 attempts / 472 successes | 200+200+200+104=704；170+134+108+60=472；samples_kept 合计 1,900 | `evidence/reports/r2/{file-a,file-b,browser-forms,browser-catalog}-stats.json` | 相符（control 120 次未计入，正确） |
| §6.1:116 | 446 个 task/source/attempt 组合 | 446 | `evidence/reports/r2/sft-v21.jsonl.gz` | 相符 |
| §6.1:118 | 1,677 训练 / 223 验证；2 epoch、1e-4、rank 16、8192 | 1,677/223；2.0；1e-4；16；8192；seed 0 | `evidence/reports/r3/{data-stats,train-config}.json` | 相符 |
| §6.2:133 | R3 (22,22,20) vs base (9,12,9)；(1,0,0) vs (5,5,5) | 逐次合计精确一致 | `evidence/kaggle/v26-results.tar.gz` | 相符 |
| §6.2:133 | R3e (22,21,22)、(1,0,0)；同会话锚点 11/24、7/12 | 逐次合计 22/21/22、1/0/0；v32 A0 单次 11/24、7/12 | `evidence/kaggle/v32-results.tar.gz` | 相符 |
| §6.2:135 | R3e 发票 7/18 vs 同接口 raw 0/18；0/54 是 3 个 raw 臂合并 | R3EV2PKTSTCK invoice 7/18；V2PKTSTCK 0/18；V2PKST/V2PKTST/V2PKTSTCK 各 0/18 → 0/54 | `evidence/kaggle/v33-results.tar.gz` | 相符 |
| §6.2:135 | 通用能力 27–28/30 | R3 28、R3b 28、R3c 28、R3d 27、R3e 28（R3 A0 28） | `evidence/reports/r3*/summary.json` | 相符 |
| §6.3:139 | 202 条无推理 write_file、101 条有推理 | 202 条无推理 ✓；有推理 = **102** 条（其中 1 条属负例族 lookalike_readonly，排除后 101） | `evidence/reports/r2/sft-v21.jsonl.gz` | 相符（101 需注明口径） |
| §6.3:141 | 随机回放 1,400 vs LESS 879；来源构成不同 | 1,400（800+600）；879（123+756） | `evidence/reports/{r3b,r3c}/replay-stats.json` | 相符 |
| §7:161 | 表 7 数值 | 见 §2.7 | `evidence/reports/d7/*.json` | 相符 |
| §7:168 | 36.5→0.8 s；16 s（失败工具循环）→2.3 s | D7 README 同值（私有活动日志，仓库只有汇总） | `evidence/reports/d7/README.md` | 相符（报告级，不可独立复算） |
| §9:188 | 适配器位置私有；校验索引未覆盖全部最新产物 | 见 §6(v) | `evidence/SHA256SUMS`；`evidence/reports/r3/analysis.md` | 相符 |

### 2.9 无法核验项

`US$1.83`（draft.md:31）。论文已写 “this revision does not independently reconcile that private ledger”，这一保留是恰当的；
但“preceding project report records US$1.83”这一出处不准确：仓库内技术报告写 US$1.12，1.83 只见于工作日志，
按报告内残留余额反推约 US$1.78–1.79（cap 4.00）。建议改为“项目私有账本记录约 US$1.8（未在公开仓库核对）”，
不要把它挂在技术报告名下。

另有三类“数字可读但不可独立复算”的内容，已在正文被限定为报告级/案例级，不判为不符：
（a）读回验证 48/72→0（v0.4 已删去数字，只留定性表述，未复算 trace）；（b）硬件（M4 Mac、Kaggle T4、Colab A100）只写在报告里；
（c）D7 延迟来自私有活动日志，仓库只有汇总表。

---

## 3. v0.3 中被前审引用、且与 v0.4 不同的数字

| v0.3 位置/表述 | 前审核验 | 我的重算/证据 | v0.4 的处理 | 我的判定 |
|---|---|---|---|---|
| v0.3:19 “making one observation field explicit … 1/18 to 17/18 (p < 1e-5)” | P1-4：应为 1/18→14/18；17/18 是组合接口 | V1 1/18、V2 14/18、V2PKST 17/18（v28）；执行层 Fisher：1→14 为 p=2.0e-5（并非 <1e-5），1→17 为 p=7.2e-8 | 摘要与表 2 改为 1/18→14/18，17/18 单列为组合 | 前审正确；v0.4 已修正 |
| v0.3:186 “R2 collected 1,900 guided successes” | P1-5：1900 是训练样本，不是成功轨迹 | 1,900 行 / 151 task / 446 组合；采集层 704 attempts、472 successes | 改为 action-level examples、151 任务，并列 472/446 | 前审正确；v0.4 已修正 |
| v0.3:64 “at most 5–8 steps and 6–10 model calls” | P1-6：桌面 manifest 是 6–20 步 | 文件 5/6/12/150 s；浏览器 8/10；桌面 max_steps 6–20（实测步数最大 20） | §2 分域写明 | 前审正确；v0.4 已修正 |
| v0.3:100 “not bit-reproducible even at temperature 0” | P1-6：7–13/24 波动来自 temperature 0.7 | 代码默认 0.7（model_provider、desktop_agent）；kaggle_e1.py:395 注释写 0.7；归档 config 未记录温度 | 改为“历史基线与桌面循环用 0.7，不能作为温度 0 确定性的证据” | 前审正确；v0.4 已修正 |
| v0.3:199 “7/18 invoices where the raw student solves 0/54” | P1-7（相关）：指标/比较口径问题 | 同接口匹配对照应为 0/18；0/54 是 V2PKST+V2PKTST+V2PKTSTCK 三个 raw 臂合并 | §6.2 用 0/18 匹配对照，明确 0/54 是合并 | 前审正确；v0.4 已修正 |
| v0.3:29 “30/30 on two held-out phrasing sets” | P1-7：第二批阈值后是 28/30 | 表 7 已分开：30/30 与 28/30；阈值下 2 条 | 表 7 两列并列 | 前审正确；v0.4 已修正 |
| v0.3:24 “30/72 → 65/72” | P1-3/P1-1：不同版本混用 | R3=64/72（v26）；R3e=65/72（v32）；base=30/72（v26） | 摘要用 R3 的 64/72，表 5 列全部版本 | v0.4 表述更准确 |
| v0.3:181 “29/30 vs 19/30 p=0.003；12/15 vs 3/15 p=0.003” | P1-1：执行层 Fisher 被当作任务级证据 | 执行层 Fisher：29/30 vs 19/30 = 0.00247；12/15 vs 3/15 = 0.00281（≈0.003，数值本身对）；任务级：10 训练题 p=0.03125（6 个有信息题）、5 个测试变体 p=0.125（4 个有信息题）、15 题合并 p=0.00195 | v0.4 删除主结果中的逐运行显著性 | 前审正确（数值对、推断单位错） |
| v0.3:35 “41/45 … unseen variants” | P1-2：变体已被开发使用 | 最终配置与 a0-test-v2 使用同一批 5 个变体（config 任务列表可证） | v0.4 标注开发集 | 前审正确；v0.4 已修正 |
| r3b 报告“303 条写文件步骤中 202 无推理、101 有推理” | P1-3 引用 | 原始 R2 里 write_file 目标共 **304** 行：202 无推理、102 有推理；102 中 1 行属负例族，排除后 101 | §6.3 写 202/101 | 报告口径应注明“非负例族 303 条” |

补充：v0.3 的“read-back 48/72 → 0”在 v0.4 只保留定性表述（“less post-write reading”），本审计未解析 model-traces，
不对该数下判定；前审 P1-3 对它的**解释边界**（症状≠机制）有道理，且 v0.4 已按此改写。

---

## 4. 前审 claims P1-1…P1-7、P2-1…P2-3 核验

逐条复核 `docs/paper/review-codex-2026-10-27.md`。判定：成立 / 基本成立（细节需修正）/ 不成立。

### P1-1 重复运行不能当独立任务，显著性比泛化证据强 —— **成立**

- 前审：“G0 是 5 个测试任务各跑 3 次…R3 的 /72 是 24 题 ×3，/36 是 12 题 ×3” → 与 manifest 和归档一致。
- 前审：“G0 规则＋计划相对无规则，五题平均成功率差 [2/3,2/3,1,0,0]…2^5 符号翻转双侧 p=0.25；原 Fisher p=0.025”
  → 我重算：差值精确为 [2/3, 2/3, 1, 0, 0]；32 种符号里满足 |Σ|≥7/3 的是全正/全负两组 × 两个零差题各 2 种 = 8/32 = **0.25**
  （等价于 3 个非零题的两侧 2/2^3，正好是最小可达值）；执行层 Fisher=**0.02533**。成立。
- 前审：“v32 中 R3e 有 3 次，A0 锚点只有 1 次；与 v26 基线或 pooled A0 的比较属于跨会话” → v32 目录只有
  `e1/ae/{file,web}/A0-r1`，而 r3e-r1..r3 三份；v26 的 base 是 3 次。成立。
- 未发现夸大。

### P1-2 最终 G0 的 “unseen” 已被开发过程使用 —— **成立**

- `evidence/reports/g0/analysis.md` §3 第 4 点明确写 te_write2 仍 0/3 后“下一步是接口而不是规则：给文本框“查找替换/追加”工具…”；
  最终臂 `a0-final-v4-plan/config.json` 的 tasks 列表包含全部 15 题（含 5 个 test 变体）。
- 前审说“这些题可能没进入教师学习，但已进入开发者的诊断和设计选择” → 成立（题目 split=test 与教师 lesson 来源（10 个训练题）
  可证 student-unseen，但 final 配置确实是为这些失败改的）。

### P1-3 R3 消融不能支持“提升和遗忘来自同一批样本”的确定因果 —— **基本成立，个别数字需注明口径**

- 前审：“R3b 和 R3c 都过滤无推理目标，但迁移分别 15/36、2/36；二者同族都是 34/72” → 表 5 重算完全一致。
- 前审：“过滤也不是删除全部约 300 条 write_file：r3b 报告写的是 303 条写文件步骤中 202 无推理被删、101 有推理保留”
  → 202 无推理精确复算命中；304 条 write_file 总量里 102 有推理，其中 1 条在负例族，故“303/101”是“非负例族”口径。
  这不影响前审的论点（过滤确实不是全删），但“303”应注明口径。
- 前审：“回放 1400 vs 879，不能把差别全归因到选择算法” → 且训练条数/步数也不同（2,781 vs 2,266；696 vs 567，表 6 可证）。
  成立。
- 前审“训练后少读回文件…没有强制读回干预” → v0.4 已按此降为机制候选；我未解析 trace，不重算，但前审的谨慎方向成立。

### P1-4 摘要把组合接口收益错归到一个字段 —— **成立**

- v0.3:19 原文确为 “making one observation field explicit takes a settings task from 1/18 to 17/18 (p < 1e-5)”。
- 我的重算：V1 1/18；只显式 checked 的 V2 14/18；V2＋打包＋状态表 17/18。前审给的修法（1/18→14/18，17/18 另列）正确；
  v0.4 已改。补充：v0.3 的 p<1e-5 属于 1→17 的比较（7.2e-8），正确比较 1→14 只有 2.0e-5。

### P1-5 1900 是训练步骤样本，不是成功任务轨迹 —— **成立**

- 1,900 行、151 task_id、446 task/source/attempt；每行是“上下文+一条 target 动作”，同一轨迹可多条。
- 前审建议写法与 v0.4 §6.1 一致。成立。

### P1-6 预算、温度、checker 信息边界不准确 —— **基本成立（一处例子不完整）**

- 预算：v0.3:64 “5–8 步 / 6–10 次模型调用” vs 桌面 max_steps 6–20 → 成立。前审举例“原始结果也有 15 步”：
  实际观测步数分布里有 15（2 次），但**最大值是 20**；前审举例正确但不够完整，v0.4 写 6–20 正确。
- 温度：前审说 7–13/24 的波动来自 temperature 0.7 → 代码默认 0.7（`core/model_provider.py:116/133`、
  `core/computer_use/desktop_agent.py:178`），`kaggle_e1.py:395` 注释写 “(temperature 0.7)”。成立；
  但注意**归档的 run config 没有记录 temperature**，所以“0.7”是代码/注释级证据，不是逐 run 日志级证据。
- checker：前审说 G0 teach-log 四条都有 “Checker: expected … found …”，teacher 脚本直接传 `task['expected']`
  → `a0-baseline-v1/teach-log.json` 4/4 条含该串；`scripts/experiments/desktop_run.py:281-284` 确实用 `task['expected']`
  构造。成立。

### P1-7 D7 30/30 不是完整任务成功，也不能证明 4B 不适合做选择 —— **成立**

- `scripts/experiments/intent_eval.py` 只比较 intent 标签（`sum(r[key] == r['intent'])`），
  `combined` 是“置信度<0.8 就记为 'other'”，并没有真的执行本地回退。
- 真实留出例：`v2-heldout2.json` 中 “后天下午我有空吗”：gold `intent=calendar`、`day=today`，clef `clef_day=tomorrow`、
  `conf=0.965`。日期标签与预测都错，但 intent 仍算对。成立。
- 第二批 raw Clef 30/30、阈值后 28/30（低于阈值 2 条且都是 clef 判对 → combined 错）→ 成立。
- 没有同候选/同上下文的 4B 分类基线 → 代码与数据均无此基线。成立。

### P2-1 grounded lessons 的因素尚未隔离 —— **成立**

- 配置层面：`a0-test-v2-lessons`（lessons，默认 system 模式）vs `a0-test-v2-planonly`（只有计划、无规则）
  vs `a0-test-v2-plan`（规则在任务旁 + 先写计划并说明如何应用，`core/computer_use/desktop_agent.py:149-168`）。
  plan 相对 no-lessons 同时改变了位置、注意显著性和计划要求 → “only when / 规则内容是 TextEdit 提升的必要条件”不能由这组数据隔离。
- v0.4 §5 已改写为组合干预的探索性结果。成立。

### P2-2 主线是开发者参与的诊断改进，不能写成自主自演化 —— **成立**

- C4 接口、G0 行编辑工具（desktop.py/desktop_agent.py）、R3 数据策略、D7 路由均为开发者设计；
  教师负责 lesson/示范质量，不是自主改接口。
- 前审“41/45 的 G0 配置没有表明用了 R3 LoRA” → `a0-final-v4-plan/config.json` 无 lora 字段，
  v33 的 R3E 臂才加载 adapter；成立。
- 预算：`GLOBAL_TEACHER_CAP_USD=4.00` 是教师 API 账本，不含 GPU/推理/人力；成立。v0.4 已按此改写标题与 §2。

### P2-3 报告与复现完整性 —— **成立，但清单漏检的项比前审列的更多**

- 前审：“SHA256SUMS 已列条目通过，但清单未覆盖 v32/v33 与 G0/D7” → 我核对 `evidence/SHA256SUMS`：97 条全部通过；
  未覆盖的是 **v32、v33、reports/g0、reports/d7、reports/r3e、reports/c4/round2、eval/desktop_v1、eval/intent_v1**
  （停在 v31/r3d）。前审方向正确，但列举不全。
- 前审：“适配器报告指向私有 Drive/Kaggle” → `evidence/reports/r3/analysis.md` 写明 adapter 在用户 Google Drive 与私有
  Kaggle 数据集；成立。
- 前审：“D7 原始使用日志因隐私未入库” → `d7/README.md` 明说原始对话含真实邮件标题未入库；成立。
- 前审：“开头相关工作 §7 实际为 §8” → v0.3:4 写 “discussed in §7”，而 v0.3 的 Related work 是 `## 8.`；成立。
- 前审：“编译用 Times New Roman/Songti SC” → v0.3 的 `build.sh` 确有此字体；v0.4 已改为 Latin Modern（`git diff` 可见）。
  前审正确且 v0.4 已修。

**前审结论整体**：10 条全部成立或基本成立；没有发现前审编造或严重误判。需要修正的是两处细节（P1-6 的“15 步”应写最大 20；
P2-3 的漏检清单不全）和一处口径（P1-3 的 303/101 应注明“非负例族”）。前审没有替 v0.4 完成的任务是
**全量任务级区间分析**（它只给了 G0 一个 0.25 的示例），本报告 §5 补上。

---

## 5. 任务级（簇级）统计

### 5.1 方法

- 单位：以**任务**为簇。每个任务的成功率 = 该任务 R 次推理的通过比例（R=3：0、1/3、2/3、1；E-1 的 A3/A4 是 2 条流 → 0、1/2、1；
  A0/A1 是单次评测 → 0 或 1）。
- 配对差：同一批任务上 `rate_A − rate_B` 的均值 = 配对风险差（risk difference）。
- 检验：精确的双侧任务级符号翻转（零差题不计符号）；对 m 个非零配对差，p 的分辨率是 2/2^m。
  表中同时给“任务数 k / 有信息任务 m / 最小可达 p=2/2^k（无并列时可达）”。
- 区间：对任务做 20,000 次有放回重采样，取配对差的 2.5/97.5 百分位（任务级 bootstrap 95% CI）。
- 注意：C4 v33 的“同接口 raw 对照”只有 3 次推理、6 个任务，且 6 题里只有 3 题出现差异，因此最小可达 p=0.25；
  这是粒度限制，不是效应不存在。

### 5.2 结果总表

（RD=配对风险差；CI=95% 任务 bootstrap 区间；p=精确双侧符号翻转；floor=2/2^k）

| 比较 | 任务 k / 有信息 m | 汇总 | RD [95% CI] | p | floor | 结论 |
|---|---|---:|---|---:|---:|---|
| **C4 设置 V1→V2**（6 题） | 6 / 6 | 14/18 vs 1/18 | +0.722 [0.500, 0.944] | **0.03125** | 0.03125 | 站住，但已到 6 题能给出的最小 p |
| C4 全部 30 题 V1→V2 | 30 / 10 | 41/90 vs 29/90 | +0.133 [0.011, 0.267] | 0.0801 | 1.86e-9 | 任务级不显著 |
| C4 V2→V2PK（打包） | 30 / 6 | 36/90 vs 41/90 | −0.056 [−0.122, 0.000] | 0.1875 | 1.86e-9 | 不显著；论文未据此下结论 |
| C4 V2PK→V2PKST（状态表） | 30 / 3 | 39/90 vs 36/90 | +0.033 [−0.022, 0.111] | 0.750 | 1.86e-9 | 不显著；论文只说 17/18 含额外干预 |
| **TextEdit v4 vs 整段 fill**（6 题） | 6 / 6 | 17/18 vs 4/18 | +0.722 [0.500, 0.944] | **0.03125** | 0.03125 | 站住，同样在最小 p |
| **G0 plan vs 无规则**（5 题） | 5 / 3 | 10/15 vs 3/15 | +0.467 [0.133, 0.800] | 0.25 | 0.0625 | 不显著；论文已写 0.25 |
| G0 仅计划 vs 无规则 | 5 / 2 | 6/15 vs 3/15 | +0.200 [0.000, 0.467] | 0.50 | 0.0625 | 不显著 |
| G0 系统规则 vs 无规则 | 5 / 2 | 3/15 vs 3/15 | 0.000 [−0.200, 0.200] | 1.00 | 0.0625 | 无差异（与“系统提示无效”一致） |
| **G0 final vs 旧基线**（15 题） | 15 / 10 | 41/45 vs 22/45 | +0.422 [0.244, 0.600] | **0.00195** | 6.1e-5 | 站住（但为开发集） |
| **E-1 A3 vs A0**（24 题） | 24 / 18 | 42/48 vs 14/48 | +0.583 [0.354, 0.792] | **1.91e-4** | 1.19e-7 | 站住 |
| **E-1 A4 vs A0** | 24 / 14 | 39/48 vs 14/48 | +0.521 [0.333, 0.708] | **1.22e-4** | 1.19e-7 | 站住 |
| E-1 A3 vs A1 | 24 / 17 | 42/48 vs 12/48 | +0.625 [0.438, 0.792] | 1.53e-5 | 1.19e-7 | 站住 |
| E-1 A3 vs A4（记忆 vs 技能） | 24 / 9 | 42/48 vs 39/48 | +0.063 [−0.125, 0.250] | 0.672 | 1.19e-7 | 无差异；与论文“不能证明技能库更好”一致 |
| **R3 vs v26 base，族内 24 题** | 24 / 16 | 64/72 vs 30/72 | +0.472 [0.278, 0.667] | **3.36e-4** | 1.19e-7 | 站住 |
| **R3 vs base，迁移族 12 题** | 12 / 7 | 1/36 vs 15/36 | −0.389 [−0.667, −0.111] | **0.0469** | 4.88e-4 | 站住但只是勉强 <0.05 |
| R3 vs base，learned web 18 题 | 18 / 9 | 21/54 vs 10/54 | +0.204 [0.000, 0.407] | 0.109 | 7.6e-6 | 不显著 |
| **R3e vs v32 锚点，族内** | 24 / 13 | 65/72 vs 11/24 | +0.444 [0.250, 0.639] | **7.3e-4** | 1.19e-7 | 站住 |
| **R3e vs 锚点，迁移族** | 12 / 8 | 1/36 vs 7/12 | −0.556 [−0.833, −0.250] | **0.0156** | 4.88e-4 | 站住 |
| R3b vs v29 锚点，迁移族 | 12 / 9 | 15/36 vs 7/12 | −0.167 [−0.528, 0.222] | 0.512 | 4.88e-4 | 与 raw 不可区分（支持“回放保住迁移”） |
| **R3b vs R3c，迁移族** | 12 / 7 | 15/36 vs 2/36 | +0.361 [0.167, 0.583] | **0.0156** | 4.88e-4 | 站住（跨会话，需注意） |
| R3d vs v31 锚点，迁移族 | 12 / 8 | 6/36 vs 5/12 | −0.250 [−0.611, 0.111] | 0.258 | 4.88e-4 | 不显著（论文未称显著） |
| **R3e vs R3b，迁移族** | 12 / 7 | 1/36 vs 15/36 | +0.389 [0.167, 0.611] | **0.0156** | 4.88e-4 | 站住 |
| C4 第二轮 R3e+接口 vs 同接口 raw，全部 30 题 | 30 / 4 | 47/90 vs 41/90 | +0.067 [−0.011, 0.167] | 0.25 | 1.86e-9 | **不显著** |
| **C4 第二轮 R3e vs 同接口 raw，发票 6 题** | 6 / 3 | 7/18 vs 0/18 | +0.389 [0.111, 0.722] | 0.25 | 0.03125 | **不显著**（3 个有信息题，p 已到 0.25 的粒度下限） |
| C4 第二轮 checker 臂 vs V2PKST，30 题 | 30 / 0 | 41/90 vs 41/90 | 0.000 [0.000, 0.000] | 1.0 | 1.86e-9 | 无差异（与 59 次 0 拦截一致） |

### 5.3 哪些结论在任务单位下站住 / 消失

**站住（可作为主张）**
1. E-1：轨迹记忆/技能库相对原学生的大幅提升（A3/A4 vs A0，p≈1e-4，24 题）——即使按簇算也很强。
2. R3：族内文件题提升（+0.47，p=3.4e-4，24 题）与迁移族退化（−0.39，p=0.047，12 题）；
   R3e 复现迁移退化（p=0.0156）且族内更高；R3b 的迁移恢复与 raw 不可区分（p=0.51）。
3. R3b vs R3c 的迁移差（15/36 vs 2/36，p=0.0156）与 R3e vs R3b 的迁移差（1/36 vs 15/36，p=0.0156）——
   支持“回放的选择/覆盖决定遗忘是否回来”这一**描述性**对照（跨会话，训练量也不同，不能当因果）。
4. 两个“接口修复”标题数字（设置 1/18→14/18、TextEdit 4/18→17/18）在 6 题上 p=0.03125，
   这是 6 题能给出的最小 p；方向与效应量（RD≈0.72）都很强，但论文最好显式写“6 题时的检验粒度下限是 0.031”。
5. G0 最终配置 vs 旧基线（15 题，p=0.00195）在任务级仍显著，但它是开发集复用（P1-2），不能当确认性证据。

**消失 / 不能按任务级主张**
1. C4 “全部 30 题 29→41/90”：任务级 p=0.080，且 10 个有信息任务里主要是设置和酒店；**/90 的提升不能作为任务级显著结论**。
   （论文其实只把设置单字段和 TextEdit 当主结果，这一点没错；但 Table 2 的 41/90 容易被读者当成显著总量。）
2. C4 打包（36 vs 41，p=0.19）与状态表（39 vs 36，p=0.75）：无论执行层还是任务级都不显著；
   论文的措辞是“packing and state table are separate changes”，没有下显著结论——保持即可。
3. **C4 第二轮发票 7/18 vs 0/18（p=0.25）**：论文写 “This result suggests that some invoice behavior survives the
   interface change; it does not establish broad interface-invariant transfer”，限定语是对的，但**任务级检验连 0.05 都到不了**，
   且只有 3 个有信息题（最小可达 0.25）。建议在正文直接给“任务级 p=0.25（3 个有信息题，已是最粗粒度）”或改成纯计数描述。
   另外 47/90 vs 41/90 也是 p=0.25。
4. R3 learned web 的 10/54→21/54（p=0.109）不显著；R3d/R3e 相对锚点的 web 差（p=0.031，6 个有信息题；p=0.047，7 个）
   也都贴着 12–18 题下的检验分辨率，建议只作描述。
5. G0 规则+计划 vs 无规则（p=0.25）与 v0.4 的 §5 表述一致（论文已自认“探索性”），不需要改，但摘要可加“5 题、3 个有信息题”。

### 5.4 关于最小可达 p 的说明

- k=5：0.0625（5 题全不同向时）；但本题 G0 只有 3 个非零差 → 0.25。
- k=6：0.03125（C4 设置、TextEdit 都是全 6 题有差 → 正好在 0.03125）。
- k=12：4.88e-4；k=15：6.1e-5；k=18：7.6e-6；k=24：1.19e-7；k=30：1.86e-9。
- 含并列（零差）时实际分辨率是 2/2^m（m 为有信息任务数），表中已同时给 k 和 m。
- 因此“C4 设置 p=0.03125”“TextEdit p=0.03125”不是“刚好显著”，而是**这组设计能做到的最小 p**；
  论文若写“large descriptive gains”，与任务级检验的粒度是自洽的。
- 同理“发票 7/18 vs 0/18 p=0.25”不是“没有效应”，而是 3 个有信息题能给出的最小 p；正确表述是“方向一致但任务级不可检验”。

---

## 6. 有效性检查（逐项）

### (i) R2 训练数据与 eval 清单的 task_id 重叠 —— **0 重叠，通过**
- R2 归档 task_id 全为 `stream-v1-*-13000..13023`；`eval/stream_v1/eval.json` 为 10000–10005，`stream_web_v1/eval.json` 为 11000–11005。
- `|R2 ∩ stream_v1| = 0`，`|R2 ∩ stream_web_v1| = 0`（audit.json `r2.eval_overlap`）。
- 补充：R2 的 29 个 task_id 也出现在 control 归档里（无指导对照，~193 行，不进训练），这是设计上的对照，不是泄漏。

### (ii) held-out 族是否不在 R2 训练里 —— **是，通过**
- R2 中 `text_normalize`、`config_migrate` 行数均为 0；11 个族全部是 learned/负例族（audit.json `r2.heldout_family_rows`）。

### (iii) E-1 “42/48 vs 14/48” 的分母 —— **是，24 题 × 2 条流 / 单次复制，通过但需补 A1**
- 清单 learned-file 任务 = 24；`e1-report` 的 in-family 列是 /48。
- A3（v7 seed1+seed2）与 A4（v6 seed1+seed2）各有两条真实学习流：A3 21/24 + 21/24 = 42/48；A4 19/24 + 20/24 = 39/48。
- A0（v6 `e1/A0`）只有一次 24 题评测 7/24，报告把它复制成 14/48；A1（v5 `e1/A1`）同样只有一次 6/24，复制成 12/48。
- 论文 §4.1 只写了 “the raw baseline is duplicated”，**没有说 A1（budget-matched retry）也复制**；读者会把 12/48 当成 48 次独立评测。
  建议改为 “A0 7/24 and A1 6/24, each evaluated once and shown against the two-stream /48 learning arms”。

### (iv) D7 heldout2 日期标签错误 —— **确认存在**
- `v2-heldout2.json` 第 1 条：text=`后天下午我有空吗`，`intent=calendar`，`day=today`（gold），`clef_day=tomorrow`，`legacy_day=today`，`conf=0.965`。
- 该句语义是“后天下午”，所以 gold（today）与 clef（tomorrow）都不对；intent 仍判对。论文 §7 的说法与证据一致。
- 该套 calendar 行日期正确率：clef 2/3、legacy 3/3（`audit.json d7["v2-heldout2.json"]`）——即这条恰好是 legacy 日期对、clef 错。

### (v) SHA256SUMS 覆盖 vs 最新产物 —— **已列项全部通过；覆盖不全**
- 论文包 `docs/paper/v0.4-support/SHA256SUMS`：14 条，全部 OK（含 draft/tex/pdf/build.sh/review/handoff/recompute/audit/两个版本快照）。
- 证据包 `evidence/SHA256SUMS`：97 条，全部 OK；但**停在 v31 / r3d**，未覆盖：
  `kaggle/v32-results.tar.gz`、`kaggle/v33-results.tar.gz`、`reports/g0`、`reports/d7`、`reports/r3e`、
  `reports/c4/round2*`、`eval/desktop_v1`、`eval/intent_v1`（audit.json `checksums.evidence_manifest.missing_latest`）。
- 论文 §9 “the evidence checksum index does not cover all latest artifacts” 说法正确，但过于笼统；前审只点了 v32/v33/G0/D7，实际还漏 r3e 等。

### (vi) R3e train-config 3251 vs analysis.md/data-stats 3257 —— **已解释：预处理过滤 6 条**
- `r3e/data-stats.json` `rows_out.train=3257`；`r3e/train-config.json` `examples=3251, skipped_too_long=6`；3257−6=3251。
- R3b 同构：`rows_out.train=2787`，`examples=2781, skipped_too_long=6`。
- 因此 Table 6 用 train-config 的 3251/2781 是“实际训练条数”，正确；但论文没有注明这一点，
  读者拿 r3e/analysis.md 的 3257 会对不上。建议表 6 脚注 “train-config 记录实际使用的 examples（已扣除 6 条超长样本）”。

### (vii) R3b 1400 / R3c 879 回放与 Table 6 —— **正确**
- R3b：`replay-stats.json` agentnet kept 800 + toucan kept 600 = 1,400；data-stats replay_inputs rows=1400。
- R3c：`replay-stats.json` selected 879（pool agentnet 5000 / toucan 4963；selected 123 / 756）；R3d 复用 879；R3e 随机 1,400。
- Table 6 的 examples/replay/steps 全部与 train-config 一致（`validity.replay_counts.table6_*_match=true`）。

### (viii) G0 桌面：max_steps 范围 / temperature / teacher 可见 checker —— **均与论文一致**
- max_steps：`eval/desktop_v1/tasks.json` 取值 6–20；`results.jsonl` 实测步数分布 1–20（15 步存在，最大 20）。
- temperature：代码默认 0.7（`core/model_provider.py:116/133`、`core/computer_use/desktop_agent.py:178`），
  `scripts/experiments/kaggle_e1.py:395` 注释明确 “(temperature 0.7)”；但**归档 config 无 temperature 字段**，
  故该结论是代码/注释级而非 run 级记录。
- teacher 可见 checker：`a0-baseline-v1/teach-log.json` 4/4 条 prompt 含 “Checker: expected … found …”；
  `scripts/experiments/desktop_run.py:281-284` 用 `task['expected']` 拼该串。论文 §2 的描述成立。
- 另外：最终臂 config 无 lora 字段（G0 未用 R3 adapter）；lesson 数 1 calculator + 3 textedit = 4。

### (ix) 额外检查（本报告新增，均通过/已注明）
- **R3 训练/验证任务数**：data-stats `tasks.train=133, val=18`，合计 151 = R2 唯一任务数 151。
  （无法核验“按 task 划分且无同题跨集”，因为仓库没有 R3 的 train.jsonl/val.jsonl——**无法核验**该项，只能核数字一致。）
- **C3 原始归档**：v17+v19 的原学生 4 次评测发票 0/24；AGL/A4mGL 的 cp44 合计 14/24（1+3+4+6）——与 §4.1 和 c3 报告一致。
- **E-1 后验原始评测**：v6=7/24、v11 A0-r1..r3 = 10/13/7，v29–v32 锚点 10/11/6/11；
  论文 §4.1 的 “7 to 13” 与 v31 的 6/24 不符（**应改为 6–13 或限定为 E-2b 的四个重复**）。
- **通用能力**：R3 28、R3b 28、R3c 28、R3d 27、R3e 28（R3 的 A0 也是 28）——论文 “27–28” 相符。
- **训练时长**：五份配置 20,748.2 s = 5.7634 h——论文 “约 5.8 h” 相符。
- **Table 3 第一行是两臂拼接**：fill 行 = a0-baseline-v1（3 训练题）+ a0-test-v2（3 测试题）；
  论文脚注只说“6 个不同题、各 3 次、非后选择测试”，没说是两个臂拼的（风险项 R9）。
- **D7 “After confidence fallback”列**：combined 的计算是“置信<0.8 → 'other'”，不是真的跑本地回退；
  论文脚注已说 fallback 完成度未评测，但列名仍可能误导（风险项 R11）。

---

## 7. 主要偏差 / 风险（按对论文的影响排序，共 14 条）

| # | 严重度 | 问题 | 证据/复算 | 建议 |
|---|---|---|---|---|
| R1 | S1 | **C4 第二轮“R3e 发票 7/18 vs 0/18”任务级不可检验**（p=0.25，3 个有信息题 = 粒度下限）；47/90 vs 41/90 也是 p=0.25 | audit.json `c4_round2.comparisons` | 正文给任务级 p 与“3 个有信息题”；或改成纯计数并明确“不显著” |
| R2 | S1 | **C4 “全部 30 题 29→41/90”任务级 p=0.080**，只有 10 个有信息题；把 /90 当显著总量会被审稿人挑战 | audit.json `c4_round1.comparisons[1]` | 保留 1/18→14/18（p=0.03125，最小可达）；/90 只作描述 |
| R3 | S1 | 两个“接口修复”主结果的 p 恰好是 6 题的**最小可达值 0.03125**，论文没有说明检验粒度 | `c4_round1`、`g0`（TextEdit） | 在 §4.2/§4.3 加一句“6 tasks ⇒ smallest attainable two-sided p = 0.031” |
| R4 | S1 | **E-1 A1 的 12/48 是把 6/24 复制成 /48**，论文只说明了 raw baseline 的复制，未说明 budget-matched retry 也复制 | `e1_denominator`（A0=7/24→14/48；A1=6/24→12/48） | 改写 §4.1：A0 7/24、A1 6/24，各评一次；学习臂是两条流的 /48 |
| R5 | S2 | Table 6 的 R3e 3251 与 r3e/analysis.md 的 3257 不一致，未解释（R3b 2787→2781 同理） | `r3e/train-config.json` `skipped_too_long=6` | 表 6 脚注：“实际训练 examples（已扣除 6 条超长）” |
| R6 | S2 | “preceding project report records US$1.83”：仓库技术报告写 US$1.12（10-16），1.83 只在工作日志；按账本余额反推约 1.78–1.79 | `docs/report/kage-tech-report.md` §7；`docs/worklog/2026-10-claude.md:652`；d7/g0/r3d 的 ledger 余额 | 改为“项目私有账本（未在公开仓库）记录约 US$1.8”，不写“前项目报告” |
| R7 | S2 | §4.1 “Later raw evaluations ranged from 7 to 13” 与 v31 锚点 6/24 矛盾；全部可复算范围是 6–13 | `v6`、`v11`、`v29–v32` 的 A0 | 改为 6–13，或限定为“E-2b 的四个重复 7/10/13/7” |
| R8 | S2 | R3 迁移族退化的任务级显著性只是勉强（p=0.0469，7 个有信息题 / 12）；R3d 的 6/36 与锚点差异不显著（p=0.258） | `r3.comparisons` | 在 §6.2 给任务级 p/CI，避免让读者以为所有版本差异都显著 |
| R9 | S3 | Table 3 第 1 行是 a0-baseline-v1 + a0-test-v2 两个臂的拼接，脚注未说明 | `table3_recomputed.v2_whole_text_fill.source` | 脚注加“v2 行由两次同接口运行拼接（训练/测试 TextEdit 各 3 题）” |
| R10 | S3 | Table 5 的 R3b–R3e 用的是**第 2 轮（最终）adapter**，报告也评了第 1 轮；论文未说明 | `evidence/reports/r3{b,c,d,e}/analysis.md`；v29–v32 的 `*e1-*` 臂 | §6.2 脚注说明“表中均为最终（2 epoch）adapter” |
| R11 | S3 | 表 7 “After confidence fallback”列实为“置信<0.8 记为 'other'”，不是执行本地回退；脚注已说未评测 fallback 完成度 | `scripts/experiments/intent_eval.py` | 列名改 “Thresholded label”；或加“模拟阈值路由” |
| R12 | S3 | 前审 P1-6 的“原始结果也有 15 步”应写“最大 20 步”；P2-3 漏检清单应补 r3e/C4 round2/eval 清单；P1-3 的 303 条应注明“非负例族” | audit.json `validity.g0.max_observed_steps=20`；`checksums`；`r2.write_file` | 若沿用前审行文，修正这三处 |
| R13 | S3 | 跨会话 base 波动很大（v29–v32 锚点族内 10/11/6/11，v26 的 9/12/9），R3b–R3e 的“族内提升”里有相当部分可能是会话/锚点噪声 | `r3.variants[*].base_per_run_totals` | 已部分由“跨会话”限制覆盖；建议表 5 附锚点值 |
| R14 | S3 | 没有图；摘要与 §9 的复现限制写得较散；R3 训练/验证按任务划分无法从公开数据核验（无 train/val 文件） | `paper.tex` 无 `includegraphics`；仓库无 r3 train.jsonl | 加 1 张干预-结果图/协议表；在 §9 明确“无法公开核验按任务划分” |

（另：v0.3 的 read-back 48/72→0 未在 v0.4 出现数字；本审计未解析 trace，故不列为 discrepancy，也不替 v0.4 背书。）

---

## 8. 附录

### 8.1 复现命令

```sh
cd /Users/wenbo/Kage/.claude/worktrees/task-progress-861574
python3 docs/paper/deepseek-support/audit.py
# 输出 docs/paper/deepseek-support/audit.json；脚本内断言覆盖 R2=1900/151/446、E-1=7/6/42/39、
# C4 表 2、G0 41/45、R3 表 5、Table 6、checker 59/0、SHA256SUMS 等
```

### 8.2 audit.json 键映射（本报告用到的主要数字）

| 报告内容 | audit.json 键 |
|---|---|
| 清单/分母 | `manifests.*` |
| R2 单位、重叠、write_file、held-out | `r2.*` |
| E-1 各臂与任务级检验 | `e1.arms`、`e1.comparisons`、`validity.e1_denominator` |
| C3 发票 | `c3_invoice.*` |
| C4 第一轮 | `c4_round1.table2_recomputed`、`c4_round1.comparisons` |
| C4 第二轮 + checker | `c4_round2.*` |
| G0 表 3/4/最终/检验/teacher | `g0.table3_recomputed`、`g0.table4_recomputed`、`g0.final_config`、`g0.comparisons`、`g0.split_comparisons`、`g0.teacher_logs` |
| R3 表 5/6、逐次、检验、通用 | `r3.table5_recomputed`、`r3.table6_recomputed`、`r3.variants[*].per_run_totals`、`r3.comparisons`、`r3.general_check` |
| D7 | `d7.*` |
| 校验清单 | `checksums.paper_manifest`、`checksums.evidence_manifest` |
| 有效性检查 | `validity.*` |
| 论文 45 条数值声明 | `paper_claims`（44 相符 / 1 无法核验） |

### 8.3 本次未独立核验的内容（如实说明）

1. 私有教师账本 `US$1.83`（及 Clef 列表价口径）。
2. R3 的 `train.jsonl`/`val.jsonl` 本体（仓库没有；只能核 data-stats 的数字与 133+18=151 的一致性，不能核“按任务划分无同题跨集”）。
3. adapter 文件本身（私有 Drive/Kaggle；仓库只有 sha256 与配置记录）；因此“适配器确实生效”只能核报告级说法
   （r3/analysis.md 记录首个模型调用 A0 与 L3 只有 2–3/48 相同，说明适配器确实生效）。
4. 读回验证 48/72→0（需要解析 `model-traces`；v0.4 已不把该数字写进正文，本轮不重算）。
5. C4 第二轮 “Clef 逐项目标 48/48 正确”（round2.md 的说法；论文正文未引用该数字，本轮不重算）。
6. D7 延迟与端到端案例（私有活动日志；论文已限定为案例）。
7. 硬件信息（M4 Mac / T4 / A100）与训练 GPU 型号：只出现在报告/日志文字，结果文件未记录。
