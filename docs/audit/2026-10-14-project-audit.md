# Kage 项目审查报告（2026-10-14）

审查范围：仓库 HEAD `8dea7c4` 的全部文档（README、总规划、E/C 任务队列、执行交接、自演化技能提案及第 7 章评审）与 `core/`、`tests/`、`scripts/` 代码。
审查方式：通读规划文档；对照代码核实文档中声称"已修复/未修复"的问题；在 Linux 云端容器（Python 3.13）建立虚拟环境跑全量测试。
项目目标（用户确认）：**自进化、自演化、会主动交互的 Agent 系统**。

> 本报告只记录事实与结论。修复与后续工作见 [总任务规划](../plans/MASTER-TASK-PLAN.md)，每个任务的执行过程见 [任务日志](../task-logs/README.md)。

## 1. 结论摘要

| 级别 | 问题 | 处理 |
|---|---|---|
| P0 目标偏差 | "主动交互"是项目核心目标之一，但 E0–E7 / C0–C8 任务队列里**没有任何主动交互任务**；现有 `core/heartbeat.py` 生成的通知被 `_loop()` 直接丢弃，主动行为实际不工作 | T03 修复送达；新增 P 线任务 T04–T08 |
| P0 目标偏差 | 自演化只存在于离线实验脚本，**没有接入日常主链**：没有空闲/定时演化作业，晋级的技能也没有"采用到日常使用"的路径（文档自己承认 skill_call=0、候选未晋级） | 新增 S 线任务 T09–T13 |
| P0 安全 | 模型可在工具参数里自带 `"confirmed": true` 绕过危险操作确认（第 7 章评审 B2，仍未修复） | T02 修复 |
| P0 安全 | 确认回调抛异常时，执行器记录 warning 后**继续执行**危险操作（fail-open） | T02 修复 |
| P1 安全 | `proactive_agent` 工具的 `skill_name` 未校验，可路径穿越写文件（与已修复的 `skills_save_local` 同类问题，B7 遗漏） | T02 修复 |
| P1 安全 | 未注册工具的安全等级默认 `SAFE`（fail-open；目前执行前会先拒绝未知工具，风险较低） | T02 改为 `DANGEROUS` |
| P1 安全 | Agent 循环在失败后会**自动** `npx skills install` 远程技能，无用户同意（评审 B6） | 规划 T12 |
| P1 安全 | `skills_save_local` 的 `target_dir` 由模型决定，可写任意目录 | 规划 T13 |
| P1 环境 | `core/memory.py` 顶层 `from rank_bm25 import BM25Okapi`，但 `requirements.txt` 没有 `rank-bm25` → 新环境按 README 安装后服务无法启动 | T01 修复 |
| P2 环境 | 未声明 pytest 等开发依赖；README 让用户建 `.venv/` 但 `.gitignore` 没有忽略 `.venv/` | T01 修复 |
| P2 文档 | 交接文档依赖 `/Users/wenbo/...` 本机路径、本地 worktree 和不在 Git 中的 `artifacts/`；换机器/云端/便宜模型无法按文档执行 | 新规划写明环境要求，标出 macOS-only 任务 |
| P2 文档 | 规划分散在 7+ 份文件（roadmap.md、总规划、任务队列、执行交接、两份路线、技能提案+评审），且行文密度极高、术语缩写多，便宜模型难以执行 | 新建单一入口 `MASTER-TASK-PLAN.md`，旧文档保留为历史/详细规格 |
| P2 文档 | `roadmap.md` 停留在早期阶段（ChromaDB、LoRA 人设），末尾有残缺行 `**: 支持摄像头输入…` | T00 标注为历史文档并修正 |
| P2 文档 | `self-evolving-skill-architecture-proposal.md` 已被第 7 章评审判定"不应按当前形态实现"（主进程 import 自生成代码、文献错误归因），但文件头仍写"等待评审"，容易被当作待执行任务书 | T00 在文件头加"已被评审否决/仅供参考"说明 |
| P3 当前队列 | 当前"下一实现包"C1.2 macOS AX 只能在 macOS 真机上做；云端/Linux 执行者没有可领取的任务 | 新规划按环境分组，Linux 可做的任务可并行领取 |

## 2. 测试结果（Linux 容器，Python 3.13.16）

命令与环境见规划文档"测试环境"一节。

| 轮次 | 结果 | 说明 |
|---|---|---|
| 首次收集 | 收集错误 | 缺 `rank_bm25`（真实缺陷，requirements 未声明）；`tests/test_round14_audio.py` 需 `pyaudio`/`funasr`（macOS 音频依赖，Linux 跳过） |
| 补依赖后 | 111 failed | 几乎全部为 Playwright 浏览器版本与容器预装版本不一致（环境问题） |
| 对齐浏览器、建 `.venv-computer-use` 链接后 | **984 passed, 4 failed, 4 skipped, 1 xfailed** | 见下 |

剩余 4 个失败：

| 测试 | 判断 |
|---|---|
| `test_memory_round7_features.py::test_memory_merge` | 依赖嵌入模型（`sentence_transformers` 未安装且未声明）；回退的 BM25 合并使用绝对阈值 5，五条短句永远达不到 → 在无嵌入模型的环境下必然失败。T01 让该测试在无嵌入模型时跳过，回退算法的改进列入 T01 日志的后续项 |
| `test_browser_suite.py::test_browser_worker_hard_timeout_retains_checkpoint_and_stops_descendants` | 容器内孤儿进程不被 PID 1 回收（僵尸进程仍可 `kill(pid, 0)`），属环境差异；需在 macOS 上复核 |
| `test_browser_task_service.py::test_stop_running_worker_kills_descendants_and_preserves_stopped` | 同上（`DID NOT RAISE ProcessLookupError`） |
| `test_browser_demonstration_routes.py::test_restart_terminates_suspended_owner_before_replacement` | 同上（`old browser worker recovery is incomplete`） |

## 3. 已核实"已修复"的历史问题

- 评审 B7 `skills_save_local` 签名不匹配与路径穿越：已修复（`core/tools/skill_ops.py` 使用 `SKILL_NAME_RE` 校验）。
- Markdown 相对链接：全仓库 0 处失效。

## 4. 对任务书（E/C 队列、执行交接）本身的评价

**做得好的地方**：每个包都要求真实证据、原始分母、失败保留、预算上限，"实验完成≠能力提升"的区分很严格，负结果如实记录。这些原则在新规划中全部保留。

**主要问题**：

1. **只覆盖了"执行"和"离线演化"，漏掉了"主动交互"**，且"自演化"停留在实验脚本层，日常使用的 Kage 不会自己变好。
2. **执行门槛过高**：大量缩写（R2-local、B2.1c、C4.5-DOM…）、一句话里塞多个条件，便宜模型很难判断"具体改哪个文件、做到什么程度算完成"。
3. **环境耦合**：只有作者本机的 worktree/私有配置/原始 artifacts 能用；没有说明 Linux 下如何跑测试。
4. **安全债未进入队列**：第 7 章评审列出的 B2/B6 阻断级问题没有对应任务编号，被研究线优先级挤掉。

## 5. 不改动的内容

- 历史实验报告（`docs/experiments/*`）按其"历史结果不回写"原则保持原样。
- E/C 任务队列与执行交接保留为**研究线的详细规格**；新规划引用它们，不重复其内容。
