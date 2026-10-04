# C5.0：受控浏览器任务入口与可信状态

日期2026-10-04；开发基线`6bc671d`，最终源码`e1e9fff`。**最小入口集成、工程验收与两次真实本地模型pilot完成，下一包C4.5-DOM人类示范。** 这次验收的是入口与状态语义，沿用已经暴露的dev页面，不是新的通用能力或学习收益评测。

## 实现与实际使用

Launcher在Background Tasks旁增加“浏览器实验”卡片：选择任务、local/cloud/local_teacher执行器、5/6循环步与可选工作流bundle；开始后显示run_id、实际模型、检查结论、停止原因、实际请求/tokens、费用来源、保守预留和产物链接；Stop绑定选中的run。创建与停止POST只尝试一次，避免重试产生额外任务。页面重载可从同一服务的列表恢复状态；服务重启后的历史列表恢复尚未实现。

执行路径为Launcher或`POST /api/browser/tasks` → BrowserTaskService专用BackgroundLane/BackgroundWorker → 独立Python worker → 现有EvolutionRunner/BrowserChainProvider → ModelBroker/ModelProvider → AgenticLoop/ToolExecutor → 真实Chromium Page → 保存后台与页面读回。复用原执行和评分链，没有第二套Agent循环或评分器。API在control模式也可用，不要求加载音频/记忆模型；runtime存在时发`kage:job`，否则卡片轮询同一状态。

公开任务仅`profile_dev`、`preferences_dev`和移除检查器的`preferences_unchecked`，不接受任意指令配旧checker。local_teacher只允许有独立检查的任务；执行器显式选择，禁用本次运行的hybrid，不静默改成本地/云。默认5循环步、可选6，主执行者最多6请求；教师另5步/6请求；每actor最多16浏览器primitives，整体480秒包含排队和启动。bundle默认空，显式加载时显示digest/未晋级，不自动安装候选。

使用现有Kage启动方式打开Launcher，确保`model.local_runtime`指向已启动的实际模型服务。浏览器worker使用当前Python，或用`KAGE_BROWSER_PYTHON`指定已有Playwright实验环境；`KAGE_BROWSER_RUNS_DIR`可改证据目录，默认`~/.kage/browser-runs`。本次pilot仅在隔离control应用内存中指定18082端口，没有改用户日常配置。

## 状态、费用和停止

| 证据 | 用户任务状态 |
|---|---|
| 独立检查明确通过 | completed |
| 独立检查明确未通过 | failed，检查未通过 |
| 启动/模型/超时等执行错误，未得到否定检查 | failed，执行失败、目标未确认 |
| 无检查器且执行正常结束 | unknown，待确认 |
| 用户取消 | stopped |

`execution_status`单列后台生命周期；后台completed不等于目标通过。恢复后最终检查通过可以completed，历史模型错误仍保留。无检查器时runner内部的`run_status=failed`只是旧评分内核的无评分结果，不能解释为目标被检查否定；本包对外任务状态仍为unknown。

费用区分实际reported usage与保守reservation，缺usage保留partial/unknown；本地API费用0不含硬件、电力。云无价格配置时金额为null/unknown，配置价格只能形成带来源的估算。本包没有真实云调用，未验证现场云账单。配置经worker stdin传递；响应/错误/工具参数中的凭据回显在进入后续日志前脱敏。

worker独立进程组，bootstrap在重导入和私有stdin前发布PID/PGID；取消先写停止标记，处理排队、启动句柄迟到、运行中停止、超时和shutdown，清理自有worker/Chromium，不杀外部模型服务。若OS让新进程一直无法调度，停止标记阻止其日后开始工作，迟到句柄再回收；这一现实边界保留在工程报告。停止后迟到返回不得覆盖stopped。产物访问限定本run已索引文件，带URL与SHA256。

## 问题与修复记录

| 实际发现 | 根因与最终处理 | 提交 |
|---|---|---|
| 启动取消、缺解释器或模型错误缺可信结果 | 管理启动任务、结构化错误、启动纳入deadline；最终检查优先，历史错误保留 | `4723aa4`、`0631c91` |
| 子进程已生成但句柄未交付，stop提前返回 | bootstrap早期PID/PGID记录和停止标记，迟到句柄清理 | `a1f7838` |
| A任务延迟GET覆盖已选B，Stop可能指错run | 选择generation、请求顺序和终态锁；真实Launcher延迟响应回归 | `59dfe35` |
| 通知无限等待拖住开始/停止；执行错误误写检查失败 | 通知移出串行执行关键路径并限时；否定检查与目标未确认分别显示 | `c451cc8` |
| 通知超时取消语音后，旧播放线程可能卸载新语音 | 撤回语音修补试验；浏览器任务只更新事件/面板/日志，普通后台语音保持原路径 | 试验`e3cfc78`，撤回`cecbf77`，最终`e1e9fff` |
| 独立审计断言温度0，而本次实际为0.7 | 我错误复制上一显式温度实验的断言和运行注释；冻结源码的MeteredProvider默认0.7，全部7请求确认；保留原审计/初始运行注释，另存修正审计，不改协议、源码或样本 | 原始`audit-initial.log`、`audit-correction.json` |

