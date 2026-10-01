# C4.2 / E2.0 最小经验档案

状态：最小档案完成；未实现双岛、完整谱系搜索或向学生自动注入经验。下一包是C4.3示范生成技能。

## 实现与过程

ExperienceArchive直接在既有Journal SQLite增加episodes索引，沿用RunResult与原轨迹，避免另起日志/评分系统。记录goal、family、split、执行版本元数据、检查、usage、真实工具trace/产物文件引用、字节数和SHA256。另存可复原的setup JSON（只含目标和初始文件，不含expected或隐藏测试）。新接管运行在教师动作前复制学生失败工作目录到相邻student-state目录，引用与摘要写入takeover；真实教师继续操作原工作目录。

每个执行episode保留，身份重复导入不增加记录。检索只选verified且dev且家族相符；按目标和证据内容去重，避免三次重复运行变成三份训练示范。文件缺失或内容改变转为stale，不再检索。failed与holdout始终保留但不作正示范。现阶段stale检测覆盖文件证据；工具升级后的兼容性还要由未来候选复验确认，不能宣称自动证明所有经验仍然适用。

先写重启/重复、留出过滤、失败过滤与产物改变回归，首次因缺少模块失败。补充不同run ID的同一示范去重回归后再次失败（返回两个dev），再修为证据内容去重。增加失败状态快照回归：学生错误文件值7保留在snapshot，原目录被教师改为14。

## 实验与验证

导入真实C2全部18运行：18episode，检索只返回去重后的3条dev示范。再次导入仍18条/3条，不吞失败样本。导入真实C4留出接管：1episode，检索0条。初次开发索引未包含setup引用，补齐字段后清空并重建的仅是本轮临时episodes索引，原runs/events/原始文件未改。两个索引库分别沿用各实验的journal.sqlite。

相关20 passed。最终全量817 passed、4 skipped、1 xfailed，69.43秒（没有活跃模型推理）。raw/model日志仍在artifacts，未写入规划正文或Git；原始C4旧实验没有新加入的failure_state_ref，不能倒填成当时已捕获快照。以后运行自动产生该引用。

```sh
python scripts/experiments/index_episodes.py --results artifacts/c2-files-v1/results.json --journal artifacts/c2-files-v1/journal.sqlite
python scripts/experiments/index_episodes.py --results artifacts/c4-takeover-meeting-v1/results.json --journal artifacts/c4-takeover-meeting-v1/journal.sqlite
```

原始数据工作树位置：`/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/artifacts/`。工作树保留以维持SQLite里的绝对引用。归档/迁移前必须迁移证据并重建索引，否则检索会按设计标stale。结果和报告没有声称本地权重改变，也尚未运行技能迁移及关闭云端对照。

## 接口补齐：失败类型与环境过滤

领取下一包时复核队列发现，仅家族过滤不足以覆盖原C4.2验收中的失败类别/环境过滤。补可选failure_status与environment过滤，后者精确匹配记录的环境字段；验证无误匹配才进入证据去重。先写三个环境/失败类别组合的实际SQLite检索回归，旧实现因不接受参数失败；修复后3项档案测试通过。未声称精确字段匹配可以代替跨版本兼容性测试。全量结果待C4.4结束后的空闲检查另记。
