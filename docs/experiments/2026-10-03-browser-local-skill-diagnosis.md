# C2.1-R2-local：本地模型真实发现与调用浏览器技能

日期2026-10-03；父基线c4730fa，代码b64505a。执行者为Mac M4 Air 16GB上的Agents-A1-4B Q4_K_M，llama.cpp 0.4.1/build10964/b29c606e2，模型SHA `d93c393a9bd5139a4b5cfe24d31ef553c5a497bfb8afec178a354ecbf508f062`。没有云请求/救场、脚本模型替代、权重训练或新技能生成。

## 固定协议与实现

原三个preferences dev各一次search/preview，共6次，task交替组顺序，重置Page/历史/后台。复用原未晋级候选9400d42f…、已修复词项检索和直接描述预览；固定compact-v2。BrowserChainProvider保持此前本地不打包旧DOM的策略，AgenticLoop原输出限制不覆盖；实际13次请求max_tokens均300，temperature=0、服务reasoning off。与云1024输出/教师打包协议不同，不能直接跨执行者比较能力或速度。

每次最多6调用/5循环步/16 primitives/480秒，HTTP120秒，名义48000输入/2000输出预留；整包36调用/288000输入/12000输出。模型服务单槽、8192上下文、Metal/flash-attn auto、q8 KV，其他服务采样配置同前；增加alias只明确API模型身份。config冻结实际props/chat template/build/argv/模型hash、候选/prompt/sourcehash，不读云凭据。评分仍为后台保存与页面读回匹配公开目标，模型不见checker文件。

## 真实结果

| 策略 | 独立保存通过 | skill_search/call | 模型请求 | 输入/输出tokens | browser primitives | 合计墙钟秒 |
|---|---:|---:|---:|---:|---:|---:|
| search | 3/3 | 0 / 0 | 8 | 22556 / 1100 | 8 | 127.939 |
| preview | 3/3 | 2 / 2 | 5 | 11238 / 872 | 10 | 85.162 |

| dev任务 | search请求/实际技能 | preview请求/实际技能 |
|---|---|---|
| original | 3 / 无，原语保存 | 2 / 搜索后调用，正确改设置并保存 |
| satisfied | 1 / 无，直接保存 | 1 / 无，直接保存 |
| reverse | 4 / 无，原语保存 | 2 / 搜索后调用，正确反向设置并保存 |

两次实际skill_call使用正确digest，本地模型根据公开指令绑定三项bool/语义标签和save_label，工作流在同一Page执行，独立后台/页面检查通过。两者都是需要修改设置的例子；satisfied通过未调用技能，不能把预览组3/3都计作学习。预览组仍先搜索，没有达到云预览的直接一请求调用。

共13次本地模型请求、33794/1972报告tokens、22实际工具结果全部ok（18 browser primitives+2 search+2 call），约213.101秒。usage全已知、无参数截断/模型错误/预算超预留；所有停止为external_check，POST/读回/截图齐全。云费用0表示没有云请求，不表示硬件/电力免费。名义预留与实际报告tokens分开，不把预留充当测量。

预览相对search本轮请求少37.5%、输入少50.2%、合计墙钟少33.4%，browser primitives多25%；这是单任务族每格一次的开发线索，不是稳定速度认证。两组均3/3，不能把技能发现收益写成完成率提升，也不与旧v1 raw留出失败合成因果提升。数据支持“小模型现在实际会调用参数化浏览器技能”，不支持权重学会或通用GUI能力。

## R3条件审查与下一项

6个run均在原步数内独立完成，没有待保存失败、循环耗尽或参数截断，因此不满足R3增量步数对照条件；本轮不扩大预算。之前旧test的失败不直接拿来调当前方法。下一步冻结新留出，固定raw/search/preview三臂、同模型/观察/预算，检验参数与标签迁移；候选/方法不再根据留出调优。新留出完成后推进C5.0入口与DOM人类示范；若出现新失败，保留负结果并另起dev诊断。

## 证据、问题与验证

命令：`.venv-computer-use/bin/python scripts/experiments/browser_skill_diagnosis.py --study local-discovery --port 18082 --local-runtime artifacts/c21-browser-local-skill-diagnosis-2026-10-03/server-runtime.json --skill-bundle artifacts/c21-browser-workflow-learning-2026-10-03/mutation/bundles/9400d42f5119acfff14f1c6acf153f66efe16323e66b9d8f32fe6904ab63ffba --output-dir artifacts/c21-browser-local-skill-diagnosis-2026-10-03`。

原始目录：`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/c21-browser-local-skill-diagnosis-2026-10-03/`。audit重算6分数，核42运行hash/18源码hash/13请求、实际actor=student+provider_mode=local、两次参数正确且没有云文件；artifact-index覆盖94文件。服务argv/props/models/log、config/results/report、独立journal/budget、请求、DOM、skill/子动作、后台/读回/截图全部保留。

服务初始未运行，核权重后启动实验自有进程；六次完成后Ctrl-C停止，端口健康检查确认无服务，不保留后台推理负担。停止后的会话已自动关闭，二次轮询返回Unknown process id，无需再发终止指令。模型hash改用流式SHA，避免一次读入2.7GB造成内存峰值；算法与原sha一致。

新增工程回归先因缺本地诊断factory红灯，补分支后真实Page工作流读回通过，确认local不会走cloud context/actor。聚焦22 passed，全量898 passed、4 skipped、1 xfailed（旧pygame warning），推理期间不并行重测试。代码与报告独立提交，未修改候选或晋级/评分规则。
