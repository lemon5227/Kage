# Kage 论文 v0.4 红队评审

**评审对象**：`docs/paper/draft.md`（v0.4，218 行，2026-10-27），及其构建产物 `arxiv/paper.pdf`（`paper.log` 显示 8 页，无图）。对照 `versions/draft-v0.3.md`、`review-codex-2026-10-27.md`、`v0.4-changes-and-handoff.md` 与 `evidence/reports/{c4,g0,r3*,e1-report,e2b-report,d7}`。

**评审性质**：对抗性但建设性的同行评审，只看论证、归因、呈现与定位。**数值审计由 verifier 负责，本评审不重算全量数字**。为判断论证是否成立，我只核了四个与论证直接相关的事实点（不替代审计）：

1. G0 的题级 sign-flip：`[2/3, 2/3, 1, 0, 0]` 在 2^5 个符号翻转下 `p = 0.25` 算术**正确**（8/32；0 差值项贡献 4 倍计数）。这条没问题，但**统计量写法与 0 差值的处理**必须写清（见 S2-3）。
2. G0 臂的 `config.json`：`a0-te-v4` 是 `interface: v4, lessons: null`，跑的是与最终配置**同样的 6 个 TextEdit 题**；`a0-final-v4-plan` 是 `interface: v4` + 四条 lesson + `lesson_mode: plan`。前者 TextEdit **17/18**，后者 TextEdit **15/18**（其余 Calculator/Settings 不同）。这不是新实验，是**已有数据没用上**（见 S1-2）。
3. C4 的 `checkpoints.jsonl` 有**逐题**记录（`task_id` 与 `score` 每行一条），因此单字段对照（V1 1/18 vs V2 14/18）**可以做题级检验**，不必只当"描述性"（见 S1-3）。
4. `v0.4-support/recompute.py` 已在仓库里能离线复算 Table 1–6 的主要数字，但正文/附录**从未告诉读者它存在**（见 S2-9）。

**一句话结论**：v0.4 把"说错的事实"和"说得过强的因果"修对了，但同时把**可辩护的强结论**（单字段接口对照、题级可做的检验、接口修复优先于 lesson 的可复现证据、小样本 SFT 的负结果价值）一起降级成了"descriptive/exploratory/future work"。现在的稿件是一份**诚实的实验记录**，还不是一篇论文：它有数据、有边界，但**没有一句可被引用、可被反驳的贡献陈述**，也缺一张让读者相信效应不是由两三个任务驱动的图。

---

## 0. 总体判断与投稿建议（详见 §10）

- **不是数据问题，是叙事与单位问题。** v0.4 的事实层（计数、单位、句界）基本站得住；问题集中在"贡献句—证据—边界"三者的对齐。
- **建议 major revision**：约 1 周、**不需要新训练**；只需要（a）重写 framing/abstract/title，（b）把 3 个已有 arm 的对照和图补上，（c）做一个题级统计小节，（d）跑 45 次本机桌面（无教师成本、约 1 小时）补一个缺的对照。
- 改完后**可以投 arXiv note / agents workshop**；**不建议**以现状投任何正式会议（单模型、单训练种子、开发集评测、5 题关键实验）。
- 不建议走"再补一个大实验"的路：这篇论文的价值在**诊断与负结果**，不在 SOTA。

---

## 1. 贡献、去升级与（残余）过度/不足表述

### S1-1（S1，阻塞投稿）论文没有可陈述的贡献

**位置**：`draft.md:9`（abstract 全段）、`draft.md:17`（"This paper contributes a trace-grounded account of these findings rather than a new general-purpose self-improvement algorithm."）、`draft.md:192`（conclusion 末句）。

**问题**：v0.4 的贡献句是"我们贡献一个 trace-grounded account"和"一个 diagnostic case study"——这是**体裁**，不是**主张**。摘要是一串带限定词的计数；引言给三个问题（interface / presentation / consolidation）却不给三个答案；结论是"实践教训是先诊断接口、再评估遗忘"——这已经接近一篇博客的 takeaway。审稿人读完会问："所以呢？哪一句是这篇论文要你相信、并且可以被数据推翻的？"

**为什么重要**：arXiv/workshop 的评审第一轮只读 title+abstract+intro。当前三者都没有给出一句"我们发现了 X，证据是 Y，边界是 Z"。这不是"谦虚"，是**可评价性缺失**——审稿人无法判断"这篇论文失败会是什么样"。

**怎么改**：在 §1 末尾加一个 3 条 **Claims** 小列表（每条一句主张 + 一个证据指针 + 一句边界），并让 abstract 的骨架与之一一对应。可用的贡献句（诚实且可辩护）：

> We show that, in a single 4B computer-use agent, three failure classes that look alike in traces are separable by intervention: **observation state**, **action representation**, and **guidance presentation**. Consolidating successful rollouts into LoRA weights raises in-family success while erasing held-out capability. The practical claim is an ordering—test the interface, then how guidance is presented, then retention—not an autonomous self-improvement algorithm.

三条 claim 建议写成：

1. *Interface*：A single observation field (explicit `checked: true/false`) and a line-oriented action space each account for most of the failures previously attributed to capability on the corresponding task families (C4 settings 1/18→14/18; G0 TextEdit 4/18→17/18). 边界：顺序开发比较，非随机化、非预注册。
2. *Presentation*：Identical teacher rules placed in the system prompt did not change behavior (3/15), while the same rules presented beside the task with an explicit application plan reached 10/15; the content is held fixed, the mechanism (placement vs. planning vs. restating) is not isolated. 边界：5 个变体、题级 p=0.25。
3. *Consolidation*：A rank-16 adapter trained on 1,900 action-level examples (151 tasks, one seed) raised in-family file success 30/72→64/72 while held-out success fell 15/36→1/36; restoring the filtered targets with rationales did not restore retention, and none of the five configurations isolates a single mechanism. 边界：单训练种子、开发集评测。

### S1-2（S1，阻塞投稿）41/45 的因果归因仍是"组合即管线"，而且缺的那个对照**有现成数据**

**位置**：`draft.md:9`（abstract 的叙述顺序：接口 → lesson 10/15 → "The final desktop configuration achieved 41/45"）、`draft.md:110`、`draft.md:91`。

**问题**：三处叠加。

1. **摘要的顺序制造了"流水线"印象**：接口 → lesson → 41/45 读起来像"接口修好、再教会 lesson、于是 41/45"。但 41/45 的配置同时包含 line tools、v2 参考修复、task-adjacent lessons + planning，**没有任何一个 arm 在最终接口下把 lesson 分量单独关掉**。
2. **正文的基线不可比**：`draft.md:110` 说 "The corresponding earlier baselines were 19/30 and 3/15 under different interface versions."——一句话把两个不同接口下的基线并排放，读者无法知道 41/45 里多少来自接口、多少来自 lesson。§5 的 Table 4（v2 接口、5 变体）只能解释 10/15 那一格。
3. **现成的反证被忽略**：`a0-te-v4`（v4 接口、无 lesson、同样 6 个 TextEdit 题）是 **17/18**，最终配置同一批题是 **15/18**。也就是说，在 v4 接口上，lesson+planning 对 TextEdit **没有增量收益，数值上还低一点**（逐题差 0,0,0,-1,-1,0：6 个任务中 2 个变差、4 个持平、0 个改善，差异在运行噪声内）。这与 §4.3 的"TextEdit 主要是接口问题"完全一致，**是本文最干净的"接口优先"证据**，但论文一个字没提。

