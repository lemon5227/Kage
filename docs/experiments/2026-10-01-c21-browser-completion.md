# C2.1-B2.0：独立完成门控与异步保存确认

日期：2026-10-01。第二阶段的B2前置小包；浏览器技能生成及多臂迁移仍未完成。目标是实际目标已通过时停止多余模型请求，并统一异步保存确认，不改模型权重或checkbox表达。

## 问题与实现

B1真实第三次教师已经保存正确产物，仍尝试生成最终总结，完整JSON超过12000字节后被预检拒绝；阶段teacher_check_passed=false而最终读回/评分为1。不能用扩大预算掩盖这个时序/收尾问题。

BrowserChainProvider增加external_completion开关，默认False保留历史协议；开启后学生/教师使用同一个CompletionGate。可信代理在下一次模型调用前以原Evaluator检查实际产物，通过就不调用底层模型，把停止原因记录为external_check。只看tool success仍然不够：错误保存即使后台与页面一致，外部目标不符也不会门控。隐藏expected/checker文件没有进入模型提示，原AgenticLoop与评分系统不重写。

CheckpointExecutor捕获实际POST /save，先撤销旧证明，最多1秒等待响应结束和实际后台/DOM一致；无保存时不增加无条件sleep。超时/IO错误只记录未确认、保留当前后台与活页面，撤销两份读回证明，供下一次观察/教师接管使用。所有可信证明更新与POST共用锁，避免旧检查复活。

开关进入config、metadata和cache_identity，历史A/B1成绩不回写。后续B2所有对照必须统一开关与保存确认协议，不能把停止优化混入学习收益。

## 修复与验证过程

1. 真实浏览器回归添加150ms读回延迟，测试模型在额外总结请求时直接抛异常。实现前因缺少开关失败；实现后正确学生3次动作即终止、教师0调用。错误学生仍不会早停；教师修订两次动作后独立通过并终止。
2. 独立审查发现一秒耗尽后仍启动至少1ms检查，超时会从actor结束检查传播，使活会话crashed。用1.5秒真实读回延迟复现TimeoutError，再修为超时保留未确认状态，不追加读取、不抛出保存确认异常；随后页面真实读回完成后可重新确认。复审通过。
3. 浏览器相关20 passed，27.65秒。完整回归856 passed、1 skipped、1 xfailed（94.01秒）；这是模型试验前的工程检查，不把测试替身当AI成绩。

## 冻结真实协议

复用browser-learning-v2与B1脚本，显式--external-completion；preferences_dev固定三次，全部进入分母，保持学生/教师最多6调用/原5步、HTTP30秒、整体runner monotonic480秒（Mac不计睡眠）、教师请求12000完整字节/输出1024。临时caffeinate防闲置休眠，单独核对墙钟与睡眠日志。唯一功能变化为开启完成门控与有界确认；不根据结果改任务或重跑挑选。

