# 执行交接：浏览器学习闭环与后续E/C顺序

日期：2026-10-03；审查基线da5f675。本文是实施规格，下面新增接口/命令对应的功能尚未实现。E/C全部状态以[任务队列](task-queue-2026-10-01.md)为准，发现代码与计划不同先核对再修改。本轮只更新文档。

## 0. 开始工作：只读最小材料

1. 读总规划、任务队列及本文中领取包，不要加载全部历史论文/实验。
2. 主仓库`/Users/wenbo/Kage`；已有活动worktree`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage`，分支`codex/c2-learning-loop`。先查两处`git status --short`和HEAD，复用干净且最新的worktree，不覆盖其他模型修改。
3. 可选浏览器Python为该worktree的`.venv-computer-use/bin/python`；系统python3不能假定兼容。私有云配置在`/Users/wenbo/Kage/artifacts/private/deepseek-settings.json`，只读取、不打印、不复制到日志。原始实验在worktree的`artifacts/`，主仓库没有这些完整数据不是丢失。
4. 每包独立代码提交和报告提交，记录父HEAD、代码/模型/协议hash、成功/失败、费用和下一项。先完成当前包验收再领取下一包。保留原始数据；尚无证据迁移工具，不能归档这个worktree。
5. 旧`browser-learning-v2.json`及A的holdout已跑过；可做回归，不称新盲测。首次新留出必须在生成候选之前冻结，生成器/示范检索不消费其内容或反馈。

## 1. 本次审查改变了什么

- B2.1不再是一句话“示范转技能”：拆成下面0/a/b/c四个独立提交边界。
- 先修复真实链路中错误观察丢失，再适配浏览器档案、活页面技能，最后运行真实生成；不通过反复自然失败抽样等待一条好示范。
- 采用小型声明式浏览器工作流。候选生成动作规则，由同一个可信browser worker解释；复用E1的Candidate、digest、Journal、预算、Promoter，不把Playwright Page传进Docker、不建立第二套晋级系统。
- B2.2先分开“模块能执行”“真实生成/调用”“新输入迁移”三层证据。云救场单列额外预算；多步技能每个实际动作计数。
- B2.2后提前接入最小任务入口与人类DOM示范。E2/E3/E4研究线可在浏览器闭环后独立领取，不必等全部GUI完成。C6/C8和训练继续按瓶颈/数据启动。

## 2. B2.1-0：错误返回必须把新观察送到模型（已完成，见[报告](../experiments/2026-10-03-browser-error-observation.md)）

**已复现：** BrowserAdapter返回`StaleObservation`时附新observation；ToolExecutor的`render_history_line`仅保留错误码/文字，AgenticLoop实际消息缺新observation_id。2026-10-03真实headless页面探针确认raw有观察、history没有。BROWSER_SOUL却要求使用错误内新观察，二者矛盾。

**文件：** 修改`core/tool_executor.py`的错误渲染（保持无结构化结果时原行为）、必要时调整`core/computer_use/context_pack.py`；扩展`tests/test_browser_takeover.py`、`tests/test_browser_context_pack.py`与`tests/test_tool_outcome_semantics.py`。不要通过把失败改成success绕过。

**步骤与验收：**
- [x] 先写经过BrowserAdapter→ToolExecutor→AgenticLoop→下一次provider消息的真实浏览器回归：观察后替换节点，旧引用被拒绝、无误点击；模型收到新观察并能对新引用执行成功。直接测试adapter返回字典不够。
- [x] 错误结果采用明确可解析的结构化载荷，保留error/outcome/message/action_applied/observation；原生tool_call_id不变。更新打包器识别该真实格式，最新错误观察不得被当旧DOM丢掉。
- [x] 验证普通工具错误兼容、JSON异常不抛出二次错误、超时且action_applied未知仍保持未知；打开/关闭打包均可恢复。
- [x] 同包验证compact-v1下checkbox缺checked的约定：仅该版本明确解释为false，不把value="on"当勾选；本包不修改观察格式。若要改为显式false，另立协议版本并给各实验臂一致启用。
- [x] 聚焦命令：`.venv-computer-use/bin/python -m pytest -q tests/test_browser_takeover.py tests/test_browser_context_pack.py tests/test_tool_outcome_semantics.py tests/test_tool_conversation.py`。触及共用executor后再跑全量一次；不调用付费模型证明消息是否丢字段。

