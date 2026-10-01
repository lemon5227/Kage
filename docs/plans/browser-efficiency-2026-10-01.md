# C7.1 浏览器观察与调用效率实施计划

> 按 executing-plans 在当前隔离 worktree 逐项实施；用户已批准上一轮的优化路线，无须重复申请设计批准。

**目标：** 同一真实本地模型与表单任务下，验证紧凑观察和初始观察直供是否减少 token、调用与任务耗时；失败全部保留。

**架构：** BrowserAdapter 增加 opt-in compact_observations。内部 current 和 JSONL 保留完整观察、完整 revision 校验；对外仅省略已定义默认值的目标属性、序列化空白，不截断额外正文、不移除非默认语义。实验协调器直接提供初始观察；原 AgenticLoop、工具执行和外部后台检查不变。复用 MeteredProvider 已有每调用 elapsed_ms；复用 ToolExecutor 外层日志统计工具时间，不把嵌套 DOM span 相加。

**约束：** 原默认格式保持兼容。姓名、当前值、动作、位置、链接/表单目的地保留。compact-v1 缺省属性约定：checked/disabled 为 false，其他省略属性为 null；实际空字符串与非默认值保留。云调用为零；无 Jev、新模型、新引擎或账号浏览器接入。协作 timeout 仍非硬截止，C2.1 才接入进程 runner。此包不冒称完成 C2.1。

## 1. 紧凑观察（独立提交）

文件：core/computer_use/browser.py、tests/test_browser_dom.py。

- [x] 在真实 Chromium 增加 compact 模式填写/保存/等待测试；断言对外载荷更短，内部完整快照、实际 HTTP 保存仍一致。
- [x] 在 compact 模式篡改表单目的地，旧观察必须拒绝且 POST 为零；现有替换/移动/导航超时测试继续通过。
- [x] 先运行新增用例确认缺失 compact 参数失败，再实现默认字段投影及紧凑 JSON 序列化。
- [x] 运行全部浏览器行为回归，检查默认行为不变，单独提交适配器与回归。

## 2. 固定配对试验与分段报告（独立提交）

新增 scripts/experiments/browser_efficiency.py；复用 browser_dom_pilot.py 的基线目标/提示、fixture、RecordedLocalProvider、MeteredProvider。

- [x] 两臂：baseline=原完整观察/原提示；optimized=compact-v1/初始观察直供/明确复用动作后观察。每臂3次，顺序交替 AB/BA/AB；每轮新服务器和context、6调用/5步、相同输出限制/服务配置。
- [x] 冻结两个提示、源码/fixture/model hash、顺序、预算和配置后开始。记录初始观察/原工具链，不能伪造一次模型调用。
- [x] 计时从初始观察之前开始到 Agent 返回；额外记录 setup、模型调用、外层工具、bootstrap、独立check、总耗时。remaining_agent_ms 是剩余开销，不能归因模型；失败/异常单独记账。
- [x] 独立check要求后台 record 正确、页面读回正确、POST 恰好一次。所有六次均入分母，记录 token、调用、stop_reason、完整轨迹及截图。
- [x] 实验结束停止本包启动的模型服务，保存日志；运行全量回归和 diff 检查。
- [x] 报告包内遇到的问题、red/green、真实数据与限制；更新报告索引和队列，保持 C2.1 待做。

验收：不预设必须更快；仅此单任务三对不能证明通用收益，组合方案也不能隔离每项贡献。如果 optimized 失败，不将它切为日常默认。
