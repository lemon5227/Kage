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

## 第一次使用的验收（C3，2026-10-18）

- 结果：按卡片完整实现 6 处改动 + 7 个测试，dsh 自报全量 1486 通过；Claude 在正常环境重跑全量通过（加修复后 1487）。约 25 分钟。
- 质量：结构清楚、风格贴近原代码、测试覆盖卡片要求的正反两面（不泄漏评分数据、字节上限、跨族不显示）；还主动修了卡片没写到的一处（`request_lessons` 改为只看 `--playbook`，避免新臂让文件技能提案顺带要经验）。
- 问题：①一个 bug 源自卡片不完整——提取经验时账本耗尽抛 `BudgetExhaustedError`，没有转成 `TeacherBudgetExhausted`，任务会崩溃反复重启（Claude 已修并加测试）；②总结里说临时 `ps` 垫片“在仓库外”，实际在仓库内 `.tmp-bin/`（结束时已删除）；③沙箱里 `ps` 不可用，它用垫片跑浏览器测试——这种情况下测试结果必须由 Claude 在正常环境重跑。
- 花费：token 估计约 $0.47（1166 万缓存命中 token，按缓存价 1/10 计）；第一次的包装器只在启动前查上限，单次运行可能超出——已改为运行中按估计花费超限即停，并在余额下降可见时按余额记账。
- 结论：好用，继续用。卡片要写清错误处理与预算异常的处理方式；验收时必须自己重跑测试、看 diff。
