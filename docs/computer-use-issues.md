# 电脑执行问题与修复记录

更新：2026-10-09。执行顺序见 [统一任务队列](plans/task-queue-2026-10-01.md)。本页记录问题、证据、修复和验证，历史实验成绩保持原样。

| 编号 | 问题与证据 | 状态 / 验收要求 |
|---|---|---|
| CU-AX-001 | 应用未激活且 Save/Close 明确 AXEnabled=false 时，适配器仍暴露文档 File 菜单容器 press（并未暴露disabled的Save/Close控件）。2026-10-08 两项 raw AX 诊断确认命令/修饰键过滤并非缺失原因 | 已修安全边界a5c633b：显式激活/实际状态验证、未激活菜单拒绝；已激活窗口闭环2/2、模型dev1 1/1，非激活controls3实际写入/独立验证2/2 |
| CU-AX-002 | 普通激活请求返回 true，但有界轮询没有观察到应用激活；框架请求接受不等于完成 | 完成判定已修a5c633b并回归；AXFrontmost在controls3非激活main/run_sync实际2/2，原NS请求及controls4 helper未前台原因仍未确认 |
| CU-AX-003 | 旧 controlled2 两项模型任务在菜单操作前失去原窗口，随后 AXWindows 为0；无 Agent Close/Save | 待定位；无模型两上下文窗口稳定不解释旧消失，不重跑救回0/2结果；[模型链报告](experiments/2026-10-07-native-model-chain.md) |
| CU-AX-004 | 两项模型 fill 都少了目标末尾换行，独立磁盘精确匹配失败 | 明确JSON文本的新dev已通过1次，57字符/末尾换行核验；旧失败不回写，没有隔离对照证明方法收益；[生命周期报告](experiments/2026-10-08-native-lifecycle-diagnosis.md) |
| CU-AX-005 | 菜单动作已作用，但读取后续 AX 状态发生 -25204（AXCannotComplete） | 已修0b7faff/6e374f2：类型明确的纯读错误、最多3次只读观察、不重发写动作；回归通过，故障分支尚无正向实测 |
| CU-AX-006 | 旧确定性 pilot 在关闭完成轮询中遭权限撤销时，原始错误有记录但聚合会把 blocked 分类为 failed | 已修853202b：结构化失败写入阶段记录，权限/平台不可用分类blocked，2项失败后通过的回归；[首包报告](experiments/2026-10-07-macos-ax.md)的P3说明；相关回归已补，不影响已留存成功 |
| CU-EVAL-001 | 既有线程并发测试以170ms阈值断言，实际194ms导致失败 | 测试修正55c39ce：两处理器Barrier验证重叠，串行mutation明确失败；运行时未改 |
| CU-EVAL-002 | worker重启后立即断言PID消失，与异步父进程回收产生检查时序竞争 | 测试修正27be3a3：候选仍立即拒绝，有界等待后仍强制PID不存在；相关4项通过。最终全量1036 passed，原失败保留 |
| CU-AX-007 | 检查器把Save尚未落盘的磁盘读数缓存为最终成绩，关闭重开AX已正确仍failed | 已修0b7faff：保留前读数、以重开后的新磁盘+AX判断；v2两项before=false/最终true，模型dev1/1 |
| CU-AX-008 | 同名文档会阻塞关闭判定；URL缺失又不能证明原窗口关闭 | 已修6e374f2：同时核验原窗口引用与精确URL均消失，回归与实际关闭重开通过 |
| CU-BUDGET-001 | 原验证协议仅计编辑4动作，漏记验证/清理另4动作 | 已修4c8c138：执行前分阶段与总量守卫，原语按actor记录；模型协议亦显式计Agent16+验证4 |
| CU-AX-009 | `f251b81`仅修改helper就绪读取，激活前/后sample_state仍cached；controls2不能排除缓存读数，先前macOS激活异常推断无依据 | 已修3a0c4c2：完整消费者均fresh，回归先2失败后通过，controls3真实非激活/Save/关闭重开2/2；旧controls1/2各0/2保留，见[纠正报告](experiments/2026-10-09-native-activation-verification.md) |
| CU-AX-010 | dev2可信Close后AXTitle值读取-25202被泛型分类，fresh窗口探测立即退出unknown | 已修79b9ef5：与属性名称读取同一失效类型；Close后最多30次只读复查、不重发动作，权限立即退出；95原生回归通过，持续失效不能冒认关闭。新controls4止于helper setup未覆盖真实故障分支；dev2原成绩不改 |
| CU-AX-011 | controls4两次自有helper未取得前台，fresh读取维持其他前台PID | 明确0/2，零编辑/Save，helper均清理；系统为何未执行本次helper NS激活请求原因未定。已有controls3的AX激活2/2保留；不操作其他前台app，不重复采样救分 |
| CU-TEXT-001 | Unicode dev2唯一精确文本差异为缺末尾换行，两次Save观察失效被拒绝；独立checkerunknown | 模型开发验收0/1、8本地请求，未追加尝试。下一新dev研究文本读回核对/失效恢复，不能把工具静默补文本或检查器修复当模型学会 |
| CU-EVAL-003 | 首轮全量浏览器硬超时测试：即时PID消失断言失败，timeout/score0/检查点/返回<8秒已通过；7个PID稍后均不存在 | ac9b85d仅测试改为总2秒只读等待，保留全部最终消失断言和原硬期限；持续残留仍失败。目标1 passed，首轮1fail/1086pass日志保留，最终1087 passed/4 skipped/1 xfailed、退出0；未确认延迟退出或zombie回收的具体原因 |
| CU-PROMPT-001 | dev3初版task要求直接Save，但原系统Soul强制先open menu；仅改任务指令无法确保真正使用一致的模型策略 | 已修6bf2fb2：显式Soul从CLI选取→provider身份/cache→真实chain/system消息→freeze统一；默认dev1/2不变。真实消费者回归先失败后通过，dev3实际首请求的专用提示/hash已审计 |
| CU-AX-012 | dev3首次激活已作用但未确认active，随后原窗口不在AX列表；七次重复observe未有进展 | dev3原0/1/checkerunknown保留，无fill/Save，来源未确认。0c519d2对确认的原窗口scope丢失阻止后续推理请求，离线8→1请求；普通控件stale仍可恢复。99原生回归通过，优化未再做真实模型尝试 |
| CU-EVAL-004 | 长时observer-ready仅表示进程启动，未确保独立owned baseline；不足以对齐父原引用等待区间 | ff00d4a新增可选baseline/start握手及实际时间戳；真实两项90样本，父原引用前后有效。同步项observer比wait-end早1.457ms，coverage=false保留；间隔采样不能认定连续覆盖。129原生聚焦通过，见[原引用报告](experiments/2026-10-09-native-parent-reference.md) |

