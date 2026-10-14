# W6 产出卡（W6-1 … W6-4）

- 档位：中（写作）　执行者：C；W6-4 录屏为 U

| ID | 做什么 | 怎么做 | 完成判定 |
|---|---|---|---|
| W6-1 相关工作 | `docs/report/related-work.md` | 按 6 类整理（技能库、经验记忆、harness/代码演化、自练课程、主动交互、蒸馏），每篇 2–3 句：做了什么、和 Kage 的区别；链接用 arXiv 页面。起点是 [实现方案](../self-evolving-proactive-agent-2026-10-14.md) 与本会话 10-14 调研的论文清单 | 每篇都有可点击链接，引用的数字和原文一致 |
| W6-2 技术报告 | `docs/report/kage-tech-report.md` | 结构：摘要 / 动机 / 系统（三环 + 交互层图）/ 基准 / 实验设置 / 结果（曲线、对照表，**数字只从 stream_report 的 summary.json 复制**）/ 负结果 / 成本 / 局限 / 相关工作 | 每个数字都能在 summary.json 里找到 |
| W6-3 README | `readme.md`、`README.zh-CN.md` | 把「Current experimental foundation」一节换成成长曲线图与对照表；删掉过时的测试数量 | 中英文一致 |
| W6-4 演示 | `docs/report/demo-script.md` + 录屏 | 写 6 个镜头的操作步骤与台词（说不会 → 求教 → 学会 → 夜间自练汇报 → 新题复用 → 负例不误用），U 按脚本录 | 视频 ≤ 3 分钟，每个镜头对应真实运行结果 |