完成后独立提交修复和报告，再进入a。

## 3. B2.1a：浏览器episode与生成输入桥接（已完成工程桥接，见[报告](../experiments/2026-10-03-browser-episode-bridge.md)）

**现有缺口：** `ExperienceArchive.record`的setup不含fixture；failure_status读取`student_check.status`，浏览器使用student_state/student_check_passed/student_chain；`scripts/experiments/skill_learning.py`找teacher_check.check_passed，不能直接复用浏览器数据；browser脚本尚未导入archive。

**文件与拟新增接口：**
- `core/evolution/archive.py`兼容增加browser fixture/setup和实际actor trace引用，不改已有episode身份/历史文件；旧记录采用新派生索引，不能覆盖旧payload。
- 新建`core/computer_use/episodes.py`：`normalize_browser_episode(task, result, workspace) -> dict`和`generation_feedback(episode) -> dict`；复用ExperienceArchive的持久化/去重入口，避免平行数据库。
- 新建`scripts/experiments/browser_skill_learning.py`的准备阶段；`tests/test_browser_episodes.py`与既有`tests/test_experience_archive.py`覆盖读写/重启/过滤/证据投影。

**归一化内容：** environment_kind、fixture/schema版本、任务family/split、学生stop_reason/模型错误、学生外部通过布尔、教师是否尝试/是否实际动作、最终外部通过、actor分段、原始路径/hash。不要把网络超时映射成“技能缺失”。模型超时文本可能使stop_reason=model_returned，诊断还须读取model_errors。

**证据与生成输入分层：** 审计层保留checker/score/后台/所有失败；生成层只允许公开instruction、相关当前/前后DOM、实际动作参数、可见工具结果与错误、来源hash和actor。fixture仅供可信reset，禁止把整个fixture/task_def/evidence目录塞给生成器。实际页面和可见保存结果可用；隐藏expected、checker文件、评分摘要及未见任务一律不输入。`_visible_feedback`按键删除不能替代白名单，尤其别给模型能读完整workspace的入口。

**示范来源规则：**
- B1 `artifacts/c21-browser-takeover-v1/workspaces/run_preferences_dev-2/`：教师只observe+Save，完整“设置偏好”操作的Email/SMS由学生执行。teacher-only轨迹只支持续做保存技能；完整混合actor轨迹可以作为另一种来源，必须标`source_kind=mixed_student_teacher`，不称纯教师示范。
- B1阶段teacher_check_passed=false但最终score=1是已记录的读回竞态。可以在派生记录按最终结果、actor动作和读回hash核验，标`legacy_final_verified`；不能改写旧阶段标志或默认丢掉唯一成功示范。
- B2.0b没有成功多步教师轨迹。若完整技能需新示范，使用预先定义的dev失败状态恢复探针（例如错误设置已保存），固定最多3次真实教师运行；这是受控恢复实验，单列于自然学生失败率。失败保留，额度耗尽无成功则标阻塞在示范验收，不能无限重试。
- 可以先用预制动作计划做运行时测试；它不是云生成成果。纯学生成功示范也有用，但必须单独标来源。

**验收：** 同一setup真实重建页面并读回；实际actor-tools/browser.jsonl入证据；旧格式与browser过滤均正确；失败/holdout不进正示范；证据改动后失效；生成器可见输入用独立sentinel检查不含checker秘密。不根据示范重复次数虚增训练样本数。新候选生成前冻结B2.2测试manifest/hash。

## 4. B2.1b：同一活页面上的参数化浏览器技能

**选择与范围：** 初版支持表单和checkbox、唯一语义目标、顺序步骤；不做任意Python/JS注入、跨域登录、规划语言或递归技能。E1文件Python技能和Docker执行仍沿用原路径。浏览器技能属于L1程序性技能，不能算E3核心源码自修改。

