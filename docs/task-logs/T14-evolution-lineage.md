# T14 E2.1 候选谱系（lineage）记录与查询

- 日期：2026-10-14
- 执行者：AI 助手（由 wenbo 领取）
- 父提交：`70eee28`
- 环境：Linux 云端容器，Python 3.13.16
- 状态：完成（工程）

## 目标

每个参与对比的候选都能回答"它是怎么来的"：父代、第几代、由哪次失败触发、假设是什么、对比结果如何。

## 过程记录

| # | 做了什么 | 改动文件 | 怎么验证 |
|---|---|---|---|
| 1 | Journal 新表 `lineage`（`CREATE TABLE IF NOT EXISTS`，不改旧表，旧数据库可直接打开）：候选 digest、id、父 digest、代数、target、hypothesis、bundle 路径、来源 JSON、对比 JSON、创建时间 | `core/evolution/journal.py` | 旧库打开测试 |
| 2 | `record_lineage(child, parent, source=, compare=)`：父代不在表中时作为第 0 代根节点补记；子代代数 = 父代 + 1；同一候选再次对比时更新对比结果、保留创建时间。`lineage(digest)` 返回从候选到根的链（防环）；`lineage_all()` 列出全部 | 同上 | 三代链测试 |
| 3 | `Promoter.compare(..., source=None)` 结束时写 lineage（对比 id、是否晋级、父/子分数） | `core/evolution/promotion.py` | 既有晋级测试不回退 |
| 4 | `run_search` 把触发本次变异的失败任务 id 与失败 run id 作为 `source` 传入 | `core/evolution/search.py` | 端到端：fixture 搜索后，晋级候选的链为 [第1代, 第0代]，来源为 `repair-whitespace` |

## 验证结果

```
python -m pytest -q tests/test_evolution_lineage.py tests/test_evolution_promotion.py tests/test_evolution_search.py tests/test_evolution_kernel.py
29 passed, 1 skipped

python -m pytest -q --ignore=tests/test_round14_audio.py --timeout=90
3 failed, 1046 passed, 5 skipped, 1 xfailed, 8 subtests passed
```

## 偏离计划

- 计划要求给 `Candidate` 增加 `parent_digest`/`source_episode_ids`/`generation` 字段；没有改 `Candidate`（它是 frozen dataclass，被序列化进 active.json 和报告，加字段影响面大）。谱系信息全部放在 Journal 的 lineage 表中，由 `compare()` 写入，效果相同。
- 来源记录的是"失败任务 id + 失败 run id"，而不是 ExperienceArchive 的 episode id（search 流程不经过 archive）。

## 遗留与后续

- 浏览器工作流候选（`core/computer_use/skill_mutator.py` 路径）也经过 `Promoter.compare`，会自动记录谱系，但其来源字段目前为空，需要在调用处传 `source`。
- T16（Launcher 展示谱系/diff）可直接读 `Journal.lineage_all()` / `lineage()`。
