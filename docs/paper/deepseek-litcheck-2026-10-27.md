# 参考文献与相关工作核查（Kage 论文 v0.4）

日期：2026-10-27 · 核查对象：`docs/paper/draft.md` §8 + §References（8 条）、`docs/paper/versions/draft-v0.3.md` §8（旧相关工作和旧参考文献）、`docs/paper/review-codex-2026-10-27.md` §文献核查边界
核查方式：仅使用公开网页（arXiv abs / HTML、OpenReview、会议 virtual site、ACL Anthology、dblp 检索片段），未使用私有凭据；未改论文，未 commit。

## 0. 结论摘要（先看这里）

1. **8 条参考文献全部真实存在，无伪造、无错误 arXiv ID。** 逐条在 arXiv abs 页面核对了题名、作者顺序、年份、编号；4 条已发表论文的会议归属也另行核对。**没有需要撤换的引用。**
2. **需要"改"的只是格式层面：** 4 条在参考文献表内用了 "et al."（正式稿件通常要求完整作者表）；4 篇已发表论文（SWE-agent=NeurIPS 2024、AWM=ICML 2025、LESS=ICML 2024、LoRA=TMLR 2024）在论文里没有写 venue。v0.4 交接文件说"使用 arXiv 版本年份避免混杂未核实会议归属"，其顾虑在本轮已消除——venue 已核实，可以补。
3. **v0.3 的一处作者错误（"Harness², Google"）在 v0.4 已修正**为 "Xu et al."；v0.3 对 LESS 的过强负面结论（"counter-productive"）在 v0.4 已收回到可辩护范围。**v0.4 的相关工作描述整体准确，没有实质误引。**
4. **最需要补的引用只有两条是"数据来源"性质**（缺了会被视为不可追溯）：回放数据来自 **AgentNet（OpenCUA, Wang et al. 2025, arXiv:2508.09123）** 与 **Toucan（Xu et al. 2025, arXiv:2510.01179）**。v0.3 有这两条，v0.4 压缩时丢了，而 §6.1/§6.3 仍在讲 "external replay" 的组成与失效机制。
5. **两项高价值的 2026 新工作直接支撑本文的核心论点**：`2609.10750`（agent 技能微调中的灾难性遗忘，EMNLP 2026 Industry）与 `2603.12011`（RFT 跨环境迁移弱、与 observation/action interface 偏移相关）。另有一篇 CVPR 2026 的 toggle 状态论文（`2509.13615`）独立支持 §4.2 的"显式状态"发现。
6. **唯一无法核验的字段**：Snell et al. (2022) 的会议归属（arXiv 页无 venue，dblp/Semantic Scholar 在本环境被反爬/限流拦截）。按预印本引用即可，不影响论文。

## 1. 逐条核对表（8 条）

判定说明：✓=题名/作者顺序/年份/ID 全部一致；需改=字段或格式需调整；无法核验=关键字段查不到。

