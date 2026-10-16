# 本地学生模型与推理引擎筛选（仅作筛选证据）

日期：2026-10-14～15。状态：**终稿**。结论：stream 实验期间不换学生模型、不换推理引擎；Nemotron-3-Nano-4B 与 Rapid-MLX 留作后续候选，MiniCPM5-2B、Qwen3.5-9B 淘汰。

## 边界

- **不改实验中的学生**：Agents-A1-4B Q4_K_M（GGUF SHA256 `d93c393a…f062`）跑在 llama.cpp 上，这是 G1/G2 freeze 记录里的学生，也是 10-14 重规划后 stream 实验（P2 主实验，A0/A1/A3/A4 各臂）使用的学生。本次没有改 `~/.kage/config.json`、任何 freeze 记录或 Kage 代码。用户在实验中途删除并清空了 `~/.kage`（开发阶段数据，不恢复）；学生 GGUF 按冻结 revision `d92b02e…` 重新下载，SHA 与 freeze 记录一致。
- **只用已暴露的开发数据**：`eval/computer-use/files-v1.json` 全部 6 题（含早已公开报告过的旧 holdout）+ `learning-dev-v1.json` 的 knapsack 修复题 `repair_selection`。没有使用 G2 基线/validation、stream 评测实例或任何最终评测数据。
- **换引擎就是换学生**：引擎不同意味着权重量化也不同（GGUF Q4_K_M 对 MLX 4bit），观测到的行为差异不能单独归因于引擎。本报告只作选型筛选，不作学习收益证据。

## 方法

- 调用链与独立 checker：复用 `scripts/experiments/task_suite.py`（KageChainProvider → AgenticLoop，6 次请求、5 步、150 秒，外部 checker 打分）。task_suite 固定 temperature=0，本次用 scratchpad 包装把请求采样换成 Kage 配置：temp 0.85、top_p 0.95、top_k 20、min_p 0、presence_penalty 1.1；另加一组 temp=0 参考。没有改 Kage 代码。
- 每个单元：在 :18090 自起服务 → tool_calls 冒烟（用 Kage `OpenAICompatibleProvider` 解析）→ 流式测速探针（同一 Kage 请求测首 token 延迟和预填充速度，128 token 散文测生成速度）→ 7 题各跑 1 次 → 停服务；每秒采样服务进程 RSS 和系统内存。单元之间隔 30 秒，每轮轮换配置顺序；记录 macOS thermalState。M4 Air 没有风扇，开始时多为 1（fair），各配置测速时温度不完全一致，速度只看量级。
- 分两段：先宽筛 13 个“引擎×模型”配置，各 2 轮；再对 3 个入围配置做聚焦对照，各 7 轮，外加 1 轮 temp=0。
- 与另一会话共享 GPU：检测到对方的 stream_run/calibration/chain 进程或 :18082 繁忙时，不开新单元；22:45 后不开新单元，22:58 看门狗中止残留单元（当晚检查时没有残留）。chain 于 00:33:10 结束，余下单元 00:33:11 才开始。另外，20:05 的一次冒烟与对方实验开头重叠约 10 秒，这次冒烟不计入结果。

## 冒烟与对接

| 引擎（版本） | 模型 | Kage tool_calls 解析 |
|---|---|---|
| llama.cpp llama-server 0.4.1（build 10964）`--jinja` | Agents-A1 / MiniCPM5 Q8_0、Q4_K_M / Qwen3.5-9B / Nemotron-3-Nano-4B | 全部正确 |
| mlx_lm.server（mlx-lm 0.31.3） | Agents-A1、Qwen3.5-9B | 正确 |
| 同上 | MiniCPM5-2B | **失败**：没有 MiniCPM 解析器，XML `<function name=…>` 原样进入文本 → 跳过 |
| Rapid-MLX 0.16.1（PyPI，独立 venv，遥测已关） | Agents-A1、Qwen3.5-9B 用 auto 解析器；MiniCPM5 需显式 `--tool-call-parser minicpm` | 冒烟正确；任务中仍有泄漏，见下表 |
| mlx-dspark 0.20.3（PyPI） | MiniCPM5 + 官方草稿 `openbmb/MiniCPM5-2B-DSpark` | 正确 |
| dflash-mlx 0.1.10（官方 GitHub `60803233af`，配 mlx-lm 0.31.3） | Qwen3.5-9B + `z-lab/Qwen3.5-9B-DFlash`；Agents-A1 + `z-lab/Qwen3.5-4B-DFlash` | 正确 |

