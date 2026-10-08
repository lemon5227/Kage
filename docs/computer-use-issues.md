# 电脑执行问题与修复记录

更新：2026-10-08。执行顺序见 [统一任务队列](plans/task-queue-2026-10-01.md)。本页记录问题、证据、修复和验证，历史实验成绩保持原样。

| 编号 | 问题与证据 | 状态 / 验收要求 |
|---|---|---|
| CU-AX-001 | 应用未激活且 Save/Close 明确 AXEnabled=false 时，适配器仍暴露文档 File 菜单容器 press（并未暴露disabled的Save/Close控件）。2026-10-08 两项 raw AX 诊断确认命令/修饰键过滤并非缺失原因 | 已修安全边界a5c633b：显式激活/实际状态验证、未激活菜单拒绝；已激活窗口Save闭环2/2、真实模型dev1/1，非激活AX写入实测仍缺 |
| CU-AX-002 | 普通激活请求返回 true，但有界轮询没有观察到应用激活；框架请求接受不等于完成 | 完成判定已修a5c633b并回归；系统未执行原NS请求的原因仍未确认，AXFrontmost激活写入尚待非激活场景实测 |
| CU-AX-003 | 旧 controlled2 两项模型任务在菜单操作前失去原窗口，随后 AXWindows 为0；无 Agent Close/Save | 待定位；无模型两上下文窗口稳定不解释旧消失，不重跑救回0/2结果；[模型链报告](experiments/2026-10-07-native-model-chain.md) |
| CU-AX-004 | 两项模型 fill 都少了目标末尾换行，独立磁盘精确匹配失败 | 明确JSON文本的新dev已通过1次，57字符/末尾换行核验；旧失败不回写，没有隔离对照证明方法收益；[生命周期报告](experiments/2026-10-08-native-lifecycle-diagnosis.md) |
| CU-AX-005 | 菜单动作已作用，但读取后续 AX 状态发生 -25204（AXCannotComplete） | 已修0b7faff/6e374f2：类型明确的纯读错误、最多3次只读观察、不重发写动作；回归通过，故障分支尚无正向实测 |
| CU-AX-006 | 旧确定性 pilot 在关闭完成轮询中遭权限撤销时，原始错误有记录但聚合会把 blocked 分类为 failed | 已修853202b：结构化失败写入阶段记录，权限/平台不可用分类blocked，2项失败后通过的回归；[首包报告](experiments/2026-10-07-macos-ax.md)的P3说明；相关回归已补，不影响已留存成功 |
| CU-EVAL-001 | 既有线程并发测试以170ms阈值断言，实际194ms导致失败 | 测试修正55c39ce：两处理器Barrier验证重叠，串行mutation明确失败；运行时未改 |
| CU-EVAL-002 | worker重启后立即断言PID消失，与异步父进程回收产生检查时序竞争 | 测试修正27be3a3：候选仍立即拒绝，有界等待后仍强制PID不存在；相关4项通过。最终全量1036 passed，原失败保留 |
| CU-AX-007 | 检查器把Save尚未落盘的磁盘读数缓存为最终成绩，关闭重开AX已正确仍failed | 已修0b7faff：保留前读数、以重开后的新磁盘+AX判断；v2两项before=false/最终true，模型dev1/1 |
| CU-AX-008 | 同名文档会阻塞关闭判定；URL缺失又不能证明原窗口关闭 | 已修6e374f2：同时核验原窗口引用与精确URL均消失，回归与实际关闭重开通过 |
| CU-BUDGET-001 | 原验证协议仅计编辑4动作，漏记验证/清理另4动作 | 已修4c8c138：执行前分阶段与总量守卫，原语按actor记录；模型协议亦显式计Agent16+验证4 |
| CU-AX-009 | 非激活受控验收中，AX 激活写入后的 AX 观察已为 active/main，但前台读取仍指向辅助窗口；controls1 的同进程读取疑似陈旧，controls2 改用每次新鲜短生命周期 AppKit 读取后仍复现辅助窗口存活期间的不一致。AXFocusedApplication 系统读为 -25204 | controls1/controls2 均0/2，无 fill/Save，辅助进程均清理；`f251b81` 的新鲜观测修复已验证但未解决真实激活。保持 AX+真实前台双重门控，具体 macOS 激活/事件循环根因未确认；Task6 暂停，不增加重试放宽门控 |

## 修复记录要求

每项修复记录根因证据、源码提交、失败后通过的回归、实际验收与未解决边界。确认不了原因时写清事实和缺口；诊断完成、工程修复、确定性执行、真实模型通过分别报告。自动保存、请求接受或模型自述都不能代替对应的独立检查。

本轮最终共用执行器回归：源码`9de41b8`，1062 passed、4 skipped、1 xfailed，退出0。分阶段证据、命令与限制见[菜单修复报告](experiments/2026-10-08-native-menu-repair.md)。

非激活 controls1 另有独立负结果：0/2，编辑动作 `[1, 0]`，Save 0，模型/云请求 0；见[菜单修复报告](experiments/2026-10-08-native-menu-repair.md)与 `artifacts/native-inactive/2026-10-08-controls1/audit.json`。

新鲜观测复验 controls2 同样为0/2，编辑动作 `[1, 0]`，Save 0，模型/云请求0；证据目录为`artifacts/native-inactive/2026-10-09-controls2/`。
