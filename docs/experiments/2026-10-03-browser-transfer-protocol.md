# C2.1-B2.2：新留出五臂迁移协议包

日期：2026-10-03。代码提交`6d32507`。本提交只完成评测协议和分母约束，没有运行新留出，也没有产生迁移成绩。

已冻结`eval/computer-use/browser-transfer-v1.json`：preferences族3个test变体，分别改变初始勾选、控件顺序、语义标签和目标状态；每个任务每个臂3次，五臂为`raw`、`cloud_takeover`、`dev_trajectory`、`learned_workflow`、`local_retries`，固定分母45 runs。文件SHA256为`46c098fe99e972acca02c76b07584d8e0326c5a9b47ec89ebb07ea5366a4d6c1`，协议状态要求生成候选前冻结；任何test任务、重复task_id、未知臂或不合法repeat都会拒绝。

新`TransferPlan`只负责读取冻结清单、计算分母和生成`task--arm--repeat`唯一键，避免重复运行被混入统计。它没有把五臂尚未实现的部分伪装成可执行：当前真实执行器还需要为trajectory和local-retries定义独立的动作/重试策略，并统一云教师额外预算、skill primitive计数和每臂结果投影。

验证：`.venv-computer-use/bin/python -m pytest -q` → **886 passed、4 skipped、1 xfailed**；协议专项3 passed，`git diff --check`通过。下一步接入可恢复五臂执行器，先做小规模单任务烟雾，再按冻结45-run分母完整执行；不把旧dev/reuse结果写入test分母。
