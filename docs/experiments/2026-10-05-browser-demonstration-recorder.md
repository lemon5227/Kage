# C4.5-DOM录制与技能提取工程报告

日期：2026-10-05。范围是受控浏览器单表单，profile/preferences两族；不是任意网站或真人示范验收。实现提交`a918264`，审查修复`97c4b64`，父版本`3d6d1eb`。

DOM录制器观察实际Page事件，在页面内同步取前后快照并按序送入Python。原始打字立即保留，归一化动作按已提交字段修改和点击计数；修正不会被抹掉，结束前未失焦的最后输入会flush。动作预算64，教学期限900秒；超限、窗口关闭、写入失败都会阻止有效候选生成。

示范经过实际保存POST、后台记录与页面读回的独立检查，进入已有ExperienceArchive/episode。来源显式区分`human_demonstration_declared`与`automation_demonstration`；`isTrusted`仅保留为DOM证据，示范不计作学生或云教师成绩。生成输入只取公开目标与可见DOM/动作，隐藏检查内容不进入工作流。

提取器生成已有v2声明式工作流：文本fill、checkbox确保目标状态、最后保存。所有可编辑字段的标签和值都成为参数，示例及来源hash单独存放；在字段反序、值与初始勾选状态不同的新Page中，仍调用同一BrowserSkillCatalog/ToolExecutor和16原语配额。候选未晋级，不自动安装。

| 问题 | 证据与处理 |
|---|---|
| 原始输入/事件不在档案顶层完整性检查里 | 窄幅扩展archive evidence引用，保持旧顺序并去重；去掉修复后真实两族测试均因篡改仍可检索而失败，恢复后拒绝 |
| 页面超时仍接收输入 | 初次新核验1失败/33通过；加页面期限计时与停止接收，保留截止前末次修改 |
| 最后轨迹写入失败但磁盘摘要仍成功 | 独立审查真实Page复现返回失败/持久成功，甚至可编译候选；将成功摘要放到所有结束证据之后，错误时尽力保存失败摘要。新增真实Page回归先红后绿，检查归档不验证且编译拒绝 |

最终聚焦命令：`.venv-computer-use/bin/python -m pytest tests/test_browser_demonstration.py tests/test_browser_episodes.py tests/test_browser_skills.py -q`，**35 passed in32.99s**，无警告。最终写入故障回归RED为1 failed in2.03s，修复GREEN为1 passed in1.39s。git diff检查通过。独立任务审查与修复复审通过；原实施者缺失模块RED日志不可恢复，未补造或声称存在。

覆盖真实纠正、末次输入、checkbox、停止后不接收、窗口关闭、配额/期限、保存POST/读回、档案重启与篡改、参数编辑后新Page复用；拒绝未保存、重复标签、多个form、unsupported控件、超16步和保存后再改值。真人来源测试是投影测试，不是人类教学成绩。

工程证据已保存到活动worktree的`artifacts/c45-browser-demonstration-2026-10-04/review-evidence/`，包含完整审查、红绿输出与当时源码hash。最终入口、992项全量检查和真实模型pilot见[总报告](2026-10-07-browser-demonstration.md)。原始证据不得随worktree清理。
