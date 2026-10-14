# W5 实验运行卡（W5-1 … W5-4）

- 档位：低　执行者：U 运行，C 分析　依赖：见各实验

通用步骤（每个实验都一样）：
1. `cd /Users/wenbo/Kage && PY=/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/.venv-computer-use/bin/python`
2. 先 `--plan-only`，把 config.json 里的清单 sha256 记进日志。
3. 正式运行。中途中断可以直接重跑同一命令续跑（已完成的任务与检查点会跳过）。
4. 跑完把账本余额记进日志：`$PY -c "from core.evolution.teacher_budget import *;print(remaining_usd(global_teacher_budget()))"`
5. 告诉 C，C 运行 `stream_report.py` 并写结论。

| 实验 | 依赖 | 命令（每臂一条） | 云费上限 |
|---|---|---|---|
| W5-1 E-0 切片 | W2-1 ✅ | `$PY scripts/experiments/stream_run.py --arm {A0,A4,A5} --root artifacts/stream-slice/{arm}` | $0.10 |
| W5-2 标定 | W1-8 | `$PY scripts/experiments/stream_calibrate.py --root artifacts/stream-calibration` | $0 |
| W5-3 E-1 | W1-9、W1-10、W2-3、W2-4 | `$PY scripts/experiments/stream_run.py --arm {A0,A1,A3,A4} --root artifacts/e1/seed{1,2}/{arm} --stream-manifest eval/stream_v1/stream-seed{1,2}.json --eval-manifest eval/stream_v1/eval.json --checkpoints 0,30,60 --teacher-cache artifacts/e1/teacher-cache` | $0.40 |
| W5-4 E-2 | W4-5、W3-2 | 同上，`--arm {A5,A6,A6-fixed}`，root 改 `artifacts/e2/...`，教师缓存复用 `artifacts/e1/teacher-cache` | $0.35 |

建议顺序：先跑不花钱的 A0/A1，再跑 A3/A4（它们共享教师缓存，第二个臂几乎不再花钱）。机器整晚跑时关掉睡眠：`caffeinate -dims $PY ...`。
