# C2.1-B1 同页教师接管实施计划

> 按已批准的浏览器学习路线逐任务执行、测试和独立审查；现有隔离worktree继续使用。B1完成接管，不提前标浏览器技能与完整B完成。

目标：学生失败时，DeepSeek沿用同一个Page/context/HTTP后台纠正，按最终真实保存状态验收，记录分阶段动作与计量。

架构：保留BrowserChainProvider生命周期，在同一会话内部增加actor执行函数与接管hook；原EvolutionRunner负责终止、预算与journal。新增browser-outcome.json只含记录与读回一致性，原browser-check.json继续保留posts与A的严格评分。POST原子撤销两份证明，避免旧满分。新browser-learning-v2任务只改变评分协议，A任务/成绩不回写。

协议：真实pilot只用preferences_dev，预先固定3次、全部进入分母。学生6调用/5步，教师最多6调用/5步；本地和云HTTP30秒，整体runner monotonic 480秒，防闲置休眠并记录墙钟。教师thinking=false，每请求输入JSON<=12000字节、输出<=1024，六次保守云费用上限$0.0289728，三次不超过$0.0869184。Journal/BudgetTracker按含本地的云价保守结算，预算$0.16足以覆盖三次全部预留；报告实际云费用只看teacher usage，不把本地token算付费。参数超限/未知usage/失败照实保留，无假模型回退。

- [x] tests/test_browser_takeover.py先验证真实错误保存→同页教师修订第二POST→外部得1；学生已经正确时教师0调用；无答案泄漏；两份证明同步失效。
- [x] task_environment.py增加独立outcome，保留A检查语义；browser-learning-v2.json冻结最终状态评分。
- [x] experiment.py共享actor执行、接管hook与工具actor日志；teacher_takeover.py实现同页失败状态观察、计量与元数据。
- [x] scripts/experiments/browser_takeover.py读取私有凭据路径（不复制/打印key），冻结配置/hash并通过原runner执行3次；保留实际费用和未知费用上限。
- [ ] 全量测试/独立审查，代码单独提交；caffeinate真实模型试验与完整报告另提交；短总规划保持B部分完成，下一包浏览器技能/重复迁移。

限制：本包不会在学生被整个worker硬杀后凭空恢复浏览器；整体timeout保持失败，教师只能接管仍存活会话里的步骤耗尽、调用错误或外部检查失败。不改checkbox观察表达，以免混淆接管与提示收益。技能生成仅允许dev成功教师轨迹，留出不用于本pilot。

工程验收：853 passed、1 skipped、1 xfailed；浏览器17项通过；独立审查两个P2均修复复审通过。真实三次pilot待运行；代码测试不计作模型成绩。
