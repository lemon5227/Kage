# v0.4-deepseek：修改说明与 Claude 交接

日期：2026-10-27。这是用户要求的第二份 v0.4 修订稿（DeepSeek 版），与 Astra/Codex 的 `docs/paper/draft.md`（v0.4）并行，便于 Claude 次日比较。两稿都基于同一份 v0.3 与同一批实验证据；本稿独立重算了数字并重做了组织，未运行任何新模型实验。

## 从这里开始

1. 论文源稿：[draft.md](draft.md)；PDF：[paper.pdf](paper.pdf)；TeX：[paper.tex](paper.tex)。
2. 审稿意见（本稿依据）：[review-deepseek-2026-10-27.md](../review-deepseek-2026-10-27.md)。
3. 对照稿：Astra 的 v0.4：[../draft.md](../draft.md)、[../review-codex-2026-10-27.md](../review-codex-2026-10-27.md)、[../v0.4-changes-and-handoff.md](../v0.4-changes-and-handoff.md)。
4. 复算：`docs/paper/deepseek-support/{audit.py,stats.py,make_figures.py}`；输出 `audit.json`、`stats.json`。审计报告：[../deepseek-audit-2026-10-27.md](../deepseek-audit-2026-10-27.md)。红队/文献：`../deepseek-redteam-2026-10-27.md`、`../deepseek-litcheck-2026-10-27.md`。
5. 原 v0.3 快照仍在 `../versions/`；Astra 的 v0.4 文件未被覆盖。

## 构建

```sh
cd docs/paper/deepseek-v0.4
./build.sh          # pandoc + tectonic；当前 9 页，3 图，无 missing character
```

本机验证：`paper.pdf` 9 页；逐页渲染检查；`paper.log` 仅有 0.1pt 的 alignment overfull（可忽略）；`audit.py` 45 条声明 44 相符 / 1 无法核验；`stats.py` 输出题级统计；`git diff --check` 未运行（未改已跟踪文件）。

## 与 Astra v0.4 的主要差异

| 方面 | Astra v0.4 | v0.4-deepseek | 理由 |
|---|---|---|---|
| 标题 | Interface Design, Teacher Guidance, and Consolidation…: An Empirical Study | Interface, Instruction Adoption, and Forgetting: A Diagnostic Case Study… | 三个 finding + 诊断定位；去掉零信息后缀 |
| 摘要 | 219 词单段；弱结果（G0 10/15）在前，边界分散 | ~200 词；三条 finding 各带数字/边界；边界集中一段 | 可评价性与可读性 |
| 贡献 | "trace-grounded account" | C1–C4 + "不主张什么"（§1） | 审稿人需要可被推翻的主张 |
| 章节 | §4 Interface、§5 Lessons、§6 Consolidation、§7 Deployment | §4 Interface、§5 Presentation-dependent adoption、§6 Consolidation、§7 Related work、§8 Limits | 三问与章节对齐；D7 移入 §8 |
| 统计 | 只 G0 题级 p=0.25；其余 descriptive/future work | §3 分析策略 + 正文题级 p/CI：C4 单字段 p=0.031、TextEdit p=0.031、E-1 p<0.001、R3 in p<0.001、held p=0.047、R3e held p=0.016、C4b p=0.25 | 不把可报的强证据降级 |
| 41/45 | 组合结果，未分解 | Table 3 训练题分解：TextEdit +6/9（v4 接口，v4 无 lesson 已 8/9）、Settings +2/9（v2 引用修复）、Calculator +2/12（guidance）；接口 +8、guidance +2；明确缺 v4-no-lesson 全臂 | 把"管线错觉"变成"接口优先"的实证 |
| v0.4 Table 5 | 单一 Base 行 | 修正稿 Table 5：每版 same-session anchor + 阴性误用列 | R3b held 15/36 仍低于自己 anchor 21/36；R3 有 2/36 阴性误用 |
| C4b | 只报发票 7/18 vs 0/18 | 同时报总体 47/90 vs 41/90（p=0.46）+ 发票子组（题级 p=0.25） | 避免选择性报告 |
| 图 | 无 | 3 图：诊断顺序、三层干预、R3 逐题 | 结论依赖分布形状 |
| 引用 | 8 条 | 14 条：补 OpenCUA/AgentNet、TOUCAN、STaR、Dror 2018、Murtaza 2026、Xi 2026、Wu 2026；补 venue/全作者 | 回放来源/方法可追溯 |
| 复现 | 附录目录 | 模型 hash/软件版本、audit/stats/figures 路径、威胁清单 | 可复现性 |
| 预算/学生 | $4/$1.83；"only one student" | 三处数字并列（$1.83/$1.78/$1.12，未对账）；披露 Nemotron 3/30 部分复现 | 诚实边界 |

