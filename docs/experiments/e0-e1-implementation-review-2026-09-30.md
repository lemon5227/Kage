# E0/E1历史实施与复核证据

原总规划§13–18，保留当时的状态和行号用于追溯；行号可能随代码变更失效。fixture得分不等于真实模型能力，当前状态见[总规划](../agent-memory-evolution-master-plan-2026-09-29.md)。

## 13. Gemini 修改后的执行前复核记录（2026-09-29）

结论：修正后可开始 E0/E1；本次只改规划，没有验证新功能已经实现。

- 修正 7 项新增文献入口：Co-Scientist、Dynamo、QwenGyre、WebCoT、WebEvolver、Aime、Repo2Run。原链接中五项可访问但对应其他论文，两项未能解析为所称论文；现以正式论文页或作者预印本替换。
- 修正机制归因：WebCoT 涉及轨迹训练，QwenGyre 是大规模在线 RL，Repo2Run 是 Dockerfile 构建，不把它们写成本地快照或原子清理保证；移除未经核验的 Spotlight 与机构背书。
- 保留假说、技能持久化、进度观察与夹具回溯；取消首期强制分岛和两步无文件变化熔断。复杂搜索与世界模型预检不阻塞核心自修改。
- 补齐 checkpoint 恢复范围、计费不回退、bundle 技能锁定、方法间隔离、异步接入、崩溃恢复、drift 拆分及基线公平性。
- 验收应以行为测试和真实轨迹为准；不要把“采用某论文机制”作为测试通过条件。

## 14. 基础设施修复记录：测试卫生与工具契约（2026-09-29，E0 复核期间）

E0 接入真实执行链、复跑全量回归时发现两类与演化主线无关、但会污染实验结论的基础设施缺陷（测试会真实操作桌面；工具 schema 与实现签名不符导致模型调用必失败）。均已修复并验证，记录如下，避免后续把“测试通过”当作能力可用。

### 14.1 测试真实操作桌面（浏览器 / 捷径 / 空应用名）

症状：每轮 `pytest` 会真实打开 YouTube、Bilibili、一个示例网址、快捷键 App，并执行 `open -a ""`。定位方法：用 PATH 垫片（假 `open`/`osascript`/`shortcuts`/`screencapture` 记录调用）跑全量，实测每轮 5 次真实副作用。

| 触发点 | 根因 | 修复 |
| :--- | :--- | :--- |
| `tests/test_open_website.py`（3 例） | `patch.object(tools_impl, "open_url")` 打错模块：`open_website` 定义在 `core.tools.web_ops`，调用的是该模块自己的 `open_url`，补丁完全未生效；测试还因真实函数返回同值而“通过” | 改为 patch 定义模块并断言构造出的命令 |
| `tests/test_round5_cleanup.py::test_shortcuts_create_*` | `shortcuts_create()` 的实现就是 `open -a Shortcuts` 打开 GUI，测试未 mock | mock `shortcuts_ops.subprocess.run` 并断言 `[["open","-a","Shortcuts"]]` |
| `tests/test_tools_impl_primitives.py::test_open_app_returns_json` | `open_app("")` 直接发出 `open -a ""` 且返回 `success: true`（生产 bug） | 生产侧对空输入返回 `InvalidArgument`；测试侧 mock 并断言“不发命令” |
| 全仓兜底 | —— | `tests/conftest.py` 新增 autouse 夹具：拦截 `subprocess.run/Popen/check_output/check_call` 中的桌面类命令（`open/osascript/shortcuts/screencapture/networksetup/pmset/brightness/displayplacer/caffeinate`），**记录后在 teardown 断言失败**（不用抛异常，因为工具函数里广泛的 `except Exception` 会吞掉）；显式人工测试可用 `@pytest.mark.allow_desktop_side_effects` |

验证：全量跑完后垫片日志为空（零真实副作用）；反向探针（真的调用 `open_url`/`open_app`）能稳定失败并打印具体命令，证明兜底非空转。

### 14.2 工具 schema 与实现签名不一致（模型的动作空间失效）

