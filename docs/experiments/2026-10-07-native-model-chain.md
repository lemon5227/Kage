# C1.2 原生模型链与两项冻结受控实验

实验日期：2026-10-07；最终回归与收尾更新：2026-10-08。父版本 `56eed1e`；工程 `58e6446`，独立审查修正 `abd0acd`。本轮接通真实本地模型与 macOS AX 执行链，完成两项单次开发实验，**独立通过 0/2；两项完整检查均为 unknown，原生任务能力尚未验收**。本报告不替代此前确定性 TextEdit 驱动通过记录。

## 实现与审查

`core/computer_use/native_model.py` 的 `NativeChainProvider` 复用现有 AgenticLoop / PromptBuilder / ModelBroker / ToolExecutor，以及 EvolutionRunner / Journal / BudgetTracker。使用 inline 执行，避免 Objective-C 的 fork 风险；记录真实请求与工具调用，沿用内核预算和完成检查入口，没有第二套实验内核。

专用任务只注册 `native_windows` / `native_observe` / `native_act`。窗口引用、标题及解析后的 AXDocument 文件 URL 必须与工作区专用文档一致；识别结果先过滤，再进入模型上下文。observe / act 的成功、失效及不确定结果都重新检查文档身份，越界的新观察不传给模型，保持真实 action_applied 归因。工作区路径使用既有 confinement helper，先校验专用初始 fixture，再打开应用；拒绝绝对路径、逃逸路径及外部 symlink。没有模型可调用的文件写入、全局按键或任意应用入口。

模型负责编辑和应用内 Save；可信环境负责初始文件 / 打开、独立磁盘检查、关闭重开与 AX 读回、最后清理，各自 actor 分开记录。不能靠 TextEdit 自动保存得分：必须有模型成功调用已观察 Save 的证据，后续成功或不确定 fill 会撤销旧证据。关闭 / 检查失败保持 unknown，不执行丢弃未保存内容等补救操作。

审查修复四项：新观察的文档范围、provider 文档路径逃逸、后续编辑后的旧 Save 证据、与共享 runner 对齐停止原因 / 计数字段。修复均有失败后通过的回归，独立复审接受；最终聚焦 **44 passed in 0.23s**。原生驱动 / 同步模型请求仍可能超过合作式期限，不声称严格墙钟限额。之前确定性 pilot 的 P3 完成轮询分类小问题仍记录在原报告，本轮未修改该脚本。

## 冻结协议与实际执行

命令：

```sh
.venv-computer-use/bin/python -m scripts.experiments.native_model_pilot --output-dir artifacts/native-model/controlled2
```

CLI 拒绝已有实验目录；在首请求之前写定源码 / 提示 / 两项任务 / 协议、权重及服务二进制 hash、实际命令和进程身份。每项一次、最多8循环步 / 10请求 / 16原语尝试 / 480秒合作式期限；总请求最多20，temperature=0，实际单请求 max_tokens=300，零云。名义预留2,000,000输入与6,000输出 token；实际 usage 单列，不声称严格逐请求 token 配平。运行后未追加样本或重跑救分。

本地执行者 Agents-A1-4B Q4_K_M，权重 SHA256 `d93c393a9bd5139a4b5cfe24d31ef553c5a497bfb8afec178a354ecbf508f062`。服务使用8192上下文、单slot、Metal offload、q8_0 K/V、reasoning off，实际参数和模型 / 服务二进制 hash 在 freeze.json。`llama-server --version` 本次3秒超时，已记录该状态；没有凭历史报告填写当前版本字符串。所有请求通过本次拥有的本地 llama 服务，无云或混合后端。

| 任务 | 内核结果 / 停止 | 独立完整检查 | 请求 / 原语尝试 | 输入 / 输出token | run墙钟 |
|---|---|---|---|---|---|
| native_status | failed，score0，step_limit | unknown；磁盘文本不完全匹配，AX重开读回不可用 | 8 / 2 | 32,432 / 792 | 119.775秒 |
| native_agenda | failed，score0，step_limit | unknown；磁盘文本不完全匹配，AX重开读回不可用 | 8 / 2 | 30,177 / 921 | 139.716秒 |