**为什么重要**：这是审稿人最容易攻击的点——"你们把三个干预打包成一个 41/45，然后暗示这是顺序流水线的成果；但你们自己的数据里，最后加入的 lesson 分量在 TextEdit 上收益为零。"不处理，41/45 只能被读成**配置成绩**，不能读成**方法结论**；处理了，它反而变成论文最强的论证：**接口修复会吸收一部分本来是"教学"责任的失败**。

**怎么改**：

- 新增一张"最终配置分解"表（**不需要新数据**，TextEdit 部分现成）：

| Arm | Interface | Lessons | TextEdit | Calculator | macOS Settings | Total |
|---|---|---|---|---|---|---:|
| baseline-v1（10 训练题） | v1 | no | 2/9（3 题） | 10/12（4 题） | 7/9（3 题） | 19/30 |
| test-v2（5 变体） | v2 | no | 2/9（3 题） | 1/6（2 题） | — | 3/15 |
| te-v4（6 TextEdit 题） | v4 | no | **17/18**（6 题） | 无此 arm | — | 17/18（仅 TextEdit） |
| final-v4-plan（15 题） | v4 | plan | **15/18**（6 题） | 17/18（6 题） | 9/9（3 题） | **41/45** |

  （注意两件事：baseline 的 TextEdit/Calculator 是**训练题**，final 同族列里含训练题+变体，不能整列相减；Calculator 在 `v4 + 无 lesson` 下**没有** arm，上表该格为"无此 arm"，这正是 45 次运行要补的洞。）

- 论文里直接写：

> At the final interface, adding task-adjacent lessons with planning did not improve TextEdit (17/18 without lessons vs. 15/18 with; within run-to-run variation). At the earlier interface, the same prompt combination raised the five variants from 3/15 to 10/15 (Calculator 1/6→5/6; TextEdit 2/9→5/9), and the TextEdit part of that gain is subsumed by line-oriented tools (`te_fix2`: 0/3 at v2 without lessons, 3/3 at v2 with lessons, 3/3 at v4 without lessons). The 41/45 configuration is therefore a composite whose gains are interface-dominated; it is not evidence that the three interventions compose additively.

- **补 45 次本机运行**（15 题 ×3，约 1 小时，无教师调用）补 `final-v4, no lessons` 全 15 题臂，把上表的 Calculator 空格填上。这是本文**性价比最高**的一个新数据点。
- 摘要不要在 lesson 句之后紧跟 41/45；把 41/45 降到最后一句并写 "a composite configuration, not a pipeline result"。

### S1-3（S1，阻塞投稿）"我们不报显著性"被用成了"我们不做推断"——C4 的强结果被自我降级

**位置**：`draft.md:48`（"We do not carry those significance claims into the main results. ... A comprehensive cluster-aware analysis and new confirmation set remain future work; absence of significance is not evidence of equivalence."）、`draft.md:9`、`draft.md:108`、`draft.md:133`。

**问题**：v0.4 对 P1-1 的修法是"删掉 execution-level Fisher，只留一个 G0 题级 sign-flip（p=0.25），其余一律 descriptive + future work"。这是**过度纠正**：

- C4 单字段对照（6 个 settings 题 × 3 次，同会话，V1 vs V2）是**完全题级配对**的：6 个任务上每题的 3 次成功率可以直接做精确符号翻转/精确符号检验，`checkpoints.jsonl` 里有逐题记录，**现在就能做**。1/18 vs 14/18 这个量级，题级检验几乎必然给出可报告的结论（预期 5–6/6 题同向改善；请 verifier 给准确值）。
- G0 的 10/15 vs 3/15 已经做了题级（0.25），但**没有给逐题 CI**，也没有在摘要/正文把它作为"组合干预只有 5 个独立任务"的正式陈述（摘要里只有一句括号）。
- R3 的 24 题（in-family）与 12 题（held-out）也都是**固定题集 ×3 重复**，同样可做精确配对符号翻转（24/12 对），并把"逐题方向一致"（R3 是 22,22,20 vs 9,12,9；held-out 是 1,0,0 vs 5,5,5）作为**比 p 值更有信息量**的描述。

**为什么重要**：审稿人不会因为你写了 "descriptive" 就不问"这个差异有多大把握"。你把**能做且会显著**的对照说成"未来工作"，等于主动交出了论文最强的一张牌；而留着的那一个 p=0.25（G0）恰好是最弱的。现在的策略是"哪里都别报"，正确策略是"**能用题级就用题级，用不了就明说为什么**"。

**怎么改**：把 §3 的 Statistical interpretation 改成一条**分析策略**（而不是免责声明）：

> We analyze at the task level. Repeated executions are averaged within task; between-condition contrasts are paired within task. For task sets of size ≤ 24 we report the exact task-level sign-flip (paired permutation) probability and a task-bootstrap 95% interval for the mean paired difference; we do not report execution-level Fisher tests. Where a design does not support inference (one arm per task, single training seed), we say so. Absence of significance is not evidence of equivalence.

然后**逐条落实**：(a) C4 单字段 → 题级 sign-flip + 6 题的 per-task 表；(b) C4 round1 vs round2 同一配置（17/18 → 18/18）当作**跨会话复现**来报（现在完全没利用）；(c) R3 家族 → 24 题的题级精确检验 + 12 题的 held-out 精确检验，并报告"每题方向"；(d) 明确训练种子 n=1 使所有 R3 推断都是"对这一个权重"的条件推断，不是对"训练随机性"的推断。verifier 正在算的这些数直接插进去即可，**不需要新数据**。

### S2-1（S2）被删掉的 "adoption gap" 其实还有证据——这是本文最概念化的发现，现在不见了

**位置**：`draft.md:17`（三问句，没有"adoption"这个问句）、`draft.md:54–60`（§4.1 标题 "Demonstration reuse"）、`draft.md:95–106`（§5）、`draft.md:174–176`（related work）。

**问题**：v0.3 的核心概念是"检索可靠、采纳不可靠"（P2-1 只要求删掉 "only when" 的因果断言）。v0.4 把整个 adoption 框架连同过强措辞一起删了。但**支撑它的证据还在**，而且比 v0.3 写得更细：

- G0 同一个 4 条规则、同一个学生：放系统提示 3/15；放任务旁 + 要求先写"每条规则怎么用于本题" 10/15。内容不变、呈现改变——这是**同一实验内**最干净的呈现对照。
- C2：相关示范确实被检索进 prompt，但发票题只在 6 题中的 1–2 题被照做（`draft.md:58` 的前半句保留了这个观察）。
- C3：**同样是系统提示**里的规则（TF-IDF 门控、取前 2 条注入 `core/evolution/lessons.py`），发票题 0/24→14/24——"系统提示 = 不采纳"作为一般规律**不成立**（见下）。

**这里有一个 v0.4 没说、但审稿人一定会问的矛盾**：`draft.md:58` 用 C3 的 0/24→14/24 证明"规则有效"，§5 Table 4 又用"系统提示 3/15"证明"放系统提示无效"。读者不知道 C3 的规则也是注入系统提示的。所以论文要么写出 C3 的投递方式并解释差异（内容类型：缺一步操作 vs 字符串转义/运算优先级；检索门控与条数；显著性），要么删掉任何"系统提示无效"的一般化暗示。

