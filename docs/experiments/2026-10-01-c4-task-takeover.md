# C4.1 真实任务级云端接管

状态：首个真实本地失败→真实云纠正→独立检查通过，C4.1完成。尚未证明学生经验迁移或权重学习。

## 机制

TeacherTakeoverProvider是受信任实验协调器，复用KageChainProvider、ToolExecutor、Evaluator、Journal和预算账本。先执行学生，检查实际产物；只有未通过才允许一次有上限的教师段。教师收到同一目标、实际工具结果和检查未通过的状态，继续操作同一工作目录，不重置文件。隐藏expected和功能测试用例不进入教师/学生提示。工具事件标明student/teacher，元数据分开保留停止原因、各自usage、前后文件状态digest、外部检查。教师也可以失败，失败不记为示范成功。

网络请求失败的HybridModelProvider继续保持原职责；本包不是把“HTTP成功”当任务成功。当前策略是整段有限接管（最多6调用/5步），尚未做先单动作纠正再接管的优化，也尚未接入桌面UI或GUI执行。

## 真实实验

2026-10-01，冻结files-v1的meeting_slot留出题；本地Agents-A1同权重、温度0和原工具预算，云DeepSeek `deepseek-flash`。

- 学生：2调用，1832输入/372输出tokens；读取真实calendar.json后未写结果，incomplete/model_returned。
- 教师：3调用，3539输入/424输出tokens；读取同目录calendar.json，写out.json，最后返回；外部JSON检查正确为start=40、end=60。
- 系统：完成，51.907秒；学生独立成功仍为0/1，云接管完成为1/1，不能把系统成绩归给学生。

这是留出集的接管评估，只能作云救场对照，禁止进入学生检索、技能或训练材料。不同输入上的学习收益尚未测量。原始完整请求响应、产物、事件/预算SQLite保存在工作树 `artifacts/c4-takeover-meeting-v1/`（Git忽略）；凭据文件未复制进产物。

## 接口问题与修复

官方API默认thinking enabled；现有Kage没有跨轮回传reasoning_content，直接使用默认模式可能出400或把300输出预算用在推理上。本次新增可选thinking参数，实验显式关闭，其余provider默认行为不变；不采隐藏推理链。见[官方thinking接口](https://api-docs.deepseek.com/guides/thinking_mode/)。测试先因缺少该构造参数失败，修复后验证实际HTTP载荷含disabled且300token上限保留。

配置找回：用户原先写入的私有 `artifacts/private/deepseek-settings.json`，权限600；现有用户config中的cloud_api实际指向旧本地服务，不能误拿它当教师。凭据未输出，生产默认仍使用本地模型。

## 预算和验证

官方[价格页](https://api-docs.deepseek.com/quick_start/pricing/)核验2026-10-01：Flash高峰缓存未命中输入$0.30/百万、输出$1.20/百万。按最高价、不享缓存折扣计算，本次云用量上界约$0.001571；这是使用量估算，不是已读取的账户账单。命令限单任务单次，最多6云调用、每请求完整消息/工具JSON至多12000字节、输出至多300token，保守费用上限$0.02376，账本预算$0.03。账本将本地和云token一并按最高云价预留，作为保守限制；真实云usage另列。

```sh
python scripts/experiments/task_suite.py --runs 1 --task meeting_slot \
  --teacher-config /Users/wenbo/Kage/artifacts/private/deepseek-settings.json \
  --max-cost-usd 0.03 --output-dir artifacts/c4-takeover-meeting-v1
```

行为测试：教师读到学生写错的真实文件并纠正、学生已通过时零教师调用、教师空泛声称完成仍不通过；隐藏评分不入提示。相关19 passed。

全量首次与模型推理重叠：814 passed、1 failed（既有技能隔离测试的0.3秒超时后，下一次正常子进程也没有及时返回value）。按systematic-debugging核对堆栈，独立复验通过；停止活跃推理后全量815 passed、4 skipped、1 xfailed，70.42秒。没有放宽超时或删除失败断言。负载引起调度超时是待进一步测量的解释，不能把一次空闲复验当已证明并修复根因；本报告保留该失败。性能时间与单元测试有重叠，不用于引擎速度比较。