实测（`create_default_registry()` 34 个工具，1 个检查脚本发现 2 处）：

| 工具 | schema 宣传 | 实现签名 | 实测后果 |
| :--- | :--- | :--- | :--- |
| `search` | `query / source(auto\|web\|youtube\|bilibili) / sort / max_results / filters` | `search(query, max_results, strategy, sort)` | 模型按 schema 传 `source="youtube"` → `TypeError: unexpected keyword argument 'source'`。视频检索能力对 agent 完全不可用；`filters` 是纯属虚构的字段 |
| `skills_save_local` | `name / description / body / target_dir / overwrite` | `skills_save_local(skill_name, content, workspace_dir)` | 模型一调用必 `TypeError`。而这是 agent 自动沉淀技能的唯一入口（`core/agentic_loop.py:567`），意味着**自我沉淀技能一直静默失败**；另外名称未消毒，`../../x` 可越界写入 |

修复：
- `core/tools/web_ops.py::search` 接受 `source`（含 enum 校验，非法值返回 `InvalidArgument` 而非静默回退），保留 `strategy` 作为 `smart_search` 的旧内部别名，`max_results` 归一到 1–10；从 schema 移除不存在的 `filters`。
- `core/tools/skill_ops.py::skills_save_local` 改为与 schema 一致的 `(name, description, body, target_dir="~/.kage/skills", overwrite=False)`，写 frontmatter + 正文（JSON 引号标量，合法 YAML，不引入 PyYAML 依赖），技能名白名单校验（封堵路径穿越），`overwrite=False` 时拒绝覆盖已存在技能。
- `core/tool_registry.py` 同步两个 schema（`source` 加 enum、去掉 `filters`、更新 `skills_save_local` 描述）；`core/prompt_builder.py` 行为准则里“保存 SKILL.md”的措辞改为“保存为本地技能文件”。

### 14.3 新增元测试（替代逐个工具的重复用例）

- 新增 `tests/test_tool_contracts.py`：对**注册表里全部工具**（含以后新增的）检查 ① 名字可用于 function calling ② `parameters` 为 object schema 且 `required ⊆ properties` ③ description 非空且 ≤200 字符（会进入每次请求）④ **schema 声明的参数 ⊆ handler 形参** ⑤ **handler 无默认值的形参必须在 schema 中声明为 required**。每条检查一次性列出所有违规工具名，不做按工具的参数化堆量；另附两个 bug 的显式回归钉子（`search` 的 `source` 真的到达实现；`skills_save_local` 接受模型侧参数名、拒绝覆盖与穿越）。
- 删除了低价值的“查字典”用例（`b站 → bilibili` 之类），只保留有安全含义的断言（坏输入不发命令 / 只发一条 argv 列表）。判断依据：宿主适配层的字符串映射坏了用户一眼可见，而 schema↔实现一致性才是 agent 能力是否可用的判据。
- `tests/test_skills_save_local.py` 按新契约重写（含 frontmatter、覆盖语义、穿越拒绝、以及 `agentic_loop` 实际传参形状）。

### 14.4 状态

- [x] 测试不再真实操作桌面；全量跑完垫片日志为空
- [x] `search` / `skills_save_local` 契约缺陷修复，模型侧调用可用
- [x] 新增全注册表契约元测试；两个历史 bug 有显式回归钉子
- [x] 回归：`python -m pytest -q` → **734 passed, 1 skipped, 1 xfailed**（含纵向 Agent 工具链测试；E0 期间为 703 passed）
- [x] `skills_save_local` 的平铺 `.md` 格式已由现有 `skill_parser` 支持；注册工具现在能完成“保存 → 本地发现 → 本地读取”，不再把这项能力误记为未接入
- [ ] 已知偏差（未做）：本次只修了 `search`/`skills_save_local` 两处**签名级**不一致；`filters` 之外未审计各工具 description 的语义准确性（元测试只保证非空与长度上限）

### 14.5 Agent 能力纵向验证（本轮补充）

契约测试只能说明 schema 与函数签名一致，不能证明模型真的能使用能力。本轮增加了从 PromptBuilder 到 ToolExecutor 再到真实 handler 的纵向回归：