| # | 论文条目（draft.md §References） | 官方题名 / 作者 / 年份 / ID | 核对结果 | URL | 需要改成什么 |
|---|---|---|---|---|---|
| 1 | Biderman, D., Portes, J., et al. (2024). *LoRA Learns Less and Forgets Less*. arXiv:2405.09673 | 题名一致；作者 12 人：Dan Biderman, Jacob Portes, Jose Javier Gonzalez Ortiz, Mansheej Paul, Philip Greengard, Connor Jennings, Daniel King, Sam Havens, Vitaliy Chiley, Jonathan Frankle, Cody Blakeney, John P. Cunningham；2024；2405.09673 一致 | ✓（正文）／需改（格式） | https://arxiv.org/abs/2405.09673 ；TMLR 2024 见 https://openreview.net/forum?id=aloEru2qCG | 作者表补全；补 venue：`Biderman, D., Portes, J., Gonzalez Ortiz, J. J., Paul, M., Greengard, P., Jennings, C., King, D., Havens, S., Chiley, V., Frankle, J., Blakeney, C., & Cunningham, J. P. (2024). LoRA Learns Less and Forgets Less. Transactions on Machine Learning Research. arXiv:2405.09673.` |
| 2 | Lee, Y., Nair, R., Zhang, Q., Lee, K., Khattab, O., and Finn, C. (2026). *Meta-Harness: End-to-End Optimization of Model Harnesses*. arXiv:2603.28052 | 题名一致；作者 6 人顺序全对：Yoonho Lee, Roshen Nair, Qizheng Zhang, Kangwook Lee, Omar Khattab, Chelsea Finn；2026-03-30；2603.28052 一致 | ✓ | https://arxiv.org/abs/2603.28052 | 无需改。可选：题名冒号后保持原样即可。 |
| 3 | Snell, C., Klein, D., and Zhong, R. (2022). *Learning by Distilling Context*. arXiv:2209.15189 | 题名一致；作者 3 人：Charlie Snell, Dan Klein, Ruiqi Zhong；2022-09-30；2209.15189 一致 | ✓（venue 无法核验） | https://arxiv.org/abs/2209.15189 | 无需改。venue 查不到（见 §5），保持 arXiv 预印本引用即可，**不要**补未核实的会议。 |
| 4 | Wang, Z. Z., Mao, J., Fried, D., and Neubig, G. (2024). *Agent Workflow Memory*. arXiv:2409.07429 | 题名一致；作者 4 人：Zora Zhiruo Wang, Jiayuan Mao, Daniel Fried, Graham Neubig；arXiv 2024-09-11；2409.07429 一致；已发表于 **ICML 2025** | ✓（正文）／需改（可选 venue/年份） | https://arxiv.org/abs/2409.07429 ；ICML 2025：https://icml.cc/virtual/2025/poster/45496 ；ACM DL：https://dl.acm.org/doi/10.5555/3780338.3782875 | 若写 venue 则年份应为 2025（v0.3 用 2025，v0.4 用 2024，二者不能混）：`Wang, Z. Z., Mao, J., Fried, D., & Neubig, G. (2025). Agent Workflow Memory. In Proceedings of the 42nd International Conference on Machine Learning (ICML 2025). arXiv:2409.07429.` 若坚持引用 arXiv 版本，则正文年份 2024 也可，但需全文一致。 |
| 5 | Xia, M., Malladi, S., Gururangan, S., Arora, S., and Chen, D. (2024). *LESS: Selecting Influential Data for Targeted Instruction Tuning*. arXiv:2402.04333 | 题名一致；作者 5 人全对；2024；2402.04333 一致；**ICML 2024**（arXiv comments 页明确） | ✓（正文）／需改（补 venue） | https://arxiv.org/abs/2402.04333 | `Xia, M., Malladi, S., Gururangan, S., Arora, S., & Chen, D. (2024). LESS: Selecting Influential Data for Targeted Instruction Tuning. In Proceedings of the 41st International Conference on Machine Learning (ICML 2024). arXiv:2402.04333.` |
| 6 | Xu, R., Chen, Y., CuiZhu, Z., et al. (2026). *Harness²: Recursive Agent Harnessing for an Open World*. arXiv:2610.14224 | 题名官方为 "Harness^2: Recursive Agent Harnessing for an Open World"；作者 9 人：Ruiyao Xu, Yanfei Chen, Zhongying CuiZhu, Bhavana Dalvi Mishra, Yifei Ming, Han Yu, Rujun Han, Chen-Yu Lee, Tomas Pfister；2026-10-09；2610.14224 一致 | ✓（正文）／需改（格式） | https://arxiv.org/abs/2610.14224 | 补全作者表并保留上标写法：`Xu, R., Chen, Y., CuiZhu, Z., Dalvi Mishra, B., Ming, Y., Yu, H., Han, R., Lee, C.-Y., & Pfister, T. (2026). Harness$^2$: Recursive Agent Harnessing for an Open World. arXiv:2610.14224.` |
| 7 | Yang, J., Jimenez, C. E., Wettig, A., et al. (2024). *SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering*. arXiv:2405.15793 | 题名一致；作者 7 人：John Yang, Carlos E. Jimenez, Alexander Wettig, Kilian Lieret, Shunyu Yao, Karthik Narasimhan, Ofir Press；2024；2405.15793 一致；**NeurIPS 2024**（ACM DL: Proceedings of the 38th NeurIPS） | ✓（正文）／需改（格式+venue） | https://arxiv.org/abs/2405.15793 ；https://dl.acm.org/doi/abs/10.5555/3737916.3739517 | `Yang, J., Jimenez, C. E., Wettig, A., Lieret, K., Yao, S., Narasimhan, K., & Press, O. (2024). SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering. In Advances in Neural Information Processing Systems 37 (NeurIPS 2024). arXiv:2405.15793.` |
| 8 | Yang, J., Li, Z., Shi, Y., et al. (2026). *Terminal-RSI: Recursive Self-Improving Terminal Agents via Recursive Self-Rewrite and Policy-Refine*. arXiv:2610.22192 | 题名一致；作者 9 人：Junyao Yang, Zongxia Li, Yucheng Shi, Zhongzhi Li, Ruhan Wang, Ruiwen Zhou, Haitao Mi, Shuicheng Yan, Leowei Liang；2026-10-15（v2 10-25）；2610.22192 一致 | ✓（正文）／需改（格式） | https://arxiv.org/abs/2610.22192 | 补全作者表（注意其中有两个 Li, Z.，不能只写一个）：`Yang, J., Li, Z., Shi, Y., Li, Z., Wang, R., Zhou, R., Mi, H., Yan, S., & Liang, L. (2026). Terminal-RSI: Recursive Self-Improving Terminal Agents via Recursive Self-Rewrite and Policy-Refine. arXiv:2610.22192.` |