**文件/接口：** 新建`core/computer_use/skills.py`，提供`BrowserSkillCatalog.from_bundle(path)`、`search(query, limit)`、`register_tools(registry, adapter, executor, workspace, quota)`；向现有browser registry注册同名稳定`skill_search/skill_call`，每个registry内只有一种相应handler。`skill_call(skill_id, digest, arguments)`为async，返回outcome、实际子步骤、最新观察和执行证据。修改`BrowserChainProvider`显式接收`browser_skill_bundle=None`并在创建Page后绑定；metadata/cache同时记录实际加载digest和解释器hash，不能仅继承文件catalog元数据假装已接通。

**建议协议：** manifest v2带`kind=browser_workflow`；描述、parameters JSON Schema、workflow语义一起计算digest；未知version/kind明确拒绝。v1文件manifest保持兼容。示例只定义表达能力，不是手写后冒称模型生成的最终技能：

```json
{
  "version": 2,
  "kind": "browser_workflow",
  "skills": [{
    "skill_id": "set_preferences",
    "description": "Set named checkbox preferences and save the page",
    "parameters": {"type":"object","properties":{
      "settings":{"type":"array","maxItems":8,"items":{"type":"object","properties":{
        "label":{"type":"string"},"checked":{"type":"boolean"}},"required":["label","checked"],"additionalProperties":false}},
      "save_label":{"type":"string"}},"required":["settings","save_label"],"additionalProperties":false},
    "workflow": [
      {"op":"for_each","items_param":"settings","step":{"op":"ensure_checked","label_item":"label","checked_item":"checked"}},
      {"op":"click","label_param":"save_label"}
    ]
  }]
}
```

descriptor的digest由工具生成并写入，不让调用方随意指定；实现时同时限制workflow结构深度/步数，首版for_each只遍历最多8项、不能嵌套。另支持`fill(label_param, value_param)`以覆盖profile；不添加不需要的表达式解释器。

**执行规则：** 每步从新观察按语义label及控件类型唯一解析，不保存e1/旧observation_id/URL端口/固定坐标；缺失/歧义返回not_applied。ensure_checked比较真实checked，只在不同才click，已满足返回unchanged。每个实际动作通过既有ToolExecutor/BrowserAdapter，随后重新观察/checkpoint；失效引用只允许重新观察后重新解析一次，计入同一预算，不重复不确定已应用的提交。最后由原外部Evaluator决定任务通过；workflow自己不能宣称评分通过。

**预算：** 在可信执行层增加共享primitive quota，raw/trajectory/skills/retries均为每次运行最多16次browser工具调用（含observe、wait、失败尝试，运行时强制初始/动作后观察另记次数与耗时），父子同上限。skill_call本身占一次模型工具调用，其内部动作不能被隐藏为零。保持本地6模型调用/5循环步、总时间沿用冻结协议；教师最多另6调用且另16 primitives，报告合计，云臂为额外算力参考。超过quota先拒绝下一个动作，保留已发生动作和产物；组合调用不能重置预算。

**真实浏览器回归：** 先红后绿验证同页执行、不同初始勾选状态、已满足无反向toggle、label重排、无/重复目标、节点替换、错误保存后修订、迟到保存、步骤耗尽及停止后无继续点击；记录每个子动作actor/skill_id/digest/parent_call_id。用既有`tests/test_browser_dom.py`/`test_browser_takeover.py`并新增`tests/test_browser_skills.py`，验证从模型可见schema→skill_call→真实HTTP保存→独立检查完整链。

**防止元数据假接通：** 空catalog、错误digest、不兼容bundle和未注册handler均明确失败；不通过读取fixture.expected或直接写backend.json完成任务。恢复模块没有接入此browser链时metadata应标未启用；不要因为父类有recovery_policy字段就宣称浏览器已自修改。

## 5. B2.1c：真实生成、真实本地调用、开发变体验收

依赖0/a/b工程通过。新增`BrowserWorkflowMutator(Mutator)`（放`core/computer_use/skill_mutator.py`），仅覆盖消息、父catalog验证、提案验证/应用：输出hypothesis/descriptor/workflow，保留E1的预算、attempt落盘、父digest、候选发布和Promoter。不能直接使用Mutator现有“生成Python写workspace”提示，也不能让SkillCatalog.from_bundle硬验证v2。

