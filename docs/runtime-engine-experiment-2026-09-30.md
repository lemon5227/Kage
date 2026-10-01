# 第一次真实本地推理实验：llama.cpp / MLX 与 Colab 接入

日期：2026-09-30。范围：推理引擎初筛、真实 Kage 工具链检查、Colab GPU 可用性检查。

## 结论

- 真实运行了 Qwen3-4B，未使用脚本模型替代推理，未调用云模型 API。
- MLX 已能提供本地 OpenAI 兼容服务，但本轮不足以决定替换默认引擎。
- 当前 Kage 循环策略会提前结束部分多步任务。引擎加速不能解决这一问题，应优先修复并重复实验。
- Colab CLI 登录后余额为 0，但成功申请到 Tesla T4；CUDA 检查通过，实验会话已释放。
- 主程序、默认模型配置和依赖声明未修改。新依赖安装在独立环境；Colab CLI 通过 uv tool 安装。

## 设备与模型

| 项目 | 实际值 |
|---|---|
| 电脑 | Apple M4，16 GiB 统一内存 |
| llama.cpp | 0.4.1，build 10964，commit b29c606e2；Metal 后端 |
| GGUF | 已有 Qwen3-4B-Q4_K_M，约 2.49 GB |
| MLX / MLX-LM | 0.32.3 / 0.31.3 |
| MLX 模型 | mlx-community/Qwen3-4B-4bit |
| MLX 模型修订 | 4dcb3d101c2a062e5c1d4bb173588c54ea6c4d25 |
| 对比限制 | 同一原始模型家族，但 GGUF Q4_K_M 与 MLX affine 4bit 不是相同量化权重 |
| 主机状态 | 观察到约 6.2 GiB swap 已使用；没有关闭用户应用；测试存在环境干扰 |

仅额外下载一份约 2.28 GB 的 MLX 权重。实验结束时系统报告约 9 GiB 磁盘可用空间，后续大模型优先放到 Colab。下载与本轮最早的 llama-bench 测试有时间重叠，这是另一项干扰，不能把数字当作严格的引擎性能结论。

## 速度初筛

两种引擎顺序运行，均使用自带 benchmark、128 个生成 token、3 次测量。MLX 每个输入长度另有一次预热。

| 指标 | llama.cpp | MLX |
|---|---:|---:|
| 512-token 输入处理，tokens/s | 98.33 | 133.23 |
| 2048-token 输入处理，tokens/s | 91.45 | 118.27 |
| 生成速度，tokens/s | 11.94（无输入上下文的 tg128） | 14.78（512 输入）／14.49（2048 输入） |
| MLX 自报峰值设备分配 | 未采用同口径测量 | 2.85 GB／3.20 GB |

**这些不是严格匹配的速度比较**：随机输入、量化方法、生成上下文和 benchmark 实现不同。MLX 数值值得继续验证，但不能从中计算可信的纯引擎加速倍数。峰值分配也不等于整个进程或系统的内存占用。

下一轮性能比较需要固定实际提示词、采样配置、缓存状态，并交替运行两臂；以有效动作延迟和成功任务耗时作为主指标。

## 真实 Kage 执行链

路径：真实模型服务 → OpenAICompatibleProvider → PromptBuilder → AgenticLoop → ToolExecutor → 工作目录文件 → 独立检查。

每种引擎各运行 3 个任务、每任务 2 次；关闭 thinking；使用现有循环策略和采样行为，不按结果调整主程序。

| 任务 | 独立检查 | llama.cpp | MLX |
|---|---|---:|---:|
| CSV 分地区汇总 | 实际输出的两个地区总额均为 10，包含负数记录 | 0/2 | 1/2 |
| 修复 clamp 函数 | 子进程检查边界、区间内数值、小数与非法区间异常 | 0/2 | 0/2 |
| 双文件 Markdown 报告 | 输出文件存在，包含收入／订单前后值及变化比例；人工查看实际报告 | 0/2 | 0/2 |
| 总计 | 检查交付物，不采用工具 success 作为任务分数 | **0/6** | **1/6** |