补充说明（不构成"需改"）：
- 正文是 author-year 风格，同时出现 "Yang et al., 2024"（John Yang）与 "Yang et al., 2026"（Junyao Yang），年份可区分；若目标 venue 要求姓名消歧，可在首次提及时写 "J. Yang et al." / "Junyao Yang et al."。
- Harness² 的官方题名是字面 "Harness^2"；用 "Harness²" 排版是通行写法，但 BibTeX 里建议 `Harness$^2$`，否则可能被下游索引当成不同题名。
- v0.4 只用 8 篇是交接文件中的有意压缩（"引用压缩到直接支撑当前论述的 8 篇"），本表不反对这一取向；上述"需改"全部是格式项，不影响论点。

## 2. 实质论断核查表

| # | 论文/旧稿中的论断 | 来源实际内容 | 判定 |
|---|---|---|---|
| 1 | v0.3 §8：Harness 优化"changes prompts, tools and memory around a model" | Meta-Harness 搜索的是 **harness code**（存/取/呈现给模型的信息），Harness² 递归改的是 **harness 组件/执行壳**，两者都不改权重；说成"只改 prompts/tools/memory"是把范围说窄了 | **v0.3 略过头（overgeneralized）**；v0.4 已拆成两句各自准确的表述，**v0.4 无问题** |
| 2 | v0.3 §8 / 任务问：Terminal-RSI 是"changes the weights of a mid-size model with large compute (27B)"? | 基座 **Qwen3.8-27B**，五阶段 Base→RSR-1→RPR-1→RSR-2→RPR-2，最终 Terminal-RSI-27B；四套基准均值 50.58%（比 Base +29.90、比 RSR-1 +16.33）；基础设施为 Tencent Hy Frontier | **成立**（27B 属实；五阶段训练+大规模评测足以称 large compute） |
| 3 | v0.3 §8：RSR "re-executes tasks with runbooks before SFT and RL at 27B" | 原文：RSR = 已验证轨迹 → **runbook planning** → **leakage review** → 在目标 harness 下带 runbook **fresh public execution** → 去掉 runbook 做 **actor-only SFT**；RPR = critic-inheriting **RL**（PPO + TB-GAE） | **成立且精确** |
| 4 | v0.4 §8：Kage "does not reproduce its reinforcement-learning stages or demonstrate a second recursive training round" | Terminal-RSI 确有 RL（RPR，PPO/GAE）且确有第二轮（RSR-2、RPR-2）；Kage 明确未做 RL/未做第二轮 | **成立**（自我限定准确） |
| 5 | v0.4 §8：Kage 的 guided re-execution "explicitly draws on the recursive self-rewrite component of Terminal-RSI" | 工作日志 **2026-10-18** "路线修订：借鉴 Terminal-RSI 增加巩固环"记录：用户给出该论文，读了 RSR/RPR，采纳 RSR 与递归、不采纳 PPO/critic；R2 采集在 2026-10-18 实现、10-21 正式跑。**有据可查** | **成立**。可选更严谨：写明"采纳的是 RSR 的'带指导重跑→成功轨迹去指导做 SFT'，未采纳 runbook 泄漏审查与 critic/RL"。 |
| 6 | v0.4 §8：Harness² "studies recursive harness adaptation" | 两个层级递归：task-level 用 contrastive Propose-Probe-Compose 无标准答案改当前 harness；harnessing-level 从这些编辑中提经验更新持续改进 harness；在 WorkBuddy-Bench/JobBench/LAB 上对 GLM-5、Gemini 3.5 Flash 最高 +11.5/+4.5/+11.8 | **公平**（略粗，可加 "two-level recursion" 一句） |
| 7 | v0.4 §8：Meta-Harness "searches harness code using prior scores and traces" | 外层 agentic proposer 通过文件系统访问**所有历史候选的源码、分数、执行轨迹**；在文本分类（+7.7、4× 更少 context token）、检索增强数学（200 道 IMO 级 +4.7）、agentic coding（TerminalBench-2）上超过手工 baseline | **准确** |
| 8 | v0.4/v0.3：LESS "selects examples aligned with a target capability" | LESS = optimizer-aware data influence + low-rank gradient similarity，做 **targeted instruction tuning**：按与"体现某能力的 few-shot 例"的梯度相似度选数据；用 5% 数据常常超过全量 | **公平**（v0.4 措辞正确） |
| 9 | v0.3 §8：LESS "is the replay selector we found counter-productive for forgetting" | LESS 原文**没有**主张自己是防遗忘方法，也没做 anti-forgetting 实验；把它当防遗忘回放选择器是**用法问题**，不是方法的普遍缺陷 | **v0.3 过头（wrong generalization）**；v0.4 已明确 "Our unequal-size replay comparison cannot establish a general limitation of LESS as an anti-forgetting method" → **v0.4 已修正，正确** |
| 10 | v0.4 §8：Biderman et al. "compare LoRA with full fine-tuning and document a learning-retention trade-off. Our work has no full-fine-tuning comparator" | 确有 **full-FT vs LoRA** 对照（编程/数学两域；~100K instruction pairs 与 20B tokens continued pretraining）。结论是：标准低秩设置下 **LoRA 在目标域明显不如全参微调（learns less）**，但**在目标域之外更能保持基座能力（forgets less）**，并优于 weight decay/dropout | **公平**，但有一个必须点破的细节：Biderman 的结论方向是"LoRA 比全参**更抗遗忘**"。本文却在 LoRA 下出现 held-out 族近全灭（15/36→1/36），**这不是 Biderman 的"预期 trade-off"，而是更极端的现象**。建议加半句："Biderman et al. find LoRA the more retention-preserving option than full fine-tuning; our held-out losses under LoRA are therefore not predicted by that comparison." 否则读者会以为本文只是复现已知 trade-off。 |
| 11 | v0.4 §8：SWE-agent "studies agent-computer interface design and demonstrates the value of tools adapted to language-model agents" | 原文：ACI（专用文件查看/编辑/测试命令、带 lint 的编辑）显著提升 SWE-bench 与 HumanEvalFix（12.5% / 87.7% pass@1），并分析 ACI 设计如何影响行为 | **公平** |
| 12 | v0.4 §8：Agent Workflow Memory "induces and retrieves reusable procedures" | 原文：从经验中归纳可复用 workflow，并**选择性提供**给 agent；Mind2Web/WebArena +24.6%/+51.1% 相对提升 | **准确** |
| 13 | v0.4 §8：context distillation "transfers information supplied in context into model behavior" | 原文：把 `[instructions]+[input]→[scratchpad]+[answer]` 蒸馏成只给 `[input]` 就输出 `[answer]`；可内化指令/解释、逐步推理、具体训练样本 | **准确** |
| 14 | v0.3 §8："the in-context learning and adoption findings predate our reading of it" | 工作日志：C2（2026-10-17）早于读 Terminal-RSI（10-18）；C3 实现始于 10-18、Kaggle 跑于 10-21。**"predate" 只在 C2 意义上严格成立**，C3 与读论文同周 | **v0.3 措辞偏宽**；v0.4 已不提此句，无需处理。若将来恢复，只写 C2 的 adoption 结论。 |
| 15 | v0.3 §8：replay data = "desktop-action text from AgentNet, MCP tool calls from Toucan" | OpenCUA 的 **AgentNet** = 跨 3 操作系统的 computer-use 演示数据集；**Toucan** = 从近 500 个真实 MCP 环境合成的 1.5M tool-agentic 轨迹 | **描述准确**；但 v0.4 把这两条引用删了（见 §3 必补项） |

