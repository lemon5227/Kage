# C2.1-B2.1-0：浏览器错误中的新观察进入模型历史

日期：2026-10-03。父提交`22be97f9b1329c70f65932c037748f366e9d4d70`；代码提交`dd716b69ea675e383ea9b2f142fb5d584c0a27d7`。验收层级：工程链路/真实本地浏览器回归；没有调用云或本地AI模型生成决策，不计作AI任务完成率提升。

## 失败与根因

真实本地HTTP页面中先观察，再替换Email复选框节点。旧`target_ref`与页面revision失效，`BrowserAdapter.act`正确拒绝动作、返回`StaleObservation`和新DOM。`ToolExecutor.render_history_line`却只留下错误码和文字，下一次provider消息没有新`observation_id`；原生`tool_call_id`虽然还在，也无法使用新引用恢复。打包器只识别`[Tool: browser_*]`，未覆盖真实错误行格式。

先加经过`BrowserAdapter → ToolExecutor → AgenticLoop → 下一次provider消息`的回归，开启/关闭浏览器历史打包各跑一次。修复前两臂都在解析下一次provider收到的错误载荷时失败：内容是纯文本`StaleObservation: DOM or node identity changed; no action applied`，并非JSON。

## 修复和观察

仅浏览器工具的结构化失败把原始JSON送入`[Tool Error: browser_*]`；保留`success/error/message/outcome/action_applied/observation`，不将拒绝伪装成成功。无结构化结果或畸形JSON仍走旧错误文字；普通工具渲染不变。打包器识别真实错误前缀，把较早DOM归档，保留最新错误观察及原生`tool_call_id`。

绿灯回归在同一真实Page替换节点：旧动作结果为`rejected`，模型下一次收到新`observation_id`和新`target_ref`，第二次动作结果为`ok`，Email复选框实际变为勾选。未观察到旧引用误点击。错误携带`action_applied: null`时保持未知，不擅自重试。compact-v1观测中该复选框`value="on"`、缺`checked`，实际初态未勾；协议含义仍为缺省`checked=false`，没有改格式。

## 验证与限制

- 聚焦：`.venv-computer-use/bin/python -m pytest -q tests/test_browser_takeover.py tests/test_browser_context_pack.py tests/test_tool_outcome_semantics.py tests/test_tool_conversation.py` → **36 passed**。
- 共用executor全量：`.venv-computer-use/bin/python -m pytest -q` → **862 passed、4 skipped、1 xfailed**；随后增强compact-v1断言并单独重跑真实浏览器两臂 → **2 passed**。
- `git diff --check`通过。运行环境：worktree可选Python、headless Chromium、本地HTTP fixture；云费用0，模型token 0。`tmp_path`证据由pytest清理，无长期原始实验资产；提交中的测试与代码是可复现依据。
- 代码SHA256：`tool_executor.py` `7122726126b1fcae1d784364454b547526fa0ab4e7f706d5f07271cb99890b86`；`context_pack.py` `f7c8c88eac61e94f1fd773fc7dfe1439b952af076c519ca16e4916e480668727`；`browser.py` `35cf452ba70401c5513f165154892b352d895d8682d2895ad1a82ccea41ee20e`。

脚本模型仅验证信息传递与真实页面动作，不能证明云/本地模型会自主选择正确恢复、泛化到网站或完成保存任务。下一包C2.1-B2.1a处理浏览器episode、示范来源和生成输入白名单；本包不修改已有模型、评分或晋级规则。
