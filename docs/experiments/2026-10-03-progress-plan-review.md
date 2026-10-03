# 进度与任务规划复核

日期：2026-10-03；代码基线da5f675。范围：代码/规划/已有原始证据交叉检查，修正规划并提供其他模型执行的规格。未修改运行时代码、未运行新的云模型实验或训练。

## 结论

E0和E1工程及文件/代码上的首轮学习链有证据；E2仅最小档案、E3仅恢复模块首pilot。浏览器执行/同页接管/完成判定/教师上下文首包已有，但浏览器技能尚未接通，实际通用电脑和持续自主进化仍未证明。之前“下一步B2.1”缺少接口与证据条件，直接交模型执行容易错误复用文件技能链。

## 已核实问题及规划修改

| 问题 | 代码或证据 | 改动后的执行要求 |
|---|---|---|
| 错误观察在送给模型前丢失 | BrowserAdapter._error附observation；tool_executor.render_history_line只输出错误文本；本轮真实浏览器探针复现 | B2.1-0先修完整消息链，包含打包开启/关闭；不把adapter字典测试当验收 |
| 浏览器没有实际技能入口 | BrowserChainProvider._run仅adapter.register_tools；父类有skill_catalog字段不等于注册 | B2.1b在live Page registry绑定技能并验证模型看到schema→实际保存 |
| 文件技能不能直接控制Page | Process/DockerSkillRunner只传workspace_dir JSON，在新进程/容器执行 | 明确采用声明式工作流+可信worker解释，复用E1候选/晋级而非直接传Page |
| 文件episode字段与浏览器不匹配 | archive setup漏fixture；failure_status读取student_check.status；skill_learning读teacher_check.check_passed | B2.1a增加浏览器归一和setup、actor引用；旧episode不覆盖 |
| 完整审计档案不能直接作为生成上下文 | archive会收集check/outcome及context-evidence等文件；Mutator的递归删键不是类型白名单 | 审计完整保留，生成输入只含公开目标/实际观察动作错误；可见页面保存值本身不是答案泄漏 |
| 成功示范覆盖被高估的风险 | B1教师仅observe+Save，Email/SMS由学生做；B2.0b无成功多步教师 | 分清纯教师/混合actor/纯学生来源；不反复自然跑到成功，必要时固定受控恢复探针 |
| 旧holdout已经运行 | browser baseline八实例含holdout，成绩已公开 | 旧集做回归，新test在生成前冻结；以后用test改候选须标exposed |
| 动作合并可能隐形增预算 | 现loop计模型轮次，未来skill可包多个动作；原cloud另有教师额度 | 统一primitive计数/截止；额外云额度单列，学习一次性成本单列 |
| 上下文打包被当通用长期记忆的风险 | context_pack只保留最新DOM，旧引用没有模型召回工具；仅teacher开启 | 首包限定单页，跨页/历史值任务另做可召回事实；对照各臂策略一致 |
| 实验能力与主链可用性混淆 | BrowserChainProvider为实验链；E3报告明确未安装生产配置 | 增加C5.0最小主链集成验收，再人类DOM示范，不等所有GUI完成 |
| 三重复可能只执行一次，默认超时隔离不匹配 | Promoter.run_id无repeat，compare禁止重复task_id；默认inline；5个kernel step是上限，当前browser finish仍只执行一次 | B2.1c最小扩展repeat身份和一次汇总；browser显式fork/1个kernel step，恢复同repeat才复用缓存 |
| 名义token预留不等于严格限额 | MeteredProvider拦调用数，runner整chain后才结算实际tokens | 对照明确匹配调用/动作/时间/单次输出，token报实耗；严格token对照另验 |
| 规划状态漂移 | 队列曾把B2.0超限写成“最新三次”；E2/E3/C详细旧复选框与当前状态不一致 | 统一任务队列完整列出E/C；详细路线标明已做与剩余；历史报告保留原始结果 |

## 本轮核验与证据边界

1. 主仓库和活动worktree开始时干净、HEAD同为da5f675；未发现适用AGENTS.md。
2. 从活动worktree读取三份results.json：B1三次3/3、B2.0三次2/3、B2.0b三次2/3；逐条核对takeover和actor-tools。B2.0b唯一教师首请求TimeoutError，不能当多步打包收益已验证。
3. 真实headless Chromium、本地HTTP fixture，通过BrowserAdapter注册到ToolExecutor，用失效observation_id调用browser_act。输出：raw_error=StaleObservation，raw_has_observation=true，history_has_new_observation_id=false。进程关闭，临时目录清理；无云调用。该probe只证明错误信息丢失，不是模型能力测试。
4. 独立只读审查确认浏览器注册、进程边界、episode协议、示范覆盖与旧holdout问题，并发现Promoter重复缓存/默认inline及token限额措辞问题；交接已修订并复审通过。复核中特别收窄泄漏措辞：公开DOM/可见结果及context-evidence不天然是泄漏，风险是完整审计材料未经投影输入生成器。
5. 没有为文档修改重跑全量测试，历史860 passed不冒称本轮验证；最终检查Markdown相对链接、路径、空白及队列和新交接一致性。

## 交付与范围

[执行交接](../plans/execution-handoff-2026-10-03.md)给出下一包文件、接口、回归、预算、示范来源、生成/迁移协议和后续E/C顺序。[统一队列](../plans/task-queue-2026-10-01.md)为状态唯一入口；总规划保持短，旧详细设计附现状说明。新规格中的代码接口与测试文件属于待实现，不伪称已存在。

原始实验仍位于`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/`，不在本次提交中复制。其他模型使用前应检查source/hash和相对/绝对路径；只拿主仓库无法重现全部历史。当前不把保存失败样本、隔离评分器等科学实验条件升级成额外审批流程。
