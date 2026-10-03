# C2.1-R1：云独立执行与勾选状态对照

日期2026-10-03，父基线6e8c42a，实验代码0cbb766。用户因B2.2低完成率同意先做可靠性诊断，再C5.0入口。这轮没有调用本地模型，也没有训练、生成或晋级技能；实际决策执行者是已配置的官方DeepSeek Flash云API，操作由Kage活Page执行器完成。

## 固定设计与实现

三个开发任务各一次配对：原始状态、已经满足目标但未保存、反向目标。沿用公开preferences_dev标签，均为dev；不读取已暴露browser-transfer-v1来调优。每次启动全新页面/上下文/历史，从初始DOM独立执行，不接管本地模型残留状态。compact-v1省略checked=false；compact-v2显式保留checkbox/radio的checked true/false，其余字段不改。两组同一提示与工具说明解释两种格式；区别只有观察投影与格式标记。

BrowserAdapter保留完整快照作新鲜度/节点身份检查与证据，仅改变模型投影。BrowserCloudProvider复用BrowserChainProvider、AgenticLoop、ToolExecutor、runner/journal/budget，primary_actor=cloud_direct，独立cloud-context-pack日志，规范初始/结束产物照常保存。没有虚构“学生模型”或另造循环。默认仍compact-v1，尚未全局改用v2。

每次最多6模型请求/5循环步/16 primitives/480秒；请求60秒、输入wire≤12000 bytes、输出≤1024 tokens、temperature=0/thinking=false；两组相同上下文归档与外部保存门控。总36请求、名义云预算$0.20；按既有假设0.3/1.2每百万tokens，保守上限$0.1738368。费率用于预算，不是当前报价或实付账单。

评分仍由后台保存记录与页面读回匹配目标，模型不见checker文件/隐藏expected。任何终止失败保留在分母，不重复抽样到成功。

## 真实结果

| 观察格式 | 独立通过 | 云请求 | 输入/输出tokens | 合计墙钟秒 | 最终未保存/保存错 |
|---|---:|---:|---:|---:|---:|
| compact-v1 | 3/3 | 12 | 23144 / 1315 | 16.647 | 0 / 0 |
| compact-v2 | 3/3 | 8 | 14962 / 995 | 11.936 | 0 / 0 |

共20个真实云请求、38106/2310报告tokens，usage全已知，名义费用$0.014204。全部6次有真实POST、后台正确记录、页面读回和截图；实际工具20次ok、2次rejected（过期观察），总22 primitives，不把被拒绝尝试藏掉。

| 开发例 | v1请求/行为 | v2请求/行为 |
|---|---|---|
| original | 3，正确改两项并保存 | 3，一次同批动作复用旧observation被拒绝，使用新观察恢复 |
| satisfied | 5，误启用SMS、先保存错误值，观察后关闭SMS并再次保存 | 1，不改已正确的checkbox，直接保存 |
| reverse | 4，一次同批过期观察拒绝后恢复，最终正确 | 4，正确修改三项并保存 |

v1 satisfied的最终stop_reason为step_limit，但第五步已正确保存，独立分数为1。循环停止原因与任务通过是两个字段，不能把step_limit自动算任务失败。两次StaleObservation都拒绝了旧引用，后续新观察恢复，没有误点证据。

## 结论、限制与下一项

本轮证明云模型在三个干净开发页面上能独立完成；此前教师接管失败不能直接归为云模型不会操作。显式状态有减少误操作的开发线索：本轮请求少33.3%、输入少35.4%、墙钟少28.3%，主要由satisfied一例贡献。每格一次、单一任务族，不声称稳定加速或通用完成率提升；两组通过率相同，不能认定省略false是旧35次失败的主因，也不能和旧留出5/9直接作提升比较。

下一项C2.1-R2固定v2观察，分别检验raw、搜索技能、直接技能预览/参数绑定，复用未晋级候选。先记录真实skill_search/call与外部保存，验证“云规划→确定性工作流”是否可行，再诊断本地模型。旧test不重跑调优；迁移收益须另冻新留出。

## 复现、问题与验证

命令：`.venv-computer-use/bin/python scripts/experiments/browser_state_diagnosis.py --cloud-config /Users/wenbo/Kage/artifacts/private/deepseek-settings.json --output-dir artifacts/c21-browser-state-diagnosis-2026-10-03`。私密配置只读，不复制key。Python3.13、Playwright1.63.0，实际Chromium版本与worker PID在各run证据；冻结config包含16个源码hash、提示hash与完整dev任务。

原始目录：`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/c21-browser-state-diagnosis-2026-10-03/`。config/results/report、独立账本与journal、20次请求/响应、DOM/actions/check/readback/截图、audit与artifact-index均保留；不清理唯一副本。audit逐一重算6分数并校验48个运行证据hash、16个源码hash与20次请求记录，确认实际actor只有cloud_direct。results的SHA见audit.json。

开发问题：新测试首次错误导入tests包，修成pytest测试目录导入；预期的三项红灯随后确认缺少投影参数/cloud provider。已有打包日志沿用teacher命名会误导执行者，新增可配置日志名，云直执行使用cloud-context-pack。实际模型批量动作复用旧观察产生两次拒绝，既有新鲜度检查与错误观察恢复有效；未为掩盖失败关闭检查。

验证：聚焦34 passed；一次全量895 passed、4 skipped、1 xfailed（旧pygame弃用warning）；真实云六次另表，不把工程测试数计成模型成绩。代码与报告分别提交。