- 普通信息请求的生产裁剪路径现在能暴露 `search`；模型发出的 `source="youtube"` 会穿过 AgenticLoop 和 ToolExecutor 到达 YouTube 后端，测试断言真实参数为 query/sort/limit，而不是只检查注册表字典。
- handler 返回 `{"success": false}` 时，ToolExecutor 会把失败传回 Agent（`ToolResult.success=False` 与错误类型），避免模型把结构化失败误判成成功。
- 重复任务触发自动沉淀时，测试经过真实 PromptBuilder/AgenticLoop，并验证 `skills_save_local` 实际落盘；同时覆盖 info/command 路由的提前返回分支。
- 保存后的技能通过注册工具 `find_skills` 本地发现，再通过 `skills_read` 本地读取正文，形成最小可验证的复用闭环。

这些测试仍不等同于真实云模型质量评估：模型决策由确定性 fake provider 驱动，网络搜索后端在测试中只替换为参数捕获函数。它们验证的是 Agent 执行链和能力接口确实连通，真实模型的选择质量需要后续离线评测集单独衡量。

## 15. 工具可见性策略与执行结果语义（2026-09-29，结构性修复）

§14 修了 `search` 被裁剪与执行器误报成功；本轮把这两点从"逐个打补丁"升级为**有不变量的策略**，因为同类缺陷是成批存在的。

### 15.1 发现：可见性缺陷不是一处，而是六处

对 34 个注册工具做覆盖审计（`registered − 所有路由可达集合`），结果是 **6 个工具在任何路由都不可见**：

```
fetch_content、memory_search、proactive_agent、search_and_open、tavily_search、tinyfish_search
```

其中 `memory_search` 是本项目（agent-memory）的记忆检索工具——模型从来没机会调用它；`tinyfish_search`/`tavily_search` 的描述却写着"首选使用"。根因是所有可见性都写死在 `PromptBuilder._select_tool_names` 的名字字面量里，新增/遗漏都无提示。

### 15.2 修复：可见性策略成为单一事实来源

新增 `core/tool_visibility.py`：`CORE`（每路由可见，含 `memory_search`）+ `BASE`（会话基线，含本地技能复用三件套）+ 能力组 `GROUPS`（web/browse/files/system/skills，按意图关键词激活）+ `CMD_BASE`/`INFO_DEFAULT`/`INFO_WEATHER`。`PromptBuilder._select_tool_names` 退化为策略调用，路由关键词与策略关键词合并为同一来源（消除此前两处关键词表漂移）。

三条结构性保证：

1. **全量分类**：`CLASSIFIED ⊇ 注册表`，未分类即测试失败；
2. **可达性**：每个注册工具都能被某个 (路由, 意图) 看到，不可达即测试失败；
3. **fail-open**：真的出现未分类工具时，仍然提供给模型（并 `logger.warning` + 在返回值里报告），使"漏登记"退化为多给一个工具，而不是静默删除能力。

结果：可达 34/34（修复前 28/34）；常驻面 `BASE` 15 个工具、`CMD_BASE` 22 个、info 面 5 个，均远低于工具选择准确率劣化的 30–50 区间。

### 15.3 修复：执行结果语义（ok / no_results / rejected / error）

§14.5 的第一版修复把所有 `success: false` 载荷一律记为调用失败，这会误伤**领域负结果**（`NoResults`/`NotFound`/`AlreadyExists`）：它们不是执行失败，不该把 Agent 推向重试/降级。现在 `ToolResult` 携带：

| 字段 | 含义 |
| :--- | :--- |
| `success` | 工具是否给出了可信答案（`ok`/`no_results` 为 True） |
| `outcome` | `ok` / `no_results` / `rejected` / `error` / `denied` / `needs_confirmation` |
| `tool_reported_success` | 载荷自身的 `success`，信息不丢失 |
| `error_type` | 工具错误码或异常类名 |

