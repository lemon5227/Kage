# C1.1 浏览器DOM执行首包

日期：2026-10-01。范围：独立Chromium会话中的顶层DOM观察、精确填写、点击、滚动、条件等待与保存读回。接入原ToolRegistry/ToolExecutor/AgenticLoop，生产全局工具未默认开启。不是至少4浏览器任务、12电脑任务或通用GUI能力验收。

## 架构与实现

`BrowserAdapter(page)`持有调用方创建的Page和一个当前观察；注册browser_open/browser_observe/browser_act三个异步工具。模型选择观察里的observation_id和target_ref，没有开放selector、任意JavaScript或坐标生成接口。观察记录DOM来源、文档身份、URL/标题、可见文本、节点身份/标签/允许动作/当前值/位置和相关链接/表单属性。节点WeakMap保持身份，临时Map只保留当前观察节点。

动作前再次观察并比对revision。节点替换、位置、值、链接地址、关联表单提交目标/方法变化会使旧观察失效；返回StaleObservation及新观察，原动作不执行。实际节点句柄用于本次动作并在结束释放，避免按同名selector自动重定位到替换节点；官方一般建议Locator，本包选择特定节点身份以满足已观察引用契约，依据[官方差异说明](https://playwright.dev/python/docs/api/class-elementhandle)。这不能消除检查与动作之间的所有竞争，也不代表检测任意JS事件处理器或截断范围以外的变化。

最多80个控件，优先当前视口中的控件，其余按文档顺序补齐；文本最多5000字符、标签200字符，截断明确标记。滚动后可观察后续控件。普通HTTP页也能生成文档身份。条件等待按当前页面可见文本判定，最长10秒；只读等待允许等待期间的状态变化，写操作要求新鲜引用。阶段JSONL记录open/observe/execute/wait和耗时；阶段耗时有嵌套，不应相加当总耗时。

操作返回success仅表示工具动作/观察返回，最终完成由外部实际保存内容决定。导航超时不能推断点击未发生，因此返回tool_error并把action_applied标为unknown（JSON null）；不伪报not_applied。等待超时不证明任务完成。

## 实验环境与行为回归

M4 Air 16GB；Python 3.13；独立`.venv-computer-use`继承已有项目依赖，新增可选`requirements-computer-use.txt`固定Playwright 1.63.0。Chromium实际版本153.0.8010.12（headless shell v1243）。依赖见[官方Page接口](https://playwright.dev/python/docs/api/class-page)，版本从[PyPI包元数据](https://pypi.org/project/playwright/)核对。未操作用户日常浏览器标签页。

八项回归都启动真实Chromium，先观察对应失败再实现/修复：

1. 原ToolExecutor填写姓名、点击保存、条件等待；HTTP服务端实际记录和页面读回一致，POST只有一次。
2. 替换同文按钮/移动按钮，拒绝旧观察，没有真实提交。
3. 真正滚动；旧观察拒绝；不存在的等待文本超时，服务端仍未保存。
4. 无crypto.randomUUID的普通HTTP页也能观察（旧实现真实报TypeError）。
5. 点击确实发起导航但响应超时，不能标为“未执行”（旧not_applied分类回归失败；导航请求证明点击已发生）。
6. 81个控件页面滚动后能观察并真正点击最后按钮。独立审查发现旧80控件截断无法到达末尾；旧实现回归失败后修复。
7. 同节点href变化拒绝旧观察，避免导航到新地址；旧实现错误允许点击，回归失败后修复。
8. 关联form action变化拒绝提交，服务端请求为0。复审发现只记录button.formAction漏掉form.action；先复现实际误提交，再补关联表单/override元数据。

最终验证：浏览器8 passed；含可选依赖的全量`.venv-computer-use/bin/python -m pytest -q`为842 passed、1 skipped、1 xfailed（84.56秒，原pygame弃用warning）；`git diff --check`通过。

首次回归因core.computer_use尚不存在而失败，属于有效接口red；导航超时测试最初从已导航的DOM读取window.clicked失败，改用独立导航请求记录核验真实副作用。没有放宽等待或伪造动作返回来让测试通过。独立只读复审确认两个P2已修复、没有剩余重要发现。报告汇总脚本曾因引号转义错误产生SyntaxError、没有执行修改；改写表达式并使用set -e后完成汇总核验，未影响模型试验数据。

## 真实本地模型试验

实际Agent为Agents-A1-4B官方Q4_K_M，llama.cpp端口18082、8192上下文、温度0、thinking关闭；不是测试序列模型。唯一表单任务：填写Wenbo Browser Lab并保存，页面读回姓名。每轮新HTTP服务/新浏览器context，服务端记录重置；模型只看到公开用户目标与工具返回，评分器和服务端记录没有注入提示；目标姓名本来就在用户目标中，不是隐藏答案。上限5循环步/6模型调用，HTTP请求超时120秒，asyncio协作超时150秒。同步模型调用可能阻塞asyncio，因此此probe不声称硬墙钟150秒；C2.1应复用runner进程隔离实现严格任务截止。

审查前v1三轮均通过，分别24.596、22.590、24.992秒，均5模型调用；输入9915/9948/9911、输出406/403/404 tokens。实际动作均observe→fill→click→observe→最终文本，模型没有使用wait，wait能力由真实行为回归验证。每轮服务端POST一次，记录和DOM均为正确姓名。云调用0、云费用0，权重未训练。

v1配置原未记录适配器hash，后从已保存的审查前源码重建hash并标注来源；原源码另存adapter-pre-review.py，未冒称预先冻结。最终版本v2另跑三轮，3/3通过，分别103.005、76.211、32.340秒，均5模型调用、POST一次。中位76.211秒，明显高于审查前中位24.596秒；观察字段与运行时负载不同，不能据此断言任何单一原因或声称加速。最终adapter SHA256为`66b3b25709cf514da31db47dc67517f06126f22df5cc2f10910af97138bbceb9`，配置另记录实际脚本hash和实施前Git revision，不覆盖v1。每轮input/output tokens：12288/392, 12349/400, 12346/397。整机事后swap used为6866.88MB，这是整机状态，不是模型峰值内存或耗时根因证明；后续C7/C8应做受控对照。

原始证据：当前worktree的`artifacts/c11-browser-dom-pilot-v1/`及`artifacts/c11-browser-dom-pilot-v2/`，含全部模型请求/响应、浏览器阶段JSONL、实际工具链、服务端结果、最终DOM及截图。artifacts被Git忽略，代码/页面/报告入Git。清理worktree前先迁移证据；报告不依赖每次把完整轨迹塞入模型上下文。

## 复现与限制

```sh
python -m venv --system-site-packages .venv-computer-use
.venv-computer-use/bin/python -m pip install -r requirements-computer-use.txt
.venv-computer-use/bin/python -m playwright install chromium
.venv-computer-use/bin/python -m pytest tests/test_browser_dom.py -q
.venv-computer-use/bin/python scripts/experiments/browser_dom_pilot.py --output-dir artifacts/c11-browser-dom-pilot-v2
```

试验需先启动与旧报告相同的Agents-A1 llama-server，端口18082；输出目录必须不存在，复跑使用新目录。依赖缺失时浏览器测试明确skip；本次使用含依赖和浏览器的venv实际跑过，不能把skip称为通过。

不覆盖iframe、shadow DOM、canvas、下拉选择、浏览器多标签、用户现有登录会话或macOS AX。观察revision是截断范围内的语义快照，不是整个页面所有变化的证明。一次简单表单三重复不能称为通用能力或学习收益；没有在本包运行云教师、技能生成或权重蒸馏。下一独立包C2.1建立至少4浏览器任务与留出变体、严格reset/check/预算，再把C4接管与学习接入浏览器。
