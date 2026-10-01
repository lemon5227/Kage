# C2.1-B2.0 独立完成门控与保存确认

按已批准B2路线，先完成独立可验收的小包，再做技能。使用现有worktree，历史A/B1报告与协议不改。

设计：BrowserChainProvider增加external_completion=False显式开关。只有开启时，可信模型代理在下一次调用前用原Evaluator检查真实产物；通过则以external_check结束，不调用模型。CheckpointExecutor观察实际/save请求，最多1秒等待响应/读回一致，再写可信checkpoint；超时/错误保留诊断，错误值即使保存/读回正常也不能触发完成。开关进入metadata/cache；学生和教师统一使用。原AgenticLoop不改，不恢复“任意tool success退出”。

- [x] tests/test_browser_takeover.py先写真实异步保存延迟回归；无最终总结调用，学生正确时教师零调用；错误保存不能终止，教师真实修订后及时停止。
- [x] task_environment.py只增加可控读回延迟fixture（测试使用）；experiment.py增加有界保存等待与外部完成门控，默认历史协议不变。
- [ ] 独立审查/全量测试；冻结三次dev真实协议（B1相同目标/模型/调用上限/HTTP30，只开启门控），费用上限不增，全部保留。没有触发教师时明确未新增真实教师样本。
- [ ] 独立代码与报告提交，短总规划/队列标B2.0完成、浏览器技能B2.1及五臂迁移B2.2仍待做。

本包不更改checkbox观察，不生成技能，不将历史B1→新成绩差解释为学习收益。只有返回的实际backend与DOM读回一致且原外部目标检查通过才结束；截图/模型文字不参与。等待窗口最多1秒，原runner整体硬截止仍兜底。

工程验收：856 passed、1 skipped、1 xfailed；浏览器20项通过；一秒边界问题已复现修复并复审通过。真实三次试验待运行。