渲染统一收敛到 `render_history_line()`（串行路径与并行批次共用）：`no_results` → `[Tool: x] （无结果）…`；`rejected` → `[Tool Error: x] …（调用被拒绝：请修正参数或改用其他方式）`；`error` → 保留"请尝试替代方案"；`denied`/`needs_confirmation` 单独措辞。JSON 解析改为仅当结果以 `{` 开头时才尝试（工具结果可能是大文档）。

### 15.4 有意的行为反转（已在测试中标注理由）

- **command 路由现在包含 `search`/`smart_search`/`web_fetch`**。旧测试 `test_command_route_excludes_search_tools` 明确断言"命令路由不该有搜索工具"，导致"查一下资料并整理成文件"这类被分类为 command 的请求完全无法检索。该测试已改名为 `test_command_route_keeps_lookup_tools_available` 并写明反转理由；浏览器类工具仍由意图关键词控制，不会随命令路由静默放开。
- **纯 info 请求保持最小面**（5 个工具，且永不包含 `open_*`）；但**特定意图**（技能/文件/系统）不会再被一个"搜索"关键词吞掉——"帮我搜索并安装一个技能"会带上技能工具。
- `tinyfish_search`/`tavily_search` 的描述不再自称"首选"，改为说明它们是 `search`/`smart_search` 的后端，模型侧入口与 `BEHAVIOR_RULE` 一致。

### 15.5 新增测试与状态

- [x] `tests/test_tool_visibility.py`（17 项）：分类完整性、可达性、fail-open、日志、常驻面预算、route×tool 矩阵（search 三路由可见 / memory_search 可见 / 本地技能三件套可见 / 远程安装与截图仅特定意图 / 天气不给浏览器 / command 能搜索）、经真实 `PromptBuilder.build()` 的端到端可见性
- [x] `tests/test_tool_outcome_semantics.py`（16 项）：载荷分类表、真实工具经执行器的语义（拒绝 / 无结果 / 异常 / 保存→已存在）、渲染措辞、以及经真实 `AgenticLoop` 断言**模型实际读到的文本**（拒绝是错误、无结果是正常答复）
- [x] 回归：`python -m pytest -q` → **770 passed, 1 skipped, 1 xfailed**；PATH 垫片日志为空（零真实桌面副作用）

### 15.6 对 §15 修复本身的自审（对抗性复核）

本轮改动完成后又做了一次针对自己产出的审计，发现并关闭 6 个问题：

| # | 自审发现 | 性质 | 处置 |
| :--- | :--- | :--- | :--- |
| 1 | 可达性测试对每条语料硬算 info/command/chat 三条路由，可能"自证"（某工具只在 `classify_route` 永不产生的路由下可达） | 测试有效性 | 改为用真实 `classify_route` 计算；复算仍 34/34，且确认无"仅假路由可达"的工具 |
| 2 | `CLASSIFIED` 含未注册的 `web_search`（幽灵项） | 策略卫生 | 显式声明 `ALIAS_SLOTS`（MCP 别名槽）并加断言：`CLASSIFIED − 注册表 ⊆ ALIAS_SLOTS` |
| 3 | `_REJECTED_OUTCOME_CODES` 定义后从未使用 | 死代码 | 让其生效：已知拒绝码 → `rejected`，未知失败码 → 新增 `tool_error`（渲染措辞不同，便于监控区分"可修正"与"工具坏了"） |
| 4 | 未分类工具的 fail-open 告警每次请求都打一次 | 运行期噪声 | 改为每个工具名告警一次，并加测试断言 5 次调用只出 1 条 |
| 5 | `prompt_builder` 里 `_TOOLS_CMD/_TOOLS_BASE/_TOOLS_WEB/_TOOLS_OPEN/_TOOLS_FILE/_TOOLS_SYSTEM` 已成死常量（仅测试引用） | 死代码 + 漂移风险 | 删除，测试改从 `core.tool_visibility` 断言策略常量（兼容别名本身就是上次漂移的温床） |
| 6 | `history_line()` 定义了但 loop 未用；另有三处特化分支（weather/web_fetch、info/smart_search、fs_apply 预览）仍手写 `[Tool: …]`/`[Tool Error: …]` | 语义分叉 | 三处统一走共享渲染器；`history_line()` 保留为 ToolResult 的公开 API 并注明 loop 为何用模块级函数（需兼容 duck-typed 结果）；现"直写工具行"残留为 0 |