云费用预留不增：按[官方峰值价格](https://api-docs.deepseek.com/quick_start/pricing/)教师每次上限$0.0289728，三次$0.0869184。实际付费保守估计只使用teacher usage；全局budget按云价含本地结算的数字不能冒称实际云账单，未知用量保留未知。没有触发真实教师时明确说未新增教师样本。

## 三次真实结果（源码1a2cbfa）

执行者为本机Agents-A1-4B Q4_K_M / llama.cpp，失败后同一页面交给DeepSeek Flash；不是测试替身。模型SHA256为d93c393a9bd5139a4b5cfe24d31ef553c5a497bfb8afec178a354ecbf508f062，Chromium153.0.8010.12、Playwright1.63.0、Python3.13.11。config中12份源码hash全部与冻结提交核对一致。

| 次数 | 外部结果 | 墙钟秒 | 学生请求attempt | 教师请求attempt | 实际保存与停止 |
|---|---|---:|---:|---:|---|
| 1 | passed / 1 | 48.456 | 4 | 0 | 1次正确保存、DOM读回通过；external_check结束 |
| 2 | passed / 1 | 47.728 | 3 | 0 | 1次正确保存、DOM读回通过；external_check结束 |
| 3 | failed / 0 | 41.122 | 1 | 4 | 学生首请求TimeoutError；教师观察、调整两个checkbox后，第4次请求预检超过12000字节，尚未保存，call_error结束 |

整体2/3，学生独立2/3，触发教师1次且0/1完成。墙钟与monotonic记录相同到毫秒，临时caffeinate断言有记录。本包没有新增成功的真实教师轨迹；不将历史B1的接管成功冒算进本次分母。学生失败前工具调用0，最终backend record=null、posts=0，完成门控没有误判成功。

前两次学生用量分别11268/472与7286/465输入/输出token，云用量0。第三次教师实际返回3份usage，合计6701输入、252输出，按冻结峰值价格的可计量部分估计$0.0023127；第4次是本地预算预检拒绝、未发网络。汇总仍将整次teacher_cost_estimate_usd保留null并给$0.0289728上界，未知/保守预留不能写成真实token或账单。

失败暴露下一项：重复观察历史使教师在实际保存前超过请求上限。完成后门控解决不了保存前上下文增长，后续B2.0b需有界状态打包/历史裁剪，保留最新观察、错误与调用结果关联，再统一协议进入B2.1技能和B2.2对照。此次不增加预算、不修改目标、不重跑筛出成功。

## 真实试验暴露的清理问题及修复

前两次关闭页面时出现Task exception was never retrieved / Target closed。核对安装的Playwright `_network.py`，Response.finished()创建on_finished监听任务，正常响应结束后仍残留，关闭页面才抛异常。产物评分并未因此变化，但日志污染必须修复。

在真实延迟保存回归中捕获事件循环未处理异常，关闭浏览器后断言为空：原实现红。改为Page requestfinished/requestfailed事件维护pending请求及Event，只等待实际/save请求，保留一秒上限与真实DOM检查；不改第三方库、不屏蔽异常。修改后浏览器20 passed（27.53秒）。清理修复之后未重新调用付费模型；三次模型结果属于冻结1a2cbfa，后续修复由真实浏览器回归验证，不声称修复后另有模型成绩。

清理修复提交3746de3；独立只读复审未发现重要问题。最终完整回归：856 passed、1 skipped、1 xfailed、1 warning（94.78秒），warning为依赖pkg_resources弃用提示。浏览器用例20 passed；Markdown链接检查无失效链接，git diff --check通过。

验证命令：

```sh
.venv-computer-use/bin/python -m pytest -q tests/test_browser_takeover.py tests/test_browser_suite.py tests/test_browser_dom.py tests/test_browser_efficiency.py
.venv-computer-use/bin/python -m pytest -q
```

pilot.log、server.log、power-assertions.txt和cleanup-full-tests.log随原始artifacts保留。实验用本地服务已关闭；未修改用户云配置，未推送远端。

原始证据保留在活动worktree artifacts/c21-browser-completion-v1/（Git忽略）；报告、脚本、测试和计划入Git。复现需相同模型服务与Playwright依赖、自己的私有云配置，并使用新输出目录：

```sh
.venv-computer-use/bin/python scripts/experiments/browser_takeover.py \
  --external-completion \
  --output-dir artifacts/c21-browser-completion-v1 \
  --teacher-config /Users/wenbo/Kage/artifacts/private/deepseek-settings.json
```

## 接下来

先做B2.0b教师上下文有界打包，再由B2.1把dev成功接管轨迹纳入浏览器经验档案，生成可验证的参数化浏览器动作技能；B2.2在新输入上用本地学生真实调用并关闭云端，做统一协议的原学生、云救场、检索、技能与预算匹配重试五臂，每臂至少三次。之后再推广macOS AX/跨应用与人类示范。当前门控属于运行时改进，尚不是技能学习或权重蒸馏。