- [ ] 从a选一份已核验dev示范，manifest标来源类型。先生成preferences一族，至少一个不同初始状态/标签的dev-reuse；候选生成前冻结测试集，不读取它来修候选。
- [ ] 初提案+最多2次格式修复，共最多3次云调用；每次完整请求≤12000字节、输出≤3000tokens。计费按运行时核验价格预留，单族生成总上限$0.05；达到上限保留失败并结束本协议，不追加隐藏人工修复。
- [ ] 父空browser-workflow v2 catalog和子catalog均走同一浏览器执行链、相同目标/观察格式/完成门控/发现策略/本地模型/预算。工具集合差异是候选能力的一部分，单独记录；若使用descriptor preview，结果称“技能+发现策略”，不单独归因源码。
- [ ] 每个候选dev父子各3次、dev-reuse子代3次，记录实际skill_call及子动作，关闭学生云回退。保存重启后再读digest并至少一次复用已有dev-reuse；所有额外请求计费。单族一候选至少10个本地run（6配对+3reuse+1重启），预算按此预留，不能照抄旧脚本36调用的全局上限。
- [ ] 先最小扩展`core/evolution/promotion.py`：`evaluate(..., repeat_id=None)`将非空repeat_id纳入run_id；`compare(..., repeats=1)`在不同task内遍历repeat，全部pair完成后汇总，只写一次active。新增`kernel_max_steps=5`保持旧默认，浏览器调用显式设为1，`step_isolation="fork"`、timeout_s=480。原默认inline没有强制中断。当前BrowserChainProvider总返回finish，实际不会因max_steps=5自动重启；显式设1用于锁定单会话协议，防止未来非finish分支重复创建整条链。
- [ ] 固定repeat_id=0/1/2；不同repeat真实执行，同repeat重启才命中缓存。不把同Promoter重复evaluate得到的同一run算三次；seed仅有记录不代表API实际接受采样种子。比较按task×repeat的原规则：全部status合法、逐pair无回退、总体child均分严格大于parent才晋级。重复身份、协议hash、失败/超时和三次汇总均落盘；原单次协议默认兼容。新增回归验证三次实际调用、同repeat恢复零重复收费、kernel step=1及worker超时清理。
- [ ] 使用原Promoter；均分相等不谎称晋级，父已满分可另报调用/token差异，但不能偷改晋级规则。成功调用与任务通过都满足才能记“真实技能链通过”；未提升仍交付实验负结果。
- [ ] 本包单族成功或负结果都先报告。若要对第二族profile执行，沿用相同协议、另列固定预算及提交；不因第一族不成功而换简单任务掩盖失败。

报告区分：运行时通过、生成提案是否有效、学生是否发现/调用、实际完成率、参数变化迁移、未知usage、一次性学习成本和每次执行成本。网络错误计入实用端到端结果，另列诊断，不能静默剔除或无上限重试。

## 6. B2.2：新留出五臂与研究结论

生成前冻结`eval/computer-use/browser-transfer-v1.json`（新建，当前不存在）与方法预算。开发可见任务和test manifest分开传入；旧A/B1及旧holdout仅回归。若留出失败后用于改进，标exposed并下一版更换盲测，保留原结果。

起步每个已完成开发族3个未见变体（内容/初始状态/控件顺序，至少一种超出纯改名），每臂每变体3次：单族45 runs；两族90 runs。小模型顺序运行，先估算wall时间及本地热压力，固定样本数后不以结果好坏中途增加。只有一族可执行时明确标单族pilot，不阻塞首轮交付，也不称通用迁移。

五臂：raw、cloud takeover、dev trajectory、learned workflow、local retries。非云四臂同模型、同调用/primitive/time/单次max_output上限；重试共享额度且在同状态继续。现BudgetTracker在整条chain前预留/结束后结算，MeteredProvider只限制调用数，不能把同BudgetConfig声称为严格累计token上限。本轮token是实测成本与名义预留，超预留/未知usage单列；若要作严格token匹配结论，另在E6实现逐调用累计输入预检/输出预留及未知usage停机控制后再跑对照。云臂单列额外教师上限与费用。所有臂统一external_completion和compact观察协议；教师打包只对cloud臂教师生效，本地上下文策略全臂一致。学习臂单列生成成本；云接管发生率和学生独立通过率分开。