复审计结果：真实路由可达 34/34、幽灵项 0、死常量 0、告警 1 次/5 次调用、分类表 `rejected|no_results|tool_error` 三态齐备、渲染分叉已消除、直写工具行 0。

同时确认影响面受限：当前只有 2 个工具会发出"良性码"（`search_and_open` → `NoResults`，`skills_save_local` → `AlreadyExists`），其余良性码是预留词汇；info 回退路径调用的是 `smart_search`，其失败码属 `rejected`，语义未变。

- [ ] 已知偏差（本轮发现，未做）：**回合内工具观察不会跨回合留存**。实际 `SessionManager.get_history()` 返回新列表，不论会话是否为空，循环内追加的工具观察都不会自动写回 session；`core/server.py` 只在回合结束后记录最终 user/assistant。此前 `_RecordingSession` 返回共享列表，不能代表实际会话行为；§16 已把结果语义测试改为检查模型下一次调用收到的 messages。跨回合持久化属于独立的 transcript 语义变更，尚未实现。
- [ ] 已知偏差（沿用）：元测试只保证 description 非空与长度上限，未审计其**语义准确性**（本轮顺手修正了两个搜索后端的描述，其余未逐一核对）

## 16. DeepSeek 改动复核与 E1 首个验收点（2026-09-30）

### 16.1 复核发现与修复

§15 的可见性策略和结果渲染统一可以保留，但针对性测试通过并不代表所有具体任务可用。本轮先写回归，观察到 4 项失败，再修正：

- `CORE` 宣称每条路由都可见，但 info/weather 分支没有使用它，`查一下我之前提过的研究方向` 看不到 `memory_search`。现在信息路由也保留记忆入口。
- `搜索视频处理技能` 会被分类为 info，只暴露远程安装工具，没有本地 `find_skills/skills_read/skills_save_local`。技能意图组现在包含这三个本地入口。
- `skills_save_local` 拒绝覆盖时返回 `AlreadyExists`；原分类却把它改成 `success=True`。这是一次没有完成的写操作，应为 `rejected/success=False`，模型可读取既有内容或明确请求覆盖。`NoResults` 的正常空查询语义保留。
- 原结果语义测试读取特制 session 的共享列表，未验证模型真正收到观察。现使用真实 `SessionState`，检查下一次 `generate(messages=...)` 中的工具结果，不依赖 session 被循环直接修改。

§15 中 info 面“5 个工具”、`AlreadyExists` 属于成功、`_RecordingSession` 能代表真实会话的说法均由本节修正。桌面默认注册表的普通 info 面现在为 6 个有效工具；候选注册表若绑定可执行技能，还可提供两个稳定执行入口。

### 16.2 E1 已交付：候选绑定的可执行技能

新增 `core/evolution/skills.py`、`sandbox.py`、`tests/test_evolution_skills.py`；`requirements.txt` 显式声明 JSON Schema 校验依赖 `jsonschema>=4.18,<5`。

manifest v1 格式：

```json
{
  "version": 1,
  "skills": [{
    "skill_id": "normalize",
    "description": "normalize record fields",
    "parameters": {"type": "object", "properties": {}, "required": []},
    "entrypoint": "normalize.py:run",
    "digest": "<sha256>"
  }]
}
```

`digest` 算法：对 `skill_id/description/parameters/entrypoint` 四项按 `sort_keys=True, separators=(',', ':')` 规范化 JSON 编码，接一个换行和入口 Python 文件原始字节，再算 SHA-256。当前支持单文件、标准库技能；其他文件与依赖封装留给后续 bundle/container 实现。

`SkillCatalog.from_bundle()` 校验 manifest、schema 与 digest，并快照代码字节。每个候选注册表只注册 `skill_search/skill_call`；搜索返回描述、参数 schema 和 digest，调用必须指定同一 digest，参数先经 JSON Schema 验证。目录后续被修改不会改变已加载的技能；重新加载则拒绝摘要不匹配。

