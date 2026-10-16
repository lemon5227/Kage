# Kage — Claude Code 入口

@AGENTS.md

## 本地 Claude Code 补充说明
- 你直接运行在 macOS 上：可以启动 llama-server、使用 Docker、执行 `git push`。Python 用 `/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/.venv-computer-use/bin/python`。
- 开工顺序：`roadmap.md` → `docs/plans/tasks-2026-10-14.md` → `docs/plans/cards/README.md` → 要做的那张卡；先 `tail -n 80 docs/worklog/2026-10-claude.md` 看最近进展。
- 每完成一步都追加到 `docs/worklog/2026-10-claude.md`（模板见 cards/README.md §4），并更新任务书状态。
- 分支只有两个（2026-10-16 用户决定）：日常开发提交并推送到 `dev`；阶段完成、用户同意后再快进合并到 `main`。不要 `push --force`，不新建长期分支。
- 实验原始证据和报告进仓库 `evidence/`（见 `evidence/README.md`）；Kaggle 运行先读 `docs/development/kaggle-runbook.md`。
- 云模型调用只能走 `core/evolution/teacher_budget.py` 的 $1 全局账本；不得打印密钥。
