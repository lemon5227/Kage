# C2.1-B2.1a：浏览器episode与生成输入桥接

日期：2026-10-03。父提交`1aec7fd01a8cfc3a5b8b0757ae6d708fde808ffc`；代码/冻结评测提交`44918324c0e7a014e18ef2974466568d15b70b0e`。验收层级：工程、旧真实运行证据投影和新测试环境健全性；没有新模型调用、云费用或候选晋级。

## 问题和方案

原E2档案对浏览器运行没有fixture、actor JSONL和浏览器trace；检索失败状态只认文件任务的`student_check.status`。直接给现有文件技能生成脚本喂浏览器档案还会把后台检查材料和完整运行元数据混进提示。B1教师成功样本也不是纯教师完成：学生先切换Email/SMS，教师只观察并保存。

`ExperienceArchive.record`现对浏览器附可信reset所需fixture/评分配置、初始观察、actor/browser trace、最终检查和文件hash；原文件episode setup编码保持不变。`normalize_browser_episode`记录学生外部结果、停止原因/模型错误、教师是否实际操作、actor分段、最终外部读回；不把请求超时归因成“缺技能”。`generation_feedback`先核验全部证据hash，再白名单投影公开任务、初始/后续DOM、真实浏览器动作与可见错误；不输出fixture、评分条件、后台文件或完整run。失败和test split不能成为正示范。准备脚本只读取dev并生成独立feedback文件，未调用模型。

## 实际旧证据

对`artifacts/c21-browser-takeover-v1/results.json`的3条B1真实运行进行只读转换，在`artifacts/c21-browser-episodes-prep-2026-10-03/`建立新索引（原始数据未改）：2条`student_only/final_verified`，1条`mixed_student_teacher/legacy_final_verified`。混合条目`student_check_passed=false`、`teacher_check_passed=false`，但最终`browser-check.json`读回与backend一致、最终RunResult评分1；教师轨迹为observe+Save，并有后续请求超限模型错误。档案保留这些相互有张力的原值，不改写旧阶段检查，也不称其纯教师多步示范。三个生成反馈均有实际动作/DOM，均未出现`scoring_criteria`或`browser-outcome.json`字段。

原始B1 `results.json` SHA256 `a39da518a508839f8e959f3775ede437be99f0d0733cd694b160f786e1ba3793`；新索引manifest SHA256 `1f1c7522da56126c907d584968482f04e93353cfcc73b8766e46702715edc5b6`。后者在忽略目录，保留活动worktree；源码与测试在提交中。

## 冻结与验证

在任何浏览器技能候选生成前冻结[preferences新test三变体](../../eval/computer-use/browser-transfer-v1.json)，SHA256 `46c098fe99e972acca02c76b07584d8e0326c5a9b47ec89ebb07ea5366a4d6c1`。三例改变初始勾选/顺序/标签，其中一例目标值反转；与已运行旧holdout分开。生成器只能读dev反馈，不读取此test任务或结果。可信脚本在三例真实本地HTTP页面上逐一保存并以外部checker确认3/3，仅证明fixture与判分自洽，**不是Agent迁移成绩**。

聚焦`.venv-computer-use/bin/python -m pytest -q tests/test_browser_episodes.py tests/test_experience_archive.py` → **10 passed**；全量`.venv-computer-use/bin/python -m pytest -q` → **869 passed、4 skipped、1 xfailed**。测试包括证据篡改后不可用于生成/检索、重启去重、test/失败不进正示范、秘密哨兵不进feedback、老文件setup不变、从归档fixture重建页面并读回。`git diff --check`通过。相关源码SHA256：`archive.py` `295a94d97b0d8c5355a5c9fada8e9e791594a4f154dd55070765d8d0ab080f69`，`episodes.py` `06a53087b216693cce5d676b3e28506383e989a310b1e7123789ca09ab6b640f`，准备脚本`542f3a0a0ffe1e7de23407d6ba2653b4b7ce78ed981e45d7a2e37abd6cca90bc`。

尚无浏览器技能解释器、模型生成候选或新test成绩。B2.1b下一步在同一Page接通`skill_search/skill_call`和逐primitive预算；B2.1c再从这份已标明来源的dev反馈生成候选，不能把本次归档计作学习效果。
