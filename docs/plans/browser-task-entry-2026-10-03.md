# C5.0 Browser Task Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task by task.

**Goal:** 用户从现有Launcher发起受控浏览器实验，看到真实执行者、任务检查、费用/预算、停止和产物。
**Architecture:** 复用BackgroundLane/BackgroundWorker；轻量BrowserTaskService调度独立Python子进程，子进程复用BrowserChainProvider/BrowserCloudProvider/BrowserTeacherTakeoverProvider与EvolutionRunner。API在control模式也可用，不触发音频、记忆模型加载；有runtime时走原kage:job事件，无runtime时前端轮询同一任务状态。
**Tech Stack:** 现有FastAPI、asyncio subprocess、Python3.13、Playwright、原Launcher HTML/JS；不加依赖。基线6bc671d。

## Global Constraints

- 此包仅受控实验页面，不接用户已登录浏览器；不宣称任意网页/通用电脑能力。任务目录只暴露公开instruction，不接受自由指令配旧checker。
- local/cloud/local_teacher均为显式执行器；主执行者6请求保护、循环默认5/可选6；teacher独立6请求/5循环。使用实际ModelBroker/ModelProvider，禁止hybrid或缺配置时的静默执行者回退。
- compact-v2、原本地输出/历史；cloud沿用现有1024输出/12000 wire bytes与教师打包；每任务480秒整体界限，16 primitives/actor。未晋级技能不默认加载；workflow_bundle仅显式提供，返回digest和未晋级标志。
- 独立检查通过才task_status=completed；有checker未通过=failed；无checker=unknown；用户停止=stopped。BackgroundWorker.completed仅运行结束；通知与UI消费task_status。
- 日常配置不含cloud有效凭据时显式失败；凭据只经子进程stdin传递，不入命令行/公共config/日志/产物。价格未配置则云费用unknown；明确区分reported usage与保守预留，未知不写0。local API成本0，不含硬件电力。
- 长任务不阻塞HTTP/event loop；停止必须绑定run_id，杀自有worker及Playwright/Chromium后代，不杀外部模型服务。处理排队取消、启动竞态、运行中取消与shutdown；不让迟到结果覆盖stopped。
- 原始产物永久保留在活动worktree实验目录或用户~/.kage/browser-runs，公共artifact路由仅返回该run中已索引文件。每包代码/报告分开提交；不推远端，不删唯一证据，不与真实推理并跑重测试。

### Task 1: BrowserTaskService与隔离worker

**Files:** 创建core/computer_use/task_service.py、core/computer_use/task_worker.py；修改core/background_worker.py（取消后不覆盖）；测试tests/test_browser_task_service.py、tests/test_background_worker.py。

**Interfaces (verbatim):**
```python
class BrowserTaskService:
    def __init__(self, run_root, config_loader, on_event=None): ...
    def catalog(self) -> dict: ...
    async def submit(self, payload: dict) -> dict: ...
    def list(self) -> list[dict]: ...
    def get(self, run_id: str) -> dict | None: ...
    async def stop(self, run_id: str) -> dict | None: ...
    async def close(self): ...
    def artifact(self, run_id: str, name: str): ...  # Path or None
```
Service复用专用BackgroundLane/BackgroundWorker实例，实现单worker串行；不是另一套Agent循环或评分器。独立实例避免实验Page挤占普通音频/聊天任务。on_event为async(event, public_job)；公共job包含job_id=run_id、task_type=browser_experiment、input_text公开指令、status、execution_status、task_id、executor、max_loop_steps、result和error。status含queued/running/completed/failed/stopped/unknown，execution_status区分后台执行生命周期。

payload字段：task_id、executor（local/cloud/local_teacher，默认local）、max_loop_steps（5/6，默认5）、workflow_bundle（可省略的本地bundle路径）。拒绝未知字段/错误类型，避免自由指令改变验证目标。目录使用browser-learning-v2.json的profile_dev、preferences_dev；另preferences_unchecked为preferences_dev副本移除scoring_criteria，公开标无自动检查，external_completion=False。不改既有清单或成绩。无checker任务拒绝local_teacher，因为不能据此推断失败并自动消费教师预算；基础设施错误仍显示执行失败与目标未确认，不伪报成功。

catalog返回tasks（task_id,title,instruction,check_available）及executors（id,model_name,configured），不返回key；云需有效远端OpenAI-compatible配置，其他provider/loopback冒充cloud明确不支持。worker使用ModelBroker，覆盖本次broker角色与hybrid=false后核实际profile.mode；配置为运行时快照，不修改用户文件。

result至少包含task_status、check_available/check_passed、run_status、stop_reason、executor/model_name、max_loop_steps、usage与usage_status、reservation、cost（金额可null、source明确）、workflow_digest/unpromoted、artifacts（name,url,sha256）、final_text。停止/崩溃时保留已有请求、DOM、后台产物；部分usage不冒充完整账单。actor费用若未知则整体云费用unknown。

