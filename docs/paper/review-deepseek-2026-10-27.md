# Kage 论文 v0.3→v0.4 独立审稿与修订建议（DeepSeek，2026-10-27）

**审查对象**：dev worktree `/Users/wenbo/Kage/.claude/worktrees/task-progress-861574`，HEAD `e55d94a`。主稿 `docs/paper/draft.md`（v0.4，218 行）与 `arxiv/paper.pdf`；对照 `docs/paper/versions/draft-v0.3.md`（v0.3）、`docs/paper/review-codex-2026-10-27.md`（前审）、`docs/paper/v0.4-changes-and-handoff.md`（v0.4 交接）。

**审查方法**：完整读取上述文件、`evidence/` 下相关报告与原始包（`evidence/kaggle/v5–v33`、`evidence/reports/{e1,e2,r2,r3*,c2,c3,c4,d7,g0}`）；另写独立复算脚本 `docs/paper/deepseek-support/audit.py`（45 项论文数字，逐项给证据路径）与 `stats.py`（题级配对统计），并生成 3 张图。**未运行模型、未调用教师、未训练、未改原始实验数据、未 commit**。本文件与 `docs/paper/deepseek-v0.4/`（DeepSeek 版修正稿）是本轮唯一新增的论文产出；委托的三份内部材料见 `deepseek-audit-2026-10-27.md`（若已生成）、`deepseek-redteam-2026-10-27.md`、`deepseek-litcheck-2026-10-27.md`。

## 0. 一句话结论

**建议 major revision，而不是 reject。** v0.4 把前审指出的"说错的事实"和"过强的因果"基本修对了；但修法过度：它删掉了所有推断、丢掉了最强证据（C4 单字段、R3 题级），把论文写成了一份诚实的实验记录，而不是一篇有主张的论文。数据与失败记录足以支撑一篇 arXiv note / agents workshop 论文；阻塞项是写作、已有数据重组和 1 个约 1 小时的本地对照，不是新研究。

## 1. 我独立核验了什么

### 1.1 v0.4 的数字：44/45 相符，1 项无法核验

逐项检查 v0.4 的 Table 1–7 与正文数字，结论：**44 项相符，1 项无法从公开文件核验**（私有教师账本的 $1.83；仓库内同时存在 $1.12 与 $1.78 两个旧值，见 §2.6）。关键重算（全部从原始包逐行重算，不采用 v0.4 的 `recompute.py` 结论）：

| 论文数字 | 重算 | 证据 | 判定 |
|---|---|---|---|
| C4：V1 1/18、V2 14/18、V2PK 14/18、V2PKST 17/18；总分 29/41/36/39 /90 | 完全一致 | `evidence/kaggle/v28-results.tar.gz` | 相符 |
| TextEdit：4/18 → 8/18 → 17/18；最终配置 15/18 | 4、8、17、15 | `evidence/reports/g0/{a0-baseline-v1,a0-te-v3,a0-te-v4,a0-final-v4-plan}` | 相符 |
| G0 四条件：3/3/6/10 /15 | 3/3/6/10 | `evidence/reports/g0/a0-test-v2*` | 相符 |
| G0 最终：41/45；训练 29/30；变体 12/15；17/18、15/18、9/9 | 完全一致 | `evidence/reports/g0/a0-final-v4-plan` | 相符 |
| R3：f 64/72、1/36、web 21/54；R3b 34/15/31；R3c 34/2/22；R3d 62/6/20；R3e 65/1/22 | 完全一致 | `evidence/kaggle/v26,v29–v32`；`evidence/reports/r3*` | 相符 |
| R2：1,900 行 / 151 task / 704 attempts / 472 successes / 446 组合 | 完全一致 | `evidence/reports/r2/sft-v21.jsonl.gz`、四个 `*-stats.json` | 相符 |
| R3e：训练 3,251、验证 236、813 步 | 3,251 = 3,257 − 6 条超长 | `evidence/reports/r3e/{train-config,data-stats}.json` | 相符（v0.4 已解释 3,257/3,251） |
| D7：15/30、30/30、30/30；16/30、30/30、28/30 | 完全一致 | `evidence/reports/d7/*.json` | 相符 |
| D7 日期标注错误例 | gold day=today，模型 tomorrow | `eval/intent_v1/heldout2.jsonl`、`v2-heldout2.json` | 相符 |
| 训练 wall time 5.8 h | 5.7634 h | 五份 `train-config.json` | 相符 |
| 私有账本 $1.83 | 无法核验 | 无公开账本；技术报告写 $1.12、README 写 $1.78 | 无法核验 |