**为什么重要**：这是本文最概念化、也最可与文献对话的发现——**采纳取决于内容类型与呈现方式，而不是知识是否存在**。AWM/context distillation/SWE-agent 都隐含"给到就会用"；C2 给出反例，C3/G0 给出"什么条件下会用"的两端。删掉以后，§4.1/§5 变成两条互不相关的实验，§8 就没有对手可打。

**怎么改**：在 §1 恢复一个"adoption"问句；§4.1 与 §5 合并成一个 §4 "Presentation- and content-dependent adoption"（E-1 作为"示范确实能让同族题从 14/48 到 42/48"的正向前提；C2 作为"检索到不照做"；C3 作为"门控注入的系统规则对缺失步骤有效"；G0 作为"同内容换放置位置效果不同"）；用**保守但明确**的措辞：

> The same four rules had no measurable effect in the system prompt (3/15) but reached 10/15 beside the task with an explicit application plan, on five tasks. This is a within-study presentation contrast; it does not generalize to all system-prompt delivery—C3's relevance-gated procedural rules did improve invoice tasks (0/24 → 14/24). We therefore read the evidence as adoption depending on content type, retrieval, and presentation, and we do not isolate which of these factors is responsible in G0.

注意：3/15→3/15 是**无差异证据**，不能写成"ignored"。可以写 "the rules were not measurably adopted in this arm"。

### S2-2（S2）少量残余过度表述（逐处）

| 位置 | 现文 | 问题 | 建议 |
|---|---|---|---|
| `draft.md:9` | "line-based editing tools increased TextEdit success from 4/18 to 17/18." | 与 P1-4 同类：4→17 跨了**两步**工具改动（+replace/append = 8/18，再加 line-list = 17/18），且是顺序开发比较。 | "replacement and line-list editing tools raised TextEdit from 4/18 to 17/18 over a sequential development comparison (the replace/append step alone reached 8/18)." |
| `draft.md:110` | "Combining the line-oriented tools, reference-handling fixes, and task-adjacent lessons with planning yielded 41/45" | "combining ... yielded" 暗示可加性/因果合成。 | "A final configuration combining ... scored 41/45; as §5.3 shows, the lesson component does not contribute at this interface, so this is a configuration result, not a decomposition." |
| `draft.md:9` | "A deployment case study illustrates the additional distinction between intent classification and end-to-end task success." | 把"意图准确率 ≠ 任务成功率"抬成贡献，实际是常识，且没有端到端对照。 | 删掉这句；D7 移到附录，或写成 "a deployment note records why we stopped treating intent accuracy as a success metric"。 |
| `draft.md:56` | "42/48 ... compared with 14/48 for the reused raw baseline" | "reused" 是内部行话；14/48 是**一次**评测 duplication。 | "42/48 across two checkpoints, against a single raw-student evaluation duplicated across the same two checkpoints (14/48); later raw evaluations of the same 24 tasks ranged 7–13/24."（现在后半句在下一句，读者容易漏） |
| `draft.md:141` | "This rules out the simple account that merely restoring visible reasoning text is sufficient..." | 这句本身成立（R3d/R3e 都恢复 rationale 仍遗忘），但上一句用它来支撑"gain 与 forgetting 非同一原因"，而 R3b-vs-R3c 的对比同时改了回放**算法、数量、来源、步数**。 | 见 S2-3。 |
| `draft.md:176` | "explicitly draws on the recursive self-rewrite component of Terminal-RSI" | 引言里对 Terminal-RSI 的表述没有"借鉴了它的哪一部分、未复现哪一部分"的证据链（v0.3 的 worklog 时间戳论证被删了）。 | 保留现措辞即可，但 related work 需给一行"借鉴的是 guided re-execution，不是其 RSR/RL 流程与 27B 规模"（litcheck 复核数字）。 |

### S2-3（S2）G0 sign-flip 写作：p 值对，但"32 次符号翻转"的解释不完整；而且论文把它当成全文唯一的统计

**位置**：`draft.md:108`。

**问题**：数值正确（我验算 8/32=0.25）。但三处表述值得修：

1. **统计量没写**。读者无法知道 0.25 是对"均值差/总和"做符号翻转（这正是 0.25 的来源），还是对"符号数/秩"做的（会对不上）。应写 "sign-flip test on the mean within-task difference (equivalently the sum), enumerating all 2^5 sign assignments; two tasks contribute zero difference and therefore only the three non-zero tasks drive the statistic"。
2. **0.25 的解释**：应明说"effective n=3（非零题）"，否则 2^5 的写法会让读者以为是 5 个独立证据。
3. **它现在承担了过多作用**。全文唯一一个显著性数字是最弱的那一个（5 题组合干预），而最强的单字段接口对照一个都没有。建议把这段扩成 §5 的一个"题级分析"小节，同时放 G0、C4、R3 三个题级结果（verifier 的数），把它从"敏感性检查"升级成"分析策略的示例"。

### S2-4（S2）"in-family" 到底是什么泛化，全文没有一处定义

**位置**：`draft.md:35`（Kage-Stream 四族 + 两族 held-out）、`draft.md:9`（abstract 直接用 "in-family file success"）、`draft.md:184`（limitations "procedural task families"）。

**问题**："in-family" 在本文意味着"**同一生成模板、不同随机种子**的新任务"，而不是"同一批任务"。审稿人可能把它读成"训练题上的记忆"，也可能读成"同分布的真正泛化"——两者天差地别，而论文没有说。held-out 族是**不同生成器**（text normalization、config migration），所以"15/36→1/36"是**跨模板**损失，这个区分是本文负结果的强度所在，必须明说。

**怎么改**：在 §3 加两句：

> "In-family" denotes new task instances drawn from the same procedural generators used for practice (different seeds and parameters), not the same instances; the two held-out families use different generators, so their scores measure cross-template transfer. All in-family gains reported here are same-generator generalization.

并在 abstract 里把 "in-family file success" 换成 "file success on new instances of the four training families"。

### S2-5（S2）D7/§7 留在正文，且摘要为它背书

**位置**：`draft.md:155–170`、`draft.md:9`。

**问题**：前审已建议"D7 收进部署案例/附录"（review:122），v0.4 把它做成了正文 §7 并给了摘要一句。但 §7：没有对照（缺同条件 4B 路由基线，`draft.md:168` 自己承认）；延迟数字是 illustrative cases；隐私 artifact 不可公开。它贡献的"意图 ≠ 端到端"是一个**常识性区分**，不值得占 8 页预算中的约 1 页和摘要的一个主张位。同时它稀释了"接口/采纳/遗忘"三线主线。

**怎么改**：§7 压成 Appendix B（保留 Table 7 + 一段"为什么我们不把 intent accuracy 当成功"），正文只留 2–3 句在 §9 Limitations 或作为"deployment context"；摘要删掉相应句。

### S2-6（S2）Related work 太薄，且"诊断流程"这个方法论贡献没有被命名

**位置**：`draft.md:172–180`、`draft.md:194–203`。

**问题**：

