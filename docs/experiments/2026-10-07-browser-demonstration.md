# C4.5-DOM浏览器教学与复用实验报告

更新：2026-10-07；录制/入口工程与首次修复完成于10月5日，协议/目录沿用2026-10-04设计日期。父版本dd3cabd，源码与实际模型版本绑定于原始provenance.json。范围为受控单表单profile/preferences；真人教学待用户实际操作，没有权重训练或自动晋级安装。

## 可使用的闭环

Launcher的浏览器教学卡片：选公开任务→开始→ready后操作专用窗口并保存，可纠正输入→结束并提取→查看独立检查与候选→按新任务目标编辑JSON参数→直接工作流复用。支持文字字段、checkbox与单保存按钮；参数包含所有可编辑字段标签/值，按语义重新定位，新页面无需复用旧DOM引用。历史教学可明确选择后加载，重启不继续旧操作。

主链是Launcher/API→既有后台lane/独立bootstrap→示范worker→实际DOM/输入/动作→保存settle与独立Evaluator→RunResult/ExperienceArchive→现有v2参数化工作流；复用仍走BrowserSkillCatalog/ToolExecutor/共享primitive quota。真实模型pilot显式把生成的同一候选交给BrowserChainProvider/ModelBroker的本地执行配置。

不把执行者混为一谈：自动化录制由Playwright脚本操作真实worker Page，确定性复用由workflow_engine执行，两者零模型请求且学生通过值为None；真实本地模型是否实际skill_call另从actor-tools和模型请求判断。来源automation不冒称human_declared；DOM isTrusted不能认证真人。

## 验证与真实运行结果

本阶段工程与冻结开发集集成pilot完成；真人教学验收待实际用户操作，模型自动采用教学技能未证明。两任务独立工程提交`a918264`/`7d98e16`，任务修复`97c4b64`/`9308906`/`9bc4105`，最终整包修复`ee52cf2`；实际运行冻结源码完整版本`ee52cf27c54b97bcb80c4c609a5e34f83909261a`，绑定303个tracked源码/测试/任务/前端文件。

最终源码全量命令`.venv-computer-use/bin/python -m pytest tests -q`：**992 passed、4 skipped、1 xfailed，249.62秒，exit0**；一个既有pygame/pkg_resources弃用warning。最终六文件聚焦102 passed/109.21秒；因JS修复重新build，exit0/1.17秒，既有Cubism经典script及674.06KB chunk警告保留。整包最终两项Important修复均复审关闭；修复前983 passed/260.40秒记录仍保留，不冒用为最终门禁。

| 证据层 | profile | preferences | 模型请求 | 结论 |
|---|---|---|---|---|
| 自动化教学 | verified；4个归一化动作，1.843秒 | verified；5个动作，2.086秒 | 0 | 实际纠正/保存/读回并形成候选，两项各一次 |
| 更改参数后的直接复用 | completed；Name/Email新值，字段反序 | completed；false/true/true，初始状态/顺序不同 | 0 | 同一编译bundle、fresh Page与workflow_engine，两项各一次 |
| 真实本地Agent | passed；score1，29.809秒，3请求，3原语 | passed；score1，58.015秒，4请求，4原语 | 7合计 | 两项都实际保存/读回，均走逐步browser_act，skill_call=0 |

六个run均实际POST一次且页面读回与后台记录一致。自动化教学来源`automation_demonstration`，直接复用`workflow_engine_replay`；两者student.external_passed=None，不混入学生成绩。模型run的实际加载digest/interpreter hash见metadata，两个候选都加载了，但actor-tools证明模型没有skill_search/skill_call。**任务通过不是技能自动学习收益**。直接复用未独立计墙钟，不据零模型请求推断稳定速度提升。

实际模型为Agents-A1-4B Q4_K_M，权重2,708,805,312字节，SHA-256 `d93c393a9bd5139a4b5cfe24d31ef553c5a497bfb8afec178a354ecbf508f062`；llama.cpp server0.4.1/build10964/b29c606e2。Mac16,12/M4 Air16GB、Python3.13.11、Playwright1.63.0、Chromium153.0.8010.12、Node24.12.0。服务使用8192上下文/单slot、Metal offload、flash-attn auto、q8_0 K/V、reasoning off，服务输出上限1024；原始命令/props/version保留。服务CLI temp0.85，**实际7个请求均temperature0.7、max_tokens300**，没有追加覆盖或声称温度0。

