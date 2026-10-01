# E3.0-A 默认关闭的恢复接口

日期：2026-10-01。本包仅实现实际AgenticLoop恢复入口，不提前声称真实模型代码演化已完成。

问题：已有工具证据之后，模型只输出解释就停止，无法由版本化恢复策略补一个动作。实现：AgenticLoop可选recovery_policy；在已有实际工具结果且本轮没有工具动作时最多调用一次recover(error, history, checkpoints)。本包仅支持stop/switch_tool，原循环步数和模型调用额度不增加；返回动作交给原ToolExecutor，记录recovery_policy actor和决策/异常。默认不启用，基线源码只返回stop。

回归先失败（构造器没有recovery_policy与事件接口），实现后8项通过：真实读7、恢复写14、后续读回；停止/非法动作/异常不会造出产物；无证据不调用策略；原多步与快速单命令路径保持。测试是临时真实文件与原工具执行器，外部模型使用确定序列，属于接口行为验证，不算真实云生成实验。

命令：`python -m pytest tests/test_evolution_self_modify.py tests/test_agentic_loop_multistep.py -q`，8 passed；`git diff --check`。首次命令误写不存在的test_evolution_agent_provider.py，未运行测试，已修正命令。

下一包：不可变bundle模块加载、源hash校验、Docker运行决策、云生成恢复源码、同技能同提示父子与新变体实际评分。完整设计见[实施计划](../plans/recovery-self-modification-2026-10-01.md)。