- 8 篇引用撑不起"interface / consolidation / retention"三条线的定位；**回放数据源（AgentNet/OpenCUA、Toucan）在 §6.1 被提到（"external replay", `draft.md:118`）却完全没有引用**，审稿人无法知道 replay 是什么、为什么它不含写代码样本；SFT/continual learning 的 forgetting 文献也缺（这是本文负结果最直接的对话对象）；instruction-following/prompt-sensitivity 文献缺（"presentation-dependent adoption"需要对话对象）。
- v0.3 明确写了"ARTEMIS 的 Android 自动化启发了接口消融"（v0.3:316），v0.4 把这条**致谢性归因**删了。这是学术信用问题（哪怕是致谢/一句话脚注，也该保留）。
- 论文反复讲"先诊断接口、再谈能力、再评估保留"，但**没有名字**：SWE-agent 的 ACI 是"设计更好的接口"，本文其实是"**对已有失败做归因的流程**"（interface → presentation → retrieval → weights）。这个流程才是可以被他人在别的 agent 上复用的东西，应该命名并放进 §1/§8。

**怎么改**：§8 每条 2–4 句；补 replay 来源、SFT forgetting、prompt presentation 三类引用（具体书目由 litcheck 定，**不要**凭记忆编）；加一段 "A diagnostic ordering" 说明四层归因顺序与每层的判据；恢复 ARTEMIS 的一句归因。

### S2-7（S2）负结果的价值被低估

**位置**：`draft.md:9`、`draft.md:120–135`、`draft.md:192`。

**问题**：现在写成"consolidation improved ... while held-out fell ... follow-up variants do not isolate a single cause"——一个**平衡的 trade-off 叙事**。但实际上：一个 4B 模型、rank-16 LoRA、1,900 条**自己成功轨迹**的 SFT，在**同模板**上 +113%（30→64/72），同时把**跨模板**能力打到 1/36；五版回放/数据修复都不能同时保住两者（除了删掉写答案样本，代价是放弃全部 in-family 收益）。这是**对"用自我轨迹 SFT 来自我改进"这一整类工作都有实践含义的负结果**——而这类负结果在小模型/agent 社区是稀缺的、可发表的。

**为什么重要**：审稿人奖励"清晰、可复现、与流行叙事相反的负结果"；把negative写成"trade-off"，它读起来像"我们没做完的消融"。写清楚，它才是这篇论文的第二个贡献。

**怎么改**：把 §6 的主张从 "observed trade-offs" 改成 "a practically important negative result"，首句直接给结论："In our setting, SFT on the student's own verified successes is not a free lunch: it buys same-generator success at the cost of cross-template capability, and the replay/data variants we tried did not recover both." 再加一句"我们**不**声称这是 SFT 的普遍性质（单模型、单配置、单种子）"。

---

## 2. 摘要、引言、标题

### S1-4（S1，阻塞投稿）Abstract 没有主张，且把最弱的事实放在最显眼处

**位置**：`draft.md:7–9`（219 词，单个自然段，8 个分数）。

**现状诊断**：

1. **无结论句**：末句是"The results motivate interface diagnosis before capability attribution and retention evaluation before deploying consolidated weights."——这是建议，不是发现。
2. **顺序次优**：先给"背景+任务"，再给三个带分数的段，最后"exploratory + 41/45 + D7"。读者最容易记住的是 41/45（最不可靠的数字），最该被记住的是"单字段 1/18→14/18"和"呈现决定采纳"。
3. **jargon 前置**："in-family file success"、"executions"、"held-out-family" 都在定义之前出现。
4. **限定词过密**："although this comparison covers only five distinct tasks"、"Follow-up variants ... do not isolate a single cause"、"this is not an untouched test"——三处免责声明夹在结果之间，读起来像作者不自信。边界应集中在**一段**里，不要每条结果后面挂一句。

**建议骨架（约 180 词，占位处填 verifier 的题级数）**：

> Small computer-use agents fail for reasons that are easy to misattribute. We report a diagnostic case study of Kage, a 4B agent (Agents-A1-4B) on file editing, browser fixtures, and native macOS tasks, in which each failure class was probed by a separate intervention. First, interface: making unchecked checkbox state explicit raised browser-settings success from 1/18 to 14/18 executions on six tasks; replacing whole-text editing with line-oriented tools raised TextEdit success from 4/18 to 17/18 in a sequential development comparison. Second, presentation: identical teacher rules produced no measurable change when placed in the system prompt (3/15) but reached 10/15 beside the task with an explicit application plan, on five tasks (task-level sign-flip p = 0.25). Third, consolidation: a rank-16 LoRA adapter trained on 1,900 action-level examples from 151 tasks raised file success on new instances of the trained families from 30/72 to 64/72, while success on two untrained families fell from 15/36 to 1/36; restoring the filtered targets with teacher-written rationales did not restore retention, and no variant isolates a single cause. These are development-set results with one student and one training seed. The contribution is a diagnostic ordering—test the interface, then how guidance is presented, then retention—not an autonomous self-improvement algorithm.

改完后与 §1 的 3 条 Claims **一一对应**。若目标 workshop 有 150 词限制，砍掉第一句与最后一句的解释，保留三个 finding。

### S1-5（S1）Title 弱且有一处不准确

**位置**：`draft.md:2`；`arxiv/paper.tex` 的 `\title` 与 `pdftitle`。

**问题**：

- "An Empirical Study" 是**零信息后缀**，向评审预告"没有主张"。
- "Teacher Guidance" 不准确：本文关于教师的核心发现是**呈现/采纳**（presentation），不是教师质量；教师本身只写了 4 条规则 + 提供 R2 示范。
- 标题 17 词，偏长。

**候选（按推荐顺序）**：

1. **Interface, Instruction Adoption, and Forgetting: A Diagnostic Case Study of a 4B Computer-Use Agent**（14 词；三个 finding 都在，诚实）
2. **When the Model Isn't the Problem: Diagnosing Interface, Adoption, and Forgetting in a 4B Computer-Use Agent**（更抓人，但 "When the Model Isn't the Problem" 略带修辞，若正文不配强证据会被批 overclaim）
3. 保守版：**Diagnosing Failures of a 4B Computer-Use Agent: Interface, Instruction Adoption, and Consolidation**（"Diagnosing" 开头，最稳）

### S2-8（S2）引言缺 findings list，三问句与章节不完全对应

**位置**：`draft.md:13–17`。

**问题**：v0.3 有 5 条 findings，v0.4 全删，只剩三问句。三问句本身也有错位：§4.1（E-1 演示复用）不属于这三问中的任何一个；§4.3（TextEdit 工具）属于第一问但被放在 §4 而不是 §5（"Ground lessons"）；§7 完全不在三问里。

**怎么改**：引言改为"问题 → 一个反直觉的观察（失败常被归因为能力，实际是接口/呈现）→ 三条 finding（数字+边界）→ 我们不主张什么（一段集中写）"。章节按三问重排：§4 Interface（C4 + G0 TextEdit）→ §5 Presentation/adoption（E-1 前提 + C2/C3 + G0 lessons）→ §6 Consolidation。这样 §1 的三问、§4–6 的章节、§0 的 claims、abstract 的三段**四层对齐**。

---

## 3. 统计推断：该怎么替代删掉的 Fisher

**v0.4 删 execution-level Fisher 是正确决定**（同一题重复 3 次不是 3 个独立样本；G0 的 execution-level p=0.025 确实误导）。但**"删掉"不等于"不做"**，正确替代是**题级配对分析**。论文应报告（不需要新数据，verifier 正在算）：