另外核验了数据有效性：(i) R2 训练 task_id 与 `eval/stream_v1`、`eval/stream_web_v1` 评测 task_id **零重叠**；(ii) 训练数据中没有 `text_normalize`、`config_migrate` 两个 held-out 族（也没有 `web_form`）；(iii) E-1 的 A0 确实只评测一次（7/24）后被复制成 14/48，A1 也是 6/24 复制成 12/48，A3/A4 是两个真实 stream（21+21、19.5+19.5）；(iv) G0 manifest `max_steps` 确为 6–20，desktop agent 温度 0.7，teach-log 中教师确实看到 `Checker: expected … found …`；(v) R3 的阴性族 `lookalike_readonly` 在 R3 中确有 2/36 次误改（详见 §2.5）。

**审计增量（verifier 报告 `deepseek-audit-2026-10-27.md`）**：除上表外，独立审计还确认了 5 个值得写进修正稿的细节：(i) E-1 的 A1 与 A0 一样是单次评测复制（6/24→12/48），v0.4 只说明了 A0；(ii) "later raw evaluations" 的范围实际是 **6–13/24**（v31 anchor 为 6），不是 7–13，v0.4 与我的初稿都需要改；(iii) C4 全部 30 题 29→41/90 的题级 p=0.080，/90 不能当显著总量；(iv) G0 15 题合并（含变体）任务级 p=0.00195，但仍是开发集复用，只能作描述；(v) `write_file` 目标总数 304（202 无推理 + 102 有推理，前审/报告写 303 是排除了 1 条负例族）。另外 R3b 的 held-out 与其 raw anchor 的差异 p=0.51（不可区分），这与"低于 anchor"不矛盾：方向低、样本不足。

### 1.2 前审（Astra/Codex review）的事实：基本全部成立

我逐条核验了前审 P1-1..P1-7、P2-1..P2-3 的事实依据：**没有发现事实错误**。具体：G0 的 5 题 ×3 重复、R3 的 24/12 题 ×3、V1/V2/V2PKST=1/14/17/18、1900 行/151 task、446 组合、472 成功、Checker 泄露、温度 0.7、D7 日期错误、v28/v33 的 0/54 与 7/18、SHA256SUMS 未覆盖 v32/v33/G0/D7——全部与我重算一致。前审的 G0 题级 sign-flip p=0.25（2^5 全枚举，8/32）也正确。

**但前审有三处需要修正或补强**：

1. **P1-3 的反例本身被混杂削弱**：前审用"R3b 与 R3c 都过滤无推理目标，但 held-out 15/36 vs 2/36"来反驳"提升与遗忘同一批样本"。问题在于 R3b vs R3c 同时改变了回放算法、回放数量（1,400 vs 879）、来源配比和步数（696 vs 567）。这个对比只能说明"保留率不是过滤的单变量函数"，不能说明"没有共同原因"。v0.4 继承了这个逻辑结构（§6.3）。
2. **P1-1 的建议没有被 v0.4 执行**：前审要求"逐题平均差、逐族结果与以任务为簇的配对区间/检验"，v0.4 只对 G0 做了一项 sign-flip，C4/R3 全部退回 descriptive + future work。这是过度纠正。
3. **前审漏掉、但重要的 5 点**：(a) 最终配置 41/45 的现成分解证据——`a0-te-v4`（v4 接口、无 lesson）在同样 6 个 TextEdit 题上是 17/18，最终配置同批题是 15/18，说明 lesson 分量在 TextEdit 上没有增量；(b) v0.4 Table 5 只放一行 Base，掩盖 R3b–R3d 的会话 anchor 漂移（R3b held-out 15/36 仍低于自己会话的 anchor 7/12≈21/36）；(c) C4 第二轮只报发票 7/18 vs 0/18，没报总体 47/90 vs 41/90（p=0.46）；(d) R3 的阴性误用 2/36 没有出现在任何表格或摘要；(e) "无图"被列为 P2，但对一篇结论依赖"聚合→逐题分布"的论文应为 S1。