`ProcessSkillRunner` 使用独立 Python 子进程和 JSON 文件协议，任务工作目录作为 context；结果与 stdout/stderr 分离，限定墙钟时间和结果读取大小，完成或超时后清理子进程组。这是可信预制技能的 process 模式，**容器模式尚未实现，不能把它记为生成代码的 OS 沙箱**。

`KageChainProvider(..., skill_catalog=catalog)` 将候选私有技能加入每次任务的注册表。记录实际 `skill_id/digest`，metadata 保留完整技能映射。E0 resume fingerprint 现在包含模型、模式、调用限额及实际技能映射；换技能代码后复用同一 run_id 会被拒绝，不返回其他版本的旧评分。

### 16.3 验收证据与下一执行包

6 个 E1 行为用例覆盖：manifest → 模型读到发现结果 → 子进程实际写文件；重载后在未见输入复用；父候选不可见子技能；代码篡改与运行快照；参数与 digest 错误不执行；超时后下一调用正常；真实 KageChainProvider 接入；外部评分为 1.0；相同 run 不重复执行；换实际技能版本拒绝缓存命中。模型由确定性 fixture 驱动，Python 技能执行、文件输出、执行器、评分器与 journal 均使用真实实现。

验证：`python -m pytest -q` → **778 passed, 1 skipped, 1 xfailed**，54.25 秒；结果语义测试随后再跑 **17 passed**；`git diff --check` 无错误。没有运行付费 API，也没有宣称完成自动进化。

下一包继续 E1：实现模型生成器 `mutator.py`、失败轨迹 → 修改假说 → Python/manifest 候选；接 ARM64 容器执行；再做配对 dev 评分与 `promotion.py` 原子激活。必须保留本轮已打通的真实执行与外部评分链，不用模型总结或文件落盘代替能力晋级证据。

## 17. E1 生成、容器执行、评分晋级与 CLI（2026-09-30）

### 17.1 当前交付状态

E1 代码链路已完成，§16 的下一执行包现由本节交付。**付费云端的两候选试验尚未通过**：本机现有配置指向不可达的测试端点，实测连接拒绝；已记录为基础设施失败，CLI 返回退出码 3，不切换到 fixture。不将本节的演示结果作为真实模型自主发现技能的研究证据。

新增 `core/evolution/mutator.py`、`promotion.py`、`artifacts.py`、`search.py`、`fixtures.py`、`sandbox/evolution/Dockerfile`、`eval/evolution/pilot.json` 和对应行为测试；CLI 已支持 `search`。

### 17.2 实现机制

- `Mutator.propose(parent, feedback)` 调用项目现有 ModelProvider。只发送用户指令、Agent 可见的 action/observation 与失败摘要，剔除隐藏评分字段；输出必须包含修改假说、技能名、描述、参数 schema 和 Python 源码。先校验语法、manifest 与 schema，再生成内容摘要绑定的候选目录。父候选文件不被改写。
- 初始生成后最多修复两次；无效响应、校验错误、usage 和修改事件都保留。optimizer 与 execution 共用预算，分账户记录。每个生成槽位保留请求摘要、尝试日志与已完成候选；恢复不重生成已完成候选，修复次数也不会因重启归零。
- `DockerSkillRunner` 每次调用创建一个独立 ARM64 容器；任务目录与临时运行协议目录作为挂载。容器禁止网络、根文件系统只读、限制 CPU/内存/进程数。按实际 image ID 执行，超时会停止容器而不仅是 Docker CLI；下次调用创建新容器。generated live 模式不回退到宿主 process。
- `Promoter.compare` 只接受显式 `split=dev` 的任务，父子使用同一任务、seed、步骤和超时配置，由 E0 评分器检查真实文件。只有平均分严格提高、每项任务不退化、且不存在超时/崩溃/预算中断，才原子更新活跃指针。比较记录持久化；外部评分失败的候选不会因 Python 能运行或局部示例成功而晋级。
- `search` 先运行基线，选择失败 dev 任务生成候选，再配对比较、激活与原任务重试；`reuse` 任务只在候选搜索结束后评价，不进入优化器或晋级判据。报告、日志、预算和 active 指针按 provider/experiment/seed 隔离。
- 恢复检查锁定任务协议、有效模型配置摘要、技能 digest、执行后端/超时/结果限制与容器 image ID。凭据不写入协议。基础设施失败退出码为 3，任务评分失败仍是实验数据。更换实验条件须使用新的 experiment_id/输出目录，保留原始失败记录。

