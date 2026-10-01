# E3.0 Recovery Module Implementation Plan

> **For agentic workers:** Use executing-plans inline, task by task. User has authorized queue execution; do not create parallel chats.

**Goal:** 模型根据真实失败修改恢复策略源码，下一代AgenticLoop实际执行不同代码，经父子dev评分与新变体检查后才在实验内晋级。

**Architecture:** 在AgenticLoop的“已有工具证据但模型未给下一动作”处增加默认关闭的恢复接口，默认策略stop保持原行为。候选bundle沿用E1 manifest/skills并添加modules.recovery，恢复源码在现有Docker运行器中执行；返回switch_tool时交给原ToolExecutor执行。隐藏评分器不进入策略输入，不能通过改提示或新增技能冒称本包完成。

**Tech Stack:** Python，既有AgenticLoop/SkillCatalog/Mutator/Promoter/Journal/DockerSkillRunner。

## Global Constraints

- 正常Agent路径默认不启用新策略；每个run最多一次恢复决策，原5循环步/6模型调用/超时仍约束执行。
- 冻结C4技能候选，父子使用相同技能、相同提示和模型预算；唯一变量为recovery源码/manifest指针。
- 本包先支持stop与switch_tool；retry/replan/rollback由后续独立任务补，不谎报已实现。
- 恢复代码只拿goal、已有实际工具结果、当前技能descriptor、空checkpoints；在单独临时工作目录运行，只返回动作，不能直接改实际任务文件。
- 真正的任务动作必须经原ToolExecutor；新策略源码/包digest/执行adapter digest/实际模块路径入trace，源码篡改拒绝执行。
- 生成预算最多3请求、每次12000输入字节/3000输出token、$0.03；参数训练仍关闭。

## Task 1: Default interface and real loop hook

Files: core/evolvable/recovery.py，core/agentic_loop.py，tests/test_evolution_self_modify.py。

Consumes: 已有工具结果与用户目标；produces: recover(error, history, checkpoints)->dict。

```python
def recover(error, history, checkpoints):
    return {"action": "stop"}
```

- [x] 写回归：真实read后模型空泛结束，baseline不写结果；可控策略返回write_file时真正写出结果并进入后续读回。正常未启用路径仍不调用策略。
- [x] 先观察失败，再实现构造器可选recovery_policy，在纯文本返回前最多调用一次。
- [x] 验证未知动作/异常不会伪造成功，记录policy事件与恢复actor，复验原多步工具链。
- [x] 独立提交接口与报告，不先勾“真实自修改完成”。

## Task 2: Versioned source loader and cloud patch

Files: core/evolution/bundle.py，core/evolution/recovery_mutator.py，core/evolution/agent_provider.py，tests/test_evolution_self_modify.py。

Bundle增加字段，不改变已有version=1技能契约：

```json
{"version":1,"skills":[],"modules":{"recovery":{"entrypoint":"recovery.py:recover","digest":"sha256-of-source"}}}
```

恢复源码必须定义三参数recover。可信adapter将JSON参数转为该接口；现有ProcessSkillRunner用于可信测试，DockerSkillRunner用于真实生成代码。输出示例：

```json
{"action":"switch_tool","tool_call":{"name":"skill_call","arguments":{"skill_id":"runtime descriptor ID","digest":"runtime descriptor digest","arguments":{}}}}
```

- [x] 测试模块digest变更、入口错误、写出实际动作后的产物、失败模块取证；先red再实现。
- [x] 模型读取真实dev失败轨迹、默认恢复源码和可用技能schema，输出JSON hypothesis/code；只发布不可变新bundle，不让模型修改评分器/技能代码。
- [x] 生成与修复都复用预算预留/结算、attempt证据和Journal mutation事件；未通过contract或外部评分不启用。
- [x] KageChainProvider把加载的候选恢复器传给实际AgenticLoop，模型提示/技能保持一致。

## Task 3: Real pilot and activation

Files: scripts/experiments/recovery_evolution.py，eval/computer-use/recovery-dev-v1.json，eval/computer-use/recovery-transfer-v1.json，docs/experiments/2026-10-01-e3-recovery-self-modification.md。

- [ ] 独立dev/新变体，不使用C4.4留出结果作为生成反馈；使用已有dev代码失败与固定C4技能，先确认默认恢复仍失败。
- [ ] 真实云生成最多一个候选（允许两次格式修复），记录所有失败尝试及源码diff。
- [ ] 同预算父子外部比较；新任务在固定候选上执行，核对实际module path/hash、恢复事件、真实ToolExecutor action与产物。
- [ ] 只有dev改善且新变体外部通过才在实验active.json启用；否则保留负结果。本包不自动改变生产桌面配置。
- [ ] 运行必要回归、空闲全量检查，更新报告/队列/轻量总规划并独立提交。
