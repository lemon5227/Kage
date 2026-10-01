# C2.1-B1：浏览器同页云教师接管

日期：2026-10-01。B1完成活会话内接管与首个真实pilot；浏览器技能生成、关闭云端迁移和五臂对照仍属后续B2，C2.1整体保持部分完成。

## 为什么单独做这一包

A的文件式评分不能直接沿用到恢复任务：它额外要求恰好一次POST，教师改正错误保存会产生第二次POST。新冻结browser-learning-v2保留相同任务目标与页面，评分只验实际最终记录和页面读回一致；提交次数留在browser-check.json作诊断。A任务、分数与轨迹不回写。这个新pilot没有相同新协议的独立父子对照，因此不把A→B成绩差当学习收益。

## 如何实现

BrowserChainProvider仍在原EvolutionRunner fork worker中创建一次HTTP环境、一次Page/context。学生与教师通过同一个BrowserAdapter/ToolRegistry/CheckpointExecutor执行；学生结束后独立评分不足1才触发教师。教师只得到公开目标、失败提示和新鲜当前DOM观察；隐藏expected/checker文件不进入提示。当前页面、已经输入的值、保存后的读回及后台记录全部延续，不启动另一个fixture或浏览器冒称接管。

BrowserTeacherTakeoverProvider记录student/final surface_id、失败状态、每阶段chain/usage、学生/教师外部检查及最终状态。每个工具即时写actor-tools.jsonl与DOM轨迹，原runner journal中的tool_results也保留actor。两份检查文件在每次POST之前原子撤销；异步check再核对最新后台，过期读不能恢复旧通过证明。

学生正确时教师0调用。学生步骤耗尽、模型返回错误或抛出异常且页面仍活着时可以接管；抛出异常保留已经执行的动作与未知usage。整体worker被硬杀后无法假装页面仍存在，timeout失败和已落盘证据如实保留。可修订任务只看最后真实状态，不把模型finish、tool success当完成。

## 遇到的问题与修复

- 回归的脚本模型最初把真实工具消息当裸JSON；实际有`[Tool: …]`前缀，导致第二步用旧引用。修正测试解析，并使用真实wait动作等异步保存完成，不用sleep伪造时序。
- 学生已正确但后台/DOM尚未可见时不能凭点击判完成；正确路径测试明确等待读回后检查，避免把未确认产物冒称完成。
- 独立审查发现教师输入检查与实际发送序列化不同、异常路径不能继续接管；两项都先复现再修复，复审通过。底层计量/载荷修复独立记录于[请求边界报告](2026-10-01-model-attempt-accounting.md)。

提交：`e6b80b2`计量/请求边界，`c48d2e6`同页接管。工程全量**853 passed、1 skipped、1 xfailed**（90.00秒）；浏览器相关17 passed（21.24秒），计量/教师边界17 passed（2.02秒）。测试使用模型替身，只证明接口和真实浏览器行为，不计真实AI成绩。

## 冻结真实pilot

只用preferences_dev，固定三次全部进入分母；没有人为缩短学生循环制造失败，也不反复挑成功。学生Agents-A1-4B Q4_K_M，最多6调用/原5步；教师deepseek-flash、thinking=false、最多6调用/原5步、输出1024、完整请求JSON不超过12000字节。双方HTTP30秒，整体原runner monotonic 480秒（macOS不计系统睡眠），另记录实际墙钟，并临时caffeinate -i -s防闲置休眠。

