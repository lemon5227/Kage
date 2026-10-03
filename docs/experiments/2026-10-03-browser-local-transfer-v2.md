# 新本地留出v2：技能调用迁移与真实开销

日期2026-10-03。方法/候选基线bd18121；新manifest与执行代码f2dca46在真实模型调用前提交。候选沿用未晋级B2.1c bundle9400d42f…、技能digest21e4ea88…，没有根据新test修改技能、提示、检索、步数或输出限制。旧browser-transfer-v1不重跑、不混分母。

## 预冻结协议

三个新test实例：全新标签与字段顺序；四项设置全部需修改；中文指令/页面标签。仅preferences单家族的迁移pilot，不能称通用电脑评测。raw/search/preview各一次，共9次，task旋转臂顺序，每次重置Page/历史/后台。字段目标是公开指令，hidden checker/expected不进入模型提示；工程脚本动作先确认三种夹具在原预算内真实可保存/读回，不作为模型成绩。

实际执行者Agents-A1-4B Q4_K_M，Mac M4 Air16GB、llama.cpp0.4.1/build10964/b29c606e2；权重d93c393a…与开发研究相同。所有臂固定compact-v2、本地原历史策略（不做教师上下文打包）、temperature=0/服务reasoning off，实际35请求max_tokens均300。服务单槽8192上下文/Metal、相同KV/采样配置。raw不加载catalog；search/preview加载同一候选，只有发现策略变化。

保持6调用/5循环步/16 primitives/480秒、HTTP120秒，每run名义48000输入/2000输出预留，整包54调用/432000输入/18000输出。没有云、救场、额外重试或候选生成/晋级。终止失败保留，不同条件数据不覆盖原九次。

## 结果

| 策略 | 独立保存通过 | 模型请求 | 输入/输出tokens | browser primitives | skill_search/call | 合计墙钟秒 |
|---|---:|---:|---:|---:|---:|---:|
| raw | 3/3 | 13 | 40717 / 1580 | 13 | 0 / 0 | 187.160 |
| search | 2/3 | 12 | 38921 / 1374 | 12 | 0 / 0 | 196.443 |
| preview | 3/3 | 10 | 31568 / 1406 | 14 | 1 / 1 | 196.248 |

| 新test | raw：请求/结果 | search：请求/结果 | preview：请求/结果 |
|---|---|---|---|
| labels | 4 / 通过、无技能 | 4 / 通过、无技能 | 4 / 通过、无技能 |
| four | 5 / 通过、无技能 | 5 / 未保存失败 | 2 / 通过、真实搜索+工作流调用 |
| zh | 4 / 通过、无技能 | 3 / 通过、无技能 | 4 / 通过、无技能 |

四项新设置的preview由真实本地模型绑定全部四个参数与新的保存按钮标签，调用原参数化工作流后实际POST/页面读回通过；这是从开发三项设置到四项设置的一个实际调用迁移证据。其内部6次browser primitives（observe+4次修改+Save）照常计量，不把“两个模型请求”写成“两个实际动作”。其他preview通过没有调用技能，不计作技能学习；中文完成只证明这三个模型run能操作中文夹具，不证明中文技能发现。

总体preview相对raw请求少23.1%、输入少22.5%，实际browser primitives多7.7%，墙钟反而多4.9%。不能宣称稳定加速或任务完成率提升：raw与preview均3/3，只有相对search多通过一个。每格一次、三实例、顺序/缓存/机器状态与自然observation ID不同，时延不作统计因果结论。四项一例raw→preview从5到2请求有线索，完整研究仍需多任务/重复及机制消融。

总35次真实本地请求、111206/4360报告tokens，39 browser primitives+1 search+1 call=41工具结果，全部outcome=ok；任务通过8/9，有1个未保存失败，零saved_wrong。usage全已知、无参数截断/模型错误、未超名义预留；总墙钟579.851秒，零云费用（硬件/电力不计此API账本）。未修改评分，不让工具success代替任务通过。

## 唯一失败与R3后续

four/search第一步额外browser_observe，随后正确改完四项checkbox。第五步结束时表单已符合公开目标，但posts=0、record=null，没有Save；score=0、stop_reason=step_limit。可归为“接近保存、缺一步”，不是工具失败、勾选状态误读或参数截断。four/raw第五步Save已经完成，stop_reason同为step_limit但score=1；评分与循环停止原因必须分开。

保持旧成绩不救回。R3在之前六次dev未触发，但这条新证据触发一个**独立新dev的5/6步小对照**，不调整或重跑本轮test。v2结果已用于诊断，后续标exposed，不再用于调优后的盲测。方法修复若需要再验证，另冻v3；不因研究重试无限延后C5.0。

下一固定包最多一次R3-a dev预算诊断，之后C5.0显式实验入口与可信状态、C4.5-DOM示范。候选仍未晋级/安装，模型权重未更新；本次学习证据是procedural skill的发现/执行，不是参数蒸馏。

## 复现与核验

命令：`.venv-computer-use/bin/python scripts/experiments/browser_skill_diagnosis.py --study local-transfer --suite eval/computer-use/browser-local-transfer-v2.json --port 18082 --local-runtime artifacts/c21-browser-local-transfer-v2-2026-10-03/server-runtime.json --skill-bundle artifacts/c21-browser-workflow-learning-2026-10-03/mutation/bundles/9400d42f5119acfff14f1c6acf153f66efe16323e66b9d8f32fe6904ab63ffba --output-dir artifacts/c21-browser-local-transfer-v2-2026-10-03`。

原始目录`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/c21-browser-local-transfer-v2-2026-10-03/`。config/prompt/source/candidate/suite/runtime hash、实际服务props/model/log、journal/预算、35请求/响应、DOM/skill与子动作、后台/页面读回、9截图、audit/artifact-index保存。audit重算9分数（8通过），核63运行hash/18源码hash/suite hash/35请求，验证四项参数绑定与唯一失败的final_form_matches_goal。索引覆盖135文件。

源码比对确认search/preview两组提示hash与已完成dev实验一致，候选不变；新增代码只是读取冻结test协议/选择三臂。工程三种真实夹具先红灯、补loader与manifest后通过，专项22 passed，全量901 passed、4 skipped、1 xfailed（旧pygame warning）。真实推理时不并行重测试。九次结束后停止实验自有服务，健康端口连接失败确认退出。代码/清单与报告独立提交，原始数据保留在活动worktree。
