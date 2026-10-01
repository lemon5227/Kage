# C7.1 浏览器效率：紧凑观察与初始观察直供

日期：2026-10-01。用户批准 DOM/AX 优先、快速决策和视觉补缺的优化路线。当前独立首包只实施紧凑观察、减少观察往返和分段计时；Jev、视觉、AX、新引擎以及 C2.1 浏览器学习均未在此包完成。

## 适配器实现与回归

原 BrowserAdapter 默认行为不变；显式 compact_observations=True 时，对模型省略目标的 null 属性与 checked/disabled=false，保留空字符串、值、位置、允许动作及所有非默认属性。工具说明明确缺省含义；不增加正文截断。内部 current 和 observe JSONL 仍为完整快照，动作前完整 revision 校验未改变。序列化采用紧凑 JSON。不是从日志里删除证据。

新增真实 Chromium 回归：通过原 ToolExecutor 填值/保存/等待，独立 HTTP record 与页面一致、POST一次；投影可还原完整 target；勾选框点击后实际取消、禁用按钮拒绝；改变表单提交目的地后旧引用拒绝且不再提交。新测试首先因缺失 compact_observations 参数 TypeError 失败，实现后通过。原八项动作回归继续保留。新旧浏览器回归10 passed；连同工具契约共18 passed（10.19秒）。

发现已有 MeteredProvider 逐调用 elapsed_ms，无须在核心创建重复计时系统。下一步固定配对试验通过实验脚本统计外层 ToolExecutor、初始观察、Agent和独立check时间，嵌套 browser span 不相加。

## 配对实验

六次配对已完成；详见下方全部结果。设计见[独立计划](../plans/browser-efficiency-2026-10-01.md)。原始证据将保留在活动worktree的独立 artifacts 目录，不能清理worktree后丢失数据。

## 固定协议与全部真实结果

Agents-A1-4B 官方 Q4_K_M，M4 Air 16GB、llama.cpp、本包独立端口18082，8192上下文、单槽、GPU offload99、Flash Attention auto、q8_0 KV、thinking off；客户端温度0、每调用输出上限300。各臂6调用/5循环步/HTTP120秒/协作150秒。与C1.1一样，协作timeout不是硬墙钟截止，基线首轮实际155秒且未触发取消；不称其满足150秒硬预算。云调用0、云费用0，无权重训练。

每次新HTTP服务、新context、同一个公开目标/页面/模型；按 baseline→optimized、optimized→baseline、baseline→optimized 顺序运行，不在看到结果后修改提示或重跑挑成绩。baseline保留C1.1提示与完整观察；optimized为compact-v1、初始观察直供与复用动作观察提示，属于组合方案，不能隔离三项各自贡献。模型自己选择实际动作，未用固定脚本代替决策。

计时从初始观察前开始：agent包含bootstrap和原AgenticLoop；seconds为agent+外部check，初始化与截图在计时外。bootstrap是实际读取页面，不伪造模型/tool call；JSON证据单独保留。模型耗时复用MeteredProvider；tool_handlers复用ToolExecutor外层日志，不相加嵌套DOM span。remaining_agent为剩余未归因开销，包括日志尾部与编排；异常中无法完整计量的时间也不得擅自归给模型。

外部check是后台GET /record准确姓名、页面Saved文本一致、POST恰好一次。模型finish和工具success不替代该检查。

| 配对 | 基线秒 / 调用 / 输入token | 优化秒 / 调用 / 输入token | 实际验收 |
|---|---|---|---|
| 0（AB） | 155.245 / 5 / 12396 | 126.601 / 4 / 9697 | 两臂通过、各POST一次 |
| 1（BA） | 91.672 / 5 / 12391 | 115.479 / 4 / 9743 | 两臂通过、优化更慢 |
| 2（AB） | 118.688 / 5 / 12392 | 80.860 / 4 / 9776 | 两臂通过、各POST一次 |
| 中位数 | 118.688 / 5 / 12392 | 115.479 / 4 / 9743 | 各3/3，没有删除尝试 |

