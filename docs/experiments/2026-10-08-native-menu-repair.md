# Native menu repair — bounded diagnosis, 2026-10-08

The two new raw AX probes reproduced the missing Save target and distinguish the failure from a driver projection bug. The document-specific Save (`S`, modifiers `0`) and Close (`W`, modifiers `0`) AX menu nodes existed and advertised `AXPress`, but both reported `AXEnabled=false`. TextEdit was inactive although the exact owned document remained its main window. A scoped File-menu press did not activate TextEdit or enable these commands. Read-only waits of 0.5 and 2 seconds did not change them.

In the second fresh document, one explicit activation request to the observed TextEdit instance returned accepted, but TextEdit remained inactive through ten bounded main-run-loop checks. The same different application remained frontmost. Acceptance of a macOS activation request therefore did not establish activation. These probes establish a disabled-menu state co-occurring with an inactive app; they do not yet establish why activation failed, or prove activation alone would enable Save.

## Evidence and limits

Base/source commit: `5648c880a6eaf325bdda40a9869d687e03816bdc`; worktree branch `codex/c2-learning-loop`. Exactly two fresh dedicated documents were opened, each filled once and its observed document menu pressed once. No Save, Close, global key, application quit, model request, or cloud call was issued. Neither old controlled2 nor lifecycle documents/artifacts were changed.

Local retained evidence: `artifacts/native-menu/2026-10-08-diagnosis1` and `2026-10-08-diagnosis2`, each containing `raw.jsonl`, `menu-result.json`, `provenance.json`, `probe-source.py`, and the dedicated text file. The second additionally contains `activation.json`. The raw records include frontmost bundle/PID, owned PID, `isActive`, CFEqual main-window identity, command/modifier/enabled/action metadata, supported attribute names and actual AX errors. Other document content and recent-file labels are absent. Raw metadata also includes modified S/W variants, clearly separated by modifier values, and no actions were dispatched to them.

The second activation used `activateWithOptions_(0)` on the exact observed instance after checking its PID and owned-main-window CFEqual identity. It requested neither all-window activation nor an unrelated app action. Exactly one request returned true; all ten checks remained inactive. The recorded loop used 0.1-second run-loop turns; total observed activation phase elapsed about 2.07 seconds. Both documents remain preserved because Save was unverified.

Installed Apple SDK `AXAttributeConstants.h` states zero command modifiers means Command alone; the driver's modifier filter is correct. `NSRunningApplication.h` states changing application properties require main-run-loop turns and activation requests need not activate immediately or at all. `NSApplicationActivateIgnoringOtherApps` is deprecated since macOS 14 and has no effect. No undocumented activation workaround is justified by this evidence.

Engineering completion, deterministic Save/close/reopen validation, and fresh model capability must be reported separately. Old controlled2 remains **0/2 passed, 2 unknown** and is not rescored by these diagnostic controls. Autosave or later disk equality cannot substitute for an issued app Save.

## Narrow production repair and regression evidence

Commit `a5c633b` adds explicit `native_act(operation="activate")` on the observed owned AXWindow. The driver checks current window membership, main-window CFEqual identity and runtime `AXFrontmost` writability before exactly one `AXFrontmost=true` application write. At most ten bounded read-only IPC checks verify both actual frontmost state and continuing owned-main identity. No activation request, menu press or Save is silently retried. The existing scoped attempted-action counter and AX trace record the activation operation. The three existing tool names remain compatible; the operation enum gains activation.

Snapshots now include `application_active`, `activation_supported`, and `activation_support_error`; menu targets are withheld unless the application is active and the selected owned window is main. A final pre-menu-dispatch check repeats frontmost/main identity. An activation write that returns success but cannot verify its postcondition reports `AXActivationUnverified`, `success=false`, `action_applied=true`; a transport error during the write reports applied unknown/null; stale or unsupported preconditions report applied false. Activation success requires the verified postcondition. This repairs the previously implicit and misleading inactive-menu boundary; it does not guarantee that an environment will permit activation.

The initial regression run showed **4 failing, 10 passing** before source implementation. Subsequent focused coverage exercises inactive-menu withholding, exact owned activation, main-window changes, unsupported activation, accepted-but-unverified state, uncertain transport outcomes, final foreground checks and shared quota/trace accounting.

Commit `c634afe` freezes `scripts.experiments.native_menu_repair`: exactly two fresh deterministic contexts, main and run_sync, with at most four scoped editor actions per context (activation, fill, document menu, Save). Review subsequently required the separate four checker/cleanup actions and total eight-action cap; `4c8c138` enforces phase and total guards before dispatch and records actual counts. No model/cloud or mutation retries. A verified issued Save gates trusted close/reopen/disk and AX readback. Failed or unsupported activation stops before edit and preserves evidence. Both contexts are counted as the complete two allowed post-fix controls.

