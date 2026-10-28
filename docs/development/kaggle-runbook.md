# Kaggle 运行手册与踩坑记录

本机跑模型会让 Mac 卡死，E-1 起所有实验在 Kaggle 免费 GPU 上跑。总控脚本 `scripts/experiments/kaggle_e1.py`。
本文记录 2026-10-15/16 在 v1–v10 上踩过的坑，**下次先读完这里再动手**。

## 1. 固定配置

- 笔记：`lemon5227/notebookf3ff1d131c`（只用这一个）。Accelerator **GPU T4 x2**，Internet on，Secret 标签 `deepseek`（DeepSeek key，由用户在 Kaggle 的 Add-ons → Secrets 里添加并勾选给本笔记）。
- 输入：本笔记**自己上一版的输出**（Add Input → Notebooks → 本笔记）。里面有预编译的 `llama-bin/` 和 `e1/teacher-cache/`，新运行据此免编译、复用已付费的教师示范。
- 第 1 格：读 Secret 写入环境变量 `DEEPSEEK_API_KEY`（不打印值）。
- 第 2 格：`git clone -b dev --depth 1 https://github.com/lemon5227/Kage.git` 到 `/kaggle/tmp`，再运行 `python scripts/experiments/kaggle_e1.py`。
- **跑哪个阶段由仓库文件 `scripts/experiments/kaggle_phase` 决定**（如 `e2`，或 `rerun A3-s1 A3-s2`）。改阶段 = 改这个文件并 git push，不用改笔记。
- 本机 Kaggle CLI：`artifacts/.kaggle-cli/bin/kaggle`（令牌在 `~/.kaggle/access_token`，不要打印）。只用于查状态和下载输出：
  - `kaggle kernels status lemon5227/notebookf3ff1d131c`
  - `kaggle kernels output lemon5227/notebookf3ff1d131c -p artifacts/kaggle-out/vN`（**版本跑完后**才能下载）

## 2. 启动一次运行

1. 改 `kaggle_phase`、提交并推送 `dev`。
2. 浏览器打开笔记编辑页 → 右上 **Save Version** → 类型 **Save & Run All (Commit)** → Save。
3. 左下出现 “Version #N … Running” 即已启动；之后可关浏览器和电脑，Kaggle 端独立运行（会话上限 12 h，脚本 11 h 时收尾打包）。
4. 跑完：CLI 下载输出 → 解包 → `stream_report.py` 出报告 → 结果包放进 `evidence/kaggle/vN-results.tar.gz`（见 `evidence/README.md`）。
5. Kaggle 端用独立的教师账本（每次全新）；跑完把花费记回本机账本：`teacher_budget.charge_external(...)`，并写入工作日志。

## 3. 踩坑记录（症状 → 原因 → 解决）

