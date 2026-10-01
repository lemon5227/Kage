# C2.1-A 浏览器任务与硬预算实施包

沿用用户已批准的通用电脑任务/独立评分与DOM优先路线；本包先完成任务环境和真实基线，C2.1-B另接同页教师与浏览器技能，C2.1整体保持部分完成。

设计：BrowserChainProvider复用KageChainProvider的计量、工具结果归一化与PromptBuilder/AgenticLoop；在E0 fork worker内部创建Playwright/context/HTTP环境，不跨线程或进程传Page。只有browser工具，无写评分文件入口。可信协调器把实际后端记录、读回与提交次数写browser-check.json，原Evaluator的json_exact_match在父进程验收；超时也保留已落盘证据，runner.status仍明确timeout，不变成passed。

四族：多字段资料保存；表格金额计算并提交；目录过滤后选最低价条目；偏好勾选/取消并保存。各有dev和holdout内容/标签/布局变体，共8项；冻结后再推理，holdout不给技能生成器。每次全新服务器/context/setup；服务端持久化真实POST事件。后台记录、页面最终展示与提交次数共同验收，不用finish或tool success评分。

预算：每项最多6模型调用/5循环步，runner1步、180秒runner monotonic截止（本机不计系统睡眠）；HTTP每调用120秒，保留全部失败。首基线每实例1次，属于起步覆盖，不是C4.4三重复消融。cloud=0。后续闭环必须增加重复对照，不依据单次分数证明学习收益。

- [x] 实现前写真实环境/评分/超时行为回归；看到缺失模块或能力失败。
- [x] 独立HTTP fixture支持四族，冻结eval/computer-use/browser-v1.json；expected只存在独立checker侧，不注入goal。
- [x] core/computer_use/experiment.py创建真实会话、紧凑观察和初始观察直供，使用原ToolExecutor。每次工具后更新独立check，以免硬杀丢失已经产生的真实副作用证据。
- [x] 复用EvolutionRunner进程组硬截止、Journal/BudgetTracker；测试真实子进程浏览器超时后停止、workspace checkpoint保留。
- [x] scripts/experiments/browser_suite.py冻结源码/任务/模型配置与hash；逐项运行8项，失败进入分母，无重跑筛选。
- [x] 全量/独立审查、报告和独立提交；更新短总规划/队列，只标C2.1-A完成。

本包不默认连接用户登录浏览器，不加入截图定位、Jev、AX或新引擎。底座支持观察/填值/点击/滚动/等待；当前任务无需iframe、select或多标签。若真实浏览器依赖缺失或macOS fork失败，保留明确crashed/日志并修复环境问题，不把跳过写成通过。

实施检查点：全量848 passed、1 skipped、1 xfailed；独立审查的陈旧评分问题已修复并复审通过。真实八项v1受休眠干扰全部保留；v2控制闲置休眠后6/8通过、2/8失败，无超时。不把环境测试记作AI成绩；详见[报告](../experiments/2026-10-01-c21-browser-suite.md)。C2.1-B仍待实施。
