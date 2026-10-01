# C2.1-B2.0b 教师DOM历史打包

已批准队列中的独立包，沿用活动worktree。目标：避免重复完整DOM使教师保存前触及12000字节上限，不增加预算，不修改目标或本地学生。

方案选择：不增加上限；不调用摘要模型。采用确定性投影：最新完整DOM保留，较旧DOM落档并换为不可变hash引用，目标/原生调用ID/动作/错误/非DOM结果不改。原始完整messages按hash持久化；引用不是可执行target_ref，也不向模型伪造置信度。当前浏览器协议操作当前页面，旧DOM不能操作；需要重新观察时用browser_observe。大最新DOM仍由既有完整wire预检拒绝，本包不保证任意长任务。

默认teacher_context_pack=False；仅teacher开启，默认学生和历史成绩不变。metadata/cache/config记录开关和实现hash。包装器在CompletionGate内、MeteredProvider前处理请求；每次保存原始输入与投影统计，实际provider日志记录投影后的真正输入。

- [ ] 写真实浏览器回归：学生失败，教师动作经过真实wire长度预检，原协议超限失败，新协议正确保存；错误和调用关联保留、输入不变、最新观察完整、无新观察不裁剪。
- [ ] 新建core/computer_use/context_pack.py，纯消息投影和模型包装；BrowserChainProvider提供actor model hook，teacher_takeover仅在显式开关包装教师；脚本增加开关与源码hash。
- [ ] 聚焦测试、独立审查、全量回归、单独代码提交。
- [ ] 冻结3次dev真实pilot，沿用B2.0同任务/学生/教师/上限，仅新增teacher_context_pack；每次完整保留，教师未触发时明确未验证新增真实教师效果。
- [ ] 报告记录问题/失败/费用/源码/测试/限制，短队列与总规划更新；独立报告提交并快进main。

本包不生成技能、不训练权重、不比较学习收益。后续B2.1/2.2全部方法须采用同一打包协议。