## 3. 建议增补/删除（按优先级，最多 10 条；全部已核验）

> 结论先说：**不建议删除任何现有 8 条**。以下是建议增补，前 3 条属于"数据/方法可追溯性"，后 7 条按相关度排序。每条都给可核对的 URL；未核验的一律不列入。

### 必补（缺了会被审稿人质疑可追溯性）

1. **OpenCUA / AgentNet** — 回放数据来源之一，v0.3 有、v0.4 丢失。
   `Wang, X., Wang, B., Lu, D., Yang, J., Xie, T., ... Yu, T. (2025). OpenCUA: Open Foundations for Computer-Use Agents. NeurIPS 2025. arXiv:2508.09123.`（作者 40+ 人，完整名单以 arXiv 页为准；**AgentNet 是该论文提出的数据集名**，不是另一篇论文）
   用在：§6.1（external replay 的来源）与 §6.3（解释为何回放覆盖不到代码能力）。
   URL: https://arxiv.org/abs/2508.09123 ；NeurIPS 2025: https://proceedings.neurips.cc/paper_files/paper/2025/hash/cc7ae529e945226b0d52ea4ac478c4f3-Abstract-Conference.html

2. **Toucan** — 回放数据来源之二，v0.3 有、v0.4 丢失。
   `Xu, Z., Meza Soria, A., Tan, S., Roy, A., Agrawal, A. S., Poovendran, R., & Panda, R. (2025). TOUCAN: Synthesizing 1.5M Tool-Agentic Data from Real-World MCP Environments. arXiv:2510.01179.`
   用在：§6.1/§6.3，与 AgentNet 一起说明回放是"桌面操作 + MCP 工具调用"，**不含写代码**，这是 R3c/R3d 迁移失败的必要背景。
   URL: https://arxiv.org/abs/2510.01179

