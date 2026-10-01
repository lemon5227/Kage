# C4.3-A 云工具参数截断诊断与修复

在新的dev代码选择器任务中，学生自然失败。首次教师沿用300输出token上限，也失败：先读selection.py，随后4次write_file均finish_reason=length，JSON参数中途截断。OpenAICompatibleProvider原来捕获JSONDecodeError后改成空对象，ToolExecutor因此反复看到缺参数，实验最终no_progress/step_limit，不能算成功示范。

修复：坏JSON明确返回ModelResponse.error=InvalidToolArguments，tool_calls为空，保留raw_output和实际usage；非对象参数也明确拒绝。合法空对象调用不受影响。先写截断HTTP响应回归，确实看到旧实现输出write_file(arguments={})；修复后26项相关provider/真实链回归通过。本次是诊断和拒绝伪调用，不声称修复了所有模型截断后恢复问题。

另一个独立变量是教师生成长度：新增1024输出token的有限教师协议，在新的完整尝试中真实纠正通过（学生仍失败，教师3调用、3642输入/570输出tokens，35.025秒）。旧300协议失败保留不覆盖，原C2冻结本地预算也未改。所有请求字节上限、调用上限和预算仍记录；1024教师的保守云上限为$0.0289728，实验账本$0.04。失败和成功原始证据分别在工作树artifacts/c4-learning-dev-takeover与artifacts/c4-learning-dev-takeover-1024。后者是dev正示范，前者仅失败档案；技能迁移实验随后单独报告。
