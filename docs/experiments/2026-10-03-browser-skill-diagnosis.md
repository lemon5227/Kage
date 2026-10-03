# C2.1-R2：云规划、技能发现与确定性执行

日期2026-10-03，父基线106a720，实验代码b1e152e。用户已同意可靠性诊断先于入口。本报告保留修复前的固定九次开发实验；随后检索修复另记，不改写原始结果。

## 设计与实现

复用R1三个dev任务，各一次raw/search/preview，共9次，按task旋转组顺序。固定compact-v2观察；实际执行者只有官方DeepSeek Flash云模型，从重置页面/历史开始。相同6调用/5步/16 primitives/480秒，单请求60秒/12000bytes/1024输出tokens，temperature=0、thinking=false、相同上下文打包与后台保存读回评分。名义总费用上限$0.30，按既有假设费率0.3/1.2每百万tokens的保守上限$0.2607552；不是当前报价/实付。

raw无catalog；search有catalog与搜索指引；preview在search基础上直供至多三个skill_id/description/digest/parameters并引导匹配时调用。实现复用已有skill_context_mode，补齐BrowserChainProvider._experiment_soul的browser catalog分支；不是新路由器。没有预填目标参数、没有提供workflow源码或checker；真实模型根据公开指令和页面自己绑定参数。此对照测发现策略整体，不能单独归因于预览内容或附加指引。

候选沿用B2.1c未晋级bundle `9400d42f5119acfff14f1c6acf153f66efe16323e66b9d8f32fe6904ab63ffba`，技能`set_notification_preferences` digest `21e4ea889ef87c241161a8df767f03f3be9cb7e11054dee7708b334b856b7cef`。执行前验证bundle/digest并固定prompt/source/task配置；0生成调用、0晋级、0主链安装。

## 修复前真实结果

| 策略 | 独立保存通过 | skill_search/call | 模型请求 | 输入/输出tokens | 实际browser primitives | 合计墙钟秒 |
|---|---:|---:|---:|---:|---:|---:|
| raw | 3/3 | 0 / 0 | 8 | 14564 / 853 | 8 | 12.843 |
| search | 3/3 | 3 / 0 | 11 | 22284 / 1158 | 9 | 15.759 |
| preview | 3/3 | 0 / 3 | 3 | 5903 / 507 | 11 | 7.715 |

preview三次均实际skill_call、模型独立绑定全部正确设置，后台POST和页面读回通过。每次只需一个云决策，工作流在同一Page观察、跳过已满足字段、改必要checkbox并保存。总11 primitives包含3次技能内部observe，不能说“3个动作完成”或隐藏执行开销。raw/search通过没有skill_call，不计作学习成功。

共22真实云请求、42751/2518报告tokens，无未知usage，假设费用$0.015847。相对同期raw，preview请求少62.5%、输入少59.5%、本轮墙钟少39.9%，实际browser primitives多37.5%；同样3/3完成，不能说完成率提升。每格一次、单族dev，不证明稳定加速、独立迁移、小模型会调用或权重蒸馏。

## 已定位的检索缺陷

search三次真实查询均返回空：前两次`notification preferences enable email disable sms save settings`，第三次`notification preferences toggle checkboxes save settings`。catalog已有通用通知设置技能，原search使用`all(term in skill_id+description for term in query.split())`，要求长查询的全部词都出现；通用技能不描述每个任务值（email/sms/enable/disable），因此被全部过滤。模型随后退回原语完成，额外搜索没有收益。

这解释本轮云search未调用技能，不能解释旧本地模型连搜索都没有调用的现象。修复应保持参数化技能与目标独立，让词项部分匹配后排序并排除零命中，保留空query列表和稳定顺序；先用真实Page回归原查询→找到技能→实际保存，再固定三次云search验证。旧数据保留，不能为了让九次结果好看而回写。

## 证据与验证

运行命令：`.venv-computer-use/bin/python scripts/experiments/browser_skill_diagnosis.py --cloud-config /Users/wenbo/Kage/artifacts/private/deepseek-settings.json --skill-bundle artifacts/c21-browser-workflow-learning-2026-10-03/mutation/bundles/9400d42f5119acfff14f1c6acf153f66efe16323e66b9d8f32fe6904ab63ffba --output-dir artifacts/c21-browser-skill-diagnosis-2026-10-03`。

原始目录：`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/c21-browser-skill-diagnosis-2026-10-03/`。audit重算9分数、验证72个运行hash、18个源码hash、22请求记录与3次模型绑定参数，逐条保存空搜索证据；artifact-index保留文件校验。config记录候选与每组prompt hash，request/response、技能父调用和子动作、后台/读回/截图均保留。

新工程回归红灯确认预览未进入浏览器system提示；补齐后真实Page一个skill_call完成保存，且无需search或多余摘要。专项24 passed，全量896 passed、4 skipped、1 xfailed（旧pygame warning）。软件回归与九次云能力结果分表。下一步先修实际检索，再固定小本地search/preview对照；之后按R3轨迹条件判断是否增加步数，另冻盲测才验收迁移。
