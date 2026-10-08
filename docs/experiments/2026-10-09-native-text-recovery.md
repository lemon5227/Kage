# 精确文本与失效观察恢复开发验收 — 2026-10-09

本轮根据Unicode dev2失败轨迹推进C1.2-R-text，保留dev2原成绩0/1、独立checkerunknown，不重跑旧任务。

## 证据与实施

逐字段比较dev2两次StaleObservation与各自前一成功观察：两次均`application_active: true → false`，Save/Close/menu目标被移除；第一次另有窗口/控件坐标变化。因此当时的拒绝符合当前可操作状态，不能认定引用检查器有缺陷，也不能忽略revision或自动激活执行。具体前台为什么变化仍未确认。

原生指引新增公开的dev3：新专用文档、21字符/3个真实LF（含末尾），要求核对fill返回的AXTextArea.value；缺末尾LF时由模型选择再次完整fill。遇StaleObservation优先用返回新观察，inactive则显式activate当前AXWindow，确认后选择最新Save；已观察Save直接使用。没有隐藏expected补值、驱动归一化或可信执行器替模型保存。

预检发现原系统提示强制fill后open menu，与dev3直接Save指引冲突。`6bf2fb2`提供显式native_soul参数，由provider的身份/cache、实际NativeModelChain/PromptBuilder与CLIfreeze共同使用。仅dev3选择专用提示；dev1/dev2及默认API沿用原NATIVE_SOUL，工具、scope、驱动revision拒绝和预算不变。候选/源码hash及实际提示/hash均在首请求前冻结。

回归先观察到dev3选择失败、selected prompt参数未支持、CLI仍使用旧提示三个失败，再修复。真实provider→chain→首次模型system消息与metadata promptSHA回归检验实际消费者，避免只验证配置函数。聚焦原生 **97 passed in2.12s**，独立源码复核通过。模型provider、AX环境为外部边界的测试替身；实际链和提示构造仍真实执行。

## 单次真实开发任务

```sh
.venv-computer-use/bin/python -m scripts.experiments.native_menu_model_dev --task dev3 --output artifacts/native-text/2026-10-09-dev3
```

冻结源码`6bf2fb2`；同TextEdit覆写/保存家族，单次dev，不是留出、第二应用或方法因果对照。8循环步/10请求/16Agent+4验证原语/总20、可信open/reopen2、480秒合作式期限、temperature0/max_tokens300、零云。独立完成须模型真实Save、关闭重开后AX和磁盘精确匹配，清理另记；进程/AX/HTTP同步调用不保证硬墙钟上限。

结果 **0/1、kernel failed/score0、独立checkerunknown**。8次本地请求、27,136输入/780输出token，191.505秒；零云费用、预算无活动预留、自有模型服务已停止。首次模型动作为显式activate，`action_applied=true`但十次有界检查内未确认active，返回AXActivationUnverified；随后七次observe均报告原窗口不再存在于AX窗口列表。没有fill/Save，磁盘仍是12字符初始文本，独立检查没有完成关闭重开/AX读回。

15项只读证据核验通过：源/测试Git冻结字节、单次提交、实际system消息包含完整专用Soul且hash一致、无旧强制菜单指引、请求/响应各8、usage/失败/unknown均保留、零fill/Save、初始文件未改变、预算结算和自有服务退出。15项是完整性检查，不是能力成绩。前置环境失败导致没有进入精确文本核对/Save恢复阶段，因此不能判定指引改善了文本能力，也不能将其当作纯文本策略的失败对照。

原始model/tool/AX日志、freeze、journal/budget与服务生命周期记录保存在活动工作树`artifacts/native-text/2026-10-09-dev3`。不追加尝试救分；公开指引与新文本同时变化，不根据本次分数宣称学习收益。激活未验证与窗口消失的外部来源仍未确认；与旧controlled2窗口消失现象相似不等于同一根因。

## 窗口失去后终止无效推理

失败轨迹明确暴露反复observe的无效请求。`0c519d2`在AXWindowClosedError增加明确的`window_closed=true`标记，保持原StaleObservation码与action_applied语义。只有失败结果带该标记才将原生scope记为丢失；普通控件revision变化仍返回新观察并允许恢复，不按错误文字猜测关闭。

下一次模型请求在预算预留、请求日志和API派发前拒发，并将链stop_reason明确记录为`native_window_closed`，避免报告成预算实际耗尽。已有API调用正常结算，不自动重开/激活/填值/Save，也不重评分dev3。门控针对**后续模型请求**；同一个已返回模型响应中的剩余工具尝试仍经过原有工具scope/引用门控，不宣称它们全部被此门控中止。

真实链回归先观察到窗口丢失后仍8次调用，修复后该场景仅1次；另一个普通控件变化回归仍2次调用并收到新观察，没有误终止。原生聚焦 **99 passed in2.00s**，独立源码复核通过。8→1是离线受控回归的请求数优化，不是本次真实dev3的成本收益；真实dev3冻结`6bf2fb2`早于该优化，原8次调用不改写。

最终全量在模型服务停止后运行，命令`.venv-computer-use/bin/python -m pytest -q`，冻结源码`0c519d2`，退出0：**1091 passed、4 skipped、1 xfailed、1 warning，361.58秒**。日志`artifacts/native-text/final-pytest-0c519d2.txt`；warning为既有pygame/pkg_resources弃用提示。源码与模型证据/文档经独立复核，回归与模型推理未重叠。

下一C1.2-R-lifecycle-long：在独立、新鲜消费者上取证长时窗口生命周期/前台状态，先解释前置失效再冻结新dev；原生示范、OCR覆盖、跨应用与更广研究验收仍未完成。