### 1.3 我新增的题级统计（v0.4 完全没报）

方法：同一 task 的 3 次重复先取平均；条件间按 task 配对；对均值差做精确 sign-flip（≤16 task 全枚举，24 task 用 20 万次随机符号），并给 task-bootstrap 95% 区间（10,000 次重采样，描述性）。

| 比较 | task 数 | 平均差 | 95% task-bootstrap | 精确 sign-flip p | 方向（改善/变差/持平） |
|---|---:|---:|---|---:|---|
| C4 settings V1→V2（单字段） | 6 | +0.722 | [0.50, 0.94] | **0.031** | 6 / 0 / 0 |
| C4 settings V2→V2PKST（组合） | 6 | +0.167 | [−0.11, 0.44] | 0.50 | 2 / 1 / 3 |
| TextEdit v4 vs fill | 6 | +0.722 | [0.50, 0.94] | **0.031** | 6 / 0 / 0 |
| TextEdit v4 vs v3 | 6 | +0.500 | [0.17, 0.83] | 0.125 | 4 / 0 / 2 |
| G0 plan+beside vs none | 5 | +0.467 | [0.13, 0.80] | 0.25 | 3 / 0 / 2 |
| E-1 A3 vs A0（in-family） | 24 | +0.583 | [0.35, 0.77] | **<0.001** | 17 / 1 / 6 |
| E-1 A4 vs A0（in-family） | 24 | +0.521 | [0.33, 0.71] | **<0.001** | 14 / 0 / 10 |
| E-1 A3 vs A4 | 24 | +0.063 | [−0.13, 0.25] | 0.67 | 5 / 4 / 15 |
| R3 vs base（in-family） | 24 | +0.472 | [0.28, 0.67] | **<0.001** | 14 / 2 / 8 |
| R3 vs base（held-out） | 12 | −0.389 | [−0.67, −0.11] | **0.047** | 1 / 6 / 5 |
| R3 vs base（web learned） | 18 | +0.204 | [0.00, 0.43] | 0.11 | 7 / 2 / 9 |
| R3e vs same-session anchor（held-out） | 12 | −0.556 | [−0.83, −0.25] | **0.016** | 1 / 7 / 4 |
| C4b R3e vs raw（invoice） | 6 | +0.389 | [0.11, 0.72] | 0.25 | 3 / 0 / 3 |
| C4b R3e vs raw（all 30） | 30 | +0.067 | [−0.01, 0.17] | 0.25 | 3 / 1 / 26 |

解释：C4 单字段、TextEdit v4、E-1、R3 in-family 在题级是站得住的（6/6 或 17/1、14/2 的方向一致性）；G0 只有 5 题且 2 题差值为 0，有效 n=3，p=0.25；R3 的 held-out 12 题里只有 7 题变化，p=0.047，方向一致但样本很小；C4b 的发票增益集中在 3/6 题，题级 p=0.25。**v0.4 把"能报的强结果"和"最弱的 G0"一起降级为 descriptive，正好倒置了证据强度。**

## 2. v0.4 仍未解决的问题（按对评审的影响排序）

### S1（阻塞投稿）

**S1-1 没有可陈述的贡献，摘要把最弱的结果放在最显眼处。** `draft.md:9` 是一段 219 词的计数串，末句是建议不是发现；`draft.md:17` 说"contributes a trace-grounded account"，这是体裁不是主张。审稿人读完 title+abstract+intro 无法回答"这篇论文要你相信什么、什么能推翻它"。我的修正稿把三条 claim（interface / adoption / consolidation）+ 一条"不主张什么"写进 §1，并让摘要与之一一对应。