| # | 症状 | 原因 | 解决（已在代码里） |
|---|---|---|---|
| 1 | v1：`CMake Error at ggml/src/ggml-cuda/CMakeLists.txt … target was not found` | Kaggle 构建环境没有 libcuda（连 stub 都没有），`CUDA::cuda_driver` 找不到 | 编译 llama.cpp 时加 `-DGGML_CUDA_NO_VMM=ON`（只改显存池分配方式，不改计算）；架构 `75`（T4） |
| 2 | v3/v4：`secret deepseek ConnectionError Connection error trying to communicate with service` | **用 CLI `kernels push` 启动的运行读不到 Kaggle Secrets** | 正式运行一律从网页 Save & Run All 启动；CLI 只查状态/下载 |
| 3 | v4：写 `host.json` 时 `FileNotFoundError` | 输出目录还没建 | 写文件前 `mkdir(parents=True)` |
| 4 | 每次运行先编译 llama.cpp 约 26–30 分钟 | 每次都是全新虚拟机 | 第一次编译后把 `llama-bin/` 存进输出；之后把上一版输出挂成输入，`find_prebuilt` 直接复用（准备阶段 ~40 s）。**复用时也要再存一份到本次输出**，否则下一版又找不到（v7 因此重编了 27 分钟） |
| 5 | v5：多个 llama-server 运行 9–16 分钟后无报错消失，后续全部 `Connection refused` | 内存不足被系统杀掉 | 并行上限 4；每 5 分钟记录内存/显存；见 #8 的根因 |
| 6 | v5：服务崩溃后的题被记成“学生失败”，分数全错 | runner 标 `crashed`，但流代码当成能力结果 | `InfrastructureError`：crashed 不记录、任务退出，总控自动重启（≤6 次）并按题续跑 |
| 7 | v5：教师缓存里 60/109 条是 `budget_exhausted` | Kaggle 账本上限太低，被拒的结果也被当成示范缓存 | 预算拒绝抛 `TeacherBudgetExhausted`：停止学习、检查点照跑、不缓存；实验上限比账本上限低 $0.10 余量 |
| 8 | v6：重启后每次 20 秒内又 “crashed”，从未调用模型 | 重启复用同一 run_id，runner 直接返回缓存的崩溃结果 | 总控按尝试次数设 `KAGE_RUN_SUFFIX=-aN`，run_id 不重复 |
| 9 | v9：内存 5.9 → 31.7 GB（共 32 GB），任务被杀 3 次 | 该版 llama-server 默认 `--cache-ram 8192`：每台服务最多占 8 GiB 主机内存缓存旧提示，4 台占满 | `local_service.server_argv` 加 `--cache-ram 0`（不影响输出） |
| 10 | 网页 Logs 页面不自动刷新，只看到前几分钟 | Kaggle 日志查看器的行为 | 刷新页面；各任务的详细日志只在输出里（`e1/<臂>-sN.log`），跑完才能看 |
| 11 | Kaggle 没有 Docker | 免费笔记不支持 | `--skill-runner process`：技能在子进程里跑（虚拟机本身是一次性的），写入冻结 config，所有臂一致 |
| 13 | 取消运行后，下次运行找不到预编译程序和教师缓存 | 笔记的输入是“本笔记最新一版的输出”；被取消的版本（如 v12）没有输出 | 启动前在右侧 Input 里确认挂的是最后一个**成功**版本（当前为 v11）的输出，必要时手动改选 |
| 14 | v22（r3-smoke）：`ImportError: cannot import name 'BucketBatchError' from 'huggingface_hub.errors'` | 同一个 Python 进程先导入了旧的 huggingface_hub（下载量化模型），之后 `pip install -U transformers` 把它在磁盘上升级，再惰性导入时新旧模块混用 | 依赖新装包的步骤（全精度模型下载、版本检查）放到全新子进程里跑（`fresh_python`）；训练与转换本来就是子进程 |
| 15 | 下载输出时 CLI 会逐个拉取几千个文件，很慢 | `kaggle kernels output` 下载整个输出目录 | 等 `e1-results.tar.gz` 大小稳定后结束 CLI，自己解包；**不要在压缩包缺失时 `rm -rf e1`**——那可能是唯一的输出 |
| 16 | v23：`NoMatchingPeftModuleError: Target modules .*language_model.* not found` | transformers 5 用因果 LM 加载 Agents-A1-4B，只载文本部分，层名是 `model.layers.N`（没有 `language_model`） | 目标正则不依赖前缀，只匹配 `layers.N.(self_attn|linear_attn|mlp)`；视觉层 `visual.blocks` 永不匹配 |
| 17 | 本地复现：`convert_lora_to_gguf` 对 `linear_attn.out_proj` 抛 `NotImplementedError` | Qwen3.5 的 V 头数（32）≠ K 头数（16），转换器要重排 out_proj 的输入列，LoRA 的 A/B 无法这样重排 | `safe` 目标只留 `self_attn.o_proj` + MLP；**训练前先用随机假适配器在本地跑一次转换器**（不需要模型权重，只要 config.json），免得几小时训练后才失败 |
| 18 | v24：`ImportError: Found an incompatible version of torchao. Found version 0.10.0` | Kaggle 预装 torchao 0.10，新 peft 包装任何 Linear 时都会检查它 | `lora_setup` 卸载 torchao（不用它）；并在加载 4B 模型前用小模型跑一次 `get_peft_model` 预检（`LORA_PREFLIGHT`） |
| 19 | v24 日志：`skipped_too_long: 119`（上限 6144） | 全是 web_catalog 的后几步（最长 7758 token）；且冒烟只取前 4 条样本，碰不到峰值显存 | 损失只对回复部分算 logits（`logits_to_keep`，24.8 万词表下省几 GB；本地小模型核对与 HF 损失完全相等）；R3 上限 8192；冒烟改用最长的 4 条 |
| 20 | v25：训练最长样本（7758 token）时 `torch.OutOfMemoryError ... Tried to allocate 3.48 GiB`（SDPA） | head_dim 256 在 T4（sm75）上没有高效注意力内核，退回普通实现，注意力矩阵 16 头 × 7758² 放不下 | R3 训练改到 Colab A100（`KAGE_PHASE="r3-train"`，产出 `r3-adapter.tar.gz`），评测仍在 Kaggle（`r3-eval` 从输入数据集读适配器）；见下方 Colab 段 |
| 21 | Colab 冒烟“成功”但适配器 `lora_B` 全为 0（训练/验证损失各轮完全相同） | fp16 下 GradScaler 遇到溢出会跳过这一步，冒烟只有 2 步，两步都被跳过；不报错 | 支持 bf16 的 GPU 自动用 bf16（不需要缩放器）；每步记录 grad_norm 与 scale；训练结束检查 `lora_B` 仍全为 0 就报错退出，绝不把空适配器交给评测 |
| 22 | Colab：训练完成后运行时“因长时间无活动断开”，`/content` 清空，适配器丢失 | 训练在后台进程里，单元格空闲；Colab Pro 空闲约一小时后回收虚拟机 | 训练放前台单元格（`colab_r3.sh run`），同一单元格末尾 `files.download(...)`，训练一结束就落到本机 |
| 23 | Colab：前台单元格训练约 36 分钟后运行时仍被断开（“未连接到代码执行程序”），两个排队单元格均无产出 | 运行时被平台回收（可能是 A100 抢占；笔记本同时有“自动保存失败”冲突），前台运行也不保证 | 工作目录放在 Google Drive（`KAGE_WORK=/content/drive/MyDrive/kage/work`），训练每 25 步写可续训检查点（`lora_train --checkpoint-every`），数据/候选池/LESS 热身与打分/已完成训练都做“已有就跳过”；断开后重连、重跑同一命令即可接着做；冒烟用独立的 `-smoke` 路径 |
| 24 | Colab 计算单元 200 → 138（两天约 62 CU，A100 约 5.3 CU/小时） | 运行时只要连着就计费：训练结束后空闲、挂载失败后空等、被回收前的空转都在扣 | 训练单元格最后一行加 `from google.colab import runtime; runtime.unassign()`，做完立即释放；不再用后台进程训练；每次开新运行时前确认上一个已断开 |