Commit `853202b` also repairs the previously encountered P3 pilot classification defect. A failing close-completion windows probe now carries its structured failure into the persisted `close_completion_probe` stage. `AXPermissionDenied` and `NotAvailable` are classified blocked. The dedicated regression was **2 failing** before this fix. Combined focused tests at this intermediate source were **61 passed in 0.94 seconds**. These tests are engineering evidence, not real Save acceptance or model capability.


## 保存验收发现的问题与第二轮修复

首次真实控制验收 `artifacts/native-menu/2026-10-08-validation1/` 固定 main/run_sync 各一次，**0/2完整通过**。两项都实际调用Save，每项3编辑原语、2验证原语；初始应用已激活，没有调用新增activate。main在关闭重开后AX文本匹配，但检查器保留了保存尚未落盘时的旧磁盘读数，判failed；run_sync在验证时读取AXWindows得到-25204，判unknown。原记录未回写或追加重复。

由该证据修复可复现的检查器缺陷，提交 `0b7faff` / `6e374f2`：

- 保留`disk_matches_before_reopen`诊断值，完整通过必须以关闭重开后的新磁盘读数与AX文本共同判断。
- 纯AX读请求的-25204采用类型明确的`AXReadUnavailable`，不能与写动作传输不确定状态混用。执行前的读失败为applied=false；写后观察失败保持已作用的true。
- 已作用的动作之后最多3次只读观察就绪检查，50ms间隔，不重发Save或菜单。耗尽后清除旧引用，禁止额外的第四次隐式刷新。
- 验证环境的观察等待只接受ScopeUnavailable/AXReadUnavailable，最多30次、每次调用前检查3秒合作式期限，记录所有失败。权限等其他错误立即暴露；同步IPC可能越过一次期限，不声称硬墙钟限额。
- 关闭完成同时要求原window_ref消失、没有指向该文档精确URL的窗口。同名其他文档不阻塞；AXDocument暂时缺失不能证明原窗口关闭。

这组回归先4失败，再补一个写后只读就绪回归失败；复审另发现3项语义边界，均先复现失败再修正。最终聚焦 **70 passed in0.82s**。复审接受后才运行新的v2协议；不是在不改源码的情况下重复抽样救分。

## 固定v2确定性验收

命令：

```sh
.venv-computer-use/bin/python -m scripts.experiments.native_menu_repair --output artifacts/native-menu/2026-10-08-validation2
```

固定源码`6e374f2`，两项各一次，协议`native-menu-repair-v2-readiness`、源码hash和期限/原语上限在执行前冻结。**main/run_sync均passed，2/2**。每项真实Save、窗口关闭、重新打开、AX文本与独立磁盘检查全部完成，清理也成功。每项3编辑原语+4验证/清理原语=7，2次可信应用open/reopen，零模型/云请求。墙钟分别2.409秒、2.339秒。

两项`disk_matches_before_reopen=false`而最终disk/AX均true，直接支持“旧读数导致错误判定”的修复。两项初始应用均已激活，activate调用0；没有出现新的只读就绪等待事件。因此本轮不声称实测了AXFrontmost激活写入或故障等待分支，其安全语义由回归覆盖。成功发生于已激活的真实窗口；系统为何未执行先前NS激活请求仍未确定。

## 单次真实本地模型开发验收

命令：

```sh
.venv-computer-use/bin/python -m scripts.experiments.native_menu_model_dev --output artifacts/native-menu/2026-10-08-model-dev1
```

源码`9de41b8`。新任务`native_menu_repair_dev1`，公开instruction提供精确JSON字符串并明确末尾换行，expected不另输入模型。沿用NativeChainProvider/ModelBroker/EvolutionRunner/Journal/BudgetTracker，单次dev，8循环步/10请求/16Agent原语/4验证清理原语/总20原语，可信应用open/reopen最多2，480秒合作式期限，零云。源、任务、提示、模型/服务hash、实际命令、协议在首请求前冻结；未追加请求救场、安装候选或训练。

结果 **1/1 passed、score1**；5模型请求、4工具调用、2Agent原语（fill及真实Save）+4验证清理原语=6。模型直接使用已观察的Save项，无需额外打开菜单或激活；不是脚本替学生保存。完整关闭重开、AX与磁盘检查均true，57字符目标包含2个真实换行和末尾换行。独立磁盘SHA256 `bc020ee43affa61f64ce9e895faebb31bc75feaefbaed8a0bd44f062041830d7`，清理成功。

