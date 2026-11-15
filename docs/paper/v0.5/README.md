# v0.5：裁决说明与逐项采纳（2026-10-28，Claude）

以 DeepSeek v0.4 的结构、题级统计和图为骨架，保留 Astra v0.4 的证据边界，按原始数据裁决两者分歧。两份旧稿原样保留：`../draft.md`（Astra v0.4，未提交修改未动）、`../deepseek-v0.4/`。本轮没有跑新模型实验、没有 commit/push。

- 源稿 [draft.md](draft.md)；构建 `./build.sh`（pandoc + tectonic，TeX 自带字体）；产物 `paper.pdf`（11 页，3 图，7 表，无缺字，最大溢出 0.8pt）。
- 独立核对 `../v0.5-support/verify.py` → `verify.json`、`verify.stdout.txt`：只读公开证据；题级 sign-flip 用整数动态规划**精确**枚举（24/30 题也精确，不用随机抽样）；bootstrap 仅描述。
- 图 `../v0.5-support/make_figures.py`（由 DeepSeek 脚本改出）→ `figures/`。
- 新增证据 `evidence/reports/g0-nemotron/`（第二学生，10-26 已跑完的数据，见下）。

## 一、用户点名的四项

### 1. “接口 +8、guidance +2”——不成立，改为按族列“观测变化 / 对照 / 相容解释”

按族重算训练题 19/30 → 29/30（`verify.json: g0_family_counts`）：TextEdit 2/9→8/9，设置 7/9→9/9，计算器 10/12→12/12。算术分解 6/2/2 对，但归因不对：

| 族 | 有无同接口无规则对照 | 裁决 |
|---|---|---|
| TextEdit +6 | 有：v4 无规则 8/9 = 最终 8/9 | 可写“与按行工具一致；未观测到规则增量” |
| 设置 +2 | 无 | 基线两次失败分别是“没调用工具”和“把整行当引用”，恰是 v2 修复的两类（轨迹核对），**机理相容但未受控**；且设置题没有规则，最终配置对它只多了“先写计划”，计划不能排除 |
| 计算器 +2 | 无 | 增益全在 calc_chain（1/3→3/3），而计算器规则正是从这道题的失败写出来的——**样本内**；规则与计划未分开 |

结论：只有 +6 有对照；“interface +8”“guidance +2”“interface-dominated”都删除。新表 4 列“观测变化、现有对照、相容解释”，摘要只说“只有 TextEdit 有匹配对照，且无规则时同分”。另外四条规则来自 10 道训练题中的 4 道（te_fix、te_append、te_write、calc_chain），已写入 §2。

### 2. 阴性误用分母——三种分母都对，但含义不同；DeepSeek 的机理描述错

原始 checkpoints（v26/v29–v32）：R3 在阴性题共 36 次执行中 2 次 `misuse`，**两次都是同一道题**（lookalike_readonly-10502 的第 2、3 遍），即 2/36 执行、2/12 该族执行、1/12 阴性题。底座与 R3b–R3e 均 0/36。

`misuse` 的代码定义是“阴性题上发出了技能调用”（`core/evolution/stream.py:552`），不是“改了文件”。两遍轨迹都只有 read_file、skill_search、一次 skill_call（技能名写成 `telemetry.py`），**没有任何写操作**。DeepSeek 稿“modified a read-only file”是错的，Astra 复核说“lookalike 子族是 2/12、全阴性 2/36”对。v0.5 写成：2/36 次在同一道只读题上调用技能并判失败，未写文件；表 7 列名改为 “Negative skill misuse (/36)”。

### 3. 图注与逐题结果

| 位置 | 问题 | v0.5 |
|---|---|---|
| DeepSeek 图 3 注 | “Nearly every in-family task improves… held-out moves almost entirely opposite” | 实际 14 升/2 降/8 平；留出 6 降/1 升/5 平（逐题核对，`R3_vs_anchor_held.per_task`），图注直接写分布 |
| DeepSeek C4 主张 | 正文写 “Figure 3 summarizes the ordering”，但流程图是图 1 | 改为图 1 |
| 流程图 | 第 4 框 “only after 1–3 are ruled out”，像已验证流程 | 框内与图注都写 “proposed order; not itself tested”；证据行加第二学生 |
| 图 2(b) | primary 的 fill 柱混合 v1 训练题与 v2 变体题 | 图注说明；加第二学生菱形点（0/18、16/18，两边都是 v2） |
| 图 2(a)(c) | 逐题与 3/3/6/10 核对一致 | 保留；(c) 注说明第二学生每个条件 0–1/15 |

### 4. 统计口径

