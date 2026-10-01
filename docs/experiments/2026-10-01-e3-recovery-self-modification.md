# E3.0 真实恢复源码演化首实验

日期：2026-10-01。结果：默认恢复源码父代0分、云生成恢复源码子代1分；冻结的新文件/函数变体通过。实际AgenticLoop加载了不同源码、触发原ToolExecutor的skill_call，不是仅改提示、技能或模型权重。仅一个模块、一个任务家族的首pilot，尚非通用持续自进化。

## 架构与唯一实验变量

执行：同一Agents-A1-4B Q4_K_M → 同一PromptBuilder/技能目录 → AgenticLoop → recovery源码（默认stop/候选switch_tool）→ 原ToolExecutor → 同一Docker技能 → 实际文件 → 外部Python函数检查。

父子都采用search发现协议（不是C4.3预览协议），提示SHA256均为`4d703ee82f82eed647abafcb1fb923419b07fc266bc6d3cb538a5aabde794366`。冻结技能digest均为`6ecb72febf4945a385909abdd49e8fbed038ae6a74647b87e874a0dda022d69d`，技能代码没有改变。恢复代码从读文件的真实历史推断路径/函数，选择运行时descriptor中的skill ID/digest，再返回工具动作。原5循环步/6模型调用/150秒上限不增加。

父bundle digest：`3963d3f2a0611705b65c7b401b5420b191772ed44b0e5726369702e069260569`。子bundle digest：`66cf3af5eefae1450bf45109877cdf24481ef7e57ee862cf4851f9802366c4ff`。新模块SHA256：`6a57906701e15aaf6e7ffacce9e65b369dfc9ec63d21014bbea580595458f1bb`；固定adapter合并后的实际执行源码SHA256：`5017bc748ffa636ab1194fa95596bae66874e6962f721e29c1d8184604282712`。实际模块文件位于当前worktree的`artifacts/e3-recovery-pilot-v1/mutation/bundles/<子digest>/recovery-<模块hash>.py`；Docker worker为/runtime/skill.py，恢复源码只挂载scratch目录，不直接挂载任务工作区。

## 冻结任务与实际成绩

开发集`eval/computer-use/recovery-dev-v1.json`复用已有开发失败，不使用C4.4留出反馈；SHA256 `5bf7129884077848849a9de67464ba8a64cb8b34597c581596e36d14830a00c7`。云生成输入只有实际dev失败、默认恢复源码与技能schema，不含评分答案。

新变体在生成前写好：scheduler.py/select_tasks、新工作项ID和值；SHA256 `97acb2a782e158014e421428c7b49a23abd8f51ea29bea28ac8735dcf31e443e`。生成器从未读取该任务；固定候选后只执行一次。外部检查验证最大价值、容量、并列字典序、空选择及非法参数；不将模型“Done”当通过。任务说明中的不修改输入要求尚没有专门的独立mutation断言，不能声称每个文本要求均已全面检查。

| 执行 | 外部结果 | 本地调用 | 实际恢复 |
|---|---|---:|---|
| 生成前dev基线 | failed / 0 | 2 | 读文件后stop，无修复 |
| 配对父代dev | failed / 0 | 2 | 同上 |
| 配对子代dev | passed / 1 | 5 | 第2步恢复skill_call(selection.py, choose)，实际保存修复 |
| 新变体 | passed / 1 | 4 | 第2步恢复skill_call(scheduler.py, select_tasks)，实际保存修复 |

所有本地评测关闭云端。子代dev实际8721输入/687输出tokens；新变体6281输入/699输出tokens。Promoter沿用E1的独立外部分数＋无回退规则，只用dev决定配对晋级。evaluation/active.json是dev结果；实验根active.json在新变体也通过且证实真实恢复动作后才写入。没有安装到生产桌面配置。

## 过程、费用与限制

- 接口/加载器测试的初次失败与修复见[接口报告](2026-10-01-e3-recovery-interface.md)、[加载报告](2026-10-01-e3-recovery-loader.md)。真实云生成本轮首提案合同通过，没有格式修复请求；没有虚构失败候选。C4此前的技能发现失败仍保留在旧报告。
- DeepSeek Flash实际生成1调用、656输入/729输出tokens，按峰时全部cache miss估计上界$0.0010716，非实际账户账单。预设最多3调用/3000输出tokens、12000请求字节/$0.03；所有请求/失败与账本保存。定价见[官方页面](https://api-docs.deepseek.com/quick_start/pricing/)。
- 实际代码已审阅：策略依赖英文关键词匹配及函数识别，未识别函数时仍带choose回退。这条回退未在本次新变体触发，后续应改为明确stop或可靠解析；不能声称对任意代码/语言稳健。只支持stop/switch_tool，没有实现replan/rollback、任意仓库自写或递归自修改；权重完全未训练。
- 这是一轮dev配对＋一个新变体各一次，不能代替三次、多任务族的研究验收。恢复代码利用已有强技能，证明的是模块代码选择动作带来收益，并非从零发明更好的修复算法。

原始证据：当前worktree`artifacts/e3-recovery-pilot-v1/`，含baseline、全部模型请求/响应、源码、journal、配对与新变体工作区、report.json及最终active.json。artifacts被Git忽略；清理worktree前先迁移证据和索引。

复现：

```sh
python scripts/experiments/recovery_evolution.py --candidate-record artifacts/c4-skill-learning-v1/mutation/proposal.json --teacher-config /Users/wenbo/Kage/artifacts/private/deepseek-settings.json --output-dir artifacts/e3-recovery-pilot-v1
```

使用新输出目录；依赖对应冻结技能、实际模型服务18082、Docker镜像`sha256:8e525133f765d7b7fef855c007f43bfcaf7fa6dc6e91f7ec705be6b60877f418`。相关29 passed、空闲全量834 passed/1 skipped/1 xfailed，代码生成/产物外部检查另由本次真实pilot记录。下一主线为C1.1浏览器DOM执行，再把该闭环推广到电脑任务。
