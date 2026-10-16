# 任务卡执行规程（所有模型通用）

每个任务一张卡：`docs/plans/cards/<任务ID>.md`。卡片写到**不需要理解全局也能照做**的程度，便宜模型可以直接执行标着「档位：低」的卡。总目标和里程碑见 [任务书](../tasks-2026-10-14.md)。

## 1. 开工前（每次都做，约 2 分钟）

1. 读本文件和要做的那张卡，**只读卡里「先读」列出的文件**，不要通读仓库。
2. 看最近进展：`tail -n 60 docs/worklog/2026-10-claude.md`。
3. 检查工作区：`git status --short`。卡片要改的文件如果已有别人未提交的改动，先停下，在日志里写明，不要覆盖。
4. 确认依赖卡已是 ✅（任务书 §3 的「依赖」列）。依赖没完成就不要开工。

## 2. 环境

| 在哪执行 | Python | 能做什么 |
|---|---|---|
| Claude / 其他模型的 Linux 沙箱 | `~/kvenv/bin/python`（只装了 pytest、jsonschema、pyflakes）；没有就 `python3 -m venv ~/kvenv && ~/kvenv/bin/pip install pytest jsonschema pyflakes` | 写代码、跑单元测试 |
| 用户的 Mac（或直接跑在 macOS 上的 Codex） | `PY=/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/.venv-computer-use/bin/python` | 真实模型（llama-server）、Docker、全量测试、git push |

测试命令（沙箱）：`~/kvenv/bin/python -m pytest -q -p no:cacheprovider <测试文件>`
测试命令（Mac）：`$PY -m pytest -q <测试文件>`
静态检查：`~/kvenv/bin/python -m pyflakes <改过的 .py 文件>`，必须没有输出。

## 3. 做事规则

- **只改卡片「产出」列出的文件**。需要改别的文件，先在日志里写理由，并且改动尽量小。
- **先写测试再写实现**：卡片「测试」一节列出的用例都要有。
- 绝对不要：修改评分器（`core/evolution/runner.py` 的 `Evaluator`、`completion.py`）；改已冻结的 `eval/stream_v1/*.json`；把隐藏用例或 `scoring_criteria` 传给学生或教师；打印或写入任何密钥；绕过 `core/evolution/teacher_budget.py` 调用云模型；`git push --force`。
- 需要真实模型、Docker 或推送的步骤，标着「执行者 U」，由用户在 Mac 上做，不要尝试模拟。
- 卡住超过 30 分钟，或者发现卡片本身有错：停下，在日志里写「阻塞：…」并把任务书状态改成 🟡，等人处理。不要自行扩大范围。

## 4. 收尾（每张卡都做）

1. 跑卡片要求的测试，全部通过；跑 pyflakes 无输出。
2. 在 `docs/worklog/2026-10-claude.md` 末尾**追加**一条（不改写旧内容）：

   ```
   ### <任务ID> <任务名>（<日期>，执行模型：<模型名>）
   - 做了什么：…
   - 改动文件：…
   - 验证：<测试命令> → <N passed>
   - 问题/决定：…
   ```
3. 把任务书 §3 对应行的状态改成 ✅（只改这一格）。
4. 日常提交推送到 `dev`；阶段完成且用户同意后快进合并到 `main`（2026-10-16 起只保留这两个分支）。

## 5. 档位

- **低**：规格完全写死，照做即可（生成器、脚本参数、文档）。
- **中**：需要读懂一两个现有模块再接线（新对照组、报告脚本）。
- **高**：涉及设计判断或安全边界（架构师、版本树、交互层）。建议用强模型，或由强模型先审卡再执行。
