# v0.8（2026-10-31）：R3 训练 seed 复现

在 v0.7 基础上，回应“只有一个训练 seed”：
- §6.2 新增“Training seeds”段与表 9：同数据同超参重训 seed 1、2（T4 fp16），学过的文件题 63/72、58/72，留出族 0/36、2/36，与 seed 0（64/72、1/36）无可检出差别；同会话锚点与原 v26 原模型总数一致。
- 摘要、§1、C3、表 1、§3（训练描述）、§6.3、§10（局限：seed 与精度未分开、校验和缺 v41）、§11、附录 A/C 同步；图 0 文字。
- 构建：`./build.sh` → 16 页；图 `../v0.8-support/make_figures.py`；统计 `evidence/reports/r3t-seeds/analyze.py`。Overleaf：`../overleaf/make_overleaf.py v0.8`。
