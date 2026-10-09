# 原调用者 AX 引用对照 — 2026-10-09

C1.2-R-parent-reference固定两个新专用TextEdit文档，各180秒、90个独立样本；0模型/0云请求，setup后无激活、编辑、Save、Close。源码`ff00d4a`，实际命令：

```sh
.venv-computer-use/bin/python -m scripts.experiments.native_parent_reference --output artifacts/native-parent-reference/2026-10-09-controls1
```

## 实现与预检

保留真实setup的environment、driver、window_ref、原四元组及AX对象；前后直接查询同一原对象的AXWindows成员身份、精确文档scope、PID存活，再通过原driver/ref做snapshot。等待后重新设读取期限，不调用windows()刷新或采用替换窗口。每字段错误独立脱敏，读取不可用是unknown，成功成员查询缺席才是false；文档scope不匹配与窗口成员缺席分开。

复用上一包的独立观察器、新鲜子进程消费者、自有进程组清理。预检明确ready不能替代有效baseline，新增可选握手：独立原文档baseline成功后parent发布等待起点，再开始90样本；上一包默认路径保持。保存所有monotonic起止与实际偏差，握手有15秒期限。URL未确认时不读标题、不snapshot；只输出owned匹配布尔/数量，不序列化窗口文本或异常消息。继承setup的生产发现流程仍会在内存枚举标题，setup日志不保留内容；本轮等待阶段不再调用该发现流程。

TDD覆盖引用保留、读取失败/确认缺席、替换缓存不冒认、scope未知/改变、握手期限、两个短离线等待与真实自有子进程、失败partial及冻结源拒绝。30 focused passed，源码独立审查通过后执行固定实验。冻结全部core Python源码、实验模块、测试和入口文件，记录Git revision/hash、平台/解释器和协议；二进制依赖与系统行为不由源码hash冻结。

## 实际结果

| 案例 | 父实际等待 | 独立样本/observer耗时 | 父原引用前/后 | 独立原身份/新鲜文档 |
|---|---|---|---|---|
| passive | 180.002秒 | 90 / 180.001秒 | present、scope、snapshot均通过 | 各90/90 |
| blocking | 180.005秒 | 90 / 180.003秒 | present、scope、snapshot均通过 | 各90/90 |

两个父引用、environment/tuple持续保留到清理阶段；应用PID27682保持，独立消费者无替换/进程变化或读取错误，磁盘47字节初始内容未变。父snapshot目标数均7→5，前台状态期间变化；这不是原引用失效。fresh前台PID计数：passive 27682×67、674×23；blocking 27682×1、674×88、684×1，不采集其他app身份/标题。

采样起点比parent wait-start分别晚12.395ms、0.783ms；最后样本约178.258秒。observer结束比parent wait-end分别晚11.109ms、早1.457ms。因此`observer_covers_wait`分别true/false，blocking末尾的小缺口原样保留，不追加样本或重跑。这个字段仅表示baseline到进程结束是否包围等待区间，不表示每个瞬间都有采样；即使true也有2秒读取间隔，父后查询也不是独立最后样本。

父级16项完整性核验通过：冻结源与Git字节、严格两案例、实际数量/时长、原调用者前后有效及保留、新鲜/独立一致、磁盘、零请求/写入、两个自有进程组不存在。观察器返回0，另对PGID做killpg(pgid,0)均ProcessLookupError；不能单凭leader退出/发送信号推断后代全部退出。完整性核验没有要求`observer_covers_wait`均true，也不抹去该边界。

原始freeze、baseline、parent前/后、timeline、observer/parent报告、audit.json及日志保存在活动工作树`artifacts/native-parent-reference/2026-10-09-controls1`。结束后原生聚焦 **129 passed in2.09s**，exit0；本轮只改诊断脚本/测试，生产core未变，历史全量1091通过不冒认为本轮重跑。

## 结论与下一包

这两项没有复现原调用者长时引用失效，补上了上一包未检验父引用的缺口。仍不能解释dev3或controlled2：没有真实推理资源负载、AX激活写入；持续独立读取/pump可能影响状态，固定顺序/有限样本不构成根因证明。旧模型失败与unknown均保持。

下一C1.2-R-text-dev4：结束纯sleep重复，冻结一个新文本开发任务及预算，在真实本地推理/激活期间加入有界独立只读生命周期观察。先对齐owned baseline与模型起点，记录实际请求/原语/observer读取和清理；将可信checker Close导致的正常窗口消失按actor/stage区分。8次本地请求上限须在实际链/预算门控落实，精确文本与Save/关闭重开检查沿用；不重复旧任务救分。有持续observer的诊断仍不能单独归因模型或激活，无复现不改生产执行器。E2/E3/E4可按队列交替推进。