| 比较 | 任务数 × 重复 | 应报告 |
|---|---|---|
| C4 V1 vs V2（单字段） | 6 × 3，同会话 | 逐题成功率、改善题数（预期 5–6/6）、精确题级 sign-flip p、6 题配对差 bootstrap 95% CI |
| C4 round1 vs round2（同配置） | 6 × 3 ×2 轮 | 作为**跨会话复现**：17/18 → 18/18（settings）、39/90 → 41/90（总体）；报告两轮各自的题级结果 |
| G0 combined vs no-lessons | 5 × 3 | 已有 p=0.25；补逐题差与 CI，并写清 effective n=3 |
| R3 vs base（in-family） | 24 × 3 | 逐题配对差、24 题中改善/恶化题数、精确 sign-flip p、bootstrap CI |
| R3 vs base（held-out） | 12 × 3 | 同上；强调"12 题里 5→1 这种量级"的方向一致性 |
| R3b–R3e vs 各自同会话 anchor | 24/12 × 3（anchor 1 次） | **必须补 anchor 列**（见 S1-6）；anchor 只有 1 次时不得做配对检验，只报描述 |

**S1-6（S1）Table 5 的单一 Base 行掩盖了会话漂移，这是本文最容易被抓的方法学问题**

**位置**：`draft.md:122–131`（Table 5；"Base, v26 | No adapter | 30 | 15 | 10"）、`draft.md:133`、`draft.md:50`。

**问题**：R3b–R3e 与 base 的比较**不是同一次会话**，而且各会话的 base anchor 差异不小（v26 的 in-family 是 9,12,9/24；后续会话的 anchor 分别在 24 题上约 10、11、6、11）。v0.4 只在正文里给了 **R3e 的 anchor（11/24、7/12）**，其余三个版本没有；而 Table 5 只放一行 "Base, v26 30"，视觉上暗示所有行共享同一个基线。后果：

- R3b 的 34/72 与 R3c 的 34/72 看起来"都比 base 30/72 高"，但按各自会话的 anchor（约 30–33/72）看，**R3c 基本没有 in-family 收益**；
- R3b 的 held-out 15/36 被写成"retained substantially more held-out success"（`draft.md:153`），但它自己会话的 anchor 是 7/12≈21/36——相对**未训练的学生**仍然是退化的，只是比 R3 好。这不推翻结论，但改变了"回放能保住迁移"的读法。

**怎么改**：Table 5 加一列 "Same-session base anchor（in-family / held-out）"，R3b–R3e 各填自己的；正文写 "cross-session comparisons use each session's single-run anchor and are descriptive". 并把 §6.2 的 R3b 句改成 "R3b retained more held-out success than R3 (15/36 vs 1/36) but still below its own session anchor (7/12)."

**其他统计表述**：

- `draft.md:48` 的 "That is a sensitivity check under task-level sign symmetry, not a preregistered randomized test." 很好，保留；但应加一句"effective n=3"。
- 全文没有任何 CI（grep 确认）。这是**形式问题**：哪怕 bootstrap 只有 5 个任务，也应给区间并说明它只是描述性区间。
- 训练种子 n=1（`draft.md:118`）目前只在 §6.1 一行。应在 §3 的分析策略里升级为**方法限制**："all consolidation comparisons are conditional on a single trained adapter; inference is over tasks and executions, not over training runs."

---

## 4. 因果：哪些分开了、哪些还混着

**已经分开的（好）**：§2 `draft.md:27`（checker/teacher 边界）、§2 `draft.md:25`（G0 lessons 从训练失败生成）、§5 `draft.md:110`（G0 最终配置 "not evidence of a desktop benefit from the separately trained LoRA adapters"）、§6.3 `draft.md:153`（reduced read-back 是候选机制）。这几处写法站得住，P2-2 的"管道错觉"在正文层面是修了的（摘要层面没有，见 S1-2）。

**还混着的**：

1. **G0 最终 41/45**：见 S1-2。缺 `v4, no lessons` 全 15 题臂；现有 TextEdit 证据反而说明 lesson 分量为零。**这是最重要的一条**。
2. **19/30（v1）vs 29/30（v4+lessons）的"训练题"对照**：两个 arm 的接口、参考处理、规则全部不同，不能读成"lesson 让训练题 +10"。若不做 v4-no-lessons 臂，只能写 "the final configuration improved the training tasks from 19/30 (v1, no rules) to 29/30; the comparison bundles interface and guidance changes."
3. **19/30 与 3/15 是两套不同的题**（训练题 vs 变体），摘要/正文并排出现时容易被读成同一套题的 before/after。`draft.md:110` 已标注 "different interface versions"，但没标 "different task sets"——补一句。
4. **lesson 内容来自训练任务 + 教师可见 expected/found**：`draft.md:25,27` 已声明，够了。但读者会问"变体上的 lesson 是从哪来的"——现文说 "four lessons were generated from failed training tasks and reused"，清楚。建议在 §5 再加半句"变体从未用于生成规则"，把这一点钉死。
5. **C4 round 2 复用配置**：`draft.md:75` 只报告了 18/18 + 41/90。但 round2 同时还跑了 V2PKTST（42/90）和 V2PKTSTCK（41/90），说明配置内的差异在 **±2/90 的会话噪声**内——这既是坏消息（效应小）也是好消息（跨会话稳定）。论文两端都没用。建议把 round1→round2 作为"同配置跨会话复现"报告，并把 41/90 标为 round2 的 raw baseline（它现在是 R3e 的比较基准，见下）。
6. **C4 round 2 对 R3e 的 report 是选择性的**（S2-9）：只写发票 7/18 vs 0/18，不写总体 47/90 vs 41/90（报告原文：整体 p=0.46，不显著，提升集中在发票）。审稿人翻到 round2.md 会认为你在挑子组。**必须**同时报总体与子组，并明确"唯一移动的子族是发票"。
7. **R3b vs R3c 作为"gain/forgetting 非同一原因"的反例是混杂的**（S2-3 已列）：两者不仅过滤方式相同，其余全不同（回放算法、数量 1400 vs 879、来源配比、步数 696 vs 567）。因此它**只能**支持"保留率不是过滤决定的单变量函数"，不能支持"gain 与 forgetting 没有共同原因"。现文后一句用 "It does not prove ... single shared cause" 表述上是对的，但把 R3b/R3c 段放在它下面会被读成论据。建议显式写 "R3b and R3c differ in replay size and composition as well as in retention, so this contrast does not identify replay selection as the cause."
8. **训练/评测同模板**：见 S2-4。

**前审漏掉、但我认为重要的因果点**：前审 P1-3 用 R3b/R3c 的差异反驳"同一批样本"的因果结论——**这个反驳本身也被同样的混杂削弱**。前审没有指出这一点，导致 v0.4 保留了一个逻辑上不成立的论证结构。

---

## 5. 基准与对照：哪些是致命的，哪些对 arXiv note 可接受