其他说明：
- PyPI 上的 dflash-mlx 0.1.8 读不了 z-lab 草稿重训后的嵌套配置（`rope_parameters`/`dflash_config`），而且需要 mlx-lm 0.31.3（0.32.0 删掉了它依赖的 `SequenceStateMachine`）。因此改装作者官方 GitHub 的修复版。
- mlx-dspark 没有 Nemotron-3-Nano-4B 的草稿模型（只支持 Nemotron-3.5-Lightning-30B），Nemotron 的 MLX 转换也未获批，所以 Nemotron 只测了 llama.cpp。
- dflash 文档写明：temp>0 时只跑目标模型的自回归，没有投机收益。为聚焦对照，原计划的 dflash temp=0 参考组被取消，因此**没有测到 dflash 的草稿接受率**。
- mlx-dspark 在 MiniCPM5 上 temp 0.85 时的平均接受长度为 2.3–2.4。

## 结果（Kage 采样）

每单元 7 题×1 次。各列含义：
- **格式错误**：Kage 报 `InvalidToolArguments`。
- **泄漏**：响应没有 tool_calls，但文本里出现工具调用标记。
- **单题秒**：每题平均耗时。
- **输出 tok/题**：每题平均输出 token。
- **TTFT（首 token 延迟）、预填充速度、生成速度**：取测速探针的中位数。
- **RSS**：服务进程峰值内存。

| 模型 | 引擎 | 轮 | 通过 | 格式错误 | 泄漏 | 单题秒 | 输出 tok/题 | TTFT s | 预填充 tok/s | 生成 tok/s | 峰值 RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Agents-A1-4B（现学生）** | llama.cpp Q4_K_M | 7 | **31/49** | 3 | 0 | 16.2 | 269 | 1.87 | 221 | 26.1 | 4761 |
| | mlx_lm 4bit | 2 | 8/14 | 0 | 0 | 20.3 | 385 | 1.86 | 231 | 29.9 | 3091 |
| | Rapid-MLX 4bit | 7 | **33/49** | 0 | 0 | 18.0 | 330 | 1.90 | 217 | 36.9 | 3197 |
| | dflash 4bit | 2 | 8/14 | 0 | 0 | 18.7 | 305 | 1.86 | 227 | 36.5 | 3920 |
| **Nemotron-3-Nano-4B** | llama.cpp Q4_K_M | 7 | **32/49** | 3 | 0 | 13.8 | 172 | 2.93 | 184 | 23.1 | 5625 |
| **MiniCPM5-2B** | llama.cpp Q8_0 | 2 | 9/14 | 2 | 0 | 7.1 | 210 | 0.78 | 538 | 35.8 | 2957 |
| | llama.cpp Q4_K_M | 2 | 6/14 | 2 | 0 | 4.4 | 170 | 0.85 | 479 | 54.9 | 1894 |
| | Rapid-MLX 4bit | 2 | 5/14 | 0 | 2 | 3.4 | 127 | 0.85 | 470 | 69.9 | 3127 |
| | mlx-dspark 4bit | 2 | 6/14 | 0 | 0 | 4.7 | 218 | 0.94 | 444 | 63.7 | 2335 |
| **Qwen3.5-9B** | llama.cpp Q4_K_M | 2 | 9/14 | 2 | 0 | 32.4 | 291 | 3.49 | 118 | 15.1 | 6243 |
| | mlx_lm 4bit | 2 | 10/14 | 0 | 0 | 22.1 | 212 | 3.45 | 120 | 16.9 | 5287 |
| | Rapid-MLX 4bit | 2 | 6/14 | 0 | 3 | 29.7 | 242 | 2.43 | 173 | 20.6 | 2667 |
| | dflash 4bit | 2 | 10/14 | 0 | 0 | 24.7 | 473 | 3.31 | 129 | 20.5 | 6296 |

**聚焦对照逐题（7 轮）**：

