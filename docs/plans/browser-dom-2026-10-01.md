# C1.1 浏览器DOM实施包

日期：2026-10-01。沿用已确认的电脑路线与任务队列，当前只做浏览器包。

设计：独立Playwright异步Page绑定观察/动作适配器，异步handler注册到原ToolRegistry/ToolExecutor；不把浏览器驱动塞入AgenticLoop。只开放已观察的节点引用，不接受模型自造selector。动作前比较新鲜DOM/节点身份/URL/位置，发现替换或移动则拒绝并返回新观察；动作后重新观察。条件等待有时间上限，阶段耗时和结果写JSONL。

- [x] 依赖在独立venv安装，固定Playwright版本；headless浏览器只打开本地验收页面，不操作用户日常标签页。
- [x] 先写失败行为测试：真实填写→保存→页面存储读回；旧观察/同样文字的替换节点拒绝，旧节点不被重定位到新节点；真实滚动与有上限的条件等待。
- [x] core/computer_use/browser.py：observe/open/act和工具注册，最长文本/节点数有上限，显式outcome贯穿既有工具执行器。
- [x] 本地可重置页面＋真实Agent工具链试验，判断实际保存内容，不用工具success代替完成检查；模型任务失败也保留。
- [x] 必要回归/全量、独立报告与提交；只勾C1.1，不提前勾至少4浏览器任务或12电脑任务。

第一包只覆盖顶层普通DOM表单/按钮/链接/文本输入，iframe、canvas、原生浏览器标签、选择框等按实际缺口后续补。page由调用方拥有，退出关闭；生产全局工具默认不增加，实验显式绑定会话。C2.1另包扩充任务和教师学习闭环，不在此包更改评分系统。

依赖依据：[官方Python Page接口](https://playwright.dev/python/docs/api/class-page)、[节点句柄身份与定位器差异](https://playwright.dev/python/docs/api/class-elementhandle)。引用特定真实节点是失效检测要求；官方一般建议Locator，本包避免自动重定位到替换节点，且每次动作后释放句柄。

实际成绩、审查修复与时延变化见[实验报告](../experiments/2026-10-01-c11-browser-dom.md)。