长时独立取证`40f43ae`：passive/blocking各180秒、90样本，原窗口/应用身份与新鲜文档读取均稳定，零模型、无setup后UI写入；未覆盖激活动作、推理负载或父原引用，CU-AX-003/012原因仍未确认。诊断脚本预检修复非匹配文档标题读取及fresh子进程清理范围，117项原生聚焦通过，12项实际证据完整性检查通过；见[长时报告](experiments/2026-10-09-native-lifecycle-long.md)。下一原调用者引用对照。

原调用者引用对照`ff00d4a`已完成：两项180秒后保留的setup原对象、scope与snapshot均有效，独立/新鲜各90样本一致，16项完整性核验通过；仅诊断源/测试改动。未复现旧失效，不改CU-AX-003/012的未知状态。下一单次新文本dev4记录真实推理/激活期，只读observer可能影响状态需明确，不能由本轮推定旧根因。

此前最终全量源码`0c519d2`，1091 passed、4 skipped、1 xfailed，退出0；这是历史全量，本轮仅改诊断CLI/tests。模型dev3先于终止优化，分数不重写；[文本/恢复报告](experiments/2026-10-09-native-text-recovery.md)记录完整分母、代码/提示/预算和剩余边界。

## 修复记录要求

每项修复记录根因证据、源码提交、失败后通过的回归、实际验收与未解决边界。确认不了原因时写清事实和缺口；诊断完成、工程修复、确定性执行、真实模型通过分别报告。自动保存、请求接受或模型自述都不能代替对应的独立检查。

本轮最终共用执行器回归：源码`9de41b8`，1062 passed、4 skipped、1 xfailed，退出0。分阶段证据、命令与限制见[菜单修复报告](experiments/2026-10-08-native-menu-repair.md)。

非激活 controls1 另有独立负结果：0/2，编辑动作 `[1, 0]`，Save 0，模型/云请求 0；见[菜单修复报告](experiments/2026-10-08-native-menu-repair.md)与 `artifacts/native-inactive/2026-10-08-controls1/audit.json`。

仅helper读取新鲜的controls2复验为0/2，编辑动作 `[1, 0]`，Save 0，模型/云请求0；原始目录为`/Users/wenbo/Kage/artifacts/native-inactive/2026-10-09-controls2/`，不能声称激活状态也已使用新鲜读取。完整修复后controls3 2/2，后续controls4 helper就绪0/2，见[最新报告](experiments/2026-10-09-native-activation-verification.md)。