| 题目 | Agents-A1 llama | Nemotron llama | Agents-A1 Rapid |
|---|---|---|---|
| csv_totals | 6 | 7 | 5 |
| inventory_join | 7 | 7 | 7 |
| repair_discount | 7 | 7 | 7 |
| incident_counts | 5 | 3 | 7 |
| meeting_slot | 0 | 1 | 0 |
| extract_actions | 6 | 7 | 7 |
| knapsack `repair_selection` | **0** | **0** | **0** |

**temp=0 参考（各 1 轮）**：Agents-A1 llama 4/7，Nemotron llama 5/7，Agents-A1 Rapid 5/7；均无格式错误。

49 次里相差 1–2 题在噪声之内：二项分布的 95% 区间约为 ±13 个百分点。

## 结论

1. **不换学生模型。**
   - Nemotron（32/49）与 Agents-A1（31/49）打平，格式错误次数相同；它的输出更短、单题更快，但首 token 慢 1 秒，内存多约 0.9GB。
   - MiniCPM5-2B 没有兑现厂商分数：4bit 下变差，还出现格式错误和泄漏，只有速度和内存占优。
   - Qwen3.5-9B 没有明显更强，单题慢 40–100%，内存约 5–6GB。
   - 所有候选都过不了 knapsack，meeting_slot 也几乎全挂；现在的瓶颈不是换个模型能解决的。
2. **不迁移推理引擎。**
   - Rapid-MLX 跑 Agents-A1 时生成快约 40%，格式错误为 0，RSS 小约 1.5GB，通过率与 llama.cpp 相同。
   - 但它同时换了 MLX 4bit 权重：每题输出多约 23%，单题耗时反而略长（18.0 对 16.2 秒）。多出来的主要是自由文本说明，两边模型调用次数相同，这本身不算质量问题。
   - Kage 改成规则化输出后，这部分差异会缩小，解码速度优势可能直接变成单题耗时下降。llama.cpp 支持 GBNF/json_schema，Rapid-MLX 支持 guided json_schema，两边都能做约束输出。
   - 现阶段不迁移的根本原因是：换引擎等于换学生，会破坏 stream 实验各臂的可比性，以及 freeze 记录里的服务和权重身份。
3. **候选保留**：Nemotron-3-Nano-4B 是后续首个学生候选；Rapid-MLX 是 Kage 改为规则化输出、或延迟真正成为瓶颈时的引擎候选。

## 何时切换才不污染证据

- stream 实验（P2/P3）的各臂共用同一学生和引擎，期间不换。
- 确需换学生或引擎时，按“只改一层”的独立同任务对照来做：同任务、同预算、更多重复，并预先固定判据——通过率不降、格式错误不增、单题耗时下降，才切换。
- 引擎重测的自然时机，是 Kage 改为规则化输出、本来就要重新冻结执行配置的时候：在同一结构化输出协议下比较 llama.cpp 和 Rapid-MLX。
- 切换后，旧实验证据保留原版本身份，不回写。

## 成本与原始证据

全部在本地运行，云请求和教师请求均为 0。下载的文件（均核对 SHA）：
- MiniCPM5-2B：GGUF Q8_0/Q4_K_M、官方 MLX 4bit、DSpark 草稿
- Qwen3.5-9B：Q4_K_M GGUF、mlx-community MLX 4bit
- Nemotron-3-Nano-4B：Q4_K_M GGUF
- z-lab Qwen3.5-9B/4B DFlash 草稿
- Agents-A1-4B bf16：用 `mlx_lm.convert -q --q-bits 4 --q-group-size 64 --q-mode affine` 转换，得到 4.503 bits/weight

原始结果（被 Git 忽略）在 `/Users/wenbo/Kage/artifacts/student-screening-2026-10-14/`：
- `runs/<引擎>-<模型>/kage-r<N>/`：`files-v1/`、`learning-dev-v1/`（results.json、逐调用 model.jsonl、journal、工作区）、`probe.json`、`mem.txt`、`env.txt`（温度和采样参数）、`smoke.json`、`server.log`；dflash 单元另有 `dflash-metrics.json`。`greedy-r0/` 为 temp=0 参考。
- `smoke/`：各引擎冒烟结果。
- `summary-kage.json`、`summary-greedy.json`：本报告的汇总。
- `tools/`：筛选脚本（采样包装、单元执行、调度、看门狗、测速探针、汇总），以及三个引擎 venv 的 `pip freeze`。
- `convert-agents-a1-mlx4.log`：MLX 转换日志。
