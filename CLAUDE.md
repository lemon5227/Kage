# Kage — Claude Code 入口

@AGENTS.md

## 本地 Claude Code 补充说明
- 你直接运行在 macOS 上：可以启动 llama-server、使用 Docker、执行 `git push`。Python 用 `/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/.venv-computer-use/bin/python`。
- 开工顺序：`roadmap.md` → `docs/plans/tasks-2026-10-14.md` → `docs/plans/cards/README.md` → 要做的那张卡；先 `tail -n 80 docs/worklog/2026-10-claude.md` 看最近进展。
- 每完成一步都追加到 `docs/worklog/2026-10-claude.md`（模板见 cards/README.md §4），并更新任务书状态。
- main 暂不提交；需要保存进度时建 `claude/<任务ID>` 分支提交并推送。不要 `push --force`，不要推 main，除非用户明确要求。
- 云模型调用只能走 `core/evolution/teacher_budget.py` 的 $1 全局账本；不得打印密钥。