本轮同时修复两处预算问题：一条 Agent 链包含多次模型调用时，之前只记一次；缺失 provider usage 时，之前聚合为零 token。现预留链的调用上限、结算实际调用数，并持久化；缺失用量按 token 预留上限结算，保留实际调用次数。旧数据库兼容迁移中已有记录只能保留原有单次计数假设，不能据此声称重建了历史实际调用数；研究测量使用新实验目录重跑。

### 17.3 实际验证与报告

本机 OrbStack 已启动，`docker info` 确认 `linux aarch64`。实际构建并执行 `kage-evolution:local`，image ID 为 `sha256:8e525133f765d7b7fef855c007f43bfcaf7fa6dc6e91f7ec705be6b60877f418`。容器测试验证真实文件输出、两个工作区隔离、每次调用模块状态重置、超时清理和下一次调用正常；验证结束无残留 `kage-skill-*` 容器。

真实命令：

```bash
docker build --platform linux/arm64 -t kage-evolution:local sandbox/evolution
python scripts/kage_evolve.py search --config eval/evolution/pilot.json --provider fixture
```

报告：`runs/evolution/search/fixture/pilot/seed-42/report.json`。测得 dev 平均分 **0.5 → 1.0**；一项未见输入 reuse 分数 **1.0**；实际执行链共 **17 次模型 fixture 调用 + 1 次 optimizer fixture 调用**。达到 dev 全通过后提前停止，没有为了凑“两候选”再生成无必要候选。活跃技能重启后 digest 一致；再次执行同命令不增加预算调用数。

最终回归：`python -m pytest -q` → **790 passed, 1 skipped, 1 xfailed**，59.98 秒；真实 Docker 集成用例本次实际执行，未被跳过。`git diff --check` 无错误。

这里的模型决策和生成代码由明确命名的 fixture 提供，Python、容器、Kage AgenticLoop、文件副作用、外部评分、晋级与恢复均真实执行。另有真实 `OpenAICompatibleProvider` + 本地 HTTP 端点的优化器测试：API 响应生成可执行候选，provider 上报 113/71 tokens，账本精确记录为 optimizer 账户，实际技能处理未见输入成功。

`pilot.json` 设置 max_candidates=2、max_api_calls=50、input=150000/output=30000、费用规划上限 $0.25。其输入/输出费率是规划系数，非官方报价；fixture 报告金额没有真实 API 支出。live 连接拒绝记录中的保守预算金额也不是已确认的账单。

### 17.4 后续执行顺序

1. 将现有不可达测试端点替换为可用云模型配置，核对计价并用新的 experiment_id 跑小规模 live 试验；如果基线本来就全部通过，报告“无需生成”，不人为降级基线制造成长。
2. E2 建立候选/失败经验档案与按环境版本过滤的检索，保留本轮完整谱系、假说、费用和外部评分证据。
3. E3 抽出可修改 recovery 模块，让能力成长从“新增技能”进一步进入 Agent 自身策略演化；真实外部评分改进后才激活。

E1 已验证单文件标准库技能；依赖安装、多文件模块、并发搜索和跨回合工具观察持久化未实现。当前恢复和原子指针按单搜索 worker 设计，未宣称多进程并发更新安全。

## 18. E0/E1 提交前复审与状态语义修复（2026-09-30）

### 18.1 评审结论与范围