**S1-2 41/45 仍是"组合即管线"，而且缺的对照有现成数据。** 摘要顺序（接口 → lesson 10/15 → 41/45）和 `draft.md:110` 的"combining … yielded 41/45"都暗示可加性；但 `a0-te-v4`（v4 接口、无 lesson、同样 6 个 TextEdit 题）是 **17/18**，最终配置同批题是 **15/18**（逐题差 0,0,0,−1,−1,0）。也就是说，在最终接口上 lesson+planning 对 TextEdit 没有增量、数值还低一点。现有数据足以把训练题 19/30→29/30 分解为：TextEdit +6/9（v4 接口，v4 无 lesson 已达 8/9）、System Settings +2/9（v2 引用修复）、Calculator +2/12（与 lesson/planning 一致）；即 **接口 +8、guidance +2**。缺的只是"v4、无 lesson、全 15 题"的 45 次本机运行（约 1 小时、无教师成本）。v0.4 应把 41/45 写成 composite，并把这张分解表放进去。

**S1-3 "不报显著性"被用成了"不做推断"。** `draft.md:48` 的免责声明本身正确，但 C4 单字段（6 题全部同向，1/18→14/18）和 R3 24 题（14 题改善、2 题变差）都可做题级检验；把可报的强证据说成 future work，同时保留全文唯一一个最弱的 p=0.25（G0），是策略倒置。我的修正稿把 §3 写成分析策略（task 级、精确 sign-flip、bootstrap、单 seed 条件推断），并在正文逐条落实上表。

**S1-4 v0.4 Table 5 的单一 Base 行掩盖会话漂移，R3b 的"保留"读法因此偏乐观。** R3b–R3e 与 base 不同会话，且 anchor 差异大：R3b 自己的 anchor 是 10/24、7/12；R3b held-out 15/36（5/12）**仍低于自己会话的未训练 anchor（7/12≈21/36）**，只是高于 R3 的 1/36。R3c 的 2/36 更是远低于 anchor 21/36。v0.4 只在正文给了 R3e 的 anchor，其余三版都没给。修正稿 Table 5 增加"same-session anchor"列/段，并把"R3b retained substantially more held-out success"改成"vs R3 是恢复，vs 自己的未训练 anchor 仍是退化"。

**S1-5 阴性结果的误用被漏报。** R3 在 `lookalike_readonly`（"已正确，不要修改"）上 **2/36 次误改**，base 0/36；v0.3 和 v0.4 都没有在任何表格/摘要里报告。v0.3 的"negative results are reported"与 v0.4 的"separation of automated learning …"使这个遗漏更显眼。它不推翻主结论，但必须出现在 Table 5 或正文：安全相关失败不能只报 in-family 收益。

**S1-6 C4 第二轮选择性报告。** v0.4 只写 R3e 发票 7/18 vs raw 0/18；第二轮原始结论是总体 **47/90 vs 41/90，p=0.46**（不显著，提升集中在发票）。审稿人翻 `c4/round2.md` 会认为作者挑子组。修正稿同时报总体与子组，并注明题级 p=0.25、增益集中在 3/6 题。

**S1-7 全文无图，而结论完全依赖分布形状。** 8 页 7 表全是聚合计数，读者无法判断效应是否由 2–3 个任务撑起。修正稿加 3 张图：逐题 R3 vs base（24+12 题）、三层干预 panel、诊断顺序图。

### S2（重要，可通过收窄表述/重组解决）