合计 **16本地请求、62,609输入 / 1,713输出token、259.491秒 run墙钟、$0云费**。每项8工具调用，包括观察 / 识别；2原语尝试分别是成功 fill 与被失效观察拒绝的菜单 press，均无有效 Save。预算已结算，无活动预留。run墙钟不含服务启动与权重加载。

两项 fill 使用真实换行，磁盘结果与目标仅差末尾一个换行，不能写成字面量反斜杠n错误。随后在准备按文档菜单前，驱动发现原窗口已不在 AXWindows 中；之后识别窗口数量为0，旧引用拒绝且未应用菜单动作。轨迹没有 Agent Close 或 Save 调用。窗口为何消失尚无根因证据，不能归因于模型、驱动、用户或系统行为。两个同模式结果不足以证明是哪一层导致。

内核 failed/score0 表示未取得外部通过；独立 completion.json 的 unknown 表示关闭重开 / AX验证无法完成，两者分别报告。末尾换行差异是已确认的文本不匹配，不能仅凭 unknown 掩盖；也不能把磁盘已有文本当应用 Save 验收。模型自述完成不参与评分。

## 证据与验证

唯一完整目录：`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/native-model/controlled2/`。含 freeze.json、results.json、budget-final.json、journal.sqlite、服务日志 / 清理、每项原始模型请求 / 响应与 usage、AX轨迹、独立 / Agent工具、chain / completion、实际专用文件。

`recompute-audit.py` 不调用模型或桌面，只复算源码hash、调用与usage、请求参数 / 上限、Save证据、unknown与停止原因、末尾换行差异、磁盘hash、预算结算及服务清理。**21/21检查通过**，audit.json 保留。21项是证据一致性，不是21项任务通过。

早期 `controlled1` 启动阶段被无上限版本探针阻塞，人工停止后自有服务已退出；只有 server.log / service-cleanup.json，无freeze、任务或模型调用，未混入两项分母。修正后版本探针有3秒上限，超时仍如实记录。本次自有服务已停止；没有终止既有服务或其他应用。两项窗口已无法观察，检查流程不继续操作其他窗口。

首轮本包全量：**1 failed、1035 passed、4 skipped、1 xfailed、298.75秒**，完整原始输出final-pytest.txt保留。失败来自既有线程并发测试的170ms墙钟断言，本次194ms；运行时仍使用asyncio.to_thread。测试修正55c39ce改为两个真实处理器必须同时到达Barrier，5秒仅为错误实现的等待上限，不放宽性能成绩。串行分发mutation明确导致测试失败，thread-overlap-mutation-red.txt保留；正常聚焦66 passed in1.57s。测试代码单独提交，原生执行源码/协议保持abd0acd，原始模型成绩不改。

第二轮全量：**1 failed、1035 passed、4 skipped、1 xfailed、407.74秒**，final-pytest-after-thread-test.txt保留。失败是既有browser重启用例在已拒绝candidate后立即断言旧PID不存在；定向原用例1 passed in6.24s，异步父进程回收时序是候选解释，未据单次重跑断言运行时缺陷已排除。测试修正27be3a3增加最多2秒条件轮询后保留相同PID不存在断言，不自行为worker发信号、不放宽candidate/ownership要求；独立审查接受，四项相关重启/所有权用例4 passed in11.22s。运行时代码仍不变。

最终全量在27be3a3冻结后完成：**1036 passed、4 skipped、1 xfailed、1既有warning，433.75秒，exit0**。完整原始输出final-pytest-after-reap-wait.txt；此前两次失败均保留。新增warning并未出现，唯一warning为既有pygame/pkg_resources弃用提示。

## 当前边界与下一项

工程模型入口和真实调用已验，原生模型编辑 / Save / 关闭重开闭环未通过，不推进为完整C1.2验收。AX已覆盖本次文本、文档菜单与保存目标，失败不是已证实的“无目标”；OCR provider / 候选仍未实现，不据本次失败自动启动视觉模型。

下一项 C1.2-R：先在独立dev探针记录窗口生命周期（必要时绑定AX通知）、确认没有模型时的稳定性，再分别诊断末尾换行精确值与菜单 / 保存步骤。预先写定每项有限次数与来源，不复用controlled2为新盲测，不把程序代填、重开或保存算模型完成。之后再另冻模型验收；C4.5-AX / 跨应用继续待条件满足。
