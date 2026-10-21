# 实验原始证据

仓库是公开的；入库前扫描过全部文件（含压缩包内 27226 个文件）：无 DeepSeek / Kaggle 密钥，也无 `sk-`、`ghp_`、`hf_`、`KGAT_` 形式的令牌。
校验：`cd evidence && shasum -a 256 -c SHA256SUMS`。

换设备恢复：克隆仓库后按需解包到被 Git 忽略的 `artifacts/`，例如
`mkdir -p artifacts/kaggle-out/v9 && tar -xzf evidence/kaggle/v9-results.tar.gz -C artifacts/kaggle-out/v9`。
报告可重算：`python scripts/experiments/stream_report.py --arm-dir A=<解包目录>/seed1/A ... --out <目录>`。

| 文件 | 内容 | 对应工作日志 |
|---|---|---|
| `2026-10-14-g1-g2-and-earlier.tar.gz` | G1 恢复晋级、G2 基线、C4 等 10-14 之前的原始实验（原 `evidence/2026-10-14` 分支，sha256 未变） | W0-3 |
| `2026-10-14-e0-stream-slice.tar.gz` | E-0 切片（Mac）：A0/A4/A5-e0、W2-5 复跑 | W5-1、W2-5 |
| `2026-10-14-student-screening.tar.gz` | 本地学生模型 / 推理引擎筛选 | `docs/experiments/2026-10-14-student-model-screening.md` |
| `2026-10-15-calibration-mac.tar.gz` | 难度标定（A0，每族 10 题） | W5-2 |
| `kaggle/v1…v4-notebook.log` | Kaggle 早期失败运行的日志（编译失败、读不到 Secret 等，见 `docs/development/kaggle-runbook.md`） | E-1 迁到 Kaggle |
| `kaggle/v5-results.tar.gz` | E-1 第 5 版（大部分作废：服务被杀、预算耗尽被缓存；仅 A1 可用） | E-1 第 5 版作废原因 |
| `kaggle/v6-results.tar.gz` | E-1 第 6 版：A0、A4×2 | E-1 第 6 版结果 |
| `kaggle/v7-results.tar.gz` | E-1 第 7 版：A3×2 重跑 | E-1 完成 |
| `kaggle/v8-results.tar.gz` | E-1b：A4r×2 | E-1b 结果 |
| `kaggle/v9-results.tar.gz` | E-1c：A4g/A4m×2 | E-1c 结果 |
| `kaggle/v10-results.tar.gz` | E-2：A4mG/A5/A6/A6-fixed×2（代码 ca1e322） | E-2 结果 |
| `kaggle/v11-results.tar.gz` | E-2b：A6×2 重跑（架构师修复后）+ 同环境 A0 只评测×3（代码 9003cc5） | E-2b 结果 |
| `kaggle/v13…v16-c-cal-summary.json` | C 浏览器族难度校准（原学生 A0，每族 12 题）四轮摘要 | C 校准 v13–v16 |
| `kaggle/v17-results.tar.gz` | C2 浏览器学习实验：A0×3、A1、A3/A4mG×2 流（stream-web-v1，代码 7a2faaf；去掉了截图与归档的旧页面快照） | C2 结果 |
| `kaggle/v19-results.tar.gz` | C3 老师规则：A4mGL/AGL/A4mG × 2 流 + A0-r4（stream-web-v1，代码 8f496d8；去掉截图与旧页面快照） | C3 结果 |
| `kaggle/v20-results.tar.gz` | R2 冒烟：带指导重新做题（文件=示范，浏览器=示范+规则），8 种子 × 2 次（代码 e21d0a2） | R2 冒烟 |
| `reports/r2-smoke/` | v20 的 build 产物（Kaggle 上 build 因路径 bug 未运行，离线重建）：各组 stats.json 与 366 条训练样本 | R2 冒烟 |
| `reports/*` | 由 `stream_report.py` 生成的 report.md / summary.json / curves.png；技术报告里的数字只从这些 summary.json 取 | — |

每个结果包内：每臂一个目录（config.json 冻结配置、stream.jsonl、checkpoints.jsonl、competence.json、library.json、模型轨迹、技能提案），共享的 teacher-cache，以及 `kaggle-status.jsonl`（任务启动/重启/内存记录）。
新的运行结果按同样方式追加：结果包放 `kaggle/vN-results.tar.gz`，报告放 `reports/<实验名>/`，再更新 SHA256SUMS 与本表。