| 缺什么 | 对哪条主张致命 | 判定 | 建议 |
|---|---|---|---|
| **同接口、去 lesson 的 G0 全 15 题臂** | 41/45 的因果分解（S1-2） | **致命**（但成本极低：45 次本机运行，约 1 小时，无教师） | 必须补；TextEdit 部分已有的 `a0-te-v4` 先写进表 |
| **同条件 4B 路由基线（D7）** | §7 的"improvement over pattern chain" | 不致命，因为论文已收窄为 case study（`draft.md:168`） | 把 §7 移附录即可；正文不再声称比较 |
| **第二个学生模型** | 标题/摘要的"a 4B agent"之外的一切泛化 | 不致命（标题保持单数、limitations 已写 `draft.md:184`） | 不要加 "small models generally" 类措辞；§9 用一句钉住 |
| **多个训练种子** | 所有 R3 结论的"训练随机性"推断 | 不致命，但**必须**在 §3 声明为条件推断（不是模型级结论） | 写清；不要用"the adapter does X"这种一般现在时 |
| **强制 read-back 干预** | "reduced verification 是机制" | 接受（已降级为 hypothesis，`draft.md:153`） | 保持；不要在任何地方写 "because the student stopped verifying, it forgot" |
| **等训练量/等步数/等来源的回放对照** | "LESS 回放不利于防遗忘" | 接受（已收窄，`draft.md:178`），但**R3b-vs-R3c 反例必须一起撤** | 若保留 LESS 讨论，只当"本实现下的 configuration 观察"；如果要保留"单原因不成立"的论证，就不要依赖这个对比 |
| **冻结方案后的确认集** | 任何 "generalization" 主张 | 接受（已全面改写为 development set，`draft.md:50,110,184`） | 保持；标题里也不要出现 "generalizes" |
| **同模板训练/评测重叠** | "in-family 泛化"的含义 | 接受，但需定义（S2-4） | 一句定义即可 |

**讨论**：对 arXiv note / workshop 而言，这一组缺口的**唯一不可接受项**是 41/45 的分解，因为它便宜且直接决定论文最主要的定性结论；其余都可以用"收窄主张 + 明写条件"处理。审稿人通常不惩罚"没做的实验"，但惩罚"没做却暗示做了"。

---

## 6. 相关工作与新颖性

**当前定位的问题**（详见 S2-6）：论文把新颖性让给了 SWE-agent（"We do not claim interface design as a new principle", `draft.md:174`），然后没有收回任何东西。结果是：

- **不是**新的接口原则（对，SWE-agent 已有）；
- **不是**新的自演化算法（对，已声明）；
- **不是**新的统计方法（对）；
- 那是什么？——**对"失败归因"的诊断性证据**：同一批 4B 学生，看似相同的失败，分别由观察字段、动作表示、指导呈现、权重覆盖导致，且**修错层次会浪费一个训练周期**。这个定位在相关工作中是**空的**：SWE-agent 证明"好接口有用"，本文证明"坏接口会被误读为能力不足"；AWM/context distillation 假设"给到就会用"，本文给出反例与一个有效的呈现方式；Biderman/LESS 研究 LoRA 与数据选择，本文给出"自我轨迹 SFT 的保留代价"的 agent 侧观察。

**建议在 §8 加一个定位句**（放在开头或结尾）：

> The closest work establishes that interfaces and guidance matter. Our contribution is narrower and, we think, complementary: evidence that, in a small agent, the *layer* at which a failure is repaired changes what the other layers can buy—an interface repair absorbs failures that otherwise look like teaching failures, and a successful consolidation can erase capabilities that no benchmark in the training families measures.

**另外**：负结果价值（S2-7）应在 §8 明确与"self-training/self-distillation 叙事"对话——现在 §8 里没有任何一句说"我们的结果对一个流行做法意味着什么"。

---

## 7. 结构、表格、图、术语、篇幅

### S1-7（S1，阻塞 workshop 投稿）全文无图，8 页 7 表

**位置**：全篇；`paper.log` 显示 8 页；`paper.tex` 无 `\includegraphics`/`figure` 环境。

**问题**：本文的两个核心论断都是**分布形状**问题（接口修复把 6 个任务从几乎全错翻到几乎全对；巩固把 in-family 推高、held-out 打崩）。7 张表全是聚合计数，读者无法判断效应是否由 2–3 个任务驱动。前审已在 P2-3 建议加图（"一张干预—结果图和一张数据谱系/实验协议表"），v0.4 一张都没加。

**必须加的 3 张图（按价值排序）**：

1. **Fig. 1（最重要）逐题哑铃图**：R3 vs base 在 24 个 in-family 题与 12 个 held-out 题上**逐题**成功率（0/3…3/3），点线连接 base→trained。它一眼回答"是不是 2 个任务在撑"，同时把 in-family 升、held-out 降的"交叉"画出来。数据在 `checkpoints.jsonl`（逐题）。
2. **Fig. 2 接口/呈现的三个对照**：(a) C4 settings V1 vs V2 的逐题点（6 题，1/18 vs 14/18）；(b) G0 TextEdit 4→8→17 的工具接口阶梯；(c) G0 lesson 四条件 3/3/6/10。三张小 panel 并排，配一句"same student, same tasks, different layer"。
3. **Fig. 3 诊断流程图**：failure → 检查 observation/action space → 检查 guidance presentation（system vs task-adjacent + plan）→ 检查 retention（in-family vs held-out）→ 才算 capability/training 问题。这张图就是"方法贡献"的图形化，也解决 S1-1 的贡献陈述。

**代价**：8 页已到 roadmap 的 4–8 页上限（`docs/plans/tasks-2026-10-14.md:153`）。必须同时删：§7→附录；Table 1 与 Table 7 合并/移附录；§2 的 Cost scope 移附录；E-2 段（`draft.md:60`）压成两句。否则加图后 10 页。

### S2-9（S2）表格可读性与信息缺失

**位置**：Table 1（`draft.md:39–46`）、Table 2（66–73）、Table 3（83–89）、Table 4（97–104）、Table 5（122–131）、Table 6（143–151）、Table 7（159–164）。

具体问题：

1. **Table 1 列了不报告的实验**：E-2 只在 `draft.md:60` 出现，R3 series 之外的 E-1/E-2 没有表；读者会以为后面有对应结果。改：只列 Table 2–6 用到的实验，或标 "context only"。
2. **Table 5 缺 anchor 列**（S1-6）；**Table 5 与 Table 6 应合并**为一表（版本 / 改动 / 训练量 / 回放量 / 步数 / anchor / 三个评测列），现在读者要来回翻。
3. **Table 3 没有版本号**（v2/v3/v4），而正文/别处用 v2/v4；Table 2 用 V1/V2/V2PK/V2PKST。全文应统一 arm 命名（建议 `I-F`=whole-text fill、`I-R`=replace/append、`I-L`=line-list；`O-1`/`O-2`…）并在 Table 1 给出对照表。
4. **表头单位**：Table 3 的 "Total (/18)" 应写 "Total executions (/18)"；Table 4 应写 "(/15 executions; 5 tasks × 3)"；Table 7 "Pattern router 15/30" 应写明 "one prediction per utterance，intent-only"。
5. **Table 4 与 `draft.md:108` 的 sign-flip 段重复**：逐题差 [2/3, 2/3, 1, 0, 0] 已经写在正文，不必再出现在表里；把表留给四条件，段留给统计。
6. **Table 7 的 "After confidence fallback 28/30"**：表注已解释，但列名易被读成"准确率下降到 28/30"，建议改为 "With <0.8 fallback (intent-only)"。

### S2-10（S2）术语与单位不一致（会直接造成审稿人困惑）

