# C2.1-B2.2：浏览器新留出五臂迁移

日期：2026-10-03。执行器提交 `8354fff`；统计修正 `9b6063b`、重试边界修正 `a692d68` 均在45次实验结束后完成。**实验完成，浏览器技能学习收益未证明，候选未激活。**

## 执行者与固定方法

本地真实执行者为 Agents-A1-4B Q4_K_M（权重SHA256 `d93c393a9bd5139a4b5cfe24d31ef553c5a497bfb8afec178a354ecbf508f062`），llama.cpp 0.4.1/build10964/commit b29c606e2，Metal、8192上下文、一个slot、reasoning off、KV q8_0。请求temperature=0。网页由真实无头Chromium执行，Playwright 1.63.0；不是字典模拟。云教师为已配置官方DeepSeek Flash，thinking=false，按自然失败同页接管。

冻结三条preferences任务：改初始状态与控件顺序、改语义标签、反转目标状态。SHA256 `46c098fe99e972acca02c76b07584d8e0326c5a9b47ec89ebb07ea5366a4d6c1` 在候选生成前记录；三变体×五臂×三重复=45 runs。repeat/task/轮转臂顺序串行运行，不根据结果增样。三次重复不是三个独立seed，也不作显著性结论。

| 臂 | 方法 | 本地共享上限 | 额外资源 |
|---|---|---|---|
| raw | 原始browser工具 | 6调用、5循环步、16primitive | 无 |
| cloud_takeover | raw失败后继续同一Page，教师DOM打包 | 同raw | 教师6调用、5循环步、16primitive，输出≤1024，请求wire≤12000字节 |
| dev_trajectory | 原始工具加一条验证开发示范的标签/状态轨迹 | 同raw | 提示更长，实测token单列 |
| learned_workflow | 提供上一轮生成的v2技能，通过skill_search/call使用 | 同raw，技能子动作也计primitive | 沿用已有生成成本，不重新生成 |
| local_retries | 同页2/2/1步分配，失败后供给当前DOM及上次停止信息 | 全部尝试合计同raw | 无云模型；不重置页面、调用额度、primitive或480秒总时限 |

每run仅一个隔离runner步骤，fork硬截止480秒。全臂使用compact DOM和独立external_completion；本地输出上限300（主链部分info请求128），不提高技能臂输出。输入48000/output2000为整链名义预留，不是严格累计token截止；超预留、未知usage单列。云费用另建每请求预留/结算ledger，本地token不计云费；按历史假设0.3/1.2美元每百万输入/输出，上限54教师attempt、假设费用≤0.30美元，不声称这是实时账单。超时未报告usage以预留计费，真实已报告usage另表。

评分虽然以`browser-outcome.json`传给通用checker，但该文件由可信观察者独立读取实际HTTP后台和页面保存回显生成，模型没有文件写入工具。只有后台三项设置均满足任务目标、且页面读回与后台一致才得1分；格式正确、工具成功或模型说“完成”均不够。这里评价的是实际网页保存行为，仍然只覆盖一类浏览器任务。

候选bundle digest `9400d42f5119acfff14f1c6acf153f66efe16323e66b9d8f32fe6904ab63ffba`；技能digest `21e4ea889ef87c241161a8df767f03f3be9cb7e11054dee7708b334b856b7cef`。它在dev父子0/3对0/3，未晋级。本轮仅评测，不按test成绩激活。轨迹来自同一次生成的混合学生/教师dev示范；教师当时只observe+Save。轨迹提示重新投影为标签/状态，不保留旧ref、URL、checker或期望文件。反馈与档案证据hash再次核对。

## 本次解决的问题

1. 原 `_run_actor` 每次清零primitive，直接复用会让本地重试多拿额度。新增可控步数/额度保留；只对教师独立actor重置，重试共享原对象。真实Chromium回归证明第一次改的勾选保留到重试保存，16额度耗尽后停止，不再请求模型。
2. 原协议包没有trajectory/retry真实执行器。新增五臂driver、任务/臂/repeat唯一键、配置/source/模型/candidate哈希、逐条原子落盘和恢复；已有终态失败不会重新采样。局部结果始终显示固定45分母。
3. 云/本地混合token会歪曲费用。教师独立ledger，只在教师请求预留/结算；总链ledger费率为0。报告学生独立通过、自然接管及教师token分开。primitive统计合计学生+教师，不只报最后actor。
4. 旧协议报告的“任何test任务拒绝”措辞错误；实际要求所有任务是test。冻结状态只是声明检查，本轮另外与生成前保存的真实SHA比较；没有自动检测所有信息泄漏的能力。开始运行后保存exposure侧记，后续若用结果调方法必须换新盲测清单。
5. 汇总器原先可能把未知usage的保守预算结算标成实测token。用“一个已报告请求+一个未知请求”的回归复现，改为逐调用已报告值汇总并标unknown；保守charge留在ledger。本轮所有请求都报告usage，修正前后各臂统计相同，不重跑模型。
6. 提前返回“Done”的错误回应原先可能造成五次短尝试。真实浏览器回归复现5次，修为最多三次、步数分配2/2/1；本轮九条真实重试恰好都是2/2/1，未受这个边界影响。保存旧源码hash和旧报告，不回写原轨迹。

## 结果与限制

完整固定分母45/45；10次通过、35次未完成，无timeout/crashed/budget_exhausted，全部计入统计。五种方法的样本不能合并为Kage通用完成率。

