# Kage 论文入口

当前版本：**v0.4，2026-10-27**（Astra/Codex 修订）与 **v0.4-deepseek，2026-10-27**（并行修订，供比较）。

- [当前论文源稿](draft.md)
- [当前 PDF](arxiv/paper.pdf)
- [v0.3 审稿意见](review-codex-2026-10-27.md)
- [v0.4 修改说明与 Claude 交接](v0.4-changes-and-handoff.md)
- [版本快照](versions/)
- [离线数据复算](v0.4-support/recompute.py)

## DeepSeek 并行修订（2026-10-27）

- [审稿意见](review-deepseek-2026-10-27.md)
- [修正稿源文件](deepseek-v0.4/draft.md)、[PDF](deepseek-v0.4/paper.pdf)
- [修改说明与 Claude 交接](deepseek-v0.4/README.md)
- [独立数值审计](deepseek-audit-2026-10-27.md)、[红队评审](deepseek-redteam-2026-10-27.md)、[文献核查](deepseek-litcheck-2026-10-27.md)
- [复算脚本](deepseek-support/)（`audit.py`、`stats.py`、`make_figures.py`）

编辑 draft.md 后运行 `bash docs/paper/arxiv/build.sh`。当前稿是基于既有数据的审查修订版；独立确认集、更多训练种子及其他待补实验并未因写作修订而完成。

## v0.5（2026-10-28，Claude 裁决稿）

- [源稿](v0.5/draft.md)、[PDF](v0.5/paper.pdf)、[逐项采纳说明](v0.5/README.md)
- [独立核对脚本](v0.5-support/verify.py)（精确题级检验）、[画图](v0.5-support/make_figures.py)
- 第二学生证据：`evidence/reports/g0-nemotron/`

## v0.6（2026-10-28，在 v0.5 上补材料）

- [源稿](v0.6/draft.md)、[PDF](v0.6/paper.pdf)、[新增内容说明](v0.6/README.md)：作者单位、系统结构图、讨论、相关工作补充、附录 B 真实例子、附录 C 复现。供作者重写正文时参考。
