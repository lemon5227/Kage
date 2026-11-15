# 对 DeepSeek review 与修订稿的复核（2026-10-27）

范围：读取 DeepSeek review、修订稿、统计实现与相关证据；另用标准库 Fraction + 动态规划从原始 checkpoints.jsonl / G0 results.jsonl 独立计算精确题级 sign-flip，不采用其 stats.json 的值作为计算输入。未改两份论文、未运行模型、未安排自动实验。

## 判断

DeepSeek 补充的题级统计、逐题图、会话 anchor、阴性误用和 C4b 总体结果应吸收。我的 v0.4 在这些部分完成得不够：不应只删旧显著性而把能做的离线分析留作未来工作。建议以 DeepSeek 的结构为下一稿基础，同时保留 v0.4 的因果边界；不建议原样接受 DeepSeek 全部措辞。

## 独立重算结果

| 对照 | 题数 | 改善/下降/持平 | 精确双侧 sign-flip p |
|---|---:|---|---:|
| C4 设置 V2 vs V1 | 6 | 6/0/0 | 0.03125 |
| TextEdit v4 vs whole-text | 6 | 6/0/0 | 0.03125 |
| E-1 A3 vs A0 | 24 | 17/1/6 | 0.00019073486328125 |
| E-1 A4 vs A0 | 24 | 14/0/10 | 0.0001220703125 |
| R3 learned-file vs base | 24 | 14/2/8 | 0.000335693359375 |
| R3 held-out vs base | 12 | 1/6/5 | 0.046875 |
| C4b R3e vs 同接口 raw，全 30 题 | 30 | 3/1/26 | 0.25 |
| C4b 同上，仅发票 | 6 | 3/0/3 | 0.25 |
| TextEdit final (rules+plan) vs v4 无规则 | 6 | 0/2/4 | 0.5 |

这些数字支持“原稿还能做更完整的题级分析”。其有效性仍依赖题级差值的符号对称性/可交换性假设；没有预注册、多重比较控制和独立确认集，不应将名义 p<0.05 等同为机制已证实。C4 的大效果量与六题同向，比单看阈值更值得强调。E-1 的原始 baseline 仍只有一次，两个 stream 也不足以估计训练/学习过程方差。可用整数/分数动态规划精确算 24/30 题，无需把这些值称作 Monte Carlo 的“精确检验”。

## 对 DeepSeek 仍需修正的地方

1. **“接口 +8、guidance +2”尚非因果分解。** 19/30→29/30 按族的算术分解确实是 TextEdit +6、Settings +2、Calculator +2。TextEdit 的 v4-no-lesson 8/9 与 final 8/9 是有用证据，但其余部分缺同接口、同会话的对照，观察波动亦未隔离。修订稿 Table 3 的 Attributed to、总行与 abstract 的 interface-dominated 比“partial attribution”免责声明更强。建议表改为 observed change / compatible explanation，明确因果贡献未定。
2. **17/18→15/18 不能证明规则无效或有害。** 它说明本样本中未观察到增量，六题中两题下降、四题持平，精确 p=0.5；不能证明总体无收益。DeepSeek 正文“no evidence”基本合适，中文 review 中“没有增量”需限定“观测值”。
3. **R3c 争论被误读。** 我的 v0.4 原文是“It does not prove that gain and forgetting have a single shared cause”，随后明确说明回放数量、来源与步数同时变化。它没有声称“已证明不存在共同原因”。DeepSeek 建议“retention is not a single-variable function of filtering”可采用，但这是表述改进，不是推翻原逻辑。
4. **实验没比较诊断顺序。** 把 interface→adoption→retention 作为建议框架有价值；没有不同顺序的试验，不宜把 C4 diagnostic ordering 写成已验证最优流程。框架/工作假设与 C1–C3 的观测发现分开。
5. **仍有几个具体编辑错误。** Figure 3 图注写“Nearly every in-family task improves”，实际是 14/24 改善、2/24 下降、8/24 持平；应直接写分布。§3 写不报 execution-level Fisher，§6 又放 p=0.46；应统一用题级 p=0.25，或明确旧值仅作历史对照。Review 把 lookalike_readonly 写为 2/36：该子族实际是 **2/12**，所有阴性族合计才是 **2/36**（修订稿主表用全阴性分母是正确的）。§2 把第二学生复现概括为 invalidated，§8 又承认一个有效 3/30 block；应统一为 incomplete，只有后两块作废。摘要的“trained on 1900”最好改为“1677 training examples from a 1900-example corpus”，避免重新混淆训练与验证样本。
6. **R3b anchor 方向不能变成已确认退化。** 15/36 数值低于同会话 7/12；只有一次 anchor，题级 p 约 0.51，不应说已经证明 R3b 相对 base 退化。应同时给 observed gap 与不确定性。不同日期的 $1.12/$1.78/$1.83 也可能只是累计账本的不同时间快照，而非彼此矛盾；待按日期核账。
7. **新增相关工作存在，但应精确限定研究对象。** 在线核对 Murtaza 2609.10750、Wu 2509.13615、Xi 2603.12011、Dror P18-1128 的题名与作者均存在。Murtaza 的直接对象是 skill retrieval 的 retriever/reranker，不等于执行 Agent 的完整策略遗忘；措辞应保留这一差异。

## 下一步实验建议

同意优先补 v4 无规则全 15 题，但不要只跑新臂再与历史 final 对比。先冻结当前代码/接口/规则/模型、记录未提交改动的快照；在同一会话交错运行 v4-no-lesson 和 v4+lesson+plan，统一预算、初始化与检查器。若两臂都各 3 次为 90 次执行；不要承诺只需 1 小时，先用历史耗时或小批估计。可先做三组最可能改变的任务，但必须预先定义选择规则。该实验主要回答固定接口下的组合提示增量，仍不能拆分 lesson 与 planning 各自效果。

冻结后新确认集是解决泛化可信度的直接手段，不应被无限推迟到许多适配器训练之后。第二学生若先改成 v5 再对比主学生 v4，会引入模型×接口混杂；应共同跑 v4，或让两个学生都跑 v4/v5，并明确每个差异。

本次不触发上述实验或明日自动任务；用户目前要求是审查 DeepSeek 的评价。
