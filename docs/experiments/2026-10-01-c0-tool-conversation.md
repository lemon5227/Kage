# C0-B：工具交互协议与上下文保真

日期：2026-10-01；基线：415bee1。本任务保持停止策略与真实模型配置不变。

## 问题、实现与验证

C0-A请求记录显示工具执行结果被伪装成普通assistant文字；参数、调用ID和tool角色丢失，原目标每轮重复插入。改为assistant.tool_calls与对应role=tool消息，保留参数并为执行记录生成匹配ID。自动预览等框架执行同样留下关联记录；技能指导保留在完整交互之后。PromptBuilder保留这些字段，裁剪时删除完整交互而非孤立结果；保留最近目标、避免重复提交。Anthropic转换为原生tool_use/tool_result，并合并连续结果。

新增4个行为回归：模型下一次请求包含真实文件证据与参数、调用结果配对、预算裁剪不留下孤立消息、Anthropic块转换及工具参数计入token估算。前三个初次运行失败；token估算测试也先失败再修复。测试准备曾使用错误的tests包导入，改为pytest可发现的测试模块，不将导入错误计为业务复现。相关回归62 passed（0.71秒）。最低保留上下文可能超过估算预算，这仍是软预算，不承诺硬限制；估算不是精确tokenizer。

## 真实模型结果与边界

Qwen3-4B、MLX本地18081服务、thinking=false、temperature=0、每请求300输出token、循环5步、链调用上限6；任务与C0-A相同。每任务3次，共9次：CSV汇总0/3、clamp修复0/3、报告有限内容检查3/3。总体3/9，耗时中位数24.682秒。原始数据：artifacts/runtime-bench/mlx-c0-native-history-chain.json。推理全在本机，不使用云API。

该结果证明工程协议回归通过，不能证明真实模型重复读取已解决。失败日志显示第2步触发旧重复检测。下一项C0-C应保存原始响应、核验是否误杀合法工具输出，再作单独修复。本报告不把协议修改当作任务成功率提升，也不将有限三任务称为通用能力评测。

## 可复现实验工具

scripts/experiments/multistep_probe.py保留同样三个任务，外部检查实际文件/函数行为，记录请求、响应、工具证据、耗时与预算。要求新的--output-dir，防止旧输出污染；不下载模型或启动服务器。运行示例：

```sh
python scripts/experiments/multistep_probe.py mlx --runs 3 \
  --model /Users/wenbo/Kage/artifacts/runtime-bench/models/qwen3-4b-mlx-4bit \
  --output-dir artifacts/runtime-bench/new-experiment
```

原始数据默认位于忽略的artifacts目录，报告和脚本提交到Git；数据未提交，跨机器复核需另行导出。