- 单位：题；重复先平均；按题配对；**精确**双侧 sign-flip（动态规划，所有规模）+ 描述性 bootstrap。DeepSeek 对 24 题用 20 万次随机抽样，改为精确值（如 R3 学过题 11/32768，与其 3.3e-4 一致）。
- 全文不再出现执行级 Fisher：DeepSeek §6 的 p=0.46 删除，C4b 只报题级（全 30 题 3/1/26，p=1/4；发票 3/0/3，p=1/4）。
- p 值标为 nominal：无多重比较校正、依赖题间符号可交换、对单一 adapter 条件化；最小可达值 2/2^k' 写入 §3。
- R3b–R3e 对其**单次** anchor 的题级对比全部给出（R3b 学过 +0.06 p=181/256、留出 −0.17 p=131/256；R3c 学过 +0.01、留出 −0.53 p=1/64；R3d 学过 p=1/32768、留出 p=33/128；R3e 学过 p=3/4096、留出 p=1/64），标为描述性。
- R3b 的 anchor 方向按 Astra：只写观测差与不确定性（p=131/256），不说“已确认退化”。
- G0 训练题 final vs baseline（6/0/4，p=1/32）**不报**：组合干预且 4/10 题样本内。

## 二、其余分歧与更正

| 项 | Astra v0.4 | DeepSeek v0.4 | v0.5 依据与取舍 |
|---|---|---|---|
| 结构/贡献 | trace-grounded account | C1–C4 + 不主张什么 | 采用 DeepSeek；C4 改为 “working procedure（未比较其他顺序）”（采纳 Astra 复核第 4 点） |
| 题级统计 | 只 G0 一项 | 全面题级 | 采用 DeepSeek，改精确算法与 nominal 表述 |
| 训练样本数（摘要） | 1,900 action-level | “trained on 1,900” | 改 “1,677 training examples”（1,900 是含验证的总库） |
| 第二学生 | “only one student” | “invalidated… 3/30 under v1” | 两者都过时/有误：复现 10-26 06:12 已跑完；训练题基线是 **v2** 下 3/30，不是 v1。新增 §7 与表 3/表 5 列：TextEdit 工具效应复现（0/18→16/18，6/6，p=1/32）；规则呈现不复现（四条件 0/1/0/0）；计算器在 v2、v4、v5 下均 0 |
| 第二学生失败机理 | — | “reading button identifiers as numbers” | 我此前的推断，v5（以控件 id 作引用）后它按列出顺序按键，仍 0/18 → 证据不支持；v0.5 只描述现象并说明原推断被推翻 |
| 模型/环境 | 只写 Q4_K_M | “llama.cpp 0.4.1 build 10964, 16k context” | GGUF SHA-256 与修订号核对一致；0.4.1/10964 只是 Mac 桌面端；Kaggle 用预编译构建；上下文按 server.log：文件 8,192、浏览器 16,384、桌面 8,192 |
| 预算 | “preceding report $1.83” | 三数并列“未对账” | 账本 10-28 实查：累计 US$1.8285；$1.12（当时上限 $2）与 $1.78 是同一累计账的早期快照（采纳 Astra 复核第 6 点）；Clef 约 $0.10 按列表价计 |
| 后续 raw 波动 | 7–13 | 6–13 | 6–13（R3d 会话 anchor 6/24） |
| Biderman 引用 | 中性 | “our losses are not predicted by that comparison” | 改为“相对比较，不意味 LoRA 不遗忘；我们无全参对照” |
| Murtaza 引用 | 无 | 泛称 agent-skill 遗忘 | 限定为 skill 系统的**检索组件**（采纳 Astra 复核第 7 点） |
| Meta-Harness | 有 | 删了 | 恢复（Astra 已在线核对） |
| D7 | 正文一节 | §8 部署注记 | 采用 DeepSeek 的位置，保留 Astra 的边界（intent-only、日期标签错、set1 复用为开发、无 4B 基线、请求外发） |
| AI 辅助声明 | 无 | 无 | 新增一段（与用户此前决定一致） |

## 三、仍然缺的（未做，按用户要求不跑新实验）

1. 同一会话交错跑 v4 无规则 vs v4+规则+计划（全 15 题×3），才能回答固定接口下规则的增量（Astra 复核：不要只补一臂对历史比）。
2. 冻结后的新确认集（G0 变体已被开发者看过）。
3. 多训练 seed；等暴露量（样本/步数/来源配比）的回放对照；强制读回干预。
4. 适配器发布或重建说明；`evidence/SHA256SUMS` 补 v32、v33、G0、D7、g0-nemotron。
5. 第二学生只有一次会话、无他人复核；若要作为正式证据，需在同一会话与主学生共同跑 v4。

## 四、文件

- 新增：`v0.5/{draft.md, build.sh, paper.tex, paper.pdf, figures/*, README.md}`、`v0.5-support/{verify.py, verify.json, verify.stdout.txt, make_figures.py, SHA256SUMS}`、`evidence/reports/g0-nemotron/`。
- 未改：`docs/paper/draft.md`、`docs/paper/deepseek-v0.4/*`、各 review 文件、原始实验数据。
