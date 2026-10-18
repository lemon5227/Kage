# 用 DeepSeek Harness（dsh）做执行子代理

用户 2026-10-18 决定：之后的任务由 Claude 规划和验收，DeepSeek-V4.1-Flash（1017）通过 dsh 执行，以节省 Claude 的 token。

## 怎么跑

```bash
python scripts/dev/dsh_run.py --cwd <工作目录> --task-file <任务说明.md> --log-dir artifacts/dsh
```

- 模型：`deepseek-flash`（DeepSeek API `/models` 返回的名称为 DeepSeek-V4.1-Flash，即 1017 版）。
- 密钥：从 `~/.config/kage/teachers/deepseek.json` 读出，只放进这一次 dsh 子进程的环境变量；不打印、不写盘，事件日志里也会替换掉。dsh 自己会把密钥从它的 shell 工具环境里去掉（已核对日志与会话文件中都没有）。
- 权限：`DSH_PERMISSION_MODE=workspace-write`，只能写 `--cwd` 之下。子进程只拿到 PATH/HOME 等少数变量，不带 Claude 会话的环境。
- 记账：单独的执行账本 `~/.kage/dsh_ledger.jsonl`，**不进** Kage 老师账本；上限 US$2.00（用户定），到上限拒绝启动。缓存命中的 token 也按全价计，偏保守。
- 续接：验收不通过时用 `--session-id <上次的 session>` 把反馈发回同一会话。

## 分工

1. Claude：写任务说明（目标、要改的文件、约束、验收标准、要跑的测试），不写实现。
2. dsh：在 worktree 里实现并跑测试。
3. Claude：读 diff 和测试结果验收；不通过就写具体反馈，用同一 session 继续。
4. 提交、推送、工作日志仍由 Claude 做（提交不加 AI 署名）。

## 约束（写进每份任务说明）

- 不得读取或打印 `~/.config/kage/teachers/` 下的文件，不得调用云模型（实验的云调用只能走 `teacher_budget` 账本）。
- 不得启动 llama-server / 本地模型，不得 git commit / push，不得改 `codex` 目录。
- 公开仓库：不写入任何密钥或个人数据。