3. **STaR** — 论文 R3d 的"teacher-written rationales"本质就是 STaR 的 rationalization 步骤（只是由教师写、非自举）。v0.3 有，v0.4 丢失；证据报告 `evidence/reports/r3b/analysis.md` 明确写 "STaR 式的 rationalization"。
   `Zelikman, E., Wu, Y., Mu, J., & Goodman, N. D. (2022). STaR: Bootstrapping Reasoning With Reasoning. NeurIPS 2022. arXiv:2203.14465.`
   用在：§6.1（"Later variants add ... teacher-written rationales"）或 §8 "Experience and consolidation" 段；一句话区分：STaR 用模型自身正确轨迹自举推理，本文用**教师**为无推理目标补写理由、不做淘汰式自举。
   URL: https://arxiv.org/abs/2203.14465 ；NeurIPS 2022: https://dl.acm.org/doi/10.5555/3600270.3601396

### 强烈建议（直接支撑本文核心论点，均为 2025–2026 工作）

4. **agent 技能微调中的灾难性遗忘**（给本文的"巩固换遗忘"提供同领域对照）
   `Murtaza, S. S., Nie, Y., Soni, U., Wen, E., & Frydenlund, A. (2026). When Synthetic Data Hurts: On Catastrophic Forgetting in Skill Retrieval for LLM Agents. EMNLP 2026 Industry Track. arXiv:2609.10750.`
   为什么相关：生产级 34,396 个 skill 的路由器，合成数据微调**提升 in-distribution 但造成真实/OOD 数据的灾难性遗忘**；并用 LwF/EWC/embedding-anchor/L2-init 等持续学习手段缓解。这是与本文 §6 最接近的已发表结果，且给 §9 的"下一步"提供了现成的缓解方法候选。
   URL: https://arxiv.org/abs/2609.10750

5. **RFT 跨环境泛化与接口偏移**（支撑"held-out 差"与"接口重要"两点，同时也提出反例）
   `Xi, Z., Guo, X., Liu, J., Zhang, J., Fan, Y., Zhang, Z., Liu, S., Chai, M., Shi, X., Zhai, Y., Cai, X., Gui, T., Zhang, Q., & Huang, X. (2026). Can RL Improve Generalization of LLM Agents? An Empirical Study. arXiv:2603.12011.`
   为什么相关：结论是 RFT 在**同一环境内跨难度**泛化好，但**跨环境迁移弱，且与 semantic priors 和 observation/action interface 的偏移相关**——正好支持本文"接口/观测空间是迁移障碍"的诊断，也为 §6.3 的"迁移损失可能不是纯遗忘"提供文献依据。注意：该文同时报告"sequential multi-environment training 的 upstream forgetting 很小"，与本文 LoRA 单轮 SFT 的剧烈遗忘不矛盾（设置不同），引用时勿混用。
   URL: https://arxiv.org/abs/2603.12011

