# C4.3 真实教师轨迹→技能→本地执行

状态：最小真实技能迁移验收通过，E1真实云生成pilot补齐；C4.4多臂/三重复独立留出、E3代码自修改和权重训练未完成。

## 冻结任务与真实教师

新增仅dev的learning-dev-v1代码修复题：choose(jobs, capacity)按容量选择最大总价值，等分时按ID列表字典序，异常边界单独外部运行。没有修改C2原六任务或原holdout。学生在6调用/5步/300输出token预算下自然失败，只有读文件和截断分析，原函数未修好。

教师300输出协议也失败，截断参数问题及1024协议的新的成功尝试见[独立修复报告](2026-10-01-c4-truncated-tool-arguments.md)。新的dev成功episode包含失败状态快照、角色和通过的外部检查，可通过档案过滤；原留出排期接管没有用于学习。

## 技能生成与执行

`scripts/experiments/skill_learning.py`只接受intact、verified、dev、同任务且教师检查通过的episode。复用E1 Mutator、SkillCatalog、Promoter，云生成1候选（上限3提议/修复，12000输入字节/3000输出token/次，优化账本$0.03）。学生所有父子与reuse执行均只连接本机API，不含云回退。技能通过既有DockerSkillRunner执行，网络隔离，不在宿主机直接运行新生成代码。

启动既有OrbStack并构建sandbox/evolution镜像；固定实际image ID：`sha256:8e525133f765d7b7fef855c007f43bfcaf7fa6dc6e91f7ec705be6b60877f418`。镜像基底解析到python:3.12-slim具体digest；没有增加训练GPU依赖。

云Mutator首次生成合法候选repair_knapsack_selection：file_path和function_name参数化，用通用DP修复函数，没有写死job IDs、数值或期待答案。bundle digest `61282a48bf51aa04499c0f0c…`，skill digest `6ecb72febf4945a385909abdd49e8fbed038ae6a74647b87e874a0dda022d69d`。优化调用1次，970输入/975输出tokens；按核验最高价估算$0.001461，非账户账单。

## 三轮结果，全保留

| 协议 | 父分 | 子分 | reuse | 实际技能调用 | 结论 |
|---|---|---|---|---|---|
| v1 原技能工具暴露 | 0 | 0 | failed | 0 | 合法技能没有被发现，未晋级 |
| v2 同一候选＋统一检索指引 | 0 | 0 | failed | 0 | 仅提示优先搜索仍未使模型调用技能，未晋级 |
| v3 同一候选＋简短目录预览 | 0 | 1 | passed | 1 | 实际调用并通过，实验内晋级 |

v2/v3复用第一次云生成的不可变候选，没有再买生成或更换算法。预览最多3条descriptor，仅给名称、digest、简短description和参数schema，不给实现源代码或隐藏测试。父子两臂使用相同指引/预览规则、工具权限、6模型调用和5步上限；父只有空目录，子有新增技能。这是系统的知识可用性变化，不是权重更新。

v3父：3调用、3932输入/491输出tokens，外部0分；子：5调用、9614输入/722输出tokens，真实read→skill_search→skill_call→read回验收，外部1分。reuse从不同初始坏函数出发，外部函数调用使用新IDs/重量/价值，学生5调用、9680输入/637输出tokens，真实skill_call=1，外部通过。reuse最后一轮仍调用list_files并达step_limit，保留该停止原因；外部检查证明程序已正确，因此completion=completed，不能把步数耗尽等同于输出错误。

reuse具体输入从未给优化器或学生；但这组reuse已在v1/v2协议调试中反复观察失败，不能当作最终独立留出成绩。C4.4必须另冻新变体、多臂至少3重复，不能凭本pilot声称统计收益或通用电脑能力。

## 工程与验证

KageChainProvider增加可选skill_context_mode=preview（默认search）；固定实验提示摘要入缓存fingerprint和metadata。改变提示不能复用旧评分：拿掉fingerprint的突变验证确实使回归失败，恢复后通过。预览及检索政策均只在实验链启用，没有把实验candidate自动装进生产技能目录。

完整真实命令与所有请求/响应、候选、两轮未晋级和v3晋级记录保存在工作树artifacts/c4-skill-learning-v1、c4-skill-learning-discovery-v2、c4-skill-learning-preview-v3，Git忽略；dev任务、脚本和本报告纳入Git。C4.3复现入口：

```sh
python scripts/experiments/skill_learning.py --episode-journal artifacts/c4-learning-dev-takeover-1024/journal.sqlite \
  --suite eval/computer-use/learning-dev-v1.json --teacher-config /Users/wenbo/Kage/artifacts/private/deepseek-settings.json \
  --candidate-record artifacts/c4-skill-learning-v1/mutation/proposal.json --skill-context preview \
  --output-dir artifacts/c4-skill-learning-preview-v3
```

首次生成不传candidate-record；输出目录必须新建。生产默认模型保持Agents-A1，候选只在实验active.json晋级。

相关30 passed；包含提示缓存回归的21 passed；最终全量822 passed、1 skipped、1 xfailed，75.97秒。相比此前4 skipped，现有Docker测试实际启用后3项执行通过。论文结论边界：这是黑盒教师的程序性技能迁移与脚手架收益，尚未训练权重、未证明通用能力、自修改Agent核心或自主持续成长。
