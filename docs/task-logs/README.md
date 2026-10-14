# 任务日志

每个任务（见 [总任务规划](../plans/MASTER-TASK-PLAN.md)）完成或阻塞时，必须在本目录留下一份日志：`Txx-简短英文名.md`，格式见 [TEMPLATE.md](TEMPLATE.md)。

规则：

1. **动手前**先创建日志，写好"目标"和"计划"。
2. **过程中**每一步追加到"过程记录"：做了什么、改了哪个文件、怎么验证。
3. **结束时**填写"验证结果"（贴命令和通过/失败数量）、"偏离计划""遗留与后续"。
4. 日志与代码、测试、总表状态放在**同一个提交**里，然后推送。
5. 失败或阻塞也要写日志并推送，不要删除或美化失败结果。
6. 不要在日志中粘贴 API key、私有配置或个人数据。

| 任务 | 日志 | 状态 |
|---|---|---|
| T00 | [T00-audit-and-plan.md](T00-audit-and-plan.md) | 完成 |
| T01 | [T01-dependencies-and-test-env.md](T01-dependencies-and-test-env.md) | 完成 |
| T02 | [T02-confirmation-gate.md](T02-confirmation-gate.md) | 完成 |
| T03 | [T03-heartbeat-delivery.md](T03-heartbeat-delivery.md) | 完成 |
| T04 | [T04-proactive-feedback.md](T04-proactive-feedback.md) | 完成（后端） |
| T05 | [T05-proactive-policy.md](T05-proactive-policy.md) | 完成 |
| T06 | [T06-important-date-reminders.md](T06-important-date-reminders.md) | 完成 |
| T07 | [T07-teaching-request.md](T07-teaching-request.md) | 完成（后端） |
| T08 | [T08-evolution-smoke-without-docker.md](T08-evolution-smoke-without-docker.md) | 完成 |