| 术语 | 冲突 | 建议 |
|---|---|---|
| "settings" | 浏览器 notification-settings（1/18→14/18）与 macOS System Settings（9/9）**同名不同物** | 全文用 "browser settings (web_prefs)" 与 "macOS System Settings"；摘要尤其要改 |
| "round" | C4 的 round 1/round 2；R3b/R3c 的 "第 2 轮 adapter"（训练 epoch 的第 2 轮）；Terminal-RSI 的 "second recursive training round" | 三处分别改成 "C4 session 2"、"end-of-epoch-2 adapter"、"a second recursive training cycle（与他文对齐）" |
| "R3" vs "R3 series" | `draft.md:44` 用 "R3 series"（=R3–R3e），`draft.md:133` 又用 "R3"（=第一个 adapter） | 第一个 adapter 改称 "R3-a" 或 "the first adapter (R3)"，系列称 "the R3 variants" |
| "executions" / "runs" / "successes" / "attempts" | 摘要 "1/18 to 14/18 executions"、§4.1 "42/48 in-family executions"、§6.2 "learned-file executions"、§6.1 "attempts/successes" 混用 | 定义一次：**execution** = 一次任务尝试；**task** = 独立题；**success** = 通过 checker 的 execution。全文只用这三个词，不再用 "run/attempt/pass" 作同义词（"run" 仅指一次完整的评测会话） |
| "G0" / "Desktop-v1" | G0 从未定义（是实验系列？benchmark 版本？），§3 才出现 "Desktop-v1" | §2 首句定义："G0 is the desktop experiment series on Desktop-v1" |
| "in-family" | 未定义（S2-4） | 定义 |
| "Kage-Stream"/"Kage-Web" vs "file benchmark"/"browser fixtures" | §2 与 §3 两套名字 | 统一 |

### S2-11（S2）附录证据地图太粗，且没告诉读者"可以复算"

**位置**：`draft.md:205–218`、`draft.md:188`。

**问题**：Appendix A 只给目录（`evidence/reports/g0`, `c4`, …），没有"哪张表来自哪个文件"。而仓库里其实有一个**离线复算脚本**（`docs/paper/v0.4-support/recompute.py` + `audit.json`），能重建主要数字——这是本文在可复现性上的**加分项**，正文和附录都没提。§9 的 "many raw evaluation traces" 也太模糊。

**怎么改**：

- Appendix A 改成"每个 Table/Figure → 具体 artifact（目录 + 文件名 + 复算函数）"的表；加一行 "Every number in Tables 2–6 is recomputed from raw archives by `docs/paper/v0.4-support/recompute.py`; see `audit.json`."
- §9 的 "many raw evaluation traces" 改成具体范围（哪些评测的所有原始 trace 在库内、哪些不在）。
- 补 commit hash、llama.cpp 版本、模型量化 hash、Kaggle 数据集版本；adapter 私有这一点已写清（`draft.md:188`），保留。

### S3 级（润色，可批量处理）

- **S3-1** 摘要 219 词、单段；多数 arXiv 模板可接受，但 workshop 常限 150–200，按 S1-4 重写完顺便压到 ≤180。
- **S3-2** 版本标记 `date: 'October 2026 · v0.4'` 与 `\date{October 2026 · v0.4}` 投稿前删掉；补作者单位/联系（arXiv 需要）。
- **S3-3** 日记体措辞："The developer introduced replacement and line-oriented tools"（`draft.md:81`）、"the developer introduced" 类句子改成中性方法陈述（"the tool schema was revised to ..."），透明度不丢、语气更像论文。
- **S3-4** `paper.tex` 用 `secnumdepth=-maxdimen` 去掉编号，但 markdown 标题里手写了 "1. Introduction" 且正文引用 "Section 5"（`draft.md:48`）——编号是手写字符串，交叉引用容易错位。建议恢复自动编号 + `\label/\ref`，或全文改为 "§5"（与 md 一致）。
- **S3-5** 引用格式不统一：有的全作者列表、有的 "et al."；`CuiZhu, Z.` 之类的姓名需核对（交由 litcheck 定，**不要**在本轮改书目以免与 litcheck 冲突）。建议统一成 arXiv 预印本格式：作者（最多 3 人 + et al.）、年份、标题、arXiv id。
- **S3-6** `draft.md:46` 表注 "D7 uses 30 authored utterances per set, evaluated once for intent classification."——D7 在正文 §7，但 Table 1 在 §3，读者会困惑；随 §7 移附录一起处理。
- **S3-7** §2 "Cost scope"（`draft.md:31`）放在方法节里很突兀；移 §9 或附录。$1.83 的"未独立核对"写法（`draft.md:31`）很好，保留。
- **S3-8** `draft.md:188` "Reproduction is not yet complete" 的自我描述在 arXiv 上可以，但建议改成"Reproduction status"小标题 + 清单（缺 adapter、缺 checksum 覆盖、缺 timing 原文），更像 artifact 声明。

---

## 8. 前一轮 P1/P2 覆盖核查

**判读**：✅ 真正解决；🟡 部分解决（表述改了，证据/分析没补）；🔴 未解决。

| 前审项 | 状态 | v0.4 位置与判据 | 仍缺什么 |
|---|---|---|---|
| **P1-1** 重复运行 ≠ 独立任务 | 🟡 | `draft.md:48` 明确"repeated executions are not independent samples"；删 execution-level Fisher；`draft.md:108` 给 G0 题级 p=0.25；`draft.md:39–44` Table 1 分单位；`draft.md:118` 训练种子 1 | 只对 G0 做了题级；C4/R3 没做（数据现成）；CI 全无；训练种子只在 §6.1 一行，未进 §3 分析策略；R3b–R3d 的会话 anchor 没报（S1-6） |
| **P1-2** 测试集被开发过程使用 | ✅ | `draft.md:50` "They measure retention during development, not final untouched generalization"；`draft.md:110` "the variants are development evaluation tasks"；`draft.md:184` "a new post-selection confirmation set was not collected" | 无（作为 scoping 已解决）；确认集列为 future work 可接受 |
| **P1-3** R3 消融不支持确定因果 | 🟡 | `draft.md:139–141` 显式列 R3b/R3c 反例与量/步数/来源混杂；`draft.md:153` read-back 降为候选机制；`draft.md:178` 不给 LESS 普遍结论 | 仍把 R3b-vs-R3c 当作"非单一原因"的论据（该对比本身混杂，见 S2-3）；`draft.md:141` 的 "This rules out the simple account" 与下一句 "It does not prove..." 逻辑指向不一致，需重排论证顺序 |
| **P1-4** 摘要把组合收益归给一个字段 | 🟡 | `draft.md:9` 改为 1/18→14/18；`draft.md:66–73` Table 2 把 17/18 单列；`draft.md:75` 明说打包/状态表是分开的改动 | 同一纪律**没**用到 TextEdit：摘要仍写 "line-based editing tools ... 4/18 to 17/18"（跨两步工具改动 + 顺序开发），见 S2-2 |
| **P1-5** 1900 样本 ≠ 1900 成功轨迹 | ✅ | `draft.md:116` "1,900 action-level examples from 151 unique task IDs ..."；`draft.md:116` 区分 704 attempts / 472 successes / 446 retained keys；`draft.md:118` 1,677/223 按题切分 | 无（472 的"采集成功"语义已写清） |
| **P1-6** 预算/温度/checker 边界 | ✅ | `draft.md:21–23`（分域预算、温度 0.7）、`draft.md:27`（G0 教师可见 expected/found）、`draft.md:91`（newline 要求在公开指令中） | 无（温度零非确定性主张已删） |
| **P1-7** D7 30/30 ≠ 任务成功、≠ 4B 不适合选择 | ✅ | `draft.md:159–168` intent-only、日期标签错误、阈值后 28/30、无同条件 4B 基线、set 1 已复用为开发数据（`draft.md:166`） | 表述上解决；但 §7 仍在正文占位（建议移附录，S2-5）；"After confidence fallback 28/30" 的列名仍可能被误读（S2-9.6） |
| **P2-1** grounded lessons 因素未隔离 | 🟡（表述✅/实验🔴） | `draft.md:106` "it does not isolate rule content, location, or extra deliberation"；无 "only when" | 未加"任务旁规则但不计划"、"同长度无关规则＋计划"两个对照；`draft.md:9` 的 "lessons beside the task with an explicit planning instruction" 已把两个因素并列，措辞是对的 |
| **P2-2** 开发者参与 vs 自主自演化 | ✅（表述）/🟡（41/45） | 标题改、`draft.md:17` "rather than a new general-purpose self-improvement algorithm"、`draft.md:110` 明确最终配置≠LoRA 收益、`draft.md:31` $4 只是教师预算 | 摘要的叙述顺序仍制造"接口→lesson→41/45"的管道印象（S1-2）；成本只报训练 wall time 5.8 h，缺评测 GPU 时间（S3） |
| **P2-3** 报告与复现完整性 | 🟡 | 字体已换（handoff 说 Latin Modern）；`draft.md:188` 列缺口；新增 `v0.4-support` 离线复算 | **一张图都没加**（前审明确建议）；PDF 仍 8 页无图；`recompute.py` 未被正文/附录引用；附录证据地图仍粗；adapter 仍私有 |

