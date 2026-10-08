# 原生激活验收修复与优化 — 2026-10-09

本轮修复了独立激活检查漏用新鲜前台读取的问题，固定 main/run_sync 两项真实非激活控制均通过。旧 controls1/controls2 各0/2保留；旧原生模型 controlled2 仍0/2，不回写历史成绩。

## 根因与纠正

前轮提交`f251b81`只替换了辅助进程就绪阶段的`helper_frontmost_pid()`，`sample_state()`仍调用同进程`NSWorkspace.sharedWorkspace().frontmostApplication()`。因此 controls2 的激活前/后检查并没有使用新鲜读数，不能得出“排除缓存解释、macOS真实激活异常”的结论。旧报告的该推断在本报告纠正，原始证据不修改。

`3a0c4c2`让激活前/后状态也使用短生命周期、每次新建的 AppKit 读取进程，超时0.5秒；无有效PID则返回明确失败，停止编辑。保持独立AX的自有主窗口CFEqual身份、同一窗口引用和应用PID核对。生产AX写入逻辑未改，仍最多一个显式激活请求，不通过重复写入或放宽门控获得通过。多个读取不是原子快照，AX期限仍为合作式。

两项新增回归先 **2 failed**，再 **37 passed** 聚焦通过。回归覆盖真实`sample_state()`消费者，禁止调用缓存对象；这补足了前轮仅测试读取辅助函数、遗漏调用链的缺口。只读读取耗时三样本为0.123/0.087/0.087秒，这项开销用于保证证据新鲜，未用缓存替代验证。

## 固定真实控制

```sh
.venv-computer-use/bin/python -m scripts.experiments.native_inactive_acceptance --output artifacts/native-inactive/2026-10-09-controls3
```

协议`native-inactive-acceptance-v2-all-fresh`，源码`3a0c4c2`，执行前冻结源/测试hash、上下文和预算。严格两个上下文各一次，无模型或云请求。

| 上下文 | 真实激活与同一主窗口 | 实际Save/关闭重开/AX+磁盘 | 自有文档/辅助进程清理 | 编辑+验证原语 | open/reopen | 墙钟 |
|---|---|---|---|---|---|---|
| main | 通过 | 通过 | 通过 | 4+4=8 | 2 | 3.207秒 |
| run_sync | 通过 | 通过 | 通过 | 4+4=8 | 2 | 2.896秒 |

独立前台PID从本次辅助进程切换到TextEdit，前后自有主窗口引用相同；真实激活动作只发一次。两项`disk_matches_before_reopen=false`保留，重开后的AX与新磁盘读数均true。父级只读审计核验冻结字节、次数、独立前台PID、窗口身份、Save、动作预算、两种清理。结果为确定性工程验收2/2，不能计为模型能力分数。

## 第二个模型开发任务

Task6入口`1821e54`预先通过独立代码复核，保留dev1默认行为，另有`--task dev2`的中文多行精确文本及末尾换行。只有上面的非激活控制通过后才执行一次。沿用既有NativeChainProvider/ModelBroker/runner/journal/budget、8循环步/10请求/16Agent+4验证原语/总20、480秒合作式期限、零云和自有服务生命周期。

命令：`.venv-computer-use/bin/python -m scripts.experiments.native_menu_model_dev --task dev2 --output artifacts/native-menu/2026-10-09-model-dev2`。源码冻结`3a0c4c2`，结果 **0/1、kernel failed/score0、独立检查unknown**，未追加尝试。8次本地请求、44,094输入/1,146输出token、173.581秒，零云费用，预算无活动预留，自有服务已停止。Agent共8工具调用、5动作尝试（fill1、Save press2、activate2），Save两次均因StaleObservation拒绝；原始AX执行7条含验证菜单/Close两次。Agent没有有效Save，未完成任务。