1. **"adoption"框架被误删。** v0.3 的"检索可靠、采纳不可靠"是本文最概念化的发现；v0.4 把框架和过强措辞一起删了。但证据还在：C2 检索到不照做；C3 系统提示规则对发票 0/24→14/24；G0 同内容换放置位置 3/15→10/15。修正稿把它重组为 §5，并显式解释 C3 vs G0 的表面矛盾（内容类型/检索门控/规划；未隔离）。
2. **"in-family"从未定义。** 它指"同生成器的新实例"，不是同一批题，也不是任意新任务；held-out 族是不同生成器。这个区分是负结果强度的来源。修正稿 §3 明确定义。
3. **R3b/R3c 反例的逻辑问题**（见 §1.2）。修正稿把这段改成"保留率不是过滤的单变量函数"，不再用它支持"没有共同原因"。
4. **预算数字不一致。** 技术报告写 US$2.00 cap / $1.12 spent；README 写 $4 / $1.78；v0.3/v0.4 写 $4 / $1.83；代码 `GLOBAL_TEACHER_CAP_USD=4.00`。v0.4 说"preceding project report records $1.83"不准确（技术报告是 $1.12）。修正稿写"work log records $1.83; earlier snapshots report $1.12/$1.78; not independently reconciled"。
5. **模型/环境 provenance 缺失。** 只写 "Agents-A1-4B Q4_K_M"；实际有 GGUF SHA-256 `d93c393a…f062`、frozen revision `d92b02e…`、llama.cpp 0.4.1 build 10964、16k context。修正稿补进 §2，便于复现。
6. **第二个学生的部分复现没有披露。** G0 的 Nemotron-3-Nano-4B 复现只得到 3/30 训练题基线（Agents-A1 19/30），且后续两次因计算器初始化和锁屏作废。v0.4 只写"only one student"，不完整。修正稿在 §8 明确写成不用于证据的部分复现，并说明失败模式可能随学生而异。
7. **D7 占正文约 1 页且摘要为它背书。** 它贡献的"intent ≠ 端到端"是常识性区分，缺同条件 4B 基线，延迟是 illustrative。修正稿把它压成 §8 的 deployment note，不再进摘要。
8. **引用压缩过度。** 回放来源 OpenCUA/AgentNet 与 TOUCAN 在 §6.1 只写 "external replay" 而无引用，STaR 的 rationalization 也未引；这三条属于可追溯性缺失。修正稿补回并补 2025–2026 的相关工作（见 §4）。
9. **术语/单位不一致。** browser settings vs macOS System Settings、round 的三种含义、R3 vs R3 series、execution/run/success/attempt 混用。修正稿统一为 execution = 一次任务尝试、task = 独立题、success = 通过 checker 的 execution；browser settings / macOS System Settings 分开。

## 3. 对前审（Astra/Codex）的意见

- **扎实的部分**：统计单位、测试集复用、1900 样本单位、单字段对照、checker/温度/步数边界、D7 指标、SHA256SUMS 覆盖，全部属实且重要；前审把论文从"过强因果"拉回到可辩护范围，这是 v0.4 最大的价值。
- **我不同意的执行**：P1-1 建议了题级区间/检验，但 v0.4 只做了 G0；正确的做法是"能题级就题级，不能就明说为什么"，而不是全面退到 descriptive。P1-3 的反例自身混杂（见 §1.2）。P2-3 把"无图"列为 P2；对本文应为 S1。
- **前审未发现的事实**（不是错误，是遗漏）：41/45 的现成分解证据（a0-te-v4 17/18 vs 15/18）、Table 5 的 anchor 漂移、R3 阴性误用 2/36、C4b 总体 47/90 p=0.46、预算三处不一致。这些都在本轮修正稿中处理。

## 4. 我的 v0.4-deepseek 修正稿做了什么

文件：`docs/paper/deepseek-v0.4/draft.md`、`paper.tex`、`paper.pdf`（9 页，3 图，7 表）；可复现脚本 `docs/paper/deepseek-support/{audit.py,stats.py,make_figures.py}`；交接 `docs/paper/deepseek-v0.4/README.md`。

