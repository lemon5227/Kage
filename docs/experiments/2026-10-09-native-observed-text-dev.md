# 真实模型文本与生命周期取证 — 2026-10-09

C1.2-R-text-dev4固定一个新专用TextEdit任务，源码`e3e7ccb`，仅一次真实本地模型尝试；结果 **0/1，kernel failed，独立checker failed**。4次请求，14977输入/857输出token，链61.786秒，0云请求。Agent实际fill和Save已作用，但写入的是带引号和字面量反斜杠n的JSON表示，不是要求的文本。旧dev3/controlled2失败保留，不追加尝试救分。

```sh
.venv-computer-use/bin/python -m scripts.experiments.native_text_observed_dev --output artifacts/native-text-observed/2026-10-09-dev4
```

## 协议与实现

新文档`kage-text-observed-dev4.txt`，公开目标21个Unicode字符、3个真实LF、含末尾LF；沿用RECOVERY_SOUL的精确文本核对/新观察Save策略。复用NativeChainProvider、NativeEvaluator、EvolutionRunner、Journal和BudgetTracker；8次实际请求上限在provider、真实chain和kernel预算同时落实，16 Agent+4可信检查/清理动作，总20，最多2次app open。输出每请求300，kernel保守预留3000；不是声称严格token上限。480秒为合作式期限，同步HTTP/AX可能越界。

只增加实验Environment/adapter/model包装与独立只读observer，旧dev入口保持。setup后observer必须先获得原owned和fresh同URL/同PID有效baseline，才返回chain并允许首模型派发；首请求另写monotonic起点。2秒采样、最多240样本/480秒，任务早结束立即停止，保留实际partial不补齐。自有session/process group包含fresh子进程，finally只清理该组；只停止自有模型service。

分别记录模型request/response/error、原生动作dispatch/result、checker Close意图/实际作用、reopen/cleanup，以及读取前后stage和时间。意图不等于窗口已关闭，读取跨阶段不强推关闭因果。observer只读原对象身份、精确URL匹配/数量、PID和磁盘hash/字节，不读写其他文档；setup raw trace关闭，但继承的发现流程仍会在内存枚举标题，不能宣称完全不读。模型只接收公开任务及owned AX结果，observer/hidden checker不输入生成上下文。

冻结源码/测试、Git revision、实际Soul/task/protocol hash、模型/server hash与实际服务命令，首请求前完成。源码审查通过，**82 focused passed**后才执行该单次实验。

## 独立结果与问题定位

| 项目 | 实际证据 |
|---|---|
| 请求/预算 | chain、派发事件、kernel usage、budget均4次；最终无active reservation |
| 动作 | Agent fill+Save共2；checker菜单+Close、cleanup菜单+Close另4，共6；open/reopen共2 |
| 目标文本 | 21字符、3真实LF、末尾LF |
| 保存实际文本 | 26字符、0真实LF、3个字面量`\n`，外围双引号；62字节 |
| 独立检查 | 实际Save已作用，关闭重开AX与磁盘精确匹配均false，checker明确failed |
| 生命周期 | 31样本；30个Agent阶段原身份/fresh均存在；另1个checker重开后的原对象被替换，fresh仍为同文档 |
| 激活分支 | 0次activate，本轮已激活；不能算非激活分支再次验收 |

磁盘原字符串的`json.loads(actual)==expected`，而`actual!=expected`；fill原参数和AX读回同样保留该编码。模型最后自述“精确匹配”被外部检查否定。本轮是实际双重编码问题，区别于dev2只有末尾LF缺失，不能用旧JSON日志转义推测代替字符核验。

observer有效fresh baseline早于首派发，采样起点晚约4.001ms。Agent阶段没有观察到原窗口失去；唯一replacement样本发生在可信checker Close已作用、reopen之后，读取期间又跨到cleanup阶段。应用PID保持32351；这与有记录的关闭/重开一致，不计Agent异常失去，也不能靠2秒采样推定每瞬间或旧失效根因。

18项父级完整性检查通过，包括冻结源与Git字节、实际prompt/hash、预算/调用/token一致、基线/时序、动作/open、失败保留、双重编码字符、阶段化身份、自有observer group不存在和自有service停止。observer返回0，父只读PGID/PID检查确认不存在，费用0；审计通过不代表任务通过。

原始目录在活动worktree的`artifacts/native-text-observed/2026-10-09-dev4`，含freeze/model请求响应/工具/阶段/observer/独立检查/预算/service日志与audit.json。固定结果不覆盖。

## 窄改进与验证范围

实验后`961fb57`给NativeAXAdapter的文本目标新增`value_metrics`：观测字符串字符数、真实LF数、末尾LF、字面量反斜杠n数，scope明确为`observed_value`。复制目标/快照，不改原始值、driver状态或原snapshot revision；quoted/code文本照原样写入，不自动JSON解码、补换行或用隐藏expected纠错。指标仅描述已有可见值，driver可能截断长文本，不冒称全文指标。

新增回归先缺指标失败，再核验真实observe/fill返回21/3与26/0的差异、原始写值不变、非文本/None不捏造指标、源snapshot不突变；**70 focused passed**。该改进在dev4之后，未重新运行模型，不能声称已解决模型文本问题或提高成功率。

最终全量源码`961fb57`：**1138 passed、4 skipped、1 xfailed、1 warning，236.87秒，exit0**。日志`artifacts/native-text-observed/final-pytest-961fb57.txt`保留；warning来自pygame的pkg_resources弃用提示。模型service先停止，再跑全量，无并行推理压力。源码/实际证据/报告独立复核通过，旧0c全量1091仅作历史验证。

## 下一包

下一C1.2-R-text-feedback：冻结一个新dev5，公开要求核对`value_metrics`的21字符/3LF/末尾LF及原文，再Save；保留实际请求/动作/阶段观察与预算，同样最多一次。先验证反馈是否被真实模型消费，不重复dev4救分；旧生命周期原因仍未知，本轮未覆盖非激活AX写入。有持续observer的运行不能单变量归因模型或激活。E2/E3/E4研究线可交替推进。
