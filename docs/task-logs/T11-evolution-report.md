# T11 触发源③：主动汇报"我学会了什么"

- 日期：2026-10-14
- 执行者：AI 助手（由 wenbo 领取）
- 父提交：`262e96e`
- 环境：Linux 云端容器，Python 3.13.16
- 状态：完成

## 目标

用户回来时，Kage 主动用一句话说明空闲期间练习了什么、结果如何（包括没有提升和出错的），有晋级技能时顺带询问是否启用。

## 过程记录

| # | 做了什么 | 改动文件 | 怎么验证 |
|---|---|---|---|
| 1 | `EvolutionScheduler.report_notifications()`：读取上次汇报之后完成的运行（状态文件 `announced_until`），按"晋级 / 没有提升 / 没跑完"三类计数，生成一条汇总通知；汇报后推进 `announced_until`，同一批运行只汇报一次 | `core/evolution/scheduler.py` | 单测 |
| 2 | 有晋级时文案追加"要启用新学到的技能吗？"，并附 `action={"type":"adopt_skill","run_id":<最近一次晋级>}`，用户点"好的"即由 T10 的处理器采用 | 同上 | 单测 |
| 3 | 调度器的 `collect()` 先汇报再判断是否开始新运行；汇报走 Heartbeat → T05 策略（免打扰、频率、静音）→ 送达 | 同上 | Heartbeat 集成单测 |
| 4 | 文案约束：只说"在对比测试中更好"，不说"学会了所有同类任务"；没有提升和出错照实说 | — | 单测断言文案 |

示例文案：`你不在的时候我练习了 3 次：1 次找到了在对比测试中更好的做法，1 次没有比原来更好，1 次没跑完（环境或预算问题）。要启用新学到的技能吗？`

## 验证结果

```
python -m pytest -q tests/test_evolution_scheduler.py
10 passed

python -m pytest -q --ignore=tests/test_round14_audio.py --timeout=90
3 failed, 1040 passed, 5 skipped, 1 xfailed, 8 subtests passed
```

## 偏离计划

计划写新建 `EvolutionReportSource` 放在 `core/proactive_sources.py`；实际作为调度器自身的方法（汇报数据就在调度器日志里），调度器已经是 Heartbeat 触发源，无需再加一个。

## 遗留与后续

- 多次晋级时只对最近一次提供"启用"；更早的晋级候选需要另一个入口（列出待采用候选），属于后续 UI/工具工作。
