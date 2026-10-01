# C0-C：重复检测误判与工具动作处理

日期：2026-10-01；基线：fc6e985。承接C0-B，模型、工具、任务和预算保持相同。

## 复现、根因和修复

保存原始模型响应后，CSV失败响应包含正常的汇总说明和合法list_files调用。旧代码先检测说明文字，任意10字符子串出现3次就退出，因此“the amounts”等正常术语触发停止，结构化动作未执行。clamp解释中“the value”也造成同类误判。

第一项回归让模型在重复解释时返回write_file，真实检查目标文件；修复前文件不存在，修复后写入并继续下一轮。将重复保护移至结构化/文本工具解析之后，只对没有工具动作的回复应用。保持步骤和调用上限，避免仅因有动作就允许无界循环。

随后用真实clamp说明构造第二项回归，证明普通解释仍被误报。检测收窄为连续重复片段：至少3次连续拷贝且重复段总长至少30字符；正常术语分散出现不触发。原有英文和中文连续重复停止测试仍通过。这个启发式不检测所有循环；实际工具无进展仍需后续状态/进展检查，不能用文字重复代替任务完成判断。

相关回归33 passed。第一次只改动作处理后的全量804 passed / 4 skipped / 1 xfailed，129.20秒，原始日志c0-final-tests.log；最终检测器的全量结果另记于下方，不拿较早结果替代最终验证。

## 分阶段真实实验

统一使用本地Qwen3-4B MLX现有4bit权重（修订4dcb3d101c2a062e5c1d4bb173588c54ea6c4d25），MLX 0.32.3 / MLX-LM 0.31.3；thinking=false、temperature=0、每请求最多300输出token、循环5步、链调用上限6。未提供固定seed；即使temperature=0，重复结果也不能假设位级相同。各阶段使用新的工作区，初始helper.py会重置，避免旧产物污染。

| 阶段 | CSV | clamp | 报告 | 原始结果 |
|---|---:|---:|---:|---|
| 原生工具协议诊断，记录原始响应 | 0/1 | 0/1 | 1/1 | artifacts/runtime-bench/c0-diagnostic/results.json |
| 仅调整动作处理顺序 | 3/3 | 2/3 | 3/3 | artifacts/runtime-bench/c0-action-first/results.json |

动作顺序版本8/9，中位总耗时20.962秒。clamp第二次只返回计划、没有写文件，外部函数行为检查失败。第一次与第三次虽然写入正确函数，后续文字仍被旧检测截断；不能把评分通过当作正常结束。最终检测器的成绩、轨迹和剩余问题见下方。

## 检查方法与限制

脚本scripts/experiments/multistep_probe.py用独立检查读真实文件：CSV要求精确East=10、West=10；clamp在隔离Python进程测试上下边界、区间内、浮点与非法区间；报告仅查必要标题/数字/百分比，不评判文本质量。因此三项是多步文件链兼容性检查，不是通用电脑能力评测、GUI定位实验或自主进化证明。

每个响应的工具调用、原始文字、请求messages、调用预算与工具结果均存入results.json。原始轨迹在忽略的artifacts目录，脚本与报告进入Git。测试与推理同时运行，主机负载与缓存未严格控制，耗时仅作诊断，不能宣称性能加速倍数。本任务没有调用云API或修改默认推理引擎。

chain中的finish表示Agent循环返回，不表示外部验收通过。一般完成/未完成/耗尽状态与通用结果检查仍需C2；本轮未宣称这些接口已经实现，也未复跑llama.cpp后端。

## 最终版本的全量回归

python -m pytest -q：805 passed / 4 skipped / 1 xfailed，154.61秒，1条既有pygame弃用警告。输出见artifacts/runtime-bench/c0-final-tests-v2.log。最终版本包含正常解释不误报与合法动作不丢弃两个新增回归；全部结果在提交前核对，不把skipped/xfail算成通过。

## 最终真实本地模型结果

最终版本每任务3次，CSV 3/3、clamp 3/3、报告3/3，共9/9通过外部检查。总耗时中位数33.226秒。结果是小样本文件任务的兼容性证据，不代表所有任务稳定成功，也不能据此保证未来每次clamp都成功。

| 任务 | 三次耗时（秒） | 实际模型调用次数 | 外部结果 |
|---|---|---|---|
| sales | 30.975, 40.562, 35.563 | 4, 4, 4 | 3/3 |
| code | 32.671, 43.306, 41.816 | 3, 3, 3 | 3/3 |
| report | 33.226, 20.799, 16.779 | 3, 3, 4 | 3/3 |

原始证据：artifacts/runtime-bench/c0-final/config.json与results.json，包含全部请求和响应，任务输出保留于同目录tasks/。较早失败数据没有覆盖。运行命令：

```sh
python scripts/experiments/multistep_probe.py mlx-c0-final --runs 3 \
  --model /Users/wenbo/Kage/artifacts/runtime-bench/models/qwen3-4b-mlx-4bit \
  --output-dir artifacts/runtime-bench/c0-final
```

复现时需要新的输出目录；原目录已存在会拒绝运行。当前结果完成MLX单后端复测，llama.cpp对照、一般任务的完成状态契约和12项GUI评测仍未完成。下一阶段推进C1/C2，避免把本次9/9扩大为通用操作电脑能力。
