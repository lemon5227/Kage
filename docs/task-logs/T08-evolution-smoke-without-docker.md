# T08 进化 smoke 不依赖 Docker 也能跑通

- 日期：2026-10-14
- 执行者：AI 助手（由 wenbo 领取）
- 父提交：`660ccad`
- 环境：Linux 云端容器（无 Docker），Python 3.13.16
- 状态：完成

## 目标

在没有 Docker 的机器上也能跑通"基线失败 → 生成候选 → 父子对比 → 晋级 → 复用"的演化闭环 smoke，供 T09 及以后的任务回归。

## 过程记录

| # | 做了什么 | 改动文件 | 怎么验证 |
|---|---|---|---|
| 1 | 复现：`kage_evolve.py search --provider fixture` 在无 Docker 时输出 `Docker image unavailable`（默认 `eval/evolution/pilot.json` 的 `execution_mode` 是 docker） | — | 手动运行 |
| 2 | 发现 `run_search` 已支持配置项 `execution_mode: "process"`，且已拒绝 live + process 组合；只缺命令行入口 | — | 阅读 `core/evolution/search.py` |
| 3 | `run_search(..., execution_mode=None)`：覆盖值与配置不同时写入配置副本，并把 `experiment_id` 加后缀（如 `pilot-process`），因为隔离后端不同就是不同协议，避免与已有 docker 结果目录的协议校验冲突 | `core/evolution/search.py` | 测试 |
| 4 | CLI 新增 `--runner {docker,process}`；选 process 时 stderr 打印"不是安全沙箱"警告 | `scripts/kage_evolve.py` | 测试 |
| 5 | 新增 2 个测试：fixture + process 跑完整闭环且晋级；live + process 抛 `ValueError("...requires docker...")` | `tests/test_evolution_search.py` | 3 passed, 1 skipped（原 docker 测试在无 Docker 时跳过） |

## 运行结果

```
$ python scripts/kage_evolve.py search --provider fixture --runner process
WARNING: process runner is a development smoke, not a security sandbox
{"provider_mode": "fixture", "execution_mode": "process", "stop_reason": "dev_passed",
 "estimated_cost_usd": 0.000785, "report_path": "runs/evolution/search/fixture/pilot-process/seed-42/report.json"}
基线 dev: [failed, passed] → 候选晋级 [True] → 复用 [passed]

$ python scripts/kage_evolve.py search --provider live --runner process
Configuration/artifact error: live generated code requires docker; process is only for trusted fixtures
```

## 验证结果

```
python -m pytest -q tests/test_evolution_search.py
3 passed, 1 skipped

python -m pytest -q --ignore=tests/test_round14_audio.py --timeout=90
3 failed, 1024 passed, 5 skipped, 1 xfailed, 8 subtests passed
```

## 偏离计划

无（计划中的"拒绝 live+process"已有实现，只补了入口和测试）。

## 遗留与后续

- fixture 模式的"生成器"是写死的合成数据，只证明管线通；真实生成需要云 key + Docker（`docker build -t kage-evolution:local sandbox/evolution`），在 Mac 上执行。
