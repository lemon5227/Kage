# 浏览器可靠性优先：B2.2之后的诊断顺序

用户已同意先提高完成率，再做C5.0入口。父基线6e8c42a；旧五臂45次数据保留，不重新抽样。

1. **C2.1-R1状态诊断**：DeepSeek Flash从重置页面独立执行；三个dev任务（原始状态、目标已满足但未保存、反向目标）各比较compact-v1与v2显式checkbox/radio checked。共6次、每格一次，只是定位pilot；无本地学生、无接管、无候选生成。共同提示和工具描述均解释两种格式，唯一区别是观察字段与版本标记。v1仍为默认；未经证据不全局替换。
2. **C2.1-R2技能发现**：复用已生成、未晋级的v2技能。dev上分别比较搜索入口与直接提供最小技能描述/digest/参数；云规划/绑定参数、确定性workflow执行，并列原始动作。不能把“没有调用技能”的成功计为学习成功。
3. **C2.1-R3步数与结束**：按轨迹区分接近保存与反复切换；只有前者才做固定增量预算对照。报告新增请求/动作/费用，不靠无限重试提高分数。
4. 方法冻结后另造盲测验证迁移；旧browser-transfer-v1已暴露不能调优。可靠性首轮结论后回到C5.0、DOM人类示范、AX与跨应用队列；E2/E3/E4研究线保持。

R1执行：`scripts/experiments/browser_state_diagnosis.py --cloud-config <已有私密配置路径> --output-dir artifacts/c21-browser-state-diagnosis-2026-10-03`。先工程回归/一次全量检查、独立代码提交，再冻结源hash执行真实云请求；最后报告提交。脚本不复制凭据。

固定R1预算：36请求上限（每运行6）、5循环步、16 primitives、480秒；单请求12000 bytes/1024输出tokens、60秒HTTP。共同上下文打包/外部保存完成检查。云名义预算$0.20，按既有假设费率0.3/1.2每百万tokens，上限$0.1738368；不是供应商账单或当前报价。真实调用usage与保守账本分开。

独立评分沿用后台记录和页面保存读回完全匹配，隐藏expected不入模型提示。模型文字/工具success不等于完成。每次保留请求、初始/最终DOM、逐步actor动作、后台POST和读回、截图、stop_reason、usage、耗时与hash。所有终止失败计入原始分母，不能为了得到成功重跑同格。

解释规则：v2优于v1只是这三个开发例上的线索，需后续重复与新留出；两者均通过则省略false不是云清洁执行的已证实瓶颈，应继续技能发现和预算诊断；两者均差先检动作轨迹/协议，不直接开始权重训练或引擎替换。

## R2固定云开发诊断

R1实际两组各3/3，原始结果独立保存。R2仍使用相同三个dev任务，固定compact-v2，重置Page/历史，九次（raw/search/preview各三次、每格一次）按task旋转组顺序。raw无技能；search有catalog与搜索指引；preview在search基础上直供至多三个descriptor的skill_id/description/digest/parameters，并引导匹配时直接调用。预览不含workflow源码、不预绑定目标值；目标参数由真实模型从公开指令与页面推导。衡量的是发现策略整体，不把descriptor和指引各自归因。

复用B2.1c未晋级候选9400d42f…及技能21e4ea88…，先核bundle/manifest hash；不再生成、不运行晋级、不默认安装。与R1相同每run预算；九次总54请求、名义云上限$0.30、保守上限$0.2607552，同假设费率，不是实付。脚本browser_skill_diagnosis.py冻结config/prompt/source/candidate后执行，终止失败不重采。

成功必须独立保存通过且实际actor-tools有skill_call；另记search/call次数、参数、内部browser primitives、费用和失败。只有云用会技能不能宣称小模型学会；若有效，下一固定小实验再检本地search/preview并决定复杂规划云端、简单执行本地的路由。只有完整新留出后才谈迁移收益。

R2实际搜索三次空返回，原因是全词AND匹配过滤通用技能；另包修复为词项部分命中排序（skill_id权重2、description权重1、无匹配不返回、同分按id稳定，空query仍列出）。这是词面检索，不宣称语义召回。修复后的`--study retrieval-repair`只跑原三个dev的search，使用独立目录/协议/hash，不覆盖九次旧数据。上限18请求、名义$0.10（保守$0.0869184），其余预算相同。验证通过后仍须本地小实验，不能将云的调用能力归给本地。

## R2-local执行冻结

基线c4730fa；脚本`browser_skill_diagnosis.py --study local-discovery --port 18082 --local-runtime <服务记录JSON> --skill-bundle <原候选目录> --output-dir artifacts/c21-browser-local-skill-diagnosis-2026-10-03`。原三个dev×search/preview各一次共6次，按task交替先后顺序。仅本地Agents-A1-4B Q4_K_M，权重SHA d93c393a…固定，启动前核API健康/模型id与实际权重；记录自有服务argv、llama版本、上下文与服务元信息。缺服务/权重不匹配在生成前报错，不回退云或脚本模型。

复用BrowserChainProvider的学生执行链、compact-v2、外部保存检查、原候选/检索/预览策略。保持此前本地上下文策略（不加教师打包）、AgenticLoop现有路由输出上限（不覆盖max_tokens）、请求temperature=0、服务reasoning off。6调用/5步/16 primitives/480秒，HTTP120秒；本地名义每run预留48000输入/2000输出，整包36调用/288000输入/12000输出。实际usage与预留分开，超预留如实记，不因过短参数输出在中途提高上限。

代码只扩展实验执行者选择，云既有协议保持可用。先工程回归、代码提交；随后停止重测试再启动单槽模型，冻结完整config/source/prompt/runtime/candidate hash后执行。逐run保存状态、search/call与子动作、参数错误/截断、真实POST/读回、tokens/耗时/截图；终止失败计入分母且不重采。完成后停止本次自有服务，独立报告/审计提交。依据失败轨迹决定R3增量预算或云规划路由；不要凭dev六次自动晋级。

## 新本地留出v2

R2-local六次全部独立通过，预览有两次真实工作流调用；R3未触发增步。方法/候选基线bd18121冻结后新建`eval/computer-use/browser-local-transfer-v2.json`：三个test实例（全新标签/顺序、四项checkbox、中文指令/页面），raw/search/preview各一次，共9次。仅preferences家族的迁移pilot，不是通用电脑评测。脚本的`--study local-transfer --suite <manifest>`仅消费此固定三臂/三任务/test协议，不允许dev诊断读test。

相同模型、v2观察、本地无额外上下文打包、原300输出策略，6调用/5步/16 primitives/480秒；没有云臂/重试/新生成。整包54请求、432000输入/18000输出名义预留。先用脚本动作验证夹具在原步数内真实可保存/读回（非模型成绩），提交manifest和代码，再冻结config/source/prompt/runtime/candidate/suite hash，启动实际九次本地运行。各臂原始分母/技能调用/子动作/成本分开，模型未调用技能的通过不能归为技能成长。

结果无论正负均保留；不得看本轮test后改描述/参数/检索再复跑同格。一次/格不证明统计收益，不与旧五臂45次直接作完成率对比。若用于后续诊断，标v2 exposed并另造v3。完成后优先回到C5.0显式入口与人类DOM示范；新盲测失败不无限阻塞产品入口。