调用中位数下降20%，输入token下降21.377%，输出token中位401→356（下降11.222%）。耗时中位仅下降2.704%，其中一对反向，不宣称稳定加速或统计显著。各轮模型占agent时间约99%以上：基线153845.4/91463.5/118367.8ms，优化126102.1/114878.7/80666.7ms；工具132–1322ms。证据指向模型调用环节；没有通过受控资源实验证明热、swap或某个引擎为根因，也不能把减少token直接写成云费用下降（本包无云调用）。

实际基线工具为observe→fill→click→observe，5模型调用包含最终回答；优化为运行时bootstrap→fill→click→observe，4模型调用。六次点击返回的观察均尚无Saved文本：最后一次observe用于等异步保存后的读回，不能当成无意义重复而删除。下一项效率实验应采用有上限的事件/状态等待，测是否能在动作返回时提供稳定结果；不能用未经验证的“已保存”假返回省调用。

## 审查修复、版本与证据

只读审查指出实验初始化/cleanup异常可能使整个任务退出、丢失失败分母。测量版六次无该异常，全部成功落盘；随后添加recorded_trial，初始化失败写failed记录并继续，cleanup失败保留已独立检查的checkpoint并附lifecycle_error。新回归先因缺失recorded_trial失败；补实现后真实Chromium对端口1导航产生ERR_UNSAFE_PORT，连续两臂均写失败记录，没有模型调用。修复后浏览器+实验行为11 passed（10.65秒），复审没有剩余重要发现。全量结果见下方最终验证。

配对试验依据的是修复前冻结脚本，不冒称用最终修复脚本重跑：原字节另存measured-script.py，SHA256 `cc9452137577aeba06d08f1b061a708144728a037e8bf03c8861158accbb8cfd`与config一致。适配器SHA256 `35cf452ba70401c5513f165154892b352d895d8682d2895ad1a82ccea41ee20e`；GGUF SHA256 `d93c393a9bd5139a4b5cfe24d31ef553c5a497bfb8afec178a354ecbf508f062`。config另含两个提示、fixture与其余执行源码hash，实施前Git为f0e0085。实测启动命令见下方；硬编码server_settings用于记录本次实际启动，脚本不会自动配置或验证任意外部server的全部设置。

原始证据目录：`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/c7-browser-efficiency-v1/`，含config、全部六条results、summary、每轮模型请求/响应、完整DOM trace、bootstrap、原工具日志、后台记录、最终截图、测量脚本原字节及llama-server.log。目录被Git忽略，清理worktree前须迁移，报告/代码进入Git。已停止本包启动的模型服务PID39384，未停止其他应用。

## 复现与下一项

```sh
/opt/homebrew/bin/llama-server -m /Users/wenbo/.kage/models/agents-a1-4b/Agents-A1-4B-Q4_K_M.gguf --jinja --host 127.0.0.1 --port 18082 --alias agents-a1-4b -ngl 99 --flash-attn auto -c 8192 -np 1 -n 1024 --reasoning off --cache-type-k q8_0 --cache-type-v q8_0 --temp .85 --top-p .95 --top-k 20 --presence-penalty 1.1
.venv-computer-use/bin/python scripts/experiments/browser_efficiency.py --output-dir artifacts/c7-browser-efficiency-new-run
.venv-computer-use/bin/python -m pytest tests/test_browser_dom.py tests/test_browser_efficiency.py -q
```

后续脚本含初始化/cleanup记录修复；需重现原测量源码时使用artifact中的measured-script.py，不能覆盖已有输出目录。组合方案仍为显式实验选择，未改日常Kage的默认浏览器会话，也未宣称通用成功率提升。C7.1完成后继续C2.1至少4类浏览器任务及留出、严格runner预算和教师学习；事件等待/动作合并在该套件上另设对照。Jev API、AX与视觉定位按各自独立包实施。

## 最终验证

`.venv-computer-use/bin/python -m pytest -q`：845 passed、1 skipped、1 xfailed、1 warning，85.52秒；既有pygame/pkg_resources弃用warning未在本包处理。`git diff --check`通过。六条结果、模型输出额度/温度、旧测量脚本与适配器hash已逐项核验；独立复审确认初始化/cleanup分母问题已解决。未将本包少量表单试验当成至少4类浏览器任务、学习收益或完整C7验收。
