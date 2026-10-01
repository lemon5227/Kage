# C2.1-A：四族浏览器环境与真实本地基线

日期：2026-10-01。范围是可重置任务、独立检查、硬预算和起步本地基线；同页云教师、浏览器技能与重复迁移对照属于C2.1-B。C2.1整体尚未完成。

## 实验问题与架构

C1.1/C7.1只验证过资料表单，不能据此说明数值推理、过滤选择或勾选状态操作也可行。本包增加四族：资料填值、表格总额计算、筛选后选择最低价、通知偏好切换。每族有开发/留出两个内容与标签变体，共八项；每次使用新HTTP服务器、新浏览器context和空后台状态。目录留出改变条目顺序与获胜id，避免总选同一位置通过。

`BrowserChainProvider`在原`EvolutionRunner`的fork worker内部启动浏览器，复用`PromptBuilder → AgenticLoop → ToolExecutor`，只有页面作用域的browser工具。初始观察由运行时直接供给，后续每次动作返回紧凑新观察；真实推理由本机`Agents-A1-4B Q4_K_M`经llama.cpp执行。没有云调用、截图定位或权重训练。

独立协调器从实际HTTP后台读记录、提交次数，再从页面读回保存结果，写`browser-check.json`；原父进程`Evaluator.json_exact_match`要求三项同时匹配：目标记录、恰好一次POST、页面读回与后台一致。目标值是公开任务要求；派生总额和选中id的评分答案不注入模型提示。没有文件写工具供模型伪造检查文件。finish、tool success或模型自述均不参与评分。

180秒runner monotonic截止由原进程组终止机制执行（本机不计系统睡眠），不靠asyncio取消阻断同步推理。正常结束、超时都会保留已写出的检查与真实POST记录。超时状态仍是timeout，即使已经提交了正确结果也不能冒称正常通过。模型调用中被硬杀时实际token不完整，预算按预留上限保守结算，不能把该额度写成实测用量。

## 实现和修复记录

1. 先写真实环境/独立评分与同步阻塞超时回归，缺失模块时出现失败，再实现环境和worker适配。八个任务的确定动作是测试代码提供的，证明环境可执行，不计入真实AI成绩。
2. 测试实际后台正确但页面读回被篡改时得0；测试模型只声称成功而不操作时得0；测试同步模型阻塞后硬截止生效，记录到的worker与浏览器子进程全部退出。
3. 独立审查发现旧检查文件可能在第二次提交后仍为满分。真实复现：第一次保存/check得1，第二次POST使posts=2，未再次check时旧分仍1。修复为POST持锁先原子撤销旧证明，再提交后台；check在异步读取结束后持同一锁核对最新后台，过时GET不能恢复旧证明。新增八实例真实重复POST与过期快照回归，复审通过。

代码提交：`e86ac27`；实际时钟补录：`132d2e8`。任务与源码hash、实际本地GGUF流式SHA256、请求与响应、后台记录、DOM轨迹、正常结束的最终截图、journal/budget均保留；超时只保留已落盘证据，不补造截图。原始数据位于活动worktree的`artifacts/c21-browser-baseline-v1/`与`artifacts/c21-browser-baseline-v2/`，默认被Git忽略；本报告、任务定义与脚本进入Git。模型SHA256为`d93c393a9bd5139a4b5cfe24d31ef553c5a497bfb8afec178a354ecbf508f062`，任务SHA256为`bfaadcfc1a165c7021124bf3c3b55a2839caa65f48cfbe6608f5523a28452ff1`。

## 冻结协议

每实例一次，全部八项串行；最多6模型调用、原AgenticLoop最多5循环步、runner1步、180秒runner monotonic截止（本机不计系统睡眠）、单次HTTP120秒。模型客户端temperature=0，输出额度沿用原AgenticLoop动态值并逐请求记录。服务器context8192、parallel1、Metal ngl99、flash-attention auto、KV q8_0、reasoning off。源码与任务在首个请求前冻结，不因观察到失败而加预算或改任务。

这是一轮覆盖性基线，不是三重复研究结果，也不是学生学习收益。留出已经由基线执行，后续不得将其失败轨迹送入示范提取或调参；如需要针对该轨迹调试，应另冻结新留出。

## 验证与实际结果

工程全量：**848 passed、1 skipped、1 xfailed**，100.21秒；浏览器相关：**14 passed**，22.02秒；独立复审另跑真实环境回归：1 passed，6.80秒。跳过/xfail保留，不计为通过。

### 第一轮：保留但不作稳定性能基线

完整八项为4正常通过、4超时；其中2超时已保存正确产物，另2目录任务未提交选择。所有结果进入分母。原`completion.status=completed`描述产物检查，`stop_reason=timeout`与`RunResult.status=timeout`仍表示执行超时；本报告按RunResult.status统计正常通过，不能将其写成6/8正常成功。

| 实例 | 执行状态 | 产物分数 | runner计时（秒） |
|---|---|---|---|
| profile_dev | passed | 1 | 175.502 |
| invoice_dev | passed | 1 | 125.680 |
| preferences_dev | timeout | 1 | 180.323 |
| catalog_dev | timeout | 0 | 180.672 |
| profile_holdout | timeout | 1 | 180.076 |
| invoice_holdout | passed | 1 | 153.402 |
| preferences_holdout | passed | 1 | 164.191 |
| catalog_holdout | timeout | 0 | 180.091 |