主指标外部真实完成率；另报模型/primitive/观察次数、输入输出token、墙钟、请求时间、超时类型、云费用区间与学习成本。列逐任务结果和原始分母，不拿3次重复作统计显著性。对成功候选追加预算匹配的人工固定工作流参考，用来判断收益来自一般动作合并还是学到的规则；预算不够则将其列E6待验，主报告明确归因限制。

在新状态中检查失败恢复与回归，不把skill_call返回success计为完成。结果不提升仍完成实验任务，能力提升项保持未验收。

## 7. B2.2之后：默认领取顺序与条件支线

1. **C5.0最小集成（新增子包，属于原C5）**：在现有任务入口/事件通道提供显式实验浏览器模式、执行器选择、运行ID/结果/费用/停止；先验证用户发起任务能走已验收链。当前CLI fixture功能不等于日常Kage已启用。复用core/server.py与现有前端，不重做桌面平台。只有实现了对应任务检查器才可自动标completed；任意网页没有可靠检查时标unknown/待人工确认，不能把fixture的隐藏评分文件当通用完成检测器。
2. **C4.5-DOM**：主动开始/结束示范，记录真实DOM与动作、用户修正，转同一episode/workflow协议；在另一个输入复验。先实现用户能教一次，不等所有原生能力完成。
3. **C1.2 → C4.5-AX → C2.2**：macOS窗口/AX文档保存重读，再原生示范，最后浏览器/原生/跨应用各4项起步集。每类至少包含一项可可靠重置/检查的真实应用任务，使用专用测试文档/数据；无法重置的外部网站任务先列探索。fixture研究成绩、真实应用受控成绩和探索记录分表；不要只换12份本地网页内容称通用电脑评测，更不能称人类级通用能力。
4. **E2.1 → E3.1 → E4**：可从B2.2完成后独立领取的研究线。先补候选谱系、兼容性与迁移证据；扩展recovery到第二失败类型，再开放一个planner/retrieval/workflow模块；最后同预算比较规则/均匀/历史收益路由。每次只开放一个演化变量，不因电脑适配无限拖后自演化研究。
5. **E5/C5完善 → E6**：真实版本diff、谱系、成本展示，更多任务族/种子、退化与消融、可重算英文报告。最小集成已提前，不等论文评测结束才有可用入口。
6. **E7条件启动**：先核验可用GPU和当前学生训练/导出支持；足量去重且多样的已验证轨迹+族隔离留出后训练LoRA。100–500是启动目标，不是自动合格标准；不同学生的可行性实验不冒称Agents-A1升级。

C6仅在DOM/AX覆盖缺口出现时；C8仅在同权重兼容和任务时间证据充分时；C7按当前长轨迹瓶颈逐包改；C3/Jev API可选且Jev自训暂缓。实施时再核验模型/接口/价格，不把2026-10-01的外部信息当永久事实。

## 8. 交付与停止规则

每包输出：实现提交、报告提交、实际命令和环境、验收层级（工程/模型pilot/迁移/研究）、原始路径/hash、失败与未完成项、下一包。只改文档不重跑全量模型实验；改共用执行器需聚焦+一次全量，模型推理时不并行跑重测试。脚本化动作是真实浏览器回归，不是AI成绩。

固定协议遇网络/模型/预算失败照常保存并继续剩余预定样本，不能不断重跑到成功。没有可用证据就交付明确缺口与剩余额度，不把“实验已执行”写成“能力已实现”。主仓库与worktree一致且干净再快进；本交接不要求推送远端或另开对话。

## 9. 给执行模型的起始指令

> 在Kage仓库先读总规划、E/C统一队列和execution-handoff-2026-10-03.md的§0、§2。本轮从C2.1-B2.1-0开始：复现并修复浏览器错误观察送入模型历史时丢失的问题，验证真实浏览器端到端恢复和打包兼容。复用活动worktree，检查已有改动；代码与实验报告分别提交，更新队列且保留失败。完成当前包后按队列领取a/b/c，不跳过示范来源、实际调用、预算及独立检查。不要用脚本化测试声称真实AI学习，不改写历史成绩。更广上下文只在对应包需要时读取。