**前审漏掉、我认为重要的 7 点**：

1. `a0-te-v4`（v4 无 lesson，TextEdit 17/18）与最终配置（15/18）的对照——**现成的"接口优先"证据**，前审没有发现 v0.4 里这个自相矛盾的地方。
2. Table 5 单一 Base 行掩盖 R3b–R3d 的会话 anchor 漂移；前审只指出 R3e anchor 缺失。
3. C4 round2 的总体 47/90 vs 41/90（p=0.46，不显著）被 v0.4 略去，只报发票子组——**选择性报告**，前审未点出（前审只关心 0/54 pooled 的问题）。
4. "删掉所有显著性"是过度纠正：C4 单字段是**可做题级检验**的（逐题 checkpoint 存在），前审 P1-1 建议了题级区间但没追责 v0.4 只对 G0 执行。
5. 前审用 R3b/R3c 差异反驳"同一批样本"的因果，**这个反驳本身被回放/步数混杂削弱**；前审没意识到自己引入的反例不成立，v0.4 继承了这个论证结构。
6. 术语冲突（settings 二义、round 三义、R3/R3 series、executions/runs/successes）与 "in-family" 未定义——全是 S2 级可读性问题，前审未覆盖。
7. 前审把"无图"放在 P2 级，v0.4 因此没加；对一篇结论完全依赖"聚合→逐题分布"的论文，这是 **S1**，建议升级。

---

## 9. 竞品 "v0.4-deepseek" 应该怎么做（≤8 条，按价值排序）

1. **先写贡献句，再改一切**：三条 Claims（interface / presentation / consolidation）+ 一句 "what this is not"，然后让 title、abstract、intro、conclusion 都指向它。标题换成 *Interface, Instruction Adoption, and Forgetting: A Diagnostic Case Study of a 4B Computer-Use Agent*（或 S1-5 备选）。
2. **把 41/45 拆开**：用现成 `a0-te-v4` 证明"v4 接口已解决 TextEdit（17/18），lesson 无增量（15/18）"；再跑 45 次本机（v4、无 lesson、全 15 题）填满分解表。41/45 从"流水线成果"改写成"接口主导的配置成绩"，这反而让"接口优先"成为实证结论。
3. **题级统计替代"全部删掉"**：C4 单字段（6 题）、C4 round1/round2 复现、G0（已有 0.25，补 CI 与 effective n=3）、R3 in-family（24 题）/held-out（12 题）各做精确配对符号翻转 + task bootstrap CI + 逐题方向计数；§3 写成分策略而不是免责声明。
4. **R3 的会话锚点进表**：Table 5 加 "same-session anchor" 列，R3b–R3e 各填；把 "R3b retained held-out success" 改成 "vs. R3 是恢复、vs. 自己的未训练 anchor 仍退化"。同时把 C4 round2 的 47/90 vs 41/90 如实写进 §6.2。
5. **加 3 张图**：Fig.1 逐题哑铃（R3 vs base，24+12 题）；Fig.2 三个接口/呈现对照的 panel；Fig.3 诊断流程图。为此删：§7→附录、Table 1 精简、§2 cost→附录、E-2 段压两句——保证 ≤8 页（当前正好 8 页）。
6. **恢复 adoption 框架但不恢复因果**：§4 合并 E-1（正向前提）+ C2/C3 + G0 lesson（呈现对照），主张"presentation matters"；对系统提示那组用"not measurably adopted"，不写"ignored"。
7. **把负结果写成卖点**：§6 标题改 "A practically important negative result: consolidation buys same-generator success and costs cross-template capability"；§8 加与 self-training/context-distillation 叙事的对话；§9 明写单模型、单种子、开发集。
8. **可复现性加分**：附录指到 `recompute.py`/`audit.json`、每张表的 artifact、commit/llama.cpp/量化 hash；附"证据地图"表；统一术语表（execution/task/success；browser settings vs macOS System Settings；C4 session 1/2；R3 variants）。

---

## 10. 总体建议与 Top-5 改动

**建议：major revision，然后作为 arXiv 预印本 / agents workshop 论文投稿。** 不建议以现状投任何正式会议，也不建议再补大实验。

理由：(a) 数据与边界基本诚实，数值审计由 verifier 复核中，不构成投稿障碍；(b) 阻塞项全部是**写作、已有数据重组、一个 1 小时的本地对照**，不是新研究；(c) 单模型、单训练种子、开发集评测、5 题关键实验，这四条决定它只能是 case study 定位，不是方法论文；(d) 一旦按 §9 重构，"接口诊断 + 呈现依赖的采纳 + 自我轨迹 SFT 的负结果"是 workshop 会感兴趣的、可引用的东西。

**Top-5（按执行顺序）**：

1. **贡献句 + 标题 + 摘要骨架**（S1-1/S1-4/S1-5）。
2. **G0 分解**：写入 `a0-te-v4` 的 17/18 vs 15/18；补 45 次 v4-无-lesson 全 15 题运行；41/45 改写成 composite（S1-2）。
3. **题级统计小节**：C4 / G0 / R3 三组精确配对检验 + CI + 逐题方向；§3 写成分策略（S1-3/S1-6）。
4. **R3 Table 5 加 anchor 列 + C4 round2 全量报告**（S1-6/S2-9）。
5. **3 张图 + 删 §7/Table 1 精简到 ≤8 页 + 术语表统一**（S1-7/S2-10）。

**如果只能做一件事**：做第 2 条。它把论文最大的软肋（41/45 的复合归因）变成论文最强的证据（接口优先），且几乎零成本。

---

### 附：本评审的核验范围声明

- 未重做数值审计；未对论文、实验数据、脚本做任何修改；未运行模型/训练/教师调用；未 commit。
- 本文件是唯一写入。文中"我核过"的四个事实点见开头说明；其余数字引用均来自论文或 evidence 报告原文。
- 前审 = `docs/paper/review-codex-2026-10-27.md`；本评审的 P1/P2 覆盖表以该文件 124 行为准。
