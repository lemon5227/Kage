# 本地学生模型与推理引擎筛选（仅作筛选证据，不改 G2 冻结）

日期：2026-10-14。状态：**中期记录**。聚焦对照已完成 6/7 轮，其余单元（第 7 轮与 temp=0 参考组）为 23:00 起的另一实验让出 GPU，结束后补跑，届时补数并改为终稿。

## 边界

- **G2 冻结不变**：学生仍为 Agents-A1-4B Q4_K_M（GGUF SHA256 `d93c393a…f062`），引擎仍为 llama.cpp；本次没有改 `~/.kage/config.json`、G2 协议、freeze 记录或任何 Kage 代码。用户在实验中途删除并清空了 `~/.kage`（开发阶段数据，不恢复），学生 GGUF 按冻结 revision `d92b02e…` 重新下载，SHA 与 G1/G2 freeze 记录一致。
- **只用已暴露的开发数据**：`eval/computer-use/files-v1.json` 全部 6 题（含早已公开报告过的旧 holdout）+ `learning-dev-v1.json` 的 knapsack 修复题 `repair_selection`。没有使用 G2 隔离 validation、G2 基线任务或 G3 数据。
- **换引擎可能改变学生行为**：下表中引擎不同即权重量化不同（GGUF Q4_K_M 对 MLX 4bit），行为差异不能归因于引擎本身；本报告只作选型筛选，不作 G2/G3 证据。

## 方法

- 调用链与独立 checker：复用 `scripts/experiments/task_suite.py`（KageChainProvider → AgenticLoop，6 次请求、5 步、150 秒，外部 checker 打分）。task_suite 固定 temperature=0，本次用 scratchpad 包装把请求采样换成 Kage 配置：temp 0.85、top_p 0.95、top_k 20、min_p 0、presence_penalty 1.1；另留 temp=0 参考组。没有改 Kage 代码。
- 每个单元：在 :18090 自起服务 → tool_calls 冒烟（Kage `OpenAICompatibleProvider` 解析）→ 流式测速探针（同一 Kage 请求测 TTFT/预填充，128 token 散文测生成）→ 7 题各 1 次 → 停服务；每秒采样服务进程 RSS 与系统内存。各单元间隔 30 秒，轮间轮换配置顺序；记录 macOS thermalState（M4 Air 无风扇，开始时多为 1=fair，跨配置温度不完全一致，速度只看量级）。
- 与另一会话共享 GPU：检测到其 stream_run/calibration/chain 进程或 :18082 繁忙即不开新单元；22:45 后不开新单元，22:58 看门狗中止残留单元。我的 20:05 冒烟与其实验开头重叠约 10 秒，未计入结果。

## 冒烟与对接

| 引擎（版本） | 模型 | Kage tool_calls 解析 |
|---|---|---|
| llama.cpp llama-server 0.4.1（build 10964）`--jinja` | Agents-A1 / MiniCPM5 Q8_0、Q4_K_M / Qwen3.5-9B / Nemotron-3-Nano-4B | 全部正确 |
| mlx_lm.server（mlx-lm 0.31.3） | Agents-A1、Qwen3.5-9B | 正确 |
| 同上 | MiniCPM5-2B | **失败**：无 MiniCPM 解析器，XML `<function name=…>` 原样进文本 → 跳过 |
| Rapid-MLX 0.16.1（PyPI，独立 venv，遥测已关） | Agents-A1、Qwen3.5-9B（auto 解析器）；MiniCPM5（需显式 `--tool-call-parser minicpm`） | 冒烟正确；任务中仍有泄漏，见下表 |
| mlx-dspark 0.20.3（PyPI） | MiniCPM5 + 官方 `openbmb/MiniCPM5-2B-DSpark` | 正确 |
| dflash-mlx 0.1.10（官方 GitHub `60803233af`，mlx-lm 0.31.3） | Qwen3.5-9B + `z-lab/Qwen3.5-9B-DFlash`；Agents-A1 + `z-lab/Qwen3.5-4B-DFlash` | 正确 |

未测项：dflash PyPI 0.1.8 读不了 z-lab 草稿重训后的嵌套配置（`rope_parameters`/`dflash_config`），改装官方 GitHub 修复版；mlx-dspark 无 Nemotron-3-Nano-4B 草稿（只支持 Nemotron-3.5-Lightning-30B），Nemotron 的 MLX 转换未获批，故 Nemotron 只测 llama.cpp。dflash 文档：temp>0 时只跑目标模型自回归，无投机收益。

## 结果（Kage 采样）

每单元 7 题×1 次。宽筛 13 配置各 2 轮；聚焦对照 3 配置各 6 轮（至今）。格式错误=Kage 报 `InvalidToolArguments`；泄漏=无 tool_calls 但文本含工具调用标记。速度为探针中位数；RSS 为服务进程峰值。