DeepSeek 提出的死分支、测试 docstring 漂移、本地技能重复定义成立；已删除旧的 `no_results+AlreadyExists` 渲染与手工断言，修正文档并抽出 `LOCAL_SKILL_TOOLS`。info 路由仅在技能意图下开放本地三件套，chat/command 常驻，原因已写入策略注释。`len(INFO_DEFAULT)<=8` 原本已有断言，不新增重复测试。

当前 E1 得分由外部评测器检查输出文件决定，晋级不按工具错误次数扣分，且执行技能使用 `skill_search/skill_call`；“AlreadyExists 系统性低估 E1 得分”已撤回。修复解决的是诊断证据丢失，不声称提高外部分数。

### 18.2 状态语义端到端

工具载荷可显式声明 `outcome`，分类器优先采纳已知且与 success 一致的值，否则返回可观察的 `InvalidOutcome/tool_error`；没有显式值的旧载荷仍使用错误码表。`ok` 已允许附加载荷字段，`err` 新增可选 outcome。

`skills_save_local` 将现有文件字节与待写入的完整 frontmatter/正文比较：相同返回 `unchanged/success=True`，文件内容与修改时间不变；不同且未允许覆盖返回 `not_applied/success=False`，提示 overwrite=true。它不会将任意重复保存自动判为成功。

Agent 串行、并行与自动技能操作保留 outcome 和 tool_reported_success；`KageChainProvider` 归一化不再丢弃这些字段，runner 的 observation/journal 保留明确状态、success 与载荷原始 verdict，ToolExecutor 的 JSONL 日志同样记录。外部评分方法保持原样。E1 的 `UnknownSkill/DigestMismatch/InvalidArgument` 显式声明 rejected，旧错误码表兼容这些代码。

`tests/test_tool_state_outcomes.py` 使用真实保存、AgenticLoop、ToolExecutor、KageChainProvider 和 journal，断言模型实际读到状态、磁盘未重写与落库字段一致；在修复前的独立 E0 快照三个用例均失败，修复后通过。

### 18.3 E1 独立审查发现与修复

独立审查复现：模型响应已保存但 proposal.json 尚未发布时中断，原 Mutator 重启把有效响应误当失败，可能再次付费；若是第三次响应则直接丢弃有效候选。尝试记录更新也原本使用非原子写入。

现尝试记录均原子写入；重启先重新校验尚未完成发布的已保存响应，再决定是否进行下一次模型调用。首次和第三次有效响应均可恢复，保留原预算与修复次数上限。四个回归覆盖“响应保存后中断”和“发布前中断”，恢复后实际执行技能处理未见输入成功，调用次数不增加。独立复审另注入比较记录、激活指针及搜索进度之间的中断，恢复后活跃候选与报告一致，未重复调用模型。

E1 的真实 Docker 隔离、外部配对评分、拒绝退化、未见输入复用与显式 fixture/live 区分保持验收；付费云端试验仍未完成，不能将工程闭环或 fixture 成绩作为模型自主进化有效的研究结论。

### 18.4 最终验收与提交边界

不含 E1 的语义修复暂存快照全量回归：**777 passed, 1 skipped, 1 xfailed**，63.22 秒。技能执行/ARM64 容器子提交的独立快照：**22 passed**。完整 E1 暂存快照全量回归：**799 passed, 1 skipped, 1 xfailed**，83.32 秒；包含真实 Docker 用例，本次未跳过。现有 pygame/pkg_resources 弃用告警不影响测试结果。

本轮另在新实验目录实际复跑 Docker fixture CLI，报告位于 `runs/evolution/search/fixture/e1-prepush-2026-09-30/seed-42/report.json`。配对 dev 平均分 0.5→1.0，未见输入 reuse=1.0，模型 fixture 调用 17 次、optimizer fixture 调用 1 次。新目录的这些结果来自本轮执行，不是旧报告缓存；金额为合成用量与规划费率的估算，没有付费 API 支出。

提交分成：状态语义修复；候选技能与容器执行；生成/评分晋级/断点恢复/CLI；规划与复审记录。E0 既有五个提交保持独立，便于按依赖顺序回退。实际实验报告是本机产物，不提交 journal、私有设置或凭据。

