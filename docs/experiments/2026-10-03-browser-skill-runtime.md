# C2.1-B2.1b：同一活页面上的声明式浏览器技能

日期：2026-10-03。父提交`0457d112489fda4bf9b74f526d4d081204ea3c2a`；代码提交`10e96857a3db945f899a1011a570a65338ac3711`。验收层级：真实本地浏览器工程回归；技能描述符在测试里预制，没有云生成、模型学习或新留出迁移成绩。

## 实现

新增v2 `browser_workflow` manifest与按描述、参数schema、workflow和协议版本计算的digest。解释器只支持有界`for_each(ensure_checked)`、`ensure_checked`、`fill`和`click`；每步在活Page的当前DOM中按唯一语义标签解析，复用BrowserAdapter与ToolExecutor，不执行候选Python/JS、不把Page传到文件技能沙箱。`BrowserChainProvider(browser_skill_bundle=...)`在页面创建后注册稳定`skill_search/skill_call`，metadata/cache均记录已加载digest及解释器hash；空/错误digest走显式失败。文件技能v1路径不变。

原始浏览器工具和嵌套技能共用每actor最多16次primitive调用，教师另起16次；模型的`skill_call`另计一次模型工具调用。实际子动作写入actor日志，带actor/skill_id/digest/parent_call_id；链metadata记录primitive数。`ensure_checked`对compact-v1缺省`checked=false`作比较，满足则跳过，不反向切换。失效节点且明确未执行动作时最多重解析一次；超时/是否执行未知立即停止，保留已发生动作。技能自己只报告工具结果，最终通过仍由独立Evaluator判断。

## 真实回归与曾遇问题

预制“设置偏好”技能经模型可见schema→`skill_search`→`skill_call`→真实HTTP保存→外部读回通过；3次实际`browser_act`（Email/SMS/Save）、1次`browser_observe`，`browser_primitives=4`，完成门控使脚本模型仅请求2次。另有profile文本字段fill+Save读回。不同初始状态、顺序重排、重复标签、节点替换、primitive耗尽、动作结果未知及无新观察均在真实页面回归；没有把脚本通过写成AI通过。

第一次端到端测试错误地从父进程读取`model.calls=0`；EvolutionRunner在隔离worker里运行模型，改用返回的链metadata核对2次调用。实现时又发现`not_applied`的`skill_call`历史行会因有错误文字而丢掉结构化新观察；已在渲染与教师上下文打包中保留，并增加最新技能观察回归。无新观察且动作状态未知时不再把旧DOM标作当前观察。

聚焦测试：`.venv-computer-use/bin/python -m pytest -q tests/test_browser_skills.py` → **10 passed**；含打包和结果语义的聚焦回归 → **32 passed**；最终全量`.venv-computer-use/bin/python -m pytest -q` → **880 passed、4 skipped、1 xfailed**。`git diff --check`通过。云费用0、模型token 0；测试用本地HTTP fixture与headless Chromium，临时原始页面数据由pytest清理。

源码SHA256：`skills.py` `64e3013c987f3bf9f38af231e01d67bf7bf99c912c3fb44fb85892bd82fa0406`，`experiment.py` `6d6746f5956d541f688b319150666e747332b0024ab9ff5eb5b0ec4581ef2f0a`，`browser.py` `2236a35a4f0c428ea8ed1c0fb2064a2ec55294c281f507b7f0d27740262a7eca`。

下一包B2.1c需从B2.1a标注来源的真实dev示范生成候选，按固定预算比较父子与新dev状态、保存重启再调用；本包没有这些证据。三条新test已在B2.1a冻结，不给生成器读取。
