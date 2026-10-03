# R3-a：第五步与第六步的真实保存预算诊断

日期2026-10-03。开发基线555894d；代码/清单提交1caad61在真实模型调用前完成。**新dev四次全部通过，5步与6步各2/2，没有观察到完成率收益；保留默认5步，下一包C5.0。** 没有重跑、救回或改写旧v2的失败分数。

## 问题与实施

来源是新v2 four/search：先observe，再正确修改四项，5步用完却没有Save。不能把多一个工具success当作完成，也不能在已暴露的test上追加第六步后重算成绩。本包新建两个dev实例：沿用原preferences_dev的公开标签，增加Security summaries；正向/反向都要求改变四项，新保存按钮为Save notification choices。完整目标来自公开指令，评分独立检查真实后台记录与页面读回；隐藏checker不进入模型历史。

BrowserChainProvider新增max_loop_steps。原6请求配置仍默认5，显式配置须为正整数且不超过主执行者的请求保护；已有更小请求预算的调用取min(5, request guard)。cache_identity、metadata及每段chain记录实际循环上限；cloud_direct也使用其主执行者配置，教师保持独立5步，原retry子类保留2/2/1协议。未修改全局AgenticLoop.MAX_STEPS。

先写回归观察红灯，再实现配置。脚本模型先observe、四次真实checkbox点击、Save：5步POST=0且表单正确、评分失败；6步POST=1、实际后台/页面读回正确、评分通过，无第七次模型请求。local/cloud两个主执行者均通过；同run_id改预算被拒绝，同5步复跑读回失败缓存且不再发请求；教师不继承主执行者6步。脚本模型是工程验证，不计入下方AI实验成绩。

## 冻结协议与实际执行者

清单eval/computer-use/browser-save-budget-dev.json，两任务×steps-5/steps-6各一次，共四次，第二任务反转臂顺序；每次重置Page、历史和后台。两组都加载未晋级B2.1c候选9400d42f…，skill_context_mode=search，提示hash完全相同，仅循环上限不同。固定compact-v2、6模型调用、16 browser primitives、480秒、HTTP120秒；无模型输出覆盖，实际21请求max_tokens全为300。

实际执行者Agents-A1-4B Q4_K_M（d93c393a…），Mac M4 Air16GB，llama.cpp0.4.1/build10964/b29c606e2，Metal/8192上下文/单槽/q8_0 KV。temperature=0、服务reasoning off，保持原本地历史策略；无云、教师接管、额外重试、技能生成/晋级/安装或权重训练。config冻结源码18文件、模型/服务props、候选、清单、提示和git版本。完整预留为24调用/192000输入/8000输出，四个终止结果均保留，不重复采样。

## 结果与解释

| 循环上限 | 独立保存通过 | 实际请求/浏览器primitives | 输入/输出tokens | skill_search/call | 合计墙钟秒 |
|---|---:|---:|---:|---:|---:|
| 5步 | 2/2 | 10 / 10 | 36727 / 1129 | 0 / 0 | 124.669 |
| 6步 | 2/2 | 11 / 11 | 41585 / 1207 | 0 / 0 | 129.598 |

| 实例 | 5步 | 6步 |
|---|---|---|
| enable | 5请求：直接改四项→Save；61.743秒；step_limit，通过 | 6请求：observe→改四项→Save；76.617秒；step_limit，通过 |
| reverse | 5请求：直接改四项→Save；62.926秒；step_limit，通过 | 5请求：直接改四项→Save；52.981秒；external_check，通过 |

四次均POST=1、保存记录正确、readback_matches_backend=true，最终表单也符合公开目标；没有模型错误/参数截断、未知usage或未保存/错误保存。工具结果21个全部ok；总实际21本地请求、78312/2336 tokens、254.267秒，API云费用0（不含本地硬件/电力），无活动预算预留。

enable的6步run确实把第六步用于Save，没有继续无效循环。工程控制轨迹证明相同“先observe再改四项”需要第六步才能保存；但实际5步run没有先observe，也已保存，**不能将它描述成一次实际失败被6步救回**。两个新任务都没有形成5步失败→6步成功的模型对照，原v2失败仍是原失败。

6步组合计请求多10%、输入多13.2%、墙钟多4.0%，没有完成率提升。本包每格一次，页面端口/observation ID不同，模型轨迹及缓存/机器状态也不同；不能从小样本推导稳定因果加速或通用能力提升。search工具虽然可用，真实模型仍未搜索/调用，本包不算技能学习证据。

## 核验、复现与下一步

专项42 passed；全量911 passed、4 skipped、1 xfailed，129.20秒，只有原pygame/pkg_resources弃用warning。重测试在模型服务启动前完成。结束后停止自有服务，健康端口连接失败确认退出。独立audit重算4个score、校验28运行证据hash/18提交源码hash/清单与候选hash/21请求，记录每个动作、最后表单、POST/读回、停止与模型错误；索引71文件。results SHA256：d15e3f83f6996233b8ee5e3d157b28a4483a34f49f5cfde8fd1f19fb52f826d3。

复现命令：`.venv-computer-use/bin/python scripts/experiments/browser_skill_diagnosis.py --study local-save-budget --suite eval/computer-use/browser-save-budget-dev.json --port 18082 --local-runtime artifacts/c21-browser-save-budget-dev-2026-10-03/server-runtime.json --skill-bundle artifacts/c21-browser-workflow-learning-2026-10-03/mutation/bundles/9400d42f5119acfff14f1c6acf153f66efe16323e66b9d8f32fe6904ab63ffba --output-dir artifacts/c21-browser-save-budget-dev-2026-10-03`。在新目录/相同代码与服务条件下重现；本次四格不可追加挑选成功，现目录只允许相同冻结配置恢复已完成结果。

原始目录`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/c21-browser-save-budget-dev-2026-10-03/`，保留配置、全部请求/响应、DOM与实际动作、后台/读回、四截图、journal/预算、测试日志、服务启动/停止、audit及artifact-index；recompute-audit.py可在对应代码版本重核。唯一原始副本仍在活动worktree，报告进Git。

本包验收完成，不再扩大R3采样。C5.0复用现有server、后台任务与前端入口，显式提供实验执行器和预算（默认5，可选6），区分运行结束与独立任务完成，展示run_id、实际调用/费用、停止及产物。不得以BackgroundWorker的completed事件代替检查通过，也不得让本包fixture检查器为任意网页签发completed。未晋级候选不默认启用；无可靠检查器标unknown/待人工确认。后续C4.5-DOM、AX与E2/E3/E4按统一队列推进。