模型输出22字符、2个真实换行；预期23字符、3个换行，**唯一文本差异为末尾换行**。实时进度曾误读日志的转义展示为字面反斜杠，此处已按字符数、换行数和逐字节比较纠正。独立检查在可信Close后遇到AXTitle读取-25202，重开读回为null、结果unknown；后续修复不用于重评分。14项原始证据审计通过是完整性检查，不是能力成绩。此任务仍属同TextEdit覆写/保存家族，不能称第二应用、留出迁移或通用电脑能力。

## 本轮发现问题后的修复与优化

`6cbd98f`将辅助窗口就绪时每次新鲜读取的timeout限定为`min(0.5, remaining)`，余时为0不启动读取。边界回归先失败后通过，聚焦38项通过。该优化只限制读取等待，进程创建/系统调度/AX及轮询sleep仍可能越过整体期限，不宣称硬3秒墙钟。controls3冻结的是`3a0c4c2`，不能当作优化源码的真实验收。

dev2的-25202暴露了另一个确定缺陷：属性名称读取已有`AXInvalidElementError`，同错误在属性值读取却是泛型AXDriverError。`79b9ef5`统一两处失效元素分类；可信Close已作用后，对fresh windows的StaleObservation/AXReadUnavailable最多30次只读复查，保留所有错误，权限/其他错误立即退出，不重发Close或菜单。原窗口引用及精确URL均消失才确认关闭。两项回归先失败后修复，另有30次持续失效仍不通过且动作仅2次的边界测试；原生相关 **95 passed**。30是读取次数上限，同步AX期限仍合作式；不能根据无法验证消失推断窗口实际仍存在。

固定源码`79b9ef5`，新controls4两项各一次，**0/2**，均因自有辅助窗口在期限内未取得前台而止于helper readiness；原生编辑动作0、Save0，两辅助进程均清理。所有前台读取都返回同一其他前台PID，末次余时不足可能为None。该前台应用未被操作，系统为什么未激活测试helper尚未确认。没有进入修复的Close分支，不认定新的真实故障分支验证通过。保留controls3通过2/2与controls4 setup未完成0/2两个分母，不循环采样到成功。

首轮全量在模型服务停止后运行，冻结`79b9ef5`，日志`artifacts/native-inactive/final-pytest-79b9ef5.txt`：**1 failed、1086 passed、4 skipped、1 xfailed，329.72秒**。唯一失败是既有浏览器硬超时测试即时检查子进程PID消失；timeout/score0、检查点存在与原有返回耗时<8秒断言全部先通过。原始PID记录22338–22344后续只读核查均消失；没有再次终止或操作这些进程。

`ac9b85d`仅修改该测试的观察时序：总计最多2秒只读等待全部PID消失，保留原<8秒断言与最后每个PID均须不存在的断言；若两秒后残留仍失败。目标测试 **1 passed in4.35s**。现有记录无法区分活进程与待回收zombie，不认定操作系统回收机制是已证实根因；也未修改浏览器生产终止逻辑。

最终全量命令`.venv-computer-use/bin/python -m pytest -q`，源码`ac9b85d`，退出0：**1087 passed、4 skipped、1 xfailed、1 warning，351.32秒**。日志`artifacts/native-inactive/final-pytest-reap-fix.txt`。warning来自既有pygame/pkg_resources弃用提示。首轮失败日志保留，模型推理与全量测试未重叠。源码、真实证据与文档均经独立复核；95项原生用例不代替真实模型能力分数。

## 原始证据位置与边界

controls1仍位于`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/native-inactive/2026-10-08-controls1`；controls2位于`/Users/wenbo/Kage/artifacts/native-inactive/2026-10-09-controls2`；controls3和本轮模型任务位于活动工作树的artifacts。两个checkout的原始目录不可混称为同一目录，不能归档或删去唯一证据。

AXFocusedApplication系统级只读探针的-25204保留为独立限制，未用于本轮验证。普通NS激活请求未实际执行的历史原因、旧controlled2窗口消失原因仍未确定；本轮只证明AX激活操作在controls3两个受控上下文可以真实生效。OCR候选仍未实现。模型末尾换行遗漏及两个Save引用失效的原因/恢复策略仍待新dev验证，不能自动补文本、吞掉失效引用或重跑旧任务救分。
