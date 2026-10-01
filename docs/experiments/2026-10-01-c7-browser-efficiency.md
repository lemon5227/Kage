# C7.1 浏览器效率：紧凑观察与初始观察直供

日期：2026-10-01。用户批准 DOM/AX 优先、快速决策和视觉补缺的优化路线。当前独立首包只实施紧凑观察、减少观察往返和分段计时；Jev、视觉、AX、新引擎以及 C2.1 浏览器学习均未在此包完成。

## 适配器实现与回归

原 BrowserAdapter 默认行为不变；显式 compact_observations=True 时，对模型省略目标的 null 属性与 checked/disabled=false，保留空字符串、值、位置、允许动作及所有非默认属性。工具说明明确缺省含义；不增加正文截断。内部 current 和 observe JSONL 仍为完整快照，动作前完整 revision 校验未改变。序列化采用紧凑 JSON。不是从日志里删除证据。

新增真实 Chromium 回归：通过原 ToolExecutor 填值/保存/等待，独立 HTTP record 与页面一致、POST一次；投影可还原完整 target；勾选框点击后实际取消、禁用按钮拒绝；改变表单提交目的地后旧引用拒绝且不再提交。新测试首先因缺失 compact_observations 参数 TypeError 失败，实现后通过。原八项动作回归继续保留。新旧浏览器回归10 passed；连同工具契约共18 passed（10.19秒）。

发现已有 MeteredProvider 逐调用 elapsed_ms，无须在核心创建重复计时系统。下一步固定配对试验通过实验脚本统计外层 ToolExecutor、初始观察、Agent和独立check时间，嵌套 browser span 不相加。

## 配对实验

待运行；完成前不声称速度或成功率改善。设计见[独立计划](../plans/browser-efficiency-2026-10-01.md)。原始证据将保留在活动worktree的独立 artifacts 目录，不能清理worktree后丢失数据。