冻结模型每run5循环步/6请求/16原语/480秒，整体最多12请求、名义预留96,000输入与4,000输出token，零云。实测**7请求、21,462输入、826输出token、87.824秒两run墙钟合计**；这不含模型启动/加载。名义预留不等于逐调用累计token的严格配平。无模型/网络错误，无救场、追加样本、重采样、晋级、安装或权重训练。

独立复算`recompute-audit.py` exit0，**35项审计全部通过**：303源码字节、协议和全部驱动hash不变；各任务仅一次、公开产物HTTP/磁盘hash、候选所有来源hash、实际保存/读回、执行来源、model attempt/response和reported usage一致、调用上限。68份公开产物通过HTTP下载hash核对。停止自有control/model服务后两个端口不监听，8个记录的自有worker/后代/服务PID均退出；只对本实验拥有的句柄执行停止。

0次模型技能调用是本轮保留的负结果。简单表单只需3/4个原语，本地模型可直接完成；是否由任务简单、通用field_N参数表达或发现策略导致不采用，尚无单变量对照，不能推断。后续教学技能发现须另定dev诊断和预算，不修改本轮成绩或把已暴露任务称新盲测。现有用户显式直接复用路径可用；下一实现仍按队列C1.2 AX，真人教学与自动采用收益分别待验。


## 工程问题与记录

[录制/提取报告](2026-10-05-browser-demonstration-recorder.md)记录输入/事件完整性、期限、最终写入失败却持久成功的修复；[入口/持久任务报告](2026-10-05-browser-demonstration-entry.md)记录真实退出码接受、挂起进程组清理、flush后索引、执行失败仍独立评分与归档。代码/修复分提交，报告另提交；完整任务审查/复审与RED/GREEN日志保留review-evidence。

## 如何亲自教一次

此次实验复用了既有环境，未新建主仓库Python环境；已有浏览器环境在活动worktree。若通过现有桌面Launcher启动，给control服务/worker配置`KAGE_BROWSER_PYTHON=/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/.venv-computer-use/bin/python`。教学本身不需要云API或本地模型服务器。

也可用两个终端从主仓库启动已有服务与前端（端口空闲时）：

```sh
cd /Users/wenbo/Kage
KAGE_MODE=control KAGE_BROWSER_PYTHON=/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/.venv-computer-use/bin/python /Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/.venv-computer-use/bin/python -m uvicorn core.server:app --host 127.0.0.1 --port 12345
```

```sh
cd /Users/wenbo/Kage/kage-avatar
npm run dev
```

打开`http://localhost:1420/launcher.html`，在“浏览器教学”选择真人声明、profile或preferences；按显示的公开目标实际填写/勾选并保存，再结束。候选生成后选择新输入任务，按新目标改参数再复用。真人窗口可见，默认不开放自动化CDP；不要设置`KAGE_BROWSER_DEMONSTRATION_HEADLESS=1`来代替真人操作。产物默认`~/.kage/browser-demonstrations`，可用`KAGE_BROWSER_DEMONSTRATIONS_DIR`指定保存目录。教程依赖既有前端Node依赖；缺Playwright时按requirements-computer-use.txt另装浏览器环境，不假定系统python可用。

## 原始证据、复算与下一任务

唯一完整原始目录：`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/c45-browser-demonstration-2026-10-04/`。源码/协议/模型/驱动身份在首个示范创建前绑定。含预先写定protocol、源码/驱动/权重hash、环境、每次提交意图、API状态快照、真实输入/DOM/动作、HTTP产物hash、候选、保存后台/读回、模型完整请求/响应、usage、journal/预算、服务退出与独立audit。不得清理唯一worktree证据副本。

`audit.json` SHA-256：`28c68960308658ce5bbfa05a1a42ca7d8db946908f5f6f1b8b3c7ec4f269f450`。复算命令是同目录`recompute-audit.py`，不执行任务/不收费。复制协议/驱动到新实验目录才能重新实验，原目录拒绝重复提交；先绑定对应源码与权重，再启动该目录serve-pilot.py，capture-pilot.py按生产API录制/复用，之后启动记录的模型服务器运行model-pilot.py。任何失败保留并继续未尝试样本，不能暗中追加重复或救场。

下一实现包C1.2 macOS AX：可可靠重置的原生文档编辑、保存重读与独立检查；之后C4.5-AX和C2.2跨应用。真人DOM验收保持待实际操作，与原生工程可分开推进。E2.1→E3.1→E4研究线按统一队列交替领取；当前工程/开发集pilot不证明通用能力或相对raw的盲测提升。