## Colab A100 训练（10-21 起，用户的 Colab Pro 计算单元）

> **2026-10-24：用户的 Colab Pro 会员已退款，A100 不再可用。** 以下内容保留作记录；之后的训练只能在 Kaggle T4（约 7k token 以内的样本）或其它平台上做。训练产物（R3b–R3e 适配器）已在 Kaggle 私有数据集。

```
!git clone -b dev --depth 1 https://github.com/lemon5227/Kage.git /content/Kage
!cd /content/Kage && KAGE_WORK=/content/work KAGE_TOOLS=/content/tools KAGE_PHASE="r3-train smoke" python scripts/experiments/kaggle_e1.py
```
推荐用 `scripts/experiments/colab_r3.sh`（`fla smoke` → `train` → `status`；Colab 编辑器会自动补全括号，长命令容易被改坏）。A100 上装 `flash-linear-attention` 后线性注意力约快 5 倍，结果一致。先跑 `r3-train smoke`（最长 4 条样本、2 步，检查显存），通过后 `KAGE_PHASE=r3-train` 正式训练。产物 `/content/work/r3-adapter.tar.gz` 下载后用 Kaggle CLI 建数据集，在笔记本里 Add Input，再把 `kaggle_phase` 设为 `r3-eval`。计算单元只用于训练，不在 Colab 上调试。
- **挂载 Drive 用左侧“文件”面板的“装载 Google 云端硬盘”按钮，不在单元格里写 `drive.mount()`**（10-23）：代码挂载的授权只对当前虚拟机有效，每次新运行时都会弹独立的 Google 账号窗口（Claude 点不到，超时即 `mount failed`）；文件面板挂载是笔记本级授权（“直到访问权限被撤消为止”），以后连接自动挂载。
- **判断训练是否结束看 Drive 上的产物和日志，不看 Colab 终端**：终端断线后画面停在旧行（10-23 显示第 521/813 步，实际 15:06 已训完并打包，15:08 的“断开”是单元格末尾的 `runtime.unassign()`）。误判后重跑同一单元格，会在已存在的分轮目录上转换 GGUF 时报错退出——不影响已有产物，但浪费一次挂载。
- **单元格内容用 JS 写入**：`colab.global.notebook.cells[i].setText(...)`，避开编辑器自动补全括号/吞掉开头字符；`!` 开头的单元格输出比 `print(subprocess.run(...))` 好读。
- **精简包**：解开 `<tag>-adapter.tar.gz`，去掉 `*.safetensors` 和 `adapter*/` 目录，把 `adapter/train-*.json*` 提到顶层再打包（约 100 MB：三个 GGUF + 统计/日志），Drive 网页下载（>100 MB 会弹“无法扫描病毒”，点仍然下载），`kaggle datasets create`。
| 25 | v34/v35（R3t 冒烟）：单张 T4 在 6144 token 也 OOM；两卡切分（`device_map='balanced'`）仍 OOM | Qwen3.5 全注意力层 head_dim 256，T4 没有高效 SDPA 内核，走 math 路径一次性分配 fp32 分数矩阵（7758 token 约 3.5 GB）；`balanced_low_0` 甚至把整个模型放到 GPU1 | `lora_train --chunked-attention`：按 1024 个 query 分块的因果注意力，每块反向时重算（CPU 上与 SDPA 前向/反向完全一致）；单卡 8192 峰值 12.5 GB |
| 26 | v36：2 步训练 22 分钟 | 线性注意力（gated delta）走 PyTorch 参考实现 | 训练前 `pip install flash-linear-attention`（0.6.0 可在 T4 安装导入） |
| 27 | v38：每步约 23 分钟 | T4 上 `torch.cuda.is_bf16_supported()` 返回 True，但 bf16 是软件模拟 | T4 训练一律 `--dtype fp16`（带 loss scaler） |
| 12 | 输出被覆盖、找不到上一版的 server.log | 每次重启覆盖日志 | `server.log` 改为追加 |

## 4. 换设备恢复

1. `git clone https://github.com/lemon5227/Kage.git && git checkout dev`。
2. DeepSeek 配置放 `~/.config/kage/teachers/deepseek.json`（格式见 `docs/development/teacher-credentials.md`；key 不进仓库）。
3. 本机账本 `~/.config/kage/teachers/ledger.sqlite` 不在仓库里：新设备上从工作日志最新的“本机账本剩 $X”恢复上限（`KAGE_TEACHER_CAP_USD`），避免超出总预算 $2。
4. 实验原始数据：`evidence/`（见其 README）。
5. Kaggle CLI：`pip install kaggle` 到任意虚拟环境，在 Kaggle 网站 Settings → API 生成令牌放 `~/.kaggle/`。
