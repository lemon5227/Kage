# C4.4 独立留出迁移与五臂对照

日期：2026-10-01。目的：区分本地独立执行、云救场、轨迹检索、可执行技能和本地多重试。结论：本次单一家族的冻结变体上，云救场与技能各3/3，其余各0/3；技能臂关闭云端，真实调用生成技能。不是通用电脑能力、权重学习或速度提升证明。

## 冻结协议与实际执行者

本地实际执行为M4 Air 16GB上的Agents-A1-4B官方Q4_K_M、llama.cpp（端口18082），而非假定本地模型运行。温度0，最多6模型调用、5循环步、单次300输出tokens、单任务150秒。云教师是DeepSeek官方deepseek-flash，thinking关闭、单次1024输出tokens、请求JSON最多12000字节；仅cloud臂使用。

技能在C4.3开发轨迹上已生成并冻结：bundle digest `61282a48bf51aa04499c0f0c9192d5443629074aeac078aabfa0ce6d738c6723`；skill digest `6ecb72febf4945a385909abdd49e8fbed038ae6a74647b87e874a0dda022d69d`。本实验不再调整候选。

新留出集：`eval/computer-use/learning-transfer-v1.json`，SHA256 `73454df09dd8eef6e4db5bf3e9dd764cfd359bc3b5e995bae6f8099cb7dc2745`。文件变为variant.py、函数变为pick_jobs，工作项ID与隐藏测试数据均不同于开发任务。生成器没有读取本次任务；轨迹臂只注入已验证dev教师的实际动作/反馈，隐藏评分答案不进入模型提示。外部Python函数检查运行实际保存代码，通过记1，否则记0。

每臂3次，按repeat交错执行，15次全部保留，不筛选成功样本。运行时存在缓存、时延波动，少量重复不能支撑统计显著性结论。

## 五臂结果

| 臂 | 外部通过 | 中位耗时/秒 | 实际模型调用数 | 含义 |
|---|---:|---:|---|---|
| 原学生 raw | 0/3 | 30.791 | 2、2、2 | 本地直接修复失败 |
| 云救场 cloud | 3/3 | 46.155 | 总6、5、5；教师4、3、3 | 教师继续同工作区完成，不能计为学生独立成功 |
| 轨迹检索 trajectory | 0/3 | 42.536 | 2、2、2 | 看到成功示范仍未写出有效修复 |
| 技能迁移 skills | 3/3 | 75.402 | 5、5、5 | 云端关闭，每次实际skill_call一次 |
| 本地多重试 retries | 0/3 | 94.669 | 5、5、5 | 三次尝试共享6调用/5步上限，没有靠新增预算获得通过 |

技能臂三次都实际传入`file_path=variant.py, function_name=pick_jobs`，执行已冻结技能、保存代码后接受同一外部检查。Docker镜像为`sha256:8e525133f765d7b7fef855c007f43bfcaf7fa6dc6e91f7ec705be6b60877f418`。不是仅检索到技能名或打印答案。

**预算与脚手架限制**：cloud臂有独立额外教师额度（最多6调用），并非与单一本地臂相同总算力；它是救场上限参考。skills臂采用C4.3冻结的descriptor预览策略，其余无技能臂不能预览不存在的技能。本对照测量“技能＋发现策略”整体收益，不能将收益完全归因于代码内容、排除提示差异。技能中位耗时高于教师，不能声称加速。本次仅一个代码修复家族，不代表跨家族泛化。

## 问题、解决与补充控制

1. 重试控制如果每次重建Agent都会放大预算。新增`LocalRetryProvider`：同工作区保留失败产物，合并实际历史，最多三次，每次最多2调用/2步，扣除已用总额；外部通过即停止。真实文件测试验证7→14的修复、读回上一轮产物、总5步上限。直接调用入口也移除隐藏评分字段，先观察泄漏回归失败再修复；实际runner原已传入脱敏任务，本轮成绩未受此修复影响。
2. 怀疑300输出tokens导致失败，而非能力/使用技能的问题。追加原学生控制，单次上限1024、总输出仍最多1800（原6×300），最多6调用/5步、云关闭。3次仍0/3，耗时44.043、44.456、42.288秒，每次2调用、1869输入/1080输出tokens。这说明单次限制不足以解释本次失败，不能证明更大预算下永远失败。该控制不替换原五臂成绩，也不修改候选。
3. 新`FlexibleLocalProvider`逐请求按剩余总输出设置max_tokens，额度耗尽不再请求；usage未知时保守停止。HTTP边界测试证明两次900输出后没有第三次请求，实际请求上限为1024和900，而非只检查常量。

## 费用与证据

教师实际10付费调用，14118输入、2332输出tokens。按2026-10-01官方Flash峰时、全部cache miss价格估计上界：`14118×0.30/百万＋2332×1.20/百万 = $0.0070338`。这不是账户实际账单；缓存/时段可能使实际更低。预先声明本轮云预算$0.10，固定最坏调用估计$0.0869184。费用依据：[官方定价](https://api-docs.deepseek.com/quick_start/pricing/)。本地token不产生云账单，预算账本按云价计本地tokens只是保守实验额度。

原始全部结果、请求/响应、journal、文件工作区在当前实验worktree的`artifacts/c4-learning-transfer-ablation-v1/`；补充控制在`artifacts/c4-transfer-flexible-output-control/`。原始artifacts被Git忽略，报告/冻结任务/脚本入Git；证据引用含当前worktree绝对路径，清理worktree前必须迁移及重建索引。所有留出任务记录不会成为dev示范。

复现命令（私有配置只传路径，不输出key）：

```sh
python scripts/experiments/learning_ablation.py --candidate-record artifacts/c4-skill-learning-v1/mutation/proposal.json --episode-journal artifacts/c4-learning-dev-takeover-1024/journal.sqlite --teacher-config /Users/wenbo/Kage/artifacts/private/deepseek-settings.json --output-dir artifacts/c4-learning-transfer-ablation-v1
python scripts/experiments/flexible_output_probe.py --output-dir artifacts/c4-transfer-flexible-output-control
```

输出目录必须不存在；重新运行请使用新的目录，不能覆盖原轨迹。跨机器需要对应模型、Docker镜像与冻结候选/示范数据。验证：`python -m pytest -q`，827 passed、1 skipped、1 xfailed（63.94秒）；`git diff --check`通过。下一包为E3真实recovery模块源码演化，保持现有技能冻结，不能把本轮技能成长称为Agent核心自修改。
