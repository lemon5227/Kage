# C2.1-B2.1c：浏览器工作流真实生成与本地调用 pilot

日期：2026-10-03。代码父提交`2318ca0`，生成/评测提交`93d1653`；随后修正统计实现提交`4d7d795`。这是一个真实云生成、真实本地模型执行、独立浏览器检查的单族 dev pilot；结果是负的，未激活候选。

## 协议

输入来自 B2.1a 已核验的`preferences_dev-2`混合示范，生成前重新校验证据 hash。DeepSeek Flash最多3次、请求≤11KB、输出≤3000 tokens、名义成本上限$0.05；实际只调用1次，输入1571、输出319 tokens，保守估算$0.0008541。生成器只收到公开指令、DOM、动作和可见结果，不收到评分条件、backend、checker或冻结test。

候选是`set_notification_preferences` v2工作流：对参数化checkbox列表执行`ensure_checked`，最后按参数化按钮标签保存。manifest/digest验证通过。父空catalog与子catalog使用同一活Page解释器、compact-v1观察、独立外部完成检查和每actor 16 primitive额度。父子在`preferences_dev`各3次，严格按task×repeat配对；另对一个不同初始状态/顺序的`preferences_dev_reuse`执行3次；再重启读取同一 repeat，RunResult命中缓存、未重复本地调用。

## 结果

| 项目 | 结果 |
|---|---:|
| 云生成有效候选 | 1/1 |
| parent dev | 0/3 |
| child dev | 0/3 |
| 晋级 | 否 |
| child reuse | 3/3 外部通过 |
| 实际 `skill_call` | 0/6（dev 3 + reuse 3） |
| 本地模型执行调用 | 41，Agents-A1-4B Q4_K_M，llama.cpp 18082 |
| 云生成调用 | 1，实际保守成本约 $0.0008541 |

parent 的0/3不是“父技能差”，它是空工作流基线在同一Agent链上的失败；child同样0/3，且没有触发`skill_search`/`skill_call`，本地模型继续直接调用`browser_act`。reuse 3/3证明本地模型和浏览器原语能完成该变体，不能证明候选被发现、调用或迁移。dev失败中有模型输出过长/`browser_act`参数错误和步数耗尽，均保留在每个run的`model_errors`、actor-tools和外部检查中；没有挑选成功样本或修改提示后重跑。

“候选有效”只表示可加载、digest正确、解释器能接受；“能力提升”必须同时满足外部通过、实际`skill_call`、父子严格提升和reuse调用证据，本轮四者未同时满足。负结果指向两个瓶颈：Agents-A1-4B没有主动发现新工具，且当前compact checkbox语义让直接原语规划容易消耗步数；下一轮应先做发现策略/提示的单变量消融，不能把reuse成功归因于技能。

原始目录：`artifacts/c21-browser-workflow-learning-2026-10-03/`（活动worktree保留，未复制到Git）。`report.json`记录完整comparison、每次RunResult、候选digest、token/费用和缓存repeat；修改后的脚本从`actor-tools.jsonl`计数，避免将通用trace误作工具调用来源。

验证：生成前的源码测试12 passed；全量回归在该代码阶段为882 passed、4 skipped、1 xfailed；统计修正后专项5 passed。没有训练权重、没有新增模型能力认证、没有把该pilot称为通用电脑Agent结果。下一包C2.1-B2.2按已冻结三变体和五臂协议测量raw、cloud takeover、dev trajectory、learned workflow、local retries；可把本pilot作为开发负结果，不把其结果混入新test分母。