| 模型 | 引擎 | 轮 | 通过 | 格式错误 | 泄漏 | 单题中位秒 | 平均输出 tok/题 | TTFT s | 预填充 tok/s | 生成 tok/s | 峰值 RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Agents-A1-4B（现学生）** | llama.cpp Q4_K_M | 6 | **27/42** | 3 | 0 | 15.6 | 266 | 1.86 | 221 | 25.2 | 4470 |
| | mlx_lm 4bit | 2 | 8/14 | 0 | 0 | 17.7 | 385 | 1.86 | 231 | 29.9 | 3091 |
| | Rapid-MLX 4bit | 6 | **29/42** | 0 | 0 | 18.3 | 324 | 1.85 | 223 | 36.3 | 3197 |
| | dflash 4bit | 2 | 8/14 | 0 | 0 | 19.8 | 305 | 1.86 | 227 | 36.5 | 3920 |
| **Nemotron-3-Nano-4B** | llama.cpp Q4_K_M | 6 | **28/42** | 3 | 0 | 13.6 | 173 | 2.85 | 190 | 23.6 | 5625 |
| **MiniCPM5-2B** | llama.cpp Q8_0 | 2 | 9/14 | 2 | 0 | 6.4 | 210 | 0.78 | 538 | 35.8 | 2957 |
| | llama.cpp Q4_K_M | 2 | 6/14 | 2 | 0 | 4.3 | 170 | 0.85 | 479 | 54.9 | 1894 |
| | Rapid-MLX 4bit | 2 | 5/14 | 0 | 2 | 3.5 | 127 | 0.85 | 470 | 69.9 | 3127 |
| | mlx-dspark 4bit | 2 | 6/14 | 0 | 0 | 4.0 | 218 | 0.94 | 444 | 63.7 | 2335 |
| **Qwen3.5-9B** | llama.cpp Q4_K_M | 2 | 9/14 | 2 | 0 | 31.3 | 291 | 3.49 | 118 | 15.1 | 6243 |
| | mlx_lm 4bit | 2 | 10/14 | 0 | 0 | 20.1 | 212 | 3.45 | 120 | 16.9 | 5287 |
| | Rapid-MLX 4bit | 2 | 6/14 | 0 | 3 | 26.5 | 242 | 2.43 | 173 | 20.6 | 2667 |
| | dflash 4bit | 2 | 10/14 | 0 | 0 | 24.1 | 473 | 3.31 | 129 | 20.5 | 6296 |

逐题（聚焦 6 轮）：csv/inventory/repair_discount/extract 大多通过；incident_counts Agents-A1-llama 5、Nemotron 3、Rapid 6；meeting_slot 仅 Nemotron 1/6；**knapsack `repair_selection` 全部配置 0**。mlx-dspark 在 MiniCPM5 上平均接受长度 2.3–2.4（temp 0.85）。dflash 草稿接受率待 temp=0 参考组。

## 结论

1. **不换学生模型。** Nemotron（28/42）与 Agents-A1（27/42）在噪声内打平，格式错误相同，TTFT 慢 1 秒、内存多约 1.1GB；MiniCPM5-2B 未兑现厂商分数，4bit 下变差且出现格式错误/泄漏，只占速度与内存优势；Qwen3.5-9B 没有明显更强却慢一倍、占 6GB。所有候选都过不了 knapsack，现瓶颈不是换模型能解决的。
2. **不迁移推理引擎。** Rapid-MLX 对 Agents-A1 生成快约 45%、格式错误 0、RSS 小约 1.3GB，但同时换了 MLX 4bit 权重：每题输出多 22%，单题耗时反而略长（18.3 对 15.6 秒），通过率差异在噪声内。多出的主要是自由文本说明（模型调用次数相同），本身不算质量问题；Kage 改为规则化输出（llama.cpp GBNF/json_schema 与 Rapid-MLX guided json_schema 均支持）后，这部分差异会缩小，解码速度优势可能直接转化为单题耗时下降。现阶段不迁移的根本原因是它会破坏 G1/G2 freeze 记录的 llama-server 与 GGUF 身份。
3. **候选保留顺序**：Nemotron-3-Nano-4B 为 G3 之后首个学生候选；Rapid-MLX 为延迟成为瓶颈时（如 G4 日常交互入口）的引擎候选。MiniCPM5-2B、Qwen3.5-9B 淘汰。

## 何时切换才不污染 G2

G2 第二次学习、旧能力回归与重启复用都完成并更新 roadmap 后，且 G3 以冻结版本对照结束之前不换。确需换学生或引擎时，按 roadmap §6 作为独立同任务对照：只改一层（学生或引擎），同权重/同任务/同预算，更多重复，预先固定判据（通过率不降、格式错误不增、单题耗时下降才切换）。切换后旧 G1/G2 证据保留原版本身份，不回写。引擎重测的自然时机是 Kage 改为规则化输出、本来就要重新冻结执行配置时：在同一结构化输出协议下比较 llama.cpp 与 Rapid-MLX。

## 成本与原始证据

全部本地，零云请求、零教师请求。下载（均核 SHA）：MiniCPM5-2B GGUF Q8_0/Q4_K_M、MLX 官方 4bit 与 DSpark 草稿；Qwen3.5-9B Q4_K_M GGUF 与 MLX 4bit；Nemotron-3-Nano-4B Q4_K_M GGUF；z-lab Qwen3.5-9B/4B DFlash 草稿；Agents-A1-4B bf16（`mlx_lm.convert -q --q-bits 4 --q-group-size 64 --q-mode affine`，4.503 bits/weight）。

原始结果（Git 忽略）：`/Users/wenbo/Kage/artifacts/student-screening-2026-10-14/`
- `runs/<引擎>-<模型>/kage-r<N>/`：`files-v1/`、`learning-dev-v1/`（results.json、逐调用 model.jsonl、journal、工作区）、`probe.json`、`mem.txt`、`env.txt`（温度、采样）、`smoke.json`、`server.log`；`greedy-r0/` 为 temp=0 参考。
- `smoke/`：各引擎冒烟；`summary-kage.json`：本表汇总；`convert-agents-a1-mlx4.log`：转换日志。
