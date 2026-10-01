# C2.1-B2.0b：教师DOM历史有界打包

日期：2026-10-01。代码提交b650ecd；计划b72ded1。浏览器技能生成B2.1与迁移B2.2仍待做，本包为保存前上下文预算问题的独立运行时修复。

## 问题、选择与实现

上一包B2.0三次真实试验2/3，第三次学生首请求超时，教师观察、调整控件后，在保存前因完整wire超过12000字节被预检拒绝。历史完整DOM逐次重复，不应直接提高云额度。

采用确定性投影：保持系统提示、原目标、动作、原生tool_call_id、非DOM结果与错误；最新完整DOM不变。较旧DOM以sha256归档到context-evidence，并换为证据引用，完整原始messages也按hash保存。只处理能明确识别的浏览器结构化观察，未知内容保留；没有更新的观察时不删除唯一DOM。投影不修改输入messages或原始轨迹，不调用额外摘要模型。已有browser.jsonl仍保存完整观察与实际动作。

BrowserContextProvider在完成门控内、MeteredProvider前包装教师，actual provider记录真正发出的投影后消息；teacher-context-pack.jsonl记录前后message字节、旧DOM数量及原始消息引用。字节统计是messages大小，不冒称整个wire大小，原RecordedLocalProvider继续对包括tools/max_tokens/thinking的最终JSON做12000字节预检；计步、计费和外部评分不变。默认teacher_context_pack=False，只有脚本显式--teacher-context-pack才启用，metadata/cache/config及源码hash记录开关，学生不改。

## 复现与工程验证

- 单元先红：context_pack模块不存在；实现后验证旧DOM可从hash文件恢复、原始消息不变、最新观察/错误/原生关联保留，无新观察不裁剪。
- 真实浏览器先红：缺少teacher_context_pack开关。实现后在同一个preferences_dev任务、相同完整wire12000字节上限下对照：关闭打包会超限并未保存；开启后教师观察→Email→SMS→Save四次动作，真实HTTP后台及DOM通过，external_check结束。这是脚本化动作的执行回归，不当AI成绩。
- 24项浏览器/投影测试通过，29.29秒。全量860 passed、1 skipped、1 xfailed、1 warning（97.11秒）；warning为依赖pkg_resources弃用提示。随后新增最新DOM过大回归，投影3项全部通过，0.11秒：请求仍被原wire检查拒绝，没有网络响应文件，不绕过预算。全量数字对应新增该1项之前，明确保留验收范围。
- 独立只读复审未发现重要问题；git diff --check通过。
- 离线重放上轮真实教师的三份已发请求：完整wire分别6846→6846、9244→7409、11846→8174字节，归档观察分别0、1、2。此处证明历史投影大小，不是新模型行为或第四次请求的真实测量。

验证命令：

```sh
.venv-computer-use/bin/python -m pytest -q tests/test_browser_context_pack.py tests/test_browser_takeover.py tests/test_browser_suite.py tests/test_browser_dom.py tests/test_browser_efficiency.py
.venv-computer-use/bin/python -m pytest -q
.venv-computer-use/bin/python -m pytest -q tests/test_browser_context_pack.py
```

## 真实模型协议与结果

冻结preferences_dev三次，沿用B2.0 external_completion、同权重Agents-A1-4B Q4_K_M / llama.cpp，本机M4 Air16GB；教师为DeepSeek Flash non-thinking。唯一本包行为变化为教师上下文打包。各actor最多6请求、5步、HTTP30秒、runner480 monotonic秒；teacher最终wire12000字节、输出1024。临时caffeinate防闲置休眠，同时记录wall_seconds；不提高上限、不改checkbox表示、不筛选失败。

沿用冻结价格假设，三次教师保守上界$0.0869184；实际云估计只计算teacher返回usage，未知保留null。全局预算按云价包含本地token的保守预留不当实际云账单。

三次全部完成，13份源码hash与冻结b650ecd核对一致，模型hash仍为d93c393a9bd5139a4b5cfe24d31ef553c5a497bfb8afec178a354ecbf508f062；Python3.13.11、Playwright1.63.0、Chromium153.0.8010.12。服务与B2.0相同8192上下文、1slot、q8_0 KV、flash-attn auto、reasoning off和采样配置。

| 次数 | 结果 | monotonic / 墙钟秒 | 学生attempt / 输入 / 输出token | 教师attempt | 真实产物与原因 |
|---|---|---|---|---:|---|
| 1 | failed / 0 | 110.790 / 110.793 | 5 / 15413 / 662 | 1 | 学生step_limit且没有保存；教师首请求读取超时，无保存 |
| 2 | passed / 1 | 68.706 / 68.706 | 4 / 11227 / 431 | 0 | 1次正确保存及DOM读回；external_check停止 |
| 3 | passed / 1 | 95.948 / 95.948 | 5 / 15307 / 561 | 0 | 最后一步正确保存及DOM读回；step_limit结束，外部检查仍通过 |

整体2/3、学生独立2/3，教师触发1次且0/1完成。第三次说明停止原因和外部任务成绩应分别报告：到步骤上限并不自动意味着产物错误。没有新增成功教师轨迹。第一例实际打包记录archived_observations=0、message bytes5547→5547：只有初始观察，不能删掉唯一当前状态；超时也不是上下文超限。教师usage缺失，费用估计null并保留上界；另两次云费用0。不能将网络超时解释成DOM打包无效，也不能据此声称真实云任务成功率提升。

运行日志未出现Target closed未取出任务异常；临时caffeinate与wall记录保留，服务PID64624在结束并核对command后已停止。完整三次保留，没有为获取成功教师样本重跑。pilot.log、server.log、power-assertions.txt、full-tests.log一并存入artifacts。

原始证据：活动worktree artifacts/c21-browser-context-v1/，Git忽略；报告/脚本/测试进入Git。复现需相同模型服务、依赖与自己的私有云配置，使用全新输出目录：

```sh
.venv-computer-use/bin/python scripts/experiments/browser_takeover.py \
  --external-completion --teacher-context-pack \
  --output-dir artifacts/c21-browser-context-v1 \
  --teacher-config /Users/wenbo/Kage/artifacts/private/deepseek-settings.json
```

## 限制与下一步

这是当前页面状态投影，不是通用长期记忆或已实现的分页召回。browser工具不能直接读取这些hash文件；模型执行时使用最新页面，旧快照用于取证。涉及跨页面抄录、需要过去值的任务，要设计可检索引用或保留任务所需事实再验收，本包不声称支持。目标/system/动作/非DOM输出仍会增长；最新DOM过大仍会失败。未改变ToolExecutor对错误消息的渲染，也不把不能解析的错误原文裁掉。

本包尚未生成技能或训练权重，不将旧2/3与新成绩差异称为学习收益。下一包B2.1：使用成功开发接管轨迹，按同一浏览器协议生成/调用参数化技能并外部验证；B2.2再做关闭云端的五臂留出对照。E/C仍共享当前任务队列、预算、档案和晋级接口。
