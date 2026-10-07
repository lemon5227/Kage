# C4.5-DOM教学入口与持久任务工程报告

初版工程：2026-10-05；整包收尾更新：2026-10-07。实现`7d98e16`，生命周期审查修复`9308906`/`9bc4105`，最终跨模块修复`ee52cf2`，父版本`97c4b64`。范围是受控profile/preferences表单，工程录制来源为automation；真人教学验收待实际用户操作。

用户在Launcher选择教学任务，开始后操作专用浏览器窗口，结束并提取；独立保存/读回检查通过后，得到未晋级候选、digest、可编辑JSON参数和证据链接。修改参数后，复用API启动新的Page和新后台实例，由现有工作流执行器执行，模型请求为0。界面分别显示示范检查、候选生成和复用检查，失败原因不会被“后台运行结束”覆盖。历史候选只在明确选择后使用。

API前缀`/api/browser/demonstrations`：GET catalog/list/run/artifacts、POST创建/finish/stop/replay。创建与复用返回202，不阻塞主循环；未知run404、参数422、已有活动任务或不可复用409。单服务一个活动session；结束和停止幂等，客户端POST仅一次。任务上限为教学64归一化动作/900秒、复用16 browser primitives/480秒。

服务继承已有BrowserTaskService/BackgroundWorker与bootstrap；专用demonstration_worker拥有浏览器和隔离进程组。真人默认headed，只有显式automation允许headless/CDP。worker保存实际DOM、输入和动作，依次flush、checkpoint settle、Evaluator、RunResult、ExperienceArchive与编译器；复用走同一BrowserSkillCatalog/ToolExecutor，不建立第二套Agent循环或评分。

session.json记录创建元数据，status.json记录ready/动作数；原始DOM/输入/事件、检查、episode、候选与参数、result及产物索引留在本地。索引排除可变控制文件，每个公开产物都有SHA-256。Journal在run目录旁，避免其后续写入破坏证据hash。所有公开索引文件均在真实API回归中通过HTTP取回核对。

| 独立审查发现 | 真实复现与修复 |
|---|---|
| worker已写成功result但尚未正常退出，重启会误信成功 | 延迟异常退出包装器复现。新增父进程实际returncode hook；退出、取消检查全部完成后才写带result hash的acceptance，重启须核对身份/状态/hash和正常退出 |
| 挂起的旧worker无法读取停止标记，重启后仍存活 | 对实际worker发SIGSTOP复现。重启核对run/root/PID/PGID及完整启动命令，先协作flush，再有界TERM+CONT/KILL/回收；所有权不明则阻止替代任务，不能猜测或误杀 |
| 顶层finalizing但嵌套候选/检查/产物已提前公开 | 最终审查延迟异常退出worker真实复现候选与20个产物可读而无acceptance。完整公开结果/检查/候选/产物及下载统一由父进程接受控制；停止收尾期间禁止提前索引，内部原始字节仍保留 |
| 历史GET与开始POST重叠，新任务响应被丢弃 | 实际JS/浏览器延迟请求复现历史run仍显示、无法取消新run。历史加载持有busy，阻止开始/复用和重入选择，失败/空选择恢复控件，保持POST单次 |
| 主进程已死但暂停的子进程组仍在，被误认为清理完成 | 第二轮复审通过真实bootstrap/Page、SIGSTOP与仅杀主进程复现。无法验证旧组所有权时公开恢复错误、无最终索引、不允许替代session且不猜测发送信号；可验证的存活主进程必须确认主进程与整个组均退出 |
| 重启在最后输入flush之前计算partial索引，hash随后变化 | 实际未失焦Name输入复现4个hash不匹配。先停旧写入者，再记录真实动作数/稳定索引；恢复标记阻止旧父进程迟到结果覆盖 |
| 工作流执行部分成功后失败，被误报浏览器不可用且无评分/episode | 合法参数中的不存在标签使第一字段已修改后失败。保留workflow_failed，仍对实际Page独立检查并归档failed RunResult；记录真实工具动作与workflow_engine来源，不计学生成绩 |

四个回归先RED：4 failed in9.42s；修复首次GREEN4 passed in11.59s。扩展检查又发现进程组消失不等于主进程已被回收，补有界PID等待/回收及剩余组清理，保留中间1 failed/56 passed日志。最终覆盖修复的命令：

```sh
.venv-computer-use/bin/python -m pytest tests/test_browser_demonstration_routes.py tests/test_browser_task_service.py tests/test_browser_demonstration.py tests/test_browser_episodes.py -q
```

首轮修复58 passed in82.38s；第二轮真实孤立进程组回归RED1 failed in2.47s、聚焦GREEN3 passed in5.04s。上述覆盖命令最终源码为**60 passed in85.45s**。此前入口聚焦80 passed in90.59s，之后UI与lazy import分别补最新聚焦验证；最终整包全量结果见总报告。初版前端build成功1.73s；最终跨模块修复因JS变更重新构建，成功1.17s，现存Cubism经典script及674.06KB chunk警告保留。最终新回归RED9 failed in15.12s→GREEN9 passed in19.00s，六文件覆盖检查102 passed in109.21s，实际命令与完整输出见review-evidence/final-fix-report.md及日志。

Launcher使用现有fetchJson与事件接口，控件有明确label、状态/错误区域，参数只进表单value/textContent。generation/run/请求序号与终态锁阻止旧GET响应改变当前任务按钮；覆盖真实开始、未保存、结束、参数复用、停止、重载、延迟响应与启动失败。浏览器通知只走面板/事件，无TTS。

重启清理依赖现有POSIX进程组与标准ps；同步恢复仅发生服务构造，单个旧worker清理有界，失败显式阻塞。历史未接受的旧成功结果不变成可用候选。真实脚本/本地模型pilot、独立审计、最终复审与当前任务状态见[总报告](2026-10-07-browser-demonstration.md)。完整审查与红绿记录存于活动worktree同包原始目录review-evidence，保留唯一证据副本。
