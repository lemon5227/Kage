# 本地模型升级：Agents-A1-4B与云端教师方案

日期：2026-10-01；工程基线：2a99e49。范围：模型候选筛选、官方权重安装、本机真实推理与默认配置切换。学习方案是设计讨论，尚未实现或训练。

## 选择依据

选用[InternScience/Agents-A1-4B](https://huggingface.co/InternScience/Agents-A1-4B)，官方模型卡记录4B版于2026-07-14发布，面向长链搜索、工程、科学任务与工具调用。[技术报告](https://arxiv.org/abs/2606.30616)描述多教师多领域on-policy蒸馏。采用其agentic定位和现成官方GGUF，官方基准分数不是Kage成绩；不会把35B版标题成绩外推到4B或本机量化版。

[Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B)作为兼容性对照候选，暂不再下载另一份。[Fara1.5-4B](https://huggingface.co/microsoft/Fara1.5-4B)擅长截图驱动浏览器行动，但依赖专门动作/观察脚手架，留作C1/C2浏览器阶段候选；本轮不拿它替换通用文字工具provider。[Nanbeige4.2-3B](https://huggingface.co/Nanbeige/Nanbeige4.2-3B)有agentic能力，但Looped Transformer存在Apple部署研究中的兼容修复问题，见[2026-08预印本](https://arxiv.org/abs/2608.13987)，不把较小参数量当作当前最快落地路径。

## 安装和实际配置问题

仓库原model.path为Qwopus3.5-9B，profile中的/Users/wenbo/.cache/kage/models/Qwen3.5-9B.Q4_K_M.gguf不存在。用户~/.kage/config.json还把model.path覆盖成旧LFM模型。它们均不能代表上一轮真正执行的模型；上一轮实验实际加载的是Qwen3-4B。

原llama-server-backup因缺libmtmd.0.dylib无法运行；TurboQuant版本为build8793，首次Metal库初始化耗时43.518秒。选用已经安装并真实可用的/opt/homebrew/bin/llama-server：0.4.1、build10964、b29c606e2。没有安装新引擎或修改TurboQuant。由旧配置改为该已验证运行时以及q8_0 KV缓存，以确保默认启动参数与本次验收一致；因此本次不能把模型与引擎变更混作单一模型速度对照。

下载[官方Q4_K_M GGUF](https://huggingface.co/InternScience/Agents-A1-4B-Q4_K_M-GGUF)，锁定修订d92b02e27074b27542384f72bc0e72203c970f0f，文件2,708,805,312字节。SHA256=d93c393a9bd5139a4b5cfe24d31ef553c5a497bfb8afec178a354ecbf508f062，与HF LFS元数据一致，验证后才安装。

安装路径：/Users/wenbo/.kage/models/agents-a1-4b/Agents-A1-4B-Q4_K_M.gguf。保留既有权重。在用户models/manifest.json登记id=agents-a1-4b-q4-k-m，并更新仓库config/settings.json和用户config.json的默认路径/本地runtime。有效配置、managed resolver、Broker模型名与启动命令已实际核验。云配置字段不改动，学习回退不自动开启。

local_runtime使用8192上下文、1024服务输出上限、reasoning=off、q8_0 K/V。生产采样temperature/temp=0.85、top_p=0.95、top_k=20、presence_penalty=1.1，来自官方推荐；同时写temp是因为现有RuntimeStart payload消费temp字段。实验请求固定temperature=0，Agent循环仍最多300输出token、5步与6次调用，不用生产采样数字冒充实验配置。

这里只安装文字GGUF，没有视觉projector，不声称截图理解/点击已接入。模型参数量、上下文上限和宣传成绩不能替代本机内存及任务测试。服务采样时观察到RSS约2.88GiB，仅为某一时刻进程RSS，不等于系统峰值或全部Metal内存。

## 真实任务检查与工程验证

在127.0.0.1:18082独立服务，加载上述实际文件，--alias agents-a1-4b。复用scripts/experiments/multistep_probe.py三任务，每任务3次；新工作区固定初始文件，检查真实CSV汇总、clamp函数行为及报告必要内容。没有调用云API。

脚本原model_label硬编码为Qwen3-4B，已改为args.model；这个标签影响provider身份元数据，不决定HTTP目标。本次实际目标由--model agents-a1-4b、服务启动文件、config.json和真实响应共同确认，没有把旧标签当作旧模型执行证据。原始数据不作静默重命名。

相关工程检查：tests/test_model_broker.py、test_local_model_runtime.py、test_server_helpers.py、test_hybrid_model.py共47 passed（1.06秒）。另实际检查有效配置能解析已安装文件，Broker本地目标为8080及agents-a1-4b，RuntimeStart命令temp确为0.85。没有改动Agent执行逻辑或评分器，未重跑无关全量测试；上轮全量结果不当作本轮新运行。

真实成绩与命令在下方补齐。原始目录artifacts/runtime-bench/agents-a1/c0-fixed-budget，包含config.json、results.json、所有请求/响应和实际产物；服务日志agents-a1/server.log。原始数据及权重未进入Git。

## 启动与回退

默认运行时端口8080，实验端口18082，不混用。Kage后端启动后，可通过POST /api/models/llama/start空JSON使用配置中的model_path，或传model_id=agents-a1-4b-q4-k-m；该API由Kage管理服务。Kage初始化本身不保证自动启动推理服务，不能只改model.path就宣称常驻运行。

已用有效配置构造LocalModelRuntime启动8080服务，通过ModelBroker实际请求2+2并检查输出精确为4，最后停止服务；证据为artifacts/runtime-bench/agents-a1/configured-runtime-smoke.json。两项实验服务均已释放，不常驻占用内存。也可在终端显式运行（进程由终端管理，不由Kage的stop API管理）：

```sh
/opt/homebrew/bin/llama-server \
  -m /Users/wenbo/.kage/models/agents-a1-4b/Agents-A1-4B-Q4_K_M.gguf \
  --jinja --host 127.0.0.1 --port 8080 -ngl 99 --flash-attn auto \
  -c 8192 -np 1 -n 1024 --reasoning off \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --temp 0.85 --top-p 0.95 --top-k 20 --presence-penalty 1.1
```

切换前repo-settings.json、user-config.json、models-manifest.json已备份到artifacts/runtime-bench/agents-a1/backups，权限600，不含于Git。模型/实验记录与云教师设计分开提交。回退仓库提交不会自动还原用户私有配置或manifest，需要对应备份；不要用旧备份覆盖之后新增配置。权重仍保留以供对照。

## 学习闭环建议

详细设计见[云端教师→本地学生](../plans/cloud-teacher-local-student-2026-10-01.md)。先做任务级失败检测、云接管真实执行及验收，再形成技能和留出复验；数据成熟后才做Colab适配器。现有hybrid仅识别ModelResponse.error，无法识别语义任务失败；本轮没有开启自动教师训练，也未产生训练/云调用费用。

## 最终真实结果

Agents-A1官方Q4_K_M：CSV 3/3、clamp 3/3、报告3/3，共9/9通过实际产物检查，耗时中位数47.659秒。

| 任务 | 三次耗时（秒） | 实际模型调用次数 |
|---|---|---|
| sales | 51.774, 32.548, 28.354 | 3, 3, 3 |
| code | 52.186, 44.673, 41.338 | 3, 3, 3 |
| report | 47.659, 47.998, 49.922 | 3, 3, 3 |

```sh
python scripts/experiments/multistep_probe.py agents-a1-gguf --port 18082 --runs 3 \
  --model agents-a1-4b --output-dir artifacts/runtime-bench/agents-a1/c0-fixed-budget
```

输出目录已存在，复现请换新目录。旧Qwen3-4B在修复后的MLX环境同样9/9，本次GGUF后端/量化不同、上下文及采样服务参数也不同，因此只能证明新模型在Kage协议上可执行，不能证明智力提升，也不能把47.659秒与旧33.226秒直接作模型/引擎的因果对比。三项有限文件任务不是通用电脑能力评测。