| 臂 | 完成 | 模型调用（本地/教师） | 实测输入/输出token（本地） | 总primitive | 整任务秒中位数 | 模型请求秒中位数 |
|---|---|---|---|---|---|---|
| raw | 2/9 | 45/0 | 139854/6182 | 43 | 87.442 | 86.230 |
| cloud_takeover | 5/9 | 44/28 | 136829/6692 | 71（含教师） | 88.365 | 86.894（两actor合计） |
| dev_trajectory | 2/9 | 42/0 | 148089/5956 | 40 | 93.294 | 91.913 |
| learned_workflow | 1/9 | 44/0 | 145118/6260 | 43 | 97.653 | 96.320 |
| local_retries | 0/9 | 45/0 | 91149/6754 | 44 | 87.597 | 86.388 |

| 变体（每格三次） | raw | cloud | trajectory | workflow | retries |
|---|---|---|---|---|---|
| 初始状态/控件重排 state | 2/3 | 2/3 | 1/3 | 0/3 | 0/3 |
| 改名/不同初始状态 digest | 0/3 | 1/3 | 0/3 | 0/3 | 0/3 |
| 目标反转 reverse | 0/3 | 2/3 | 1/3 | 1/3 | 0/3 |

云组学生独立通过2/9；自然接管7/9，教师修复3/7，最终5/9。教师实测52481输入、2763输出，28次调用，假设费用 **$0.0190599**（ledger显示$0.019060）；本轮没有未知usage或名义token超预留。工作流生成的既有假设成本$0.0008541单列，本轮未重新生成；二者合计$0.0199140。全部本地调用220次，实测661039/31844 token。45次整任务耗时合计4002.417秒，约66.7分钟。

所有actor证据只出现39次`browser_observe`和202次`browser_act`：**skill_search=0、skill_call=0**。工作流组那一次通过完全由原始动作完成，不能算技能执行收益，不能评价候选执行质量提升。轨迹2/9与raw2/9相同；九次重试未恢复。本轮没有证据证明这三种方法提升能力。云组的5/9与额外资源一起报告，样本不足以作显著性结论。

唯一解析错误在`preferences_transfer_digest--dev_trajectory--r1`：`InvalidToolArguments: browser_act (finish_reason=length)`，模型token已报告，结果保留为失败。主要停止类型为步数上限和提前文本结束；错误保存也不能通过：raw/workflow各有三次、云组两次、轨迹一次失败run曾保存错误值。模型的最终回应与工具success均未代替外部检查。截图45/45生成。

两条下一实验假设：

- **状态解释问题**：反转变体云失败轨迹里，当前Email/Weekly均未勾选，教师却点回勾选并声称“点击未生效”；工具实际均成功。compact-v1省略`checked=false`但保留`value="on"`可能诱发误读，尚未证明因果。在既有dev上只改变显式checked表示，保留动作/额度/模型，记录正确状态解释与完成率；不同时更换引擎或提高步数。另冻新盲测再验证，不用本轮test调提示。
- **技能发现问题**：在dev对比当前search引导与一个最小descriptor/参数schema预览，先检查实际skill_call及真实保存，不追加候选生成直到发现问题被定位。已有生成候选未晋级，不安装到默认主链；如果预览成为方法的一部分，成绩归属于技能+发现策略整体。成功后在生成/选择前冻结新test；人工固定工作流参考归入E6机制对照。

此轮只测preferences一族，不能证明通用电脑能力、权重蒸馏或持续自演化。工具primitive上限相同，但runtime bootstrap每actor免费：raw一份，重试最多三份，本轮重试共27份；所有311个观察snapshot另计，不能声称观察成本严格匹配。token仅名义预留，不是严格累计约束。相同kernel seed并不固定随机DOM标识/端口，独立重建重复不保证同一token流。API别名未绑定供应商内部权重快照。预算匹配人工固定工作流尚未做，留E6，不据此作学习机制归因。

## 验证与复现

代码验证：执行器专项27 passed、当时全量890 passed。两项收尾修正先复现失败再转绿，当前专项6 passed；最新全量 **892 passed、4 skipped、1 xfailed**，耗时113.60秒，有原pygame依赖警告。`git diff --check`通过。核验45唯一键、45外部评分重算、180证据hash、17份基线源码hash；统计修正未改变臂统计。`results.json` SHA256：`1d7a478e94c5e12199799b6690715648fefca19c7d7ed4542168183191b1d444`。

原始数据保留在活动worktree `/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/c21-browser-transfer-2026-10-03/`：config/runtime/exposure/audit、results/report、driver-report-original、llama-server.log、journals、teacher/chain预算、每run的actor-tools、browser.jsonl、独立读回与截图、真实模型请求/响应。凭据未复制。本地模型服务已停止。

在对应worktree启动上述版本本地服务后运行：

```bash
.venv-computer-use/bin/python scripts/experiments/browser_transfer.py \
  --learning-dir artifacts/c21-browser-workflow-learning-2026-10-03 \
  --feedback artifacts/c21-browser-episodes-prep-2026-10-03/preferences_dev-2-generation-feedback.json \
  --teacher-config /Users/wenbo/Kage/artifacts/private/deepseek-settings.json \
  --output-dir artifacts/c21-browser-transfer-2026-10-03
```

以上是实际执行命令。历史配置使用`8354fff`；收尾修正后源码hash变化，因此当前HEAD不应在原目录重新运行。恢复历史须核对旧版本与全部原始证据；新的能力实验使用另一个预注册清单和输出目录。新机器须恢复开发证据、候选、依赖和权重。不要删除失败记录后重新跑同一repeat直到成功。