实耗 **25,840输入/773输出token、5本地请求、91.200秒run墙钟、$0云费**，预算无活动预留。名义预留1,000,000输入/3,000输出token，不称逐调用严格token配平。实际请求temperature0/max_tokens300。本地Agents-A1-4B Q4_K_M权重SHA256仍为`d93c393a9bd5139a4b5cfe24d31ef553c5a497bfb8afec178a354ecbf508f062`；本次服务二进制hash、命令及版本探针状态记录在freeze.json，不凭历史填写版本。只有自有服务被启动和停止，退出已记录。

`audit.json`有16项只读核验通过：源码字节、单次提交、实际请求/响应与usage、请求参数、从模型可见目标重建真实Save、6个原始AX执行记录与归因一致、独立磁盘/读回、清理、预算结算和自有服务退出。16项是证据核验，不是16项能力成绩。

旧controlled2仍0/2、完整检查unknown2。此次是新dev任务，提示、运行时与环境均有差异，没有控制变量的前后能力对照；1次成功不证明通用原生能力、统计收益或已解决旧窗口消失。新增激活操作的真实非激活环境验收也尚缺。OCR候选未实现，本次AX覆盖了需要的控件。

## 问题记录与验证边界

[问题台账](../computer-use-issues.md)记录每项根因证据、实现修复、测试和未确认事项。初始诊断的AX窗口识别轨迹对其他窗口标题/URL做了显式脱敏，保留数量和自有文件信息，provenance记录这一处理；菜单错误与命令属性证据保留。旧实验数据未更改。

最终全量命令：`.venv-computer-use/bin/python -m pytest -q`，冻结源码`9de41b8`，退出0：**1062 passed、4 skipped、1 xfailed、1 warning，232.53秒**。日志`artifacts/native-menu/final-pytest-9de41b8.txt`。warning来自pygame使用已弃用pkg_resources，未影响结果。原生模型运行结束后才开始回归，两者不争抢推理资源。

## 非激活窗口受控验收（2026-10-09）

命令：`.venv-computer-use/bin/python -m scripts.experiments.native_inactive_acceptance --output artifacts/native-inactive/2026-10-08-controls1`。源码/测试提交`536d926`，严格运行两个上下文，各一次，无模型请求和云调用。

结果为 **0/2 acceptance passed**，该结果保留，不能升级为激活能力通过。main 上下文确实建立了辅助窗口前台、观察到 TextEdit 非前台且自有主窗口，然后只发出一次 `AXFrontmost=true` 写入；AX 动作回报已作用且新的 AX 观察回报 active/main，但独立 `NSWorkspace.frontmostApplication()` 仍返回已知的辅助进程 PID，因此未通过“实际前台 + 同一窗口”门控，未执行 fill/menu/Save。run_sync 上下文在 3 秒就绪窗口内始终读到旧辅助 PID，未开始编辑。两项都停止并清理了各自辅助进程，真实编辑动作数为`[1, 0]`，Save均未发出。

随后只读核查确认旧辅助 PID 已退出；一个新进程中的 `NSWorkspace` 读取返回当前 TextEdit PID，而 `AXFocusedApplication` 系统级读取返回`-25204`。这些事实支持“同一观测消费者/事件循环保留旧前台 PID”的诊断，但还不足以证明具体的 AppKit 缓存或 worker 线程根因。原始结果、timeline、helper日志、源码冻结和核查摘要保留在 `artifacts/native-inactive/2026-10-08-controls1/`，其中 `audit.json` 明确记录了这次负结果。

因此下一包不是模型验收，也不运行 Task6 的 Unicode dev2。先为前台观测增加新鲜、带期限的只读消费者并做离线回归，再重新冻结最多两项非激活控制；旧 controlled2、validation1 和本次 controls1 均不重跑救分。

## 新鲜前台观测复验（2026-10-09）

针对 controls1 的假设，提交`f251b81`让辅助进程就绪和激活后状态都通过新的短生命周期 AppKit 子进程读取 `NSWorkspace.frontmostApplication()`，每次有明确超时。离线聚焦回归为 **35 passed**。

新冻结目录 `artifacts/native-inactive/2026-10-09-controls2/` 仍为 **0/2**。main 上下文完成一次 AX 激活写入；AX 观察为`application_active=true`和`main_window=true`，但新鲜读取仍指向存活的辅助进程，故停止在 fill 前。run_sync 上下文的辅助窗口也无法满足自有 TextEdit 非前台的初始门控，未发激活或编辑动作。两项 Save 均未发出，辅助进程均清理。

这次复验排除了“仅由同一 `NSWorkspace` 消费者缓存旧 PID”这一单一解释：即使换用新进程，辅助窗口存活期间也观察到同样的前台不一致；辅助窗口退出后新进程才读到 TextEdit。结论仍是 AX 的 active/main 读数不能替代真实前台验证，具体 macOS 激活/事件循环根因尚未确认。不会再通过增加重试或放宽门控来制造通过，Task6 Unicode dev2 保持暂停。