6. **GUI toggle 状态感知瓶颈**（独立支持 §4.2 "explicit checkbox state" 的发现）
   `Wu, Z., Mao, R., Tian, Z., Cheng, P., Ju, T., Wu, Z., Dong, L., Sheng, H., Zhang, Z., & Liu, G. (2026). See, Think, Act: Teaching Multimodal Agents to Effectively Interact with GUI by Identifying Toggles. CVPR 2026. arXiv:2509.13615.`
   为什么相关：构造 binary toggle 指令 benchmark，发现现有 agent 在 toggle 控制上显著不可靠，**尤其当当前状态已等于目标状态时**；其 "State-aware Reasoning (StaR)" 明确要求先感知当前 toggle 状态。这与本文"observation 缺 `checked` 字段 → 设置任务 1/18"是同一类失败。**注意缩写撞名**：此 StaR = State-aware Reasoning，与 3 号 STaR（Self-Taught Reasoner）不是一回事；若两条都引，正文分别写全称。
   URL: https://arxiv.org/abs/2509.13615

### 方法学建议（本文 §3/§5 已做 task-level 敏感性分析，但缺引用）

7. **统计显著性与分析单位**
   `Dror, R., Baumer, G., Shlomov, S., & Reichart, R. (2018). The Hitchhiker's Guide to Testing Statistical Significance in Natural Language Processing. ACL 2018, pp. 1383–1392. doi:10.18653/v1/P18-1128.`
   用在：§3 "Statistical interpretation" 或 §5 的 sign-flip 段。理由：本文的核心统计争论就是"execution-level 检验 vs task-level 独立单位"，这篇是该论点的标准引文（v0.3 已有 p 值/检验讨论但无引用）。
   URL: https://aclanthology.org/P18-1128/ ；BibTeX: https://aclanthology.org/P18-1128.bib

8. **训练种子/运行方差**
   `Bouthillier, X., Delaunay, P., Bronzi, M., Trofimov, A., Nichyporuk, B., Szeto, J., Sepah, N., Raff, E., Madan, K., Voleti, V., Kahou, S. E., Michalski, V., Serdyuk, D., Arbel, T., Pal, C., Varoquaux, G., & Vincent, P. (2021). Accounting for Variance in Machine Learning Benchmarks. MLSys 2021. arXiv:2103.03098.`
   用在：§3 或 §9（"one training seed per variant"、"Cross-session baseline reuse"）。理由：该文定量说明 data sampling / init / hyperparameter 方差可以主导 benchmark 结论，直接支撑本文"单训练种子 + 跨会话基线"的保留声明。
   URL: https://arxiv.org/abs/2103.03098 （MLSys 2021 归属见 dblp 记录 `DBLP:conf/mlsys/BouthillierDBTN21`，本环境 dblp 页面被反爬拦截，未直接打开）

### 可选（有空间再加）

9. **多轮递归自我改进的对照**
   `Srikanth, D., Zhao, B., Xu, D., Wu, Y., & Jiang, Z. (2026). Recursive self-improvement of AI research agents. arXiv:2609.26457.`
   用在：§8 或 §2（"does not establish autonomous recursive self-improvement"）。理由：AIDE² 在 **harness/代码空间**连续 8 天完成 **7 轮**自我改进且迁移到 4 个 held-out benchmark；它让"我们只做了一轮权重巩固、且没做第二轮"这个限制有了具体对照物——多轮 RSI 在代码空间已被演示，本文的贡献不是 RSI 本身。
   URL: https://arxiv.org/abs/2609.26457

