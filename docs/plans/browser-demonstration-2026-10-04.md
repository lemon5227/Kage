# C4.5-DOM Browser Demonstration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development task by task.

**Goal:** 用户教一次受控浏览器form，得到可审查、可编辑参数、可在新输入复用的技能与证据。
**Architecture:** DOM录制/提取独立模块；隔离worker和示范service复用C5进程生命周期、现有episode/archive、v2工作流/ToolExecutor与独立Evaluator；Launcher提供完整入口。
**Tech Stack:** 已安装Python3.13、Playwright、FastAPI、Launcher原生JS，不增依赖。设计见browser-demonstration-design-2026-10-04.md，基线dd3cabd。

## Global Constraints

- 仅拥有的受控教学浏览器；单form文字字段/checkbox/保存按钮，profile/preferences两族。公开指令和实际可见DOM进入提取，隐藏checker/expected/后台文件不进入生成输入。
- 真人入口source_kind=human_declared；自动化测试/pilot=automation，DOM isTrusted不是真人认证。无人实际教学则真人学习验收保持待做。
- 示范最多64条归一化事件/900秒；工作流复用最多16 browser primitives/480秒。每服务最多一个活动session，重复创建409；创建/结束/取消POST只发一次。
- 原始前后DOM、事件顺序、修改/纠正、来源和hash永久保留；结束时停接收、flush、settle保存、独立检查、归档/提取，再关浏览器。未保存、取消、歧义、不支持、关闭窗口和崩溃不得生成可用候选。
- 编译所有被教学单form可编辑字段的最终可见标签/值和保存按钮，值/标签为参数；候选现有v2格式，含digest/参数schema/示例/来源hash/未晋级。不存节点IDs/坐标/端口、不自动晋级安装。
- 共用已有C5进程生命周期，bootstrap模块仅允许task_worker/demonstration_worker；保持旧服务默认、取消/启动/通知语义。示范没有模型请求，直接复用执行者为workflow_engine，费用0仅指本地API。
- 公开session元数据/结果可重启读取；旧活动session写stop.requested并标stopped/service_restart，不自动恢复。停止标记优先于迟到结果。
- 真实headed浏览器为human默认；automation才允许headless/CDP取证。工程通过真实worker Page操作，不用假事件数组冒充完整回归。事件/面板通知，无浏览器语音。
- 两任务各独立代码提交、任务审查，再最终审查/全量/build；报告另提交，本地主仓库干净时FF，不推送，不删除worktree。模型推理不与重测试并行。

### Task 1: DOM录制、已验证episode与参数化提取

**Files:** Create core/computer_use/demonstration.py, core/computer_use/demonstration_compiler.py, eval/computer-use/browser-demonstration-dev.json; modify core/computer_use/episodes.py; tests/test_browser_demonstration.py。

**Interfaces (verbatim):**
```python
class BrowserDemonstrationRecorder:
    def __init__(self, page, workspace, *, source_kind): ...
    async def start(self) -> dict: ...  # initial observation
    async def stop(self) -> dict: ...   # capture summary, flush, final observation

def compile_demonstration(episode: dict, output_dir, *, skill_id: str) -> dict: ...
# returns bundle_path, digest, skill_id, arguments, parameters, source_kind, source_hashes
def demonstration_tasks() -> dict: ...  # trusted immutable manifest tasks keyed by id
```

Recorder复用BrowserAdapter的SNAPSHOT语义/trace格式，注入Page事件记录click（checkbox/button）和change（文本fill），事件捕获本身不执行动作。写initial-observation.json、demonstration-events.jsonl（seq、时间、event、before/after、isTrusted/source）、actor-tools.jsonl（name=browser_act、arguments、actor=human或automation、result JSON与outcome）、browser.jsonl、trace.jsonl；保持实际修正，不把多次点击压成一个假动作。事件在Page内采样/有序排队，结束禁用监听后等待队列，不能用多个异步Python当前DOM读造成事件错配。最多64后明确CaptureLimitExceeded，不能默默截断形成技能。页面关闭与flush失败保留已发生记录。

episode归一读取result.metadata.demonstration_source声明：human_declared映射human_demonstration_declared，automation映射automation_demonstration；actor_segments包含真实human/automation。示范不得冒充student_passed/teacher接管，现有student/teacher行为不变。generation_feedback仍要求完整hash、verified/dev，只投影公开指令与DOM动作。

编译器调用generation_feedback校验episode；从实际最终可见单form状态和实际保存动作提取，每字段label/value分别参数化，checkbox ensure_checked、文本fill、最后click。保留示例arguments与来源hash到独立JSON，manifest只含v2描述/schema/workflow/digest。参数schemarequired全列、additionalProperties=false。拒绝无实际保存动作、重复语义标签、多个form歧义、控件不支持、超过16步；不读expected或在生成时访问后台。输出先stage再发布，失败不能留下看似有效manifest。

