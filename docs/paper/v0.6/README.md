# v0.6：在 v0.5 上补齐的材料（2026-10-28）

v0.5（已核对的裁决稿）保持不变；本目录是在其上补写的版本，供作者用自己的话重写正文时参考。正文数字与 v0.5 相同，全部来自 `../v0.5-support/verify.json`。

## 新增

| 内容 | 位置 | 依据 |
|---|---|---|
| 作者单位与邮箱 | 标题区 | EURECOM；邮箱用的是 gmail，投稿前可换成学校邮箱 |
| 系统结构图（图 2） | §2 开头 | `../v0.6-support/make_figures.py` 生成 `figures/fig0_system.pdf` |
| 讨论一节（§8） | 结果之后、相关工作之前 | 四段：小模型为何更依赖接口；规则需要能力下限（第二学生）；改权重必须测保留；老师特权反馈会进入学生规则 |
| 相关工作 | §9 | 新增 OSWorld（Xie et al., NeurIPS 2024, arXiv:2404.07972）、WebArena（Zhou et al., ICLR 2024, arXiv:2307.13854）、Lost in the Middle（Liu et al., TACL, arXiv:2307.03172），均已在线核对题名与编号；作者只写第一作者 + et al. 的两条是因为未核对全部作者 |
| 附录 B 真实例子 | 附录 | B.1 V1/V2 同一复选框（v28，web_prefs-11000）：未勾选时 V1 只少了 `checked` 键，而 `value` 仍是 `"on"`；B.2 TextEdit 工具定义与两条真实失败（a0-test-v2）；B.3 四条规则原文与三种放置方式的提示词原文（`core/computer_use/desktop_agent.py`） |
| 附录 C 复现 | 附录 | 各表/图/实验的命令；不可复现部分（适配器、私有日志、账本） |
| AI 辅助声明 | §10 | 改为“代码、数据分析、图和一致性检查用了 AI 辅助”。**作者用自己的话重写正文后，应确认此声明与实际情况一致** |

## 新发现（写进讨论 §8 与附录 B.3）

老师写给学生的第 3 条 TextEdit 规则原文含“since the checker requires each line to be newline-terminated”：老师看到的检查器信息经由规则进入了学生提示。规则不含测试答案，但说明“学生可见 / 老师可见”的边界要检查生成的规则本身。

## 构建

`./build.sh` → `paper.pdf`（13 页，4 图 7 表，无缺字，最大溢出 0.8pt）。未 commit/push。