10. **小型 computer-use agent 这一条线**（§8 目前没有任何 GUI/CUA 文献，只有 SWE-agent 与 web 的 AWM）
    `Qin, Y., Ye, Y., Fang, J., Wang, H., Liang, S., ... Shi, G. (2025). UI-TARS: Pioneering Automated GUI Interaction with Native Agents. arXiv:2501.12326.`（35 位作者，完整名单见 arXiv）
    用在：§8 "Interfaces" 段末或 §1。理由：原生端到端 GUI agent 模型，系列含 2B/7B/72B 变体（2B 变体见 Hugging Face 仓库 https://huggingface.co/ByteDance-Seed/UI-TARS-2B-SFT ），可作为"小型 CUA 已有专门模型与数据路线"的定位引文，避免本文被读成"第一个小模型 CUA"。**不宣称 UI-TARS 测过与本文相同的任务**。
    URL: https://arxiv.org/abs/2501.12326

### 不建议加入的候选（避免堆砌）

- 单纯"又一个 self-improving/记忆/技能库"论文（v0.3 的 Voyager、ExpeL、ACE、SkillRL 等）：AWM + OpenCUA + Terminal-RSI 已覆盖"经验记忆/巩固/RSI"三条线；再加会稀释 §8。
- 未核验的引用一律不列入：v0.3 的 `RouteLLM (Ong et al., 2025, arXiv:2406.18665)`、`ADAS (Hu et al., 2024, arXiv:2408.08435)`、`Voyager (arXiv:2305.16291)`、`ExpeL (arXiv:2308.10144)`、`ACE (arXiv:2510.04618)`、`SkillRL (arXiv:2602.08234)`、`Anthony et al. (arXiv:1705.08439)`、`ARTEMIS (github.com/google/artemis)` 均未在本轮逐条核验；若要恢复任何一条，先按本报告方法核验。其中 **ARTEMIS 是 GitHub 项目而非论文**，不应放在参考文献表里（v0.4 已移除，正确）。

### 删除建议

**无。** 8 条全部承重且均有对应论述；不建议为凑数增删。

## 4. 2026 年后的高相关新工作（支持 / 削弱）

| 论文 | 与本文的关系 | 结论 |
|---|---|---|
| `2609.10750` When Synthetic Data Hurts（EMNLP 2026 Industry） | **支持**：agent 技能微调"in-distribution 涨、OOD/真实数据灾难性遗忘"，且有缓解手段 | 与本文 R3 系列（in-family 30/72→64/72、held-out 15/36→1/36）同向；适合作为相关工作与 §9 缓解方案 |
| `2603.12011` Can RL Improve Generalization of LLM Agents?（2026 preprint） | **支持 + 限定**：跨环境迁移弱且与 observation/action interface 偏移相关；但 sequential 训练的上游遗忘很小 | 支持"接口是迁移障碍"；提醒本文不要把 LoRA 单轮 SFT 的遗忘外推成普遍规律 |
| `2509.13615` See, Think, Act（CVPR 2026） | **支持**：toggle 状态感知是 GUI agent 的独立瓶颈，且"当前状态已等于目标状态"时最易错 | 独立佐证 §4.2 的 explicit-state 诊断；注意与 STaR 缩写区分 |
| `2609.26457` AIDE²（2026 preprint） | **对比/限定**：harness/代码空间 7 轮 RSI，迁移到 4 个 held-out benchmark | 削弱"多轮递归改进一定伴随遗忘"的暗示；本文只做一轮权重巩固，不能反推 RSI 普遍不可行（v0.4 已如此表述，保持即可） |
| `2610.22192` Terminal-RSI（2026，已引） | **对照**：27B 五阶段 RSR/RPR 在多个 Terminal-Bench 上跨基准提升 | 说明"大规模算力 + 多阶段 + RL"下可同时获得提升与跨基准收益；本文的单轮 LoRA 结果不能与之直接比，v0.4 §8 的边界声明是必要的 |
| `2610.14224` Harness²、`2603.28052` Meta-Harness（2026，已引） | **定位**：harness 层自我改进已被证明有效 | 本文的"人工改接口 + 单轮巩固"不是 RSI，v0.4 已明确区分 |

未发现任何 2026 年工作**推翻**本文的 checkbox/行编辑工具/Intent-only D7 结论；接口类结论反而得到上面两篇的独立支持。

## 5. 无法核验 / 伪造项（critical 检查结果）

