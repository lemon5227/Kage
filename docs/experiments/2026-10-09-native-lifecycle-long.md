# 原生长时生命周期取证 — 2026-10-09

本轮执行C1.2-R-lifecycle-long，固定两项新专用TextEdit文档，各180秒、最多90个2秒间隔样本；模型和云请求均0。仅setup写初始fixture并打开文件，之后不激活、编辑、Save、Close或退出TextEdit。旧dev3及controlled2失败不回写。

## 设计与范围

passive项父进程async等待；blocking项父进程在自身主线程`time.sleep(180)`，模拟同步调用停顿。两项观察都由独立、自有主线程进程完成，持续保留原始AX对象并使用CFEqual在同一消费者内确认原窗口；每个样本另启动短生命周期只读消费者，记录新鲜应用PID、前台PID及精确文档URL匹配数量。新鲜消费者的引用不能跨进程作身份比较。

常驻观察器在采样间隔运行自身Foundation run loop，fresh读取有3秒期限。父期限含15秒startup、180秒观察和30秒grace；单次AX调用仍有合作式限制，慢采样可能产生partial。报告记录实际数量、最后样本时刻、observer elapsed与部分/损坏行，不将退出码或配置90自动当完整采样。

这是同步sleep对照，不是真实HTTP/模型推理或CPU/内存压力实验。父进程没有在等待后再次查询其setup时持有的原AX对象；本轮检验的是独立观察下的窗口生命周期，不能排除原模型进程自身的缓存/运行循环问题。持续2秒AX读取也不同于长模型调用期间的无读取间隔；两案例顺序固定，不构成随机化因果实验。

## 实现与预检修复

`15da297`新增实验CLI及回归。预检发现两项必须修复的问题：观察筛选先读所有标题，以及父停止observer时正在运行的fresh reader可能残留。`40f43ae`改为先精确URL、仅匹配后读标题；observer使用自有新session/process group，包含fresh child的cleanup覆盖leader仍在或已退出。只清理该自有组，不作用于TextEdit/父进程或其他app。

另明确absent/ambiguous/unavailable与未知原始身份，首次未建立身份不将后来窗口冒认original；去掉小固定延时后的完成速度断言，改为父同步、有界等待子进程完成的真实离线回归。**18 focused passed**，独立复核通过。cleanup中的terminated/killed仅证明发送信号与leader状态，不单独证明所有后代PID已回收。setup输出脱敏；观察器不读取非匹配文档的标题或文本，其他窗口仅计数。

## 固定真实运行

```sh
.venv-computer-use/bin/python -m scripts.experiments.native_lifecycle_long --output artifacts/native-lifecycle-long/2026-10-09-controls1
```

源码`40f43ae`，source/test、完整Git revision、平台、协议在首probe前冻结。原始freeze/timeline/observer报告/父报告及日志在活动工作树。固定两项已经全部完成，无追加采样。

| 案例 | 样本数 | observer实际覆盖 | 原窗口保持/独立新鲜文档存在 | 应用PID变化/读取错误 | 父总耗时 |
|---|---|---|---|---|---|
| passive | 90 | 180.003秒 | 90/90、90/90 | 0、0 | 180.868秒 |
| blocking | 90 | 180.003秒 | 90/90、90/90 | 0、0 | 180.710秒 |

两项observer均实际主线程运行；原应用PID27682、主窗口身份、文档路径匹配和磁盘初始内容在各90样本保持，未出现替换窗口。passive前台PID始终674，blocking记录过662/674/27682；前台改变并未伴随原文档scope缺席。未知其他前台app的名称/标题不采集。`original_present`指原AX对象仍匹配原文档scope；若它为false，不能单凭此字段推断物理窗口已关闭，标题/文档身份改变也可能影响匹配。

父级12项只读完整性检查通过：冻结Git源字节、严格两案例、各90样本/180秒完整覆盖、原身份/进程保持、新鲜消费者一致、磁盘未变。观察进程正常返回0；另在运行结束后对两个自有PGID做`killpg(pgid,0)`检查均为ProcessLookupError，支持本次组已不存在，而非只根据发送清理信号断言所有后代消失。`audit.json`保留检查与汇总；这是完整性核验和无模型稳定性证据，不是2项模型能力通过。

历史dev3原始应用PID20583在本轮之前的稍后只读检查已不存在，当时也没有正在运行的TextEdit。这只是晚时点事实，不证明191秒实验里何时/为何退出，不能认定旧窗口缺席都是进程退出。

结束后原生相关聚焦 **117 passed in1.67s**；本轮只改诊断CLI/tests，生产执行器不变，`git diff cb228d0..40f43ae -- core`为空。此前最终全量1091 passed保留为历史验证，不冒认本轮又跑过一次全量。源码/实际证据/报告经独立复核。

## 结论与下一包

180秒同步停顿、被观察文档处于非前台以及本轮前台变化，在这两个只读且持续采样的案例里均未复现旧scope丢失。不能因此声称旧问题已解决：未覆盖实际推理资源负载、AX激活写入，也没有检验原调用者长期保留的AX对象。

下一C1.2-R-parent-reference：保留setup环境与原调用者AX对象，等待前/后分别只读查询原引用，同时让独立观察器持续跟踪，再与新鲜消费者对照。采用新的两个限定案例、0模型/0后setupUI写入；先检验调用者缓存/引用与实际scope是否分歧，有复现再窄修复。不要重跑dev3或本轮样本制造通过；E2/E3/E4研究线仍可按队列交替推进。