两臂各进行了 14 次真实模型请求，均无模型传输错误。此处的“代码任务”只允许读写代码文件，模型没有终端执行工具；行为测试在独立评测进程运行。报告检查是有限内容检查，不评估完整写作质量。

该组任务是兼容性诊断，不是通用能力基准。样本小、采样未固定随机种子，不能解释为 MLX 提高了模型能力。失败任务提前返回的耗时也不能当作成功任务的效率。

## 失败定位与额外诊断

实际路由分类：sales → chat；code / report → command。

`core/agentic_loop.py` 的 command 分支（本轮行 859）在首次工具执行后生成回复并返回。代码和报告任务的首次动作均为 read_file；因此尚未写出目标结果就结束。两个任务在两个引擎上均重现，不能归因于 MLX 服务不兼容。

另一个失败模式：CSV 任务反复读取文件，达到 5 步上限。其原因还需要独立定位，不能直接断言一定由工具消息格式引起。

为区分模型能否完成任务，另跑一次 MLX 原生工具交互：复用相同文件工具、任务和实验身份说明，以标准 assistant.tool_calls / role=tool / tool_call_id 保留历史，最多 6 次请求，不经过 Kage 路由和停止策略。

结果：**3/3 通过**，汇总 12.596 秒、代码修复 13.820 秒、报告 13.845 秒。代码通过行为检查；报告实际包含正确内容。

这是诊断对照，不是修复后 Kage 成绩：同时改变了循环策略、提示上下文组装与工具历史表示，不能把差异只归因于某一个机制；每任务只有一次尝试，也不能证明稳定性。它证明这个模型在另一种执行脚手架中至少可以完成这三个任务。

## Colab

- 官方 google-colab-cli 0.7.4 已安装，用户完成 OAuth 登录。授权码与凭据不写入此报告。
- `colab usage` 返回余额 0.00、使用速率 0、活动分配 0。
- 独立会话 kage-gpu-probe 成功分配 Tesla T4，15360 MiB，驱动 580.82.07。
- Python 3.13.15，torch 2.11.0+cu128，CUDA available = true。
- 检查后执行 stop，CLI 返回 Session terminated；sessions 再次返回无活动会话。
- 未购买额度、未启动训练、未下载 GPU 模型；本轮仅验证远程 GPU 实际可用。

Google AI Pro 官方权益列出符合资格成员可获 200 CCUs，但当前账号余额未体现该权益。不假定每次都可申请 T4，也不把会员等同于确定的 A100/H100 配额。

## 复现材料

本机 `artifacts/runtime-bench/`（Git 忽略）保存：

- `environment.json`：设备、版本、模型修订和实验限制。
- `llama-bench.json`、`llama-bench.log`、`mlx-bench-512.log`、`mlx-bench-2048.log`：速度结果。
- `chain_probe.py`：真实 Kage 链任务与独立检查；支持 --model、--runs、--port。
- `llama-chain.json`、`mlx-chain.json`：每次尝试、实际工具执行、模型 usage、结果和耗时。
- `native_probe.py`、`mlx-native.json`：原生工具消息诊断与完整交互。
- `tasks/`：每次运行的输入、实际输出及工具日志。
- `colab-gpu-probe.log`：GPU / CUDA 验证输出。

Colab 会话元数据含敏感登录／连接信息，不属于可发布复现材料；不要提交整个 artifacts 目录。独立虚拟环境和模型可以复用，两个本地测试服务均已停止。

## 下一项任务

先单独修复和验证多步任务终止行为，保留单步桌面命令的原有快速执行路径；采用目标完成证据决定结束。另行定位工具历史中的重复读取问题。修复前后的真实任务检查需要分开记录和提交。

之后再重复 llama.cpp / MLX 对照；通过实际任务检查后，继续试 BaseRT，并将视觉定位或微调实验放到 Colab。当前不更换默认引擎。

## 官方资料

- MLX-LM：https://github.com/ml-explore/mlx-lm
- llama.cpp：https://github.com/ggml-org/llama.cpp
- Colab CLI：https://github.com/googlecolab/google-colab-cli
- Google AI Pro 权益：https://support.google.com/googleone/answer/14534406?hl=en