逐轮红灯/修复/绿灯与限制分别保存为[worker工程报告](2026-10-04-browser-task-service-engineering.md)和[API/Launcher工程报告](2026-10-04-browser-task-entry-engineering.md)。最终独立审查无开放Critical/Important；语音试验的失败与撤回仍可回溯，不能宣称修复了通用共享mixer所有权。

## 工程检查与真实模型分表

工程用例用脚本HTTP模型，但确实执行独立worker、真实Chromium、checkbox修改、保存POST与读回。验证未保存失败、无checker unknown、排队取消零请求、挂起模型时杀自有PID、后续任务可继续、启动竞态、异常/脱敏、旧请求与迟到事件不改新任务、通知挂起不阻塞stop/shutdown。Launcher回归实际点击开始/停止、检查POST次数、证据链接、重载与模型文本按文字渲染；不是检查字典含某键。

最终源码全量命令`.venv-computer-use/bin/python -m pytest tests -q`：exit0，**946 passed、4 skipped、1 xfailed，191.64秒**；1个既有pygame/pkg_resources弃用warning。最终聚焦67 passed，54.72秒；`kage-avatar`下`npm run build`成功，1.53秒，原Vite非module脚本/大chunk警告仍在。构建后frontend源码未再变化。重测试全部结束后才启动真实推理。

真实执行者为Mac M4 Air16GB上的**Agents-A1-4B Q4_K_M**，模型SHA256`d93c393a9bd5139a4b5cfe24d31ef553c5a497bfb8afec178a354ecbf508f062`；llama.cpp0.4.1/build10964/`b29c606e2`，Metal、8192上下文、单槽、q8_0 KV、reasoning off。实际全部请求max_tokens=300、temperature=0.7（原Agent链默认）；compact-v2。两任务各一次，共12请求/96000输入/4000输出保守预留，无bundle、云、教师、救回或追加采样。

本次从生产HTTP `POST /api/browser/tasks`入口提交，使用与Launcher一致的payload。真实AI pilot没有点击Launcher；Launcher点击路径由上述工程回归验收。

| 任务 | 对外状态/停止原因 | 实际请求 | 输入/输出tokens | POST/读回 | 墙钟秒 |
|---|---|---:|---:|---|---:|
| preferences_dev | completed / external_check | 3 | 7480 / 341 | 1 / 正确 | 55.606 |
| preferences_unchecked | unknown / model_returned | 4 | 11686 / 431 | 1 / 正确 | 67.695 |

两次均实际保存`email=true,sms=false,weekly=false`，后台和页面读回一致；动作都是browser_act，合计6个工具结果ok，0次技能搜索/调用。合计**7个本地请求、19166输入/772输出tokens、123.301秒、零云请求**。有checker唯一任务独立重算score=1；unchecked无评分，即使模型明确说已保存、后台也符合目标，对外仍unknown。不能把两次记录写成新的2/2通用任务成绩或小模型学到了技能。

## 证据、复算与下一项

原始目录保留在`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/c5-browser-entry-2026-10-03/`；目录沿用协议创建日，实际模型运行于10月4日。含冻结protocol/provenance、20份提交源码hash、全部请求/响应、DOM/动作、后台/保存读回、截图、journal/预算、API状态快照、28份运行产物HTTP下载hash、工程检查、服务启动/停止、审查记录、audit和artifact-index。`results.json` SHA256：`8afb6110a141d4e6e469ac9e3d1cbbad4568119d27a6c3afe0133c5a5fe9ca23`。

独立复核`.venv-computer-use/bin/python artifacts/c5-browser-entry-2026-10-03/recompute-audit-final.py`：exit0，重算检查、请求/usage、冻结源码与28产物hash；原`recompute-audit.py`及其冻结hash不改。修正脚本及原因在audit-correction单独记录。结束后只停止自有control/model服务，两个端口连接失败，14个已记录浏览器后代PID均退出。原始数据仍是活动worktree中的唯一副本，不归档或删除该worktree。

复现时使用`e1e9fff`源码、记录的模型服务参数与Python环境，复制本目录协议/driver到一个新的artifacts实验目录，先启动该目录的serve-pilot.py，再运行run-pilot.py；已有submissions.json的原目录拒绝追加。复算使用修正审计。工程与真实运行记录按包分别提交，本包不推远端。

下一包**C4.5-DOM**：用户主动开始/结束一次浏览器示范，记录实际DOM、动作和修正，进入同一episode/workflow协议，在不同输入复验；再按队列推进AX与更广电脑任务。C5.0只完成受控实验入口；自由网页/活浏览器接入、服务重启历史恢复、E5谱系/diff展示、通用任务检查仍待做。浏览器学习候选未晋级，旧留出失败与负结果保留；本包无训练或自动安装。
