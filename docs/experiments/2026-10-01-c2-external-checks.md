# C2.0-B 外部完成检查与六任务起步套件

状态：工程检查通过；本地18次评测进行中，成绩随后追加，不提前勾选C2.0。

## 目标与实现

沿用EvolutionRunner、Journal、ProgressTracker、预算账本，未新增平行评分晋级系统。增加 `metadata.completion` 与evaluation日志：status、stop_reason、check_passed。外部评分1才算completed；无产物/错误产物为incomplete，重复同一动作/同一观察为no_progress，调用/步数/总预算/超时/执行异常分别记call_limit/step_limit/budget_exhausted/timeout/call_error。保留旧passed/failed等RunStatus和E1分数语义。已完成产物允许通过，同时保留耗尽上限的停止原因。

新增python_function验收类型：隔离子进程运行隐藏输入及异常边界，不凭源代码字符串判断；2秒限时并清理进程组。它是实验进程隔离，不是安全沙箱。既有JSON相等/部分分规则保持原样。当前仍是有限文件/代码任务，并未证明通用电脑操作。

`eval/computer-use/files-v1.json` 六任务族：dev为CSV聚合、多文件库存对账、代码修复；holdout为日志分析、约束排期、文档行动项提取。按家族划分并冻结；原C0三个探针保持原状。不同家族留出只测有限跨任务表现，后续技能迁移还需要未见输入变体，不能用本套件冒称同族迁移成立。隐藏真值/代码测试用例不传给模型。

`scripts/experiments/task_suite.py` 使用真实Kage链、同一外部Evaluator和预算账本，固定温度0、最多6模型调用/5循环步、150秒总时限。每项3次，保留全部结果、工作目录、模型请求响应、工具轨迹、SQLite事件与调用账本，模型凭据不写入。数据规模小，不给统计显著性结论。

## 过程与验证

先写三个行为回归。首次测试除真实缺陷外还暴露测试夹具误用了 `inprocess` 和 `input_files`；修正为既有inline与initial_files后，三个均按预期因缺少代码检查或completion字段失败。实现后25项相关回归通过。

2026-10-01全量：811 passed、4 skipped、1 xfailed，97.42秒。无限循环候选在实际子进程超时失败；错误函数失败、正确函数通过；重复读真实文件标为无进展；写出正确文件后达到调用上限仍按外部验收通过且实际api_calls=1。

真实运行命令（输出目录必须不存在）：

```sh
python scripts/experiments/task_suite.py --port 18082 --model agents-a1-4b --runs 3 --output-dir artifacts/c2-files-v1
```

服务：官方Agents-A1-4B Q4_K_M，llama.cpp，8192上下文、单slot、Metal99层、q8 KV、reasoning off；权重版本和hash沿用本地模型升级报告。真实实验结果待运行结束追加；没有触发云调用或学习，不把工程测试冒充模型成绩。
