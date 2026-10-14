# T00 项目审查 + 总任务规划 + 日志体系

- 日期：2026-10-14
- 执行者：AI 助手（由 wenbo 领取）
- 父提交：`8dea7c4`
- 环境：Linux 云端容器，Python 3.13.16
- 状态：完成

## 目标

检查项目文档与代码，修正规划中的问题；写出面向"自进化、自演化、主动交互 Agent"的总任务规划，每个任务写清实施步骤（便宜模型可执行），并建立任务日志制度。

## 计划

1. 通读 README、总规划、E/C 任务队列、执行交接、自演化技能提案及评审。
2. 对照代码核实评审中列出的缺陷是否仍存在。
3. 在 Linux 建环境跑全量测试，区分真实缺陷与环境问题。
4. 写审查报告、总任务规划、日志模板；给过期文档加说明。

## 过程记录

| # | 做了什么 | 改动文件 | 怎么验证 |
|---|---|---|---|
| 1 | 通读规划文档；发现 E/C 队列无"主动交互"任务，自演化未接入日常主链 | — | 全文检索"主动/proactive"，仅出现在历史日志 |
| 2 | 核实评审 B7（`skills_save_local`）已修复；B2（`confirmed` 自签确认）、B6（自动安装远程技能）仍存在；新发现确认回调异常时 fail-open、`proactive_agent` 路径穿越 | — | 阅读 `core/tool_executor.py` 约 615–660 行、`core/tools/agent_ops.py`、`core/agentic_loop.py` 约 430–460 行 |
| 3 | 发现 `core/heartbeat.py::_loop()` 丢弃 `tick()` 返回的通知，`get_queued_notifications()` 无调用者 → 主动通知从未送达 | — | `grep -rn get_queued_notifications core` 只有定义 |
| 4 | 建 venv 跑测试：首次因缺 `rank_bm25` 收集失败（requirements 未声明）；补齐后 111 失败（Playwright 浏览器版本不匹配）；对齐浏览器并建 `.venv-computer-use` 链接后 984 passed / 4 failed | — | 见下方"验证结果" |
| 5 | 分析剩余 4 个失败：1 个依赖嵌入模型，3 个为容器不回收孤儿进程 | — | 阅读失败栈与 `core/memory.py::merge_similar_facts` |
| 6 | Markdown 相对链接检查：0 失效 | — | Python 脚本扫描所有 `*.md` 的 `](相对路径)` |
| 7 | 写审查报告 | `docs/audit/2026-10-14-project-audit.md` | — |
| 8 | 写总任务规划 T00–T24（新增主动交互 P 线、自演化接入主链、安全修复；研究线引用原 E/C 规格） | `docs/plans/MASTER-TASK-PLAN.md` | 规划中引用的文件/函数逐一 `grep` 确认存在 |
| 9 | 建日志制度 | `docs/task-logs/README.md`、`TEMPLATE.md`、本文件 | — |
| 10 | 过期文档加说明：`roadmap.md`（并删除末尾残缺行）、自演化技能提案（标"已被评审否决"）、总规划/任务队列/执行交接（指向新入口）；README 中英文路线链接加入新入口 | `roadmap.md`、`docs/self-evolving-skill-architecture-proposal.md`、`docs/agent-memory-evolution-master-plan-2026-09-29.md`、`docs/plans/task-queue-2026-10-01.md`、`docs/plans/execution-handoff-2026-10-03.md`、`readme.md`、`README.zh-CN.md` | 链接检查 0 失效 |

## 验证结果

```
python -m pytest -q -p no:cacheprovider --ignore=tests/test_round14_audio.py --timeout=90
（PLAYWRIGHT_BROWSERS_PATH 指向与 playwright 1.63.0 匹配的 headless shell；.venv-computer-use -> venv）
4 failed, 984 passed, 4 skipped, 1 xfailed, 8 subtests passed in 245.27s
```

失败项：`test_memory_merge`（无嵌入模型）与 3 个进程回收测试（容器环境），详见审查报告 §2。

本任务只改文档，未改代码。

## 偏离计划

无。

## 遗留与后续

- 修复类问题已拆为 T01（依赖）、T02（确认闸门/路径穿越）、T03（Heartbeat 送达）、T12/T13（远程安装与写入目录）。
- 测试会写入真实的 `~/.kage/`（发现 `browser-demonstrations/`、`tool_log.jsonl` 出现在家目录），建议后续在 `tests/conftest.py` 中把 HOME 或 Kage 工作目录重定向到临时目录（可并入 T22 或单独立项）。