按[DeepSeek官方价格](https://api-docs.deepseek.com/quick_start/pricing/)的峰值/缓存未命中输入$0.30/M、输出$1.20/M作保守估算：每次六教师调用预留$0.0289728，三次$0.0869184。Journal/BudgetTracker为整体按含本地的云价保守结算，$0.16总预算覆盖全部预留；这不是实际账单。实际付费估计只使用teacher usage；未确认用量保留null与费用上限。非峰值/缓存命中费用可能更低。

本地服务与A第二轮相同配置：context8192、parallel1、Metal ngl99、flash auto、KV q8_0、reasoning off；客户端temperature0。云端非thinking模式可能忽略temperature设置，不能据此宣称云模型完全确定。未更改checkbox状态表达，避免混淆观察优化与教师恢复。

原始证据：活动worktree `/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/c21-browser-takeover-v1/`，包含配置/源码/任务/模型hash、三次学生/教师请求响应、实际后台、失败快照、actor动作、最终截图与journal/budget。默认被Git忽略，报告、任务和脚本入Git；私有key只读取原文件，没有复制到证据或输出。

## 真实结果

固定三次最终**3/3通过**：学生独立2/3，教师触发1次且恢复1/1。全部保留，没有补跑或排除错误。

| 次数 | 学生检查 | 教师接管 | 最终状态/分数 | runner / 实际秒数 | 学生 / 教师尝试 |
|---|---|---|---|---|---|
| 0 | 通过 | 否 | passed / 1 | 44.860 / 44.860 | 5 / 0 |
| 1 | 通过 | 否 | passed / 1 | 82.637 / 82.637 | 5 / 0 |
| 2 | 未通过 | 是 | passed / 1 | 79.501 / 79.501 | 3 / 3 |

第三次学生已实际点击Email和SMS，但本地请求TimeoutError后停止，失败检查为record=null、posts=0。教师在同一surface/document/context里观察现有控件并点击Save settings；最终真实后台为email=true、sms=false、weekly=false，posts=1，页面读回一致。没有从空页面重做，也未注入隐藏评分答案。证据中的阶段teacher_check_passed仍为false，后续final_state读回一致、最终独立评分才为1；这是异步保存/页面展示完成时序的差异。“恢复1/1”按最终评分统计，不冒称阶段检查已通过。B2需补明确完成等待与一致的阶段/最终检查记录。这次真实接管证明了未完成任务的续做；“已保存错误值后第二POST修订”由真实浏览器回归验证，尚未获得真实模型该分支pilot，不能混写成已实测。

第一次学生正常完成，教师0调用；第二次本地请求异常时产物已经正确，也未调用教师。第三次教师两次网络响应已成功：browser_observe、browser_act(click Save)。其后最终总结请求被本地完整JSON字节检查拒绝，teacher stop_reason=call_error；已保存产物仍独立得1。这个错误保留，不冒称教师无错误正常结束。下一包应使用独立完成检查停止多余请求或减少重复DOM上下文，不能仅为让总结成功而无上限加预算。

已返回云响应2次，已知usage为输入3766、输出214；按峰值/缓存未命中费率的保守估计$0.0013866，不是实际账单。计量器教师attempts=3，第三次preflight没有发送网络但仍按保守策略记未知，因此RunResult中teacher费用汇总为null并保留$0.0289728上限；报告不把3attempts冒称3次付费API，也不把未知usage写成0。学生第二/第三次用量同样不完整，整体预算按预留结算。

运行实际207.018秒、runner累计206.998秒，各单项wall/runner差0；期间睡眠/唤醒事件0，临时防休眠与模型服务已停止。配置中任务/源码hash核对一致。HTTP30秒与A的120秒不同，新评分也允许修订，因此A→本pilot分数不能作能力提升或蒸馏对照；这三个开发重复只验接管，不是留出研究。


复现（需要已启动同配置本地服务、可选Playwright环境和自己的私有云配置；使用新输出目录）：

```sh
.venv-computer-use/bin/python scripts/experiments/browser_takeover.py \
  --output-dir artifacts/c21-browser-takeover-v1 \
  --teacher-config /Users/wenbo/Kage/artifacts/private/deepseek-settings.json
```

## 后续验收

成功教师轨迹只属于开发数据，下一包才能进入浏览器经验档案与受控动作技能生成。技能必须由本地学生真实调用，在不接云端的新输入上复验；需要原学生、云救场、轨迹检索、技能迁移与预算匹配重试五臂、每臂至少三次。本文不会把云替学生完成说成学生已学会，也未进行权重蒸馏。