运行期间发现严重环境干扰：配置创建于15:40:04 +0200，结果结束于19:31:27，实际间隔13883.442秒；runner的`time.monotonic()`累计1339.937秒。macOS实现为`mach_absolute_time()`，系统日志在此期间有200条睡眠/唤醒记录；llama服务日志单调用也出现远超runner计时的跨度。保留`power-timing.json`和完整服务日志，不将该轮耗时或超时率解读为纯模型能力/稳定吞吐。

处理只针对实验条件：脚本补录UTC开始/结束与wall_seconds，临时`caffeinate -i -s`为实验服务持有防闲置/AC系统休眠assertion；不修改系统设置、任务、模型、预算或评分。全八项以同协议再跑一轮v2，不只挑失败项；进程结束时撤销临时assertion。强制合盖仍可能打断实验，所以也要核对第二轮睡眠日志和实际时间差。这不是“重跑直到成功”。

### 第二轮：控制闲置休眠后的完整重跑

完整第二轮为**6/8通过、2/8失败、无超时**；dev与holdout各3/4。资料、金额与目录各2/2，偏好0/2。没有第三轮挑选成功结果。

| 实例 | 状态/分数 | runner / 实际秒数 | 模型调用 | 输入/输出token |
|---|---|---|---|---|
| profile_dev | passed / 1 | 30.458 / 30.458 | 4 | 10152 / 411 |
| invoice_dev | passed / 1 | 28.696 / 28.695 | 4 | 9484 / 436 |
| preferences_dev | failed / 0 | 57.676 / 57.675 | 5 | 15773 / 718 |
| catalog_dev | passed / 1 | 52.703 / 52.703 | 5 | 16127 / 535 |
| profile_holdout | passed / 1 | 59.707 / 59.707 | 5 | 13840 / 508 |
| invoice_holdout | passed / 1 | 50.132 / 50.132 | 4 | 9562 / 435 |
| preferences_holdout | failed / 0 | 84.775 / 84.775 | 5 | 15552 / 559 |
| catalog_holdout | passed / 1 | 87.103 / 87.103 | 5 | 16383 / 577 |

实际区间18:00:02–18:07:34 UTC，452.236秒；每项runner累计451.250秒、wall累计451.248秒，最大单项差0.001秒。此期间睡眠/唤醒事件为0，assertion证据已保存，实验模型服务与临时防休眠进程已结束。单项中位55.190秒，包含浏览器启动与清理；这是一次运行，不能与受休眠干扰的v1作模型性能因果比较，也不能直接与C7.1不同任务/提示口径相减。

实际计量为37模型调用、106873输入token、4179输出token，云调用/费用均0。最后的catalog_holdout达到step_limit，但独立产物已正确，因此原runner给passed；这与被硬终止的timeout不同。没有要求额外最终文字才能评分。

两项偏好失败的实际后台均为email=false、sms=false、weekly=false，读回一致但目标email=true未满足。开发轨迹明确显示：模型把原生checkbox的value="on"当作已勾选，漏点Email，反而来回切换Weekly。compact-v1省略checked=false有明确契约与提示，但这不保证小模型能正确解释；数据已证明这一观察表达需要继续实验。工具动作正常，外部评分没有被模型错误的成功描述蒙混。留出失败仅公开成绩与产物，不送入技能生成器；后续开发依据dev轨迹。

本套件“恰好一次POST”是额外工程约束，公开goal没有限制修订次数；它有助于发现重复提交，却不适合直接当通用恢复任务的定义。两轮失败结果均因错误/缺失记录而不满足目标，不是正确记录被多次提交误拒。C2.1-B应另冻结可修订任务协议：以最终真实状态验收、提交次数作诊断，只有公开目标要求一次时才硬约束次数；父子/基线/教师必须使用同一新协议，不回写本轮分数。否则同页教师纠正已保存的错误值会被第二次POST阻断。

本包完成了四族环境与真实覆盖基线，**没有完成浏览器学习、AX、截图决策、真实登录网站/iframe/多标签或通用电脑任务评测**。单次变体结果不能证明稳定成功率。另有明确运行限制：原runner的macOS monotonic截止不计系统睡眠，新增wall记录只是诊断，未实现含休眠的墙钟截止；强制休眠仍须将性能实验标为受干扰。

复现命令（需在新输出目录运行，已启动同配置本地服务，并使用已安装Playwright的可选环境；macOS可用`caffeinate -i -s`包裹服务以临时防止闲置休眠）：

```sh
.venv-computer-use/bin/python scripts/experiments/browser_suite.py \
  --output-dir artifacts/c21-browser-baseline-v2
```

## 下一包边界

C2.1-B需让教师继承学生失败时的同一个Page/context/后台状态，分别记录actor与预算；不能用第二个新环境冒称接管。已有Python文件沙箱技能不能直接标为浏览器技能：需要实际页面执行的受控动作格式、验证与版本契约，再比较原学生/教师接管/轨迹检索/技能迁移/预算匹配重试，关闭云端的留出复验每臂至少三次。本包没有完成这些工作。