| 方面 | v0.4 | v0.4-deepseek | 理由 |
|---|---|---|---|
| 标题 | Interface Design, Teacher Guidance, and Consolidation…: An Empirical Study | Interface, Instruction Adoption, and Forgetting: A Diagnostic Case Study… | 三个 finding 进标题；去掉零信息后缀；"teacher guidance" 改 "instruction adoption" 更准确 |
| 摘要 | 219 词单段，先讲背景，弱结果在前，免责声明分散 | ~200 词，三条 finding 各带数字与边界，边界集中 | 让摘要与 Claims 一一对应 |
| 贡献 | 只有"trace-grounded account" | C1–C4 + "不主张什么" | 可评价性 |
| 结构 | §4 Interface、§5 Lessons、§6 Consolidation、§7 Deployment | §4 Interface、§5 Presentation-dependent adoption、§6 Consolidation、§7 Related work、§8 Limits | 三问与章节对齐；D7 移入 §8 |
| 统计 | 只 G0 一个 p=0.25；其余 descriptive | §3 分析策略 + 正文题级 p/CI（C4、TextEdit、G0、E-1、R3、R3e、C4b） | 用可辩护的强证据替代"全面免责" |
| 41/45 | 组合结果，称无法分解 | 训练题分解表（TextEdit +6 接口、Settings +2 接口、Calculator +2 guidance）+ 明确缺 v4-no-lesson 全臂 | 把弱点变成"接口优先"的实证 |
| v0.4 Table 5 | 单一 Base 行 | 修正稿 Table 5：每版 same-session anchor + 阴性误用列 | 跨会话比较透明；安全失败可见 |
| C4b | 只报发票子组 | 总体 47/90 vs 41/90 + 发票子组 + 题级 p | 避免选择性报告 |
| 图 | 无 | 3 图（逐题 R3、三层干预、诊断顺序） | 分布形状可见 |
| 引用 | 8 条 | 14 条（补 OpenCUA/AgentNet、TOUCAN、STaR、Dror 2018、Murtaza 2026、Xi 2026、Wu 2026；补 venue/全作者） | 可追溯性与定位 |
| 复现 | 附录只给目录 | 明确 audit/stats/figures 脚本、模型 hash、检查清单 | 可复现性 |
| 预算/学生 | $4/$1.83；"only one student" | 三处数字并列；披露 Nemotron 部分复现 | 诚实与边界 |

**我没有做什么**：没有跑新实验（包括缺的 45 次 v4-no-lesson 对照、第二学生完整复现、多训练 seed）；没有改任何原始证据；没有发布私有 adapter；没有把 v0.4 的绝对措辞恢复。修正稿的所有数字来自既有证据，新增的分析是题级统计与图。

## 5. 仍缺的证据与优先级（给 Claude / 用户）

1. **P0（约 1 小时，$0 教师）：`v4 + 无 lesson` 全 15 题 ×3**。填上 41/45 分解表的 Calculator 空格，把"接口主导"从推断变成测量。这是性价比最高的新数据。
2. **P1（约 1.5 小时，$0）：第二学生完整 G0 复现**。Nemotron-3-Nano-4B 的 3/30 基线失败模式是"把按钮编号当数字"，与主学生不同；先加 v5 界面（按钮名作编号）再跑完整 7 组，才能支持"失败模式随学生而异"还是"接口问题普遍"。
3. **P1（训练成本）：每个 R3 变体至少 3 个训练 seed**。当前所有 consolidation 推断都是对单一 adapter 的条件推断；没有 seed 方差就无法区分"方案差异"与"训练噪声"。
4. **P2：冻结方案后的新确认集**（新说法/新参数/新组合），修复"developer-seen"问题；旧结果保留。
5. **P2：等训练量/等步数/等来源配比的回放对照**，隔离 replay 算法 vs 数量的影响；否则 R3b-vs-R3c 永远不能作为因果证据。
6. **P2：发布 adapter 或重建说明 + 补全 SHA256SUMS（v32/v33/G0/D7/R3e/C4 round2/eval manifests）**。
7. **P3：read-back 干预**（强制写后读回）检验"验证习惯丢失"机制；目前只能作为候选项。

## 6. 给 Claude 的核对清单（明天）

