# G2本地基线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task.

**Goal:** 独立检查自然读取任务是否误用G1技能，并检查旧knapsack能力；不产生学习候选。

**Architecture:** 原Evaluator增加read_preserve评分条件，读取原runner实际history。纯本地CLI复用Promoter与现有真实执行器，最多两任务；模型服务由已有LocalService管理。使用活动worktree。

**Tech Stack:** Python、pytest、现有SQLite/llama-server/Docker；不新增依赖。

## Global Constraints

- 用户2026-10-12批准适用性方案；协议为g2-applicability-protocol-2026-10-11.md。教师0、候选0。
- 2任务，每任务6请求、5循环步、12工具派发、150秒；总12本地请求。单worker、同root幂等；失败保留不重放。
- G1子bundle/技能不修改；独立新root/namespace。教师配置不读取。
- 基线没有自然缺口就停止，不能人为强制恢复；G2尚未验收。

### Task 1: Existing Evaluator的读取保留条件

**Files:** core/evolution/runner.py；tests/test_evolution_read_preserve.py。

**Interface:** `Evaluator.score(task_def, workspace_dir, *, history=None)`；仅read_preserve调用携带真实history，旧criteria保持原调用兼容。

criteria精确格式：`{'type':'read_preserve','file':'pricing.py','sha256':<64小写hex>}`。

- [x] 先写失败测试：合法文件+成功read返回1；同文件未读/失败读/错误路径/文件变化/无history返回0；任何actor的skill_call尝试即使失败且无副作用返回0；坏schema或越界路径返回0。未知观察不算成功。
- [x] 运行新测试观察红，再最小实现：路径用原_workspace_file，hashlib.sha256文件字节；在history中检查action.name=read_file及arguments.path/path与criteria.file一致、observation明确成功；所有skill_call行拒绝。runner在评分时仅新type传history。
- [x] 真runner受控模型边界测试读→保留1，读→skill失败0；证明criteria/hash不传provider与visible_feedback，旧评分回归。
- [x] `python -m pytest -q tests/test_evolution_read_preserve.py tests/test_evolution_agent_chain.py tests/test_recovery_loop.py`；提交并审查。

### Task 2: Pure local frozen baseline entry

**Files:** scripts/experiments/recovery_baseline.py；tests/test_recovery_baseline_cli.py；eval/computer-use/g2-applicability-baseline-v1.json。

**Interface:** `run_baseline(config_path)` returns report；CLI `--config CONFIG`。配置包含root、candidate_record（G1 active.json）、suite、student_settings，与G1相同local-only配置。没有教师/学习开关。

- [x] 测试优先：非法cloud/大于2任务/任务重复ID或不同协议拒绝，零教师读取/创建/请求、零mutator、固定provider6/5/12与fork150。重复入口返回持久report，不消费/重放；不同输入root拒绝。
- [x] 复用RecordedLocalProvider、FiveStepLoop、ModelBroker、RecoveryPolicy、SkillCatalog、DockerSkillRunner、Promoter、BudgetTracker。预算12calls；run_namespace为canonicalroot SHA前12位；每项运行前持久保留attempt，异常/中断不重放。不要复制整个build_loop。
- [x] 冻结task/source/candidate/settings公共配置/实际model与image身份；禁用cloud，保留原提示及search目录策略。预检候选hash/模型配置后才启动服务。LocalService只清理自己启动的服务。
- [x] 两任务：source pricing.py读取保留，内容正常discounted；old_regression复用G1validation仅改变task_id/split为dev，标已暴露。parent始终G1晋级子。先提交真实输入与代码再运行。
- [x] report保存每项原RunResult、失败分类、actual skill_call actor与派发、服务清理和总usage；判定source能力失败+不适用skill_call、旧能力通过且技能实际调用才报告可进入学习。任何infra/resource问题停止，不算学习缺口。
- [x] focused CLI/checker测试与旧G1 CLI/promotion tests；提交并审查。完整源码回归一次通过后，只运行冻结真实基线一次。

### Task 3: Actual baseline and handoff

- [x] 执行已冻结两项一次，零教师；核对trace、评分、实际调用/动作/费用、旧能力、候选digest与源码hash。
- [x] 保存正负结果、服务退出、人工贡献和缺口；没有新学习不能标G2完成。
- [x] 更新roadmap §2/3/4和问题报告，明确下一项或停止。保留raw ignored数据、私有配置和其他模型文件；审查后本地main快进，不push。
