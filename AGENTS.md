# Kage：模型开工入口

开始项目工作前，完整阅读根目录 [roadmap.md](roadmap.md)。该文件自包含总目标、当前阶段、下一任务、验收、预算、停止条件与证据位置。

- 用户最新要求优先；当前路线及任务领取以 roadmap.md 为准。
- 旧 E/C 队列、旧交接和实验报告仅作状态/接口/证据附件；历史“下一步”不自动成为当前任务。
- 当前主线是自学习、自演化 Agent；按 roadmap 的验收阶段推进，不能以工程测试数代替成长证据。
- 开工先检查本 checkout 与活动 worktree 的 HEAD 和未提交修改；保留其他模型工作及被 Git 忽略的原始实验。
- 阶段完成后，用证据更新 roadmap 的当前状态与下一项；没有验收证据不标完成。
- 教师配置先读 [私有配置约定](docs/development/teacher-credentials.md)：DeepSeek规范路径`~/.config/kage/teachers/deepseek.json`，无需在worktree复制key。已有授权/预算持续有效，不重复索要同一key或额度；不得输出密钥。