本稿**保留** Astra v0.4 中已被独立核实的修正：任务/执行单位、测试集复用、单字段 1/18→14/18、checker/温度/步数边界、D7 intent-only、因果收窄、开发集定位。

## 关键数字与来源（全部为既有证据，无新实验）

- C4 第一轮：V1 1/18、V2 14/18、V2PK 14/18、V2PKST 17/18；总分 29/41/36/39 /90。题级 V1→V2：6/6 改善、平均 +0.72、p=0.031（6 题最小可达值）。第二轮 V2PKST 18/18、41/90；R3e 47/90（vs raw 41/90，p=0.46），发票 7/18 vs 0/18（题级 p=0.25，3/6 题有差异）。来源 v28、v33。
- TextEdit：4/18（fill）→8/18（replace/append）→17/18（line-list）；v4 vs fill 题级 6/6、+0.72、p=0.031。v4 无 lesson 17/18 vs 最终配置 15/18（2 题各差 1 次，噪声内）。来源 `evidence/reports/g0/*`。
- G0：训练题基线 19/30；最终 41/45（29/30 + 12/15；17/18、15/18、9/9）。四条件 3/3/6/10；题级 plan vs none +0.47、p=0.25（5 题，2 题差值为 0）。来源 `evidence/reports/g0/*`。
- E-1：A0 7/24（复制 14/48）、A1 6/24（复制 12/48）、A3 42/48、A4 39/48；题级 A3/A4 vs A0 p<0.001，A3 vs A4 p=0.67；held-out 无提升（−0.17，p=0.50）。来源 v6/v7、e1-report。
- R3：64/72、1/36、21/54；题级 in +0.47（p=3.3e-4）、held −0.39（p=0.047）、web +0.20（p=0.11）。R3b 34/15/31（held 15/36 仍低于自己 anchor 7/12≈21/36）；R3c 34/2/22；R3d 62/6/20；R3e 65/1/22（vs 自己 anchor held −0.56、p=0.016）。R3 阴性误用 2/36，其余 0。来源 v26、v29–v32。
- R2：1,900 行 / 151 task / 704 attempts / 472 successes / 446 组合；训练 1,677/223。来源 `evidence/reports/r2/`。
- 训练：五个配置合计 5.7634 h；R3e 3,257 行 − 6 超长 = 3,251 训练条。
- D7：15/30→30/30→30/30；16/30→30/30→28/30（intent-only）；日期标注 bug 实例存在；无同条件 4B 基线；私有日志未公开。来源 `evidence/reports/d7/`。

## 验证与本轮边界

- `docs/paper/deepseek-support/audit.py` 独立复算 45 项声明：44 相符、1 无法核验（私有账本 $1.83）；运行结果见 `audit.json`，报告见 `../deepseek-audit-2026-10-27.md`。
- `stats.py` 生成题级统计；`make_figures.py` 从原始归档生成 3 图。
- 未运行模型、未训练、未调用教师、未改原始实验数据、未 git commit、未 push、未发布适配器。
- 未完成的实验（与 Astra v0.4 交接一致）：v4-no-lesson 全 15 题 45 次（约 1 小时，$0）；第二学生完整 G0；多训练 seed；冻结方案后的确认集；等训练量 replay 对照；私有 adapter 发布与补全 SHA256SUMS。

## Claude 建议检查顺序

1. 先看本文件表格，再读 `draft.md`；与 Astra v0.4 对照时以 `review-deepseek-2026-10-27.md` §4 的差异表为索引。
2. 重跑 `audit.py` / `stats.py` / `make_figures.py`，核对 44/1 与题级 p。
3. 重点检查 41/45 的 Table 3 分解与 `a0-te-v4` 17/18 vs 15/18 的事实；这是两稿最大的分析差异。
4. 检查 R3 的 anchor 列、阴性误用 2/36、C4b 总体 47/90 vs 41/90。
5. 检查引用真实性（litcheck 已核 8/8；新增 6 条均给 URL）。
6. 构建 9 页 PDF；如合并两稿，建议以本稿为骨架、保留 Astra 的克制措辞；不要把任何一稿的 exploratory 结果升级为确认性结论。

## 文件清单

- `draft.md` — 论文源（English）。
- `paper.tex` / `paper.pdf` — 构建产物。
- `figures/fig1_diagnostic_order.pdf`、`fig2_interventions.pdf`、`fig3_r3_per_task.pdf`。
- `build.sh` — pandoc + tectonic。
- 本文件。
- 相关性材料：`../review-deepseek-2026-10-27.md`、`../deepseek-support/`、`../deepseek-audit-2026-10-27.md`、`../deepseek-redteam-2026-10-27.md`、`../deepseek-litcheck-2026-10-27.md`。
