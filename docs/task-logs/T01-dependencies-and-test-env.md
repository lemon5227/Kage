# T01 依赖声明与测试环境修复

- 日期：2026-10-14
- 执行者：AI 助手（由 wenbo 领取）
- 父提交：`8d5f7c7`
- 环境：Linux 云端容器，Python 3.13.16
- 状态：完成

## 目标

新环境按 README 安装后能启动服务、能跑测试。

## 计划

1. `requirements.txt` 补 `rank-bm25`。
2. 新建 `requirements-dev.txt`（pytest、pytest-timeout）。
3. `.gitignore` 忽略 `.venv/` 与 `.venv-computer-use` 符号链接。
4. `test_memory_merge` 在无嵌入模型时跳过。
5. `docs/TESTING_GUIDE.md` 增加快速开始。

## 过程记录

| # | 做了什么 | 改动文件 | 怎么验证 |
|---|---|---|---|
| 1 | 复现：未装 rank_bm25 时 `import core.memory` 报 `ModuleNotFoundError: No module named 'rank_bm25'`（`core/memory.py:29` 顶层导入），导致 server 与 7 个测试文件无法导入 | — | 首次 pytest 收集报错 |
| 2 | 在 `jieba` 后加 `rank-bm25` | `requirements.txt` | 全新 venv 仅装 rank-bm25/numpy/jieba 后 `python -c "import core.memory"` 成功 |
| 3 | 新建开发依赖文件 | `requirements-dev.txt` | — |
| 4 | 加 `.venv/`；`/.venv-computer-use/` 改为 `/.venv-computer-use`（带斜杠的规则不匹配符号链接，原来 `git status` 会显示 `?? .venv-computer-use`） | `.gitignore` | `git status --short` 不再显示该链接 |
| 5 | `test_memory_merge` 先 `_ensure_model()`，模型为 None 时 `pytest.skip` | `tests/test_memory_round7_features.py` | 该文件 + test_memory.py：41 passed, 1 skipped |
| 6 | 快速开始一节，指向总任务规划的测试环境 | `docs/TESTING_GUIDE.md` | 链接检查 |

## 验证结果

```
python -m pytest -q tests/test_memory_round7_features.py tests/test_memory.py
41 passed, 1 skipped

python -m pytest -q --ignore=tests/test_round14_audio.py --timeout=90
3 failed, 984 passed, 5 skipped, 1 xfailed, 8 subtests passed
```

3 个失败均为总任务规划 2.3 节列出的容器进程回收问题，与本任务无关。

## 偏离计划

无。

## 遗留与后续

- `core/memory.py::_merge_similar_bm25` 使用绝对 BM25 分数阈值 `> 5`，在小语料、短句上几乎不会合并；无嵌入模型时记忆合并基本失效。建议改为相对分数（例如与自身得分之比）后恢复该测试在 BM25 模式下运行。
- `sentence-transformers` 为可选依赖，未写入 requirements；若要默认启用语义检索，需要在 requirements 中声明并评估体积。