1. 先读本 review，再读 `deepseek-v0.4/draft.md`；不要用本文件的建议直接覆盖 Astra 的 v0.4，先比较 §4 的差异表。
2. 重跑 `python3 docs/paper/deepseek-support/audit.py`（应输出 44 相符 / 1 无法核验）与 `stats.py`、`make_figures.py`；核对 `audit.json`/`stats.json`。
3. 逐项检查 41/45 分解：`a0-te-v4` 是否 17/18、`a0-final-v4-plan` 的 TextEdit 是否 15/18、训练题 19/30→29/30 的 6/2/2 分解是否成立。
4. 检查修正稿 Table 5 的 anchor 列（R3b 10/24、7/12；R3c 11/24、7/12；R3d 6/24、5/12；R3e 11/24、7/12）与 R3 阴性误用 2/36。
5. 检查 C4 第二轮总体 47/90 vs 41/90 与发票子组 7/18 vs 0/18 是否同时报告。
6. 检查题级统计的口径：是否 task 级、是否 3 次重复先平均、是否精确 sign-flip 与 bootstrap 区间；不要恢复 execution-level Fisher。
7. 检查引用：OpenCUA/AgentNet、TOUCAN、STaR、Dror 2018、Murtaza 2026、Xi 2026、Wu 2026 的题名/作者/年份；Harness² 用 `Harness$^2$`；AWM 年份全文一致（arXiv 2024 / ICML 2025）。
8. 检查模型 provenance：GGUF SHA-256、frozen revision、llama.cpp 版本、16k context；预算三处数字并列。
9. 构建：`cd docs/paper/deepseek-v0.4 && ./build.sh`；当前 9 页、3 图、无 missing character；如有 TeX 环境差异，以 `paper.log` 为准。
10. 不要恢复绝对表述（only / proves / every comparison same-session）；不要把 41/45 写成流水线因果；不要把 D7 意图准确率写成任务成功率。

## 附录 A. 本轮新增/使用的文件

- `docs/paper/deepseek-v0.4/draft.md` — 修正稿源文件（English，9 页构建）。
- `docs/paper/deepseek-v0.4/paper.tex`、`paper.pdf` — pandoc+tectonic 构建产物。
- `docs/paper/deepseek-v0.4/figures/fig{1,2,3}*.pdf` — 三张图（诊断顺序、三层干预、R3 逐题）。
- `docs/paper/deepseek-v0.4/README.md` — 交接说明、与 v0.4 的逐项差异、构建命令。
- `docs/paper/deepseek-support/audit.py` + `audit.json` — 45 项数字的独立复算（44 相符、1 无法核验）。
- `docs/paper/deepseek-support/stats.py` + `stats.json` — 题级配对统计。
- `docs/paper/deepseek-support/make_figures.py` — 从原始 Kaggle 包/G0 结果生成三图。
- `docs/paper/deepseek-redteam-2026-10-27.md` — 内部红队评审（供 Claude 参考，不对外）。
- `docs/paper/deepseek-litcheck-2026-10-27.md` — 文献核查（8/8 真实，无伪造；补引建议）。
- `docs/paper/deepseek-audit-2026-10-27.md` — 独立审计报告（若 verifier 已生成；否则以 `audit.json` 为准）。

## 附录 B. 与前审/ v0.4 的关系

- v0.4 是 Astra/Codex 按前审做的修订；本稿是在同一 v0.3 基础上、按本 review 重新组织的**竞争性修订**，并吸收了 v0.4 中已被我独立核实的修正（单位、测试集、单字段、D7 指标、因果收窄）。
- 本稿不声称 v0.4 的修正是错的；相反，v0.4 的事实修正大多正确。分歧在**证据强度与呈现**：v0.4 过度降级，本稿把可辩护的强结果放回正文，并把不可辩护的部分明确标为 pilot/composite。
- 两份稿子都可以给 Claude 比较；本稿的优势是题级统计、41/45 分解、anchor/阴性误用透明、3 张图和补回的数据来源引用；v0.4 的优势是更短（8 页）且改动更保守。若只选一版，我建议以本稿为骨架、保留 v0.4 的克制措辞。