新manifest包含四个dev任务：demo_profile（Name=Kage Demo, Email=demo@example.test），reuse_profile（Name=Kage Reuse, Email=reuse@example.test，字段反序）；demo_preferences（Email notifications=true, SMS notifications=false, Weekly digest=false，初始false/true/false），reuse_preferences（同标签反序，目标false/true/true，初始true/false/false）。保存按钮分别Save profile/Save settings。公开instruction包含全部目标，可信checker独立json_exact_match保存记录+readback。此manifest不修改历史test或成绩。

- [ ] 写真实Page事件回归，先确认模块缺失失败；填写profile并纠正Name，保存/结束，原始轨迹有纠正且最终值正确。支持preferences checkbox，保存实际POST/读回。
```python
recorder = BrowserDemonstrationRecorder(page, tmp_path, source_kind='automation')
await recorder.start()
await page.get_by_label('Name', exact=True).fill('Mistake')
await page.get_by_label('Email', exact=True).fill('demo@example.test')
await page.get_by_label('Name', exact=True).fill('Kage Demo')
await page.get_by_role('button', name='Save profile', exact=True).click()
summary = await recorder.stop()
assert summary['event_count'] >= 4
```
- [ ] 实现录制/来源归一与可信清单；实际checkpoint+Evaluator构造RunResult，ExperienceArchive.record/retrieve→compile。停止后事件不能再入档；快速连续checkbox、输入失焦与结束队列不丢事件。
- [ ] 使用编译bundle和更改后的arguments在fresh reuse Page调用现有BrowserSkillCatalog、注册到现有ToolRegistry/ToolExecutor/BrowserPrimitiveQuota；两个新输入均真实POST/读回。验证无保存不编译、重复label/多form拒绝、篡改源文件后生成失败，旧episode回归不变。
```python
lesson = compile_demonstration(episode, candidate_dir, skill_id='form-demo')
catalog = BrowserSkillCatalog.from_bundle(lesson['bundle_path'])
assert lesson['source_kind'] == 'automation_demonstration'
assert lesson['arguments']  # explicitly editable example; no fixed values in workflow
```
- [ ] 聚焦`.venv-computer-use/bin/python -m pytest tests/test_browser_demonstration.py tests/test_browser_episodes.py tests/test_browser_skills.py -q`，保存红/绿结果与源码/产物关系；git diff --check，独立feat(computer-use)提交。不调用AI/云，不运行全量。报告写本plan scratch task-1-report.md。

### Task 2: 持久示范session、隔离worker、复用API与Launcher

**Files:** Create core/computer_use/demonstration_service.py, demonstration_worker.py, core/routes/browser_demonstrations.py, kage-avatar/public/browser-demonstrations.js; modify task_service.py/task_bootstrap.py, core/routes/__init__.py, core/server.py, kage-avatar/public/launcher.html; tests/test_browser_demonstration_routes.py与已有相关回归。

**Consumes:** Task1 BrowserDemonstrationRecorder/compile_demonstration/demonstration_tasks，manifest task IDs；现有BrowserTaskService生命周期、BrowserSkillCatalog/ToolExecutor、checkpoint/Evaluator、ExperienceArchive/Journal。
**Interfaces (verbatim):**
```python
class BrowserDemonstrationService(BrowserTaskService):
    def __init__(self, run_root, config_loader, on_event=None): ...
    def catalog(self) -> dict: ...
    async def submit(self, payload: dict) -> dict: ...
    async def finish(self, run_id: str) -> dict | None: ...
    async def replay(self, run_id: str, payload: dict) -> dict: ...
    # get/list/stop/close/artifact retain signatures; adapt persisted result/status
```

BrowserTaskService.WORKER_MODULE默认task_worker；子类demonstration_worker，bootstrap可选第4argv模块名且只接受这两个。继承同一lane/worker、deadline、早期所有权/迟到句柄/kill逻辑，覆写示范任务定义、公共状态、partial结果、submit/replay。请求保留config={}供既有生命周期释放，不带任何模型配置/凭据；真实worker不使用ModelBroker。旧C5默认行为不变，保持已有20项生命周期覆盖。

public job有run_id/task_type=browser_demonstration、operation=demonstration或replay、task_id、source_kind、status、execution_status、event_count、check_available/check_passed、stop_reason/error、result/artifacts。状态queued/starting/recording/finalizing/verified/completed/incomplete/failed/stopped；示范verified必须check通过且候选成功，复用completed必须check通过。来源和执行者明确；有检查通过但候选失败显示failed+check_passed=true+candidate_error，不伪报学会。

submit payload严格task_id/source_kind（默认human_declared）；只允许demo_profile/demo_preferences；已有活动session返回409。非阻塞创建202；持久session.json公开元数据，status.json更新ready、event_count、automation CDP地址；worker单独启动resettable fixture与Playwright（human headed、automation可headless），监听finish.requested/stop.requested，900秒整体deadline。结束禁监听/flush、用既有CheckpointExecutor(settle_saves=True)等待实际保存、Evaluator独立检查、RunResult→archive→编译，写episode/feedback/candidate/parameters/result/索引后关Page。后台/预期只留审计，不进feedback。用户关窗口/挂起/不可用浏览器/编译失败都有具体错误，保留partial。止损标记优先于迟到文件与结果。

