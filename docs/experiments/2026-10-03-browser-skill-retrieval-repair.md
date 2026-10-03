# C2.1-R2修复：长查询找到通用技能并实际执行

日期2026-10-03，父基线c9cbf3b，修复代码82542fe。依据修复前九次开发对照的三条空搜索证据修复检索；原报告与数据不覆盖。未改评分、技能内容、动作解释器、模型、观察格式或每run预算。

## 原因与修复

BrowserSkillCatalog.search原来要求query中全部词出现在skill_id/description里。真实任务查询夹带email/sms/enable/disable等目标参数词，参数化通用技能因没有硬编码这些值而被过滤。实际查询已在原actor-tools中复现，三次均success但skills=[]。

改为Unicode词项集合部分命中排序，skill_id命中权重2、description权重1，同分按id稳定排序，零命中不返回、空query保留列举。仍是词面召回，不含嵌入、同义词推断或通用语义检索；技能库扩展后还需检验召回和误匹配。本次不改变manifest/digest，现有直接预览照常可用。

先扩展已有“模型搜索→得到digest/schema→skill_call→真实Page保存”的回归，加入实际长query。修复前长查询失败、短查询通过；修复后均实际保存正确。不是仅比较返回字典。

## 固定真实修复验证

使用`browser_skill_diagnosis.py --study retrieval-repair`单独协议/目录，只跑R2同三个dev的search，每格一次。由官方DeepSeek Flash独立执行，固定compact-v2、相同提示/工具/上下文打包与6调用/5步/16 primitives/480秒；总18请求上限、名义$0.10，按既有假设费率的保守上限$0.0869184。这是开发修复验证，不是新盲测或修复前后的统计推断。

| 开发例 | 实际搜索/调用 | 模型请求 | 独立通过 | 墙钟秒 |
|---|---:|---:|---:|---:|
| original | 1 / 1 | 2 | 是 | 4.143 |
| satisfied | 1 / 1 | 2 | 是 | 3.472 |
| reverse | 1 / 1 | 2 | 是 | 3.845 |

三次均查到原技能、真实模型绑定正确参数、同Page工作流按状态跳过/点击后保存，后台POST与页面读回均通过。3/3实际skill_call，6云请求，11355/680报告tokens，11个browser primitives，11.460秒；无未知usage，假设费用$0.0042225。与原search的3/3保存、0/3技能调用分开：修复提高本轮技能可发现/使用程度，没有宣称完成率从失败变成功。

本轮合并R1/R2/修复共18次云dev运行、48个真实请求，报告tokens共92212/5508，按假设费率总$0.0342732；分别保留三份固定协议与原始分母。无本地模型调用、无权重训练、无新候选生成/晋级/主链安装。

## 原始证据、命令与检查

命令：`.venv-computer-use/bin/python scripts/experiments/browser_skill_diagnosis.py --study retrieval-repair --cloud-config /Users/wenbo/Kage/artifacts/private/deepseek-settings.json --skill-bundle artifacts/c21-browser-workflow-learning-2026-10-03/mutation/bundles/9400d42f5119acfff14f1c6acf153f66efe16323e66b9d8f32fe6904ab63ffba --output-dir artifacts/c21-browser-skill-retrieval-repair-2026-10-03`。

原始目录`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/c21-browser-skill-retrieval-repair-2026-10-03/`。audit重算3分数，校验24个运行hash、18源码hash、6请求记录，核对每次搜索命中digest与模型绑定参数；artifact-index、config/results/report、请求、DOM、技能/子动作、后台/读回/截图保留。所有终止结果保留，不重采成功。

工程专项25 passed，全量897 passed、4 skipped、1 xfailed（旧pygame warning）；真实云三次独立列出。修复前长查询的红灯来自真实链路未找到技能，修复后同链路读回正确，未降低验收条件。

## 下一包：R2-local，再R3

固定小本地对照：Agents-A1-4B Q4_K_M，复用原候选与三个dev，search/preview各一次，共6次；观察均v2，其余链/预算相同，两组同样使用本地已有上下文策略，不同时改引擎或输出限制。先记录实际运行服务/权重hash、参数生成是否截断、search/call、真实保存、调用/primitive/token/耗时；无云生成或救场，不能把脚本动作当本地模型能力。新配置在调用前冻结；无技能调用的通过不得记作学习。保留每个失败，不挑成功复跑。

这包测本地发现策略，不与旧v1 raw结果合成“提升”。若仍不调用/参数失败，依据请求和停止轨迹诊断，在R3固定预算测试或路由云规划；若能够调用，再冻结新的raw/search/preview留出验证迁移。不要因为云preview每次1请求就宣称小模型已经学会，更不要立即训练权重。可靠性首轮后按队列恢复C5.0入口与人类示范。