- **伪造：无。** 8 条参考文献的 arXiv ID 均可打开，题名与作者顺序逐一吻合；不存在"ID 对不上题名"或"作者张冠李戴"的情况。旧稿 v0.3 的 19 条参考文献中，被 v0.4 保留的 8 条已全部核验；**v0.4 没有引入任何新引用**，因此不存在新伪造风险。
- **无法核验的单一字段：Snell et al. (2022) 的 venue。** arXiv abs 页无 comments/venue；dblp 页面被 Anubis 反爬拦截，Semantic Scholar API 返回 HTTP 429。按 arXiv 预印本引用即可，**不要**在未核实的情况下写 ICLR/NeurIPS。
- **无 venue 的三条 2026 工作（Meta-Harness、Harness²、Terminal-RSI）**：arXiv 页面均无会议信息，按预印本处理（harness² 仅 v1，Terminal-RSI v2，均为 2026-10）。这与"concurrent work"定位一致，正文最好显式标 "(concurrent work)"（v0.3 有，v0.4 丢了，见下）。
- **旧稿中已修正但值得记录的偏差**：
  - v0.3 "Harness², concurrent, Google, 2026" 把机构当作者 → v0.4 改为 "Xu et al., 2026"，**已修正**。
  - v0.3 把 LESS 说成"防遗忘回放的反面教材" → v0.4 收回为"不等量比较不能给 LESS 普遍负面结论"，**已修正**。
  - v0.3 "changes prompts, tools and memory" 把 harness 层改动说窄 → v0.4 拆句后**已修正**。

## 6. 给修订的具体动作（最小改动，按顺序）

1. **§6.1/§6.3**：加一句回放来源与内容——"External replay mixed 800 randomly sampled AgentNet desktop-action steps (OpenCUA; Wang et al., 2025) and 600 Toucan MCP tool-call trajectories (Xu et al., 2025); neither contains code-writing steps." 并引用 #1/#2。
2. **§6.3**：补一句 LESS 选择的目标集（来自 `evidence/reports/r3c/analysis.md`：目标集 = 原学生自己带推理的成功样本 + R2 验证集），说明"选择目标与同族训练分布一致，因此'更像目标'的回放可能恰好削弱防遗忘所需的分布差异"——这是本文对 LESS 结果最有力的解释，且不构成对 LESS 的普遍否定。
3. **§6.3 末**：接 #4（`2609.10750`）一句"同类现象已在 agent 技能路由微调中被独立报告，并有持续学习式缓解手段"，为 §9 的缓解实验铺路。
4. **§4.2 末**：接 #6（`2509.13615`）一句，说明"toggle/checkbox 当前状态是 GUI agent 的独立失败点"，把本文的单字段修复放进已知文献谱系（勿声称本文首先发现）。
5. **§3 "Statistical interpretation"**：引 #7/#8，支撑"execution 级检验不独立、需 task 级与多种子"的立场（只作为方法依据，不新增主张）。
6. **§8**：把 Harness² 与 Terminal-RSI 重新标 "(concurrent work)"；顺带把 #5（`2603.12011`）放进 "Experience and consolidation" 或 "Interfaces" 段，说明跨环境迁移与接口偏移相关。
7. **References**：按 §1 表补全 4 条 "et al." 作者表，补 4 个已核实 venue；Harness² 用 `Harness$^2$`；AWM 全文年份在 2024/2025 间取一致。
8. 若篇幅允许：§8 末尾加 #9（AIDE²）与 #10（UI-TARS）各一句，分别锚定"多轮 RSI 已有代码空间先例"与"小型 CUA 已有专门模型线"。

## 7. 方法与限制

- 每条引用都以 arXiv abs 页面为第一手依据；会议归属以 arXiv comments、会议 virtual site（ICML/NeurIPS/CVPR）、ACL Anthology BibTeX、ACM DL 记录交叉确认；**没有打开任何 PDF**（abs 摘要足够回答"题名/作者/年份/ID/一句话论断"这四个问题）。
- Semantic Scholar API 全程 HTTP 429，dblp 被 Anubis 拦截，因此 **Snell et al. 的 venue 与 Bouthillier 的 MLSys 归属只用交叉检索确认，未在 dblp 页面直接打开**；已在相应位置标注。
- 本报告只核验"引用是否真实、描述是否公平"，不重复数值审计（由另一条并行任务负责）；§2 表中的所有"来源实际内容"均可从所给 URL 的摘要页直接复核。
- 所有判定只针对 2026-10-27 时点的 arXiv 版本；若论文投稿前这些 2026 预印本更新版本号，作者表/题名需再核对一次。