worker通过stdin接收私有配置，公共配置/实际请求响应可落盘但必须去key。执行EvolutionRunner(step_isolation='inline')，仅因它已在独立受管理子进程内；service以start_new_session启动并施加480秒整体deadline，超时/取消杀树并留明确状态。结果写result.json，普通返回与异常均有证据；model response/error原样保留。服务支持KAGE_BROWSER_PYTHON选择已有电脑实验Python（默认sys.executable），不自动安装依赖。

- [ ] 写失败回归：真实HTTP脚本模型→实际子进程→真实Page修改/POST/读回；成功与未保存失败；preferences_unchecked的模型说Done也只能unknown。
```python
job = await service.submit({'task_id':'preferences_dev','executor':'local'})
final = await wait_terminal(service, job['run_id'])
assert final['status'] == 'completed'
assert json.loads(service.artifact(job['run_id'], 'browser-check.json').read_text()) == {
    'record': {'email': True, 'sms': False, 'weekly': False},
    'posts': 1, 'readback_matches_backend': True}
```
- [ ] 对未保存模型：status=failed、check_passed=false、posts=0；无checker同样未保存不伪报failed/completed，status=unknown。
- [ ] 对挂起HTTP模型：等真实Chromium/worker已启动，停止run，所有自有PID退出；事件状态不可由迟到返回改成completed；排队取消不发模型请求；另一任务可继续。BackgroundWorker原普通任务回归仍通过。
- [ ] 运行红灯，再实现接口；局部命令`.venv-computer-use/bin/python -m pytest tests/test_browser_task_service.py tests/test_background_worker.py -q`。只允许脚本HTTP模型，不调用云/真实大模型。
- [ ] 自检配置/产物无key，服务shutdown可清理、错误有状态，git diff --check，独立提交feat(computer-use): add managed browser experiment task service。

### Task 2: API、Launcher与可信通知

**Files:** 创建core/routes/browser_tasks.py，注册core/routes/__init__.py与core/server.py；修改kage-avatar/public/launcher.html；测试tests/test_browser_task_routes.py（可含真实Launcher行为）与已有后台通知测试。

**Consumes:** Task1 BrowserTaskService接口与公共job/result。使用core.server._load_effective_config；全局惰性service，run_root=KAGE_BROWSER_RUNS_DIR或~/.kage/browser-runs，on_event在kage_server存在时调用其_notify_job_event。lifespan finally关闭service，不依赖是否启动重runtime。
**Produces:**
```text
GET /api/browser/catalog                  -> catalog
POST /api/browser/tasks                   -> 202 public_job
GET /api/browser/tasks                    -> list[public_job]
GET /api/browser/tasks/{run_id}            -> public_job / 404
POST /api/browser/tasks/{run_id}/stop      -> public_job / 404
GET /api/browser/tasks/{run_id}/artifacts/{name} -> FileResponse / 404
```
Payload/配置不支持返回422或409并提供短错误，不隐藏为成功；POST立即返回run_id、后台执行。复用现有APIRouter与kage:job；_background_completion_notification对browser_experiment按task_status表达通过/未通过/待确认/已停止，普通任务行为不改。

Launcher在Background Tasks附近新增“浏览器实验”卡片：选择公开任务、显示目标、执行器/实际模型、5/6步预算，显式可选workflow_bundle（默认空，显示未晋级）；开始按钮、运行ID/状态/stop_reason/请求tokens/费用/保守预留、截图/保存证据链接与停止按钮。仅普通文字/DOM构造渲染模型文本，不让它生成HTML。复用fetchJson，创建/停止POST只发一次，避免默认重试创造额外任务；完成/unknown等终态停止轮询，页面重连先GET list补齐。UI异步显示运行状态，不因模型超时冻结按钮。

- [ ] 先API回归控制模式：POST真实service+HTTP脚本模型，等待terminal后GET独立保存证据；未保存为failed而不是后台completed；artifact取该run，未知run/name=404；停止后status不被迟到事件覆盖。
```python
created = client.post('/api/browser/tasks', json={'task_id':'preferences_dev','max_loop_steps':5})
assert created.status_code == 202
assert created.json()['status'] in {'queued','running'}
```
- [ ] 用真实Playwright加载Launcher点击开始→检查实际POST/界面终态/证据链接；用无checker与失败结果验证文字没有任务成功；点击停止触发绑定run API；不写只检查源码含字符串的用例。
- [ ] 红灯后接route/service/lifespan、卡片与通知，聚焦API/界面/普通通知回归；然后一次全量pytest与kage-avatar npm run build，不与真实推理并行。独立提交feat(ui): expose checked browser experiment tasks。
- [ ] 冻结本次入口pilot：两个local任务preferences_dev和preferences_unchecked各一次，固定5步/6请求/480秒、无bundle/云；合计12请求/96000输入/4000输出预留。代码提交后启动自有Agents-A1-4B服务和隔离control HTTP应用，用户入口（真实Launcher或相同POST API）发起；保留任何终止结果，不复跑求成功。
- [ ] 报告两个run的实际执行者/请求、POST/读回、checked vs unknown、停止与费用、源码/提示/协议hash和证据；这只验入口集成，不是新能力分数。停止自有服务，报告/队列/master/index另提交，主仓库干净时FF；下一C4.5-DOM。