replay payload严格task_id/arguments；只允许已verified完整候选到相同family的reuse_profile/reuse_preferences，验证manifest/source hashes与参数schema，创建新run、operation=replay、executor=workflow_engine，不复用旧Page或旧checkpoint。参数由用户编辑，禁止从checker自动填值。现有工作流执行器真正操作freshPage，共享16primitives；保存/读回独立检查。零模型请求，与真实AI复用分表。

服务持久历史从session.json/result读取；重启遇活动旧run写stop.requested并显示stopped/service_restart，不重做用户动作。artifact限制本run已索引文件/包含路径，持久候选引用可重启读取，跨run访问拒绝。service singleton/lifespan close与原control应用兼容，环境KAGE_BROWSER_DEMONSTRATIONS_DIR默认~/.kage/browser-demonstrations、KAGE_BROWSER_PYTHON沿用；仅automation可发布CDP以操作实际worker Page。真人模式不启动远程调试。

```text
GET /api/browser/demonstrations/catalog
POST /api/browser/demonstrations             -> 202
GET /api/browser/demonstrations
GET /api/browser/demonstrations/{run_id}
POST .../{run_id}/finish                    -> current job, idempotent
POST .../{run_id}/stop                      -> stopped/current terminal
POST .../{run_id}/replay                    -> 202 new run
GET .../{run_id}/artifacts/{name:path}
```

路由静态catalog在动态run_id前，缺run404、输入422、状态/不支持/并发409。复用有界_notify_runtime事件桥；server对browser_demonstration也只发事件/日志、不启语音；Launcher在旧generic HTML渲染前分流该类型，新JS模块监听事件/轮询。相同generation/run绑定与终态锁，乱序旧响应不能让结束/取消/复用指错session。

卡片使用语义label/真实按钮：选择教学任务、公开目标；开始、结束并提取、取消；ready才提示操作独立窗口；显示来源、动作数、check/错误、候选digest、未晋级、可编辑JSON参数与新输入目标，复用按钮、独立状态/请求=0/费用来源/产物。默认不加载旧未晋级候选；模型文本/参数全用textContent或表单value。清楚区分“示范检查通过/候选已生成/复用检查通过”和“AI学会”。新模块不复制全套Launcher状态系统，复用最小公共事件接口。

- [ ] 先失败回归：TestClient control app→真实demo worker→automation CDP连接同一Page→填写/纠正/保存→finish→verified、episode+候选产物；replay参数改为公开新目标→真实freshPage POST/读回通过。无保存incomplete无bundle。真正操作Page，不能直接写events/结果文件假装录制。
```python
created = client.post('/api/browser/demonstrations', json={'task_id':'demo_profile','source_kind':'automation'})
assert created.status_code == 202
run_id = created.json()['run_id']
# wait recording, use returned automation CDP endpoint to operate the actual worker Page
finished = client.post(f'/api/browser/demonstrations/{run_id}/finish')
assert finished.status_code == 200
```
- [ ] 实现worker/session/routes；验double-start409、finish/stop幂等、启动/活动/窗口关闭清理真实PID、后续session可开始、重启读候选并复用、旧活动stop标记、迟到结果不能覆盖、越run产物404。核对旧C5生命周期不退化。
- [ ] 实现Launcher/new JS模块；真实Playwright点开始、ready/finish/取消、参数编辑、复用、失败、重载；注入延迟旧GET证明按钮绑当前run，终态不复活。普通通知与C5事件仍通过。无AI/云/TTS副作用。
- [ ] 聚焦`.venv-computer-use/bin/python -m pytest tests/test_browser_demonstration_routes.py tests/test_browser_demonstration.py tests/test_browser_task_service.py tests/test_browser_task_routes.py tests/test_server_helpers.py -q`，npm run build，git diff --check，独立feat(ui)提交，task-2-report记录红/绿/覆盖。最终全量/真实模型由controller在最终审查后运行，不在本任务重复。

### Controller delivery (after both reviewed tasks)

- [ ] 最终独立整包审查；一次全量pytest、frontend源码有新变更才复建；冻结实际模型小pilot后再推理，最多2个新reuse dev ×一次，无云/额外重试/重采样。保留automation来源，无真人来源冒认；若模型不用技能也照实记录。
- [ ] 主实验报告与两任务工程报告分开；记录商业可用路径、限制、失败/解决、源码/协议/模型/hash/资源/停止。全部scratch审查复制原始目录再清理该plan scratch，保留worktree；报告另提交，主仓库干净时FF。C4.5-DOM区分工程/自动化复验和真人示范验收，后续C1.2按队列。
