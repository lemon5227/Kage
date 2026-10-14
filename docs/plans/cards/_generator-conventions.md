# 生成器通用规范（W1-2 … W1-7 共用）

照 `core/evolution/stream_tasks.py` 里的 `log_aggregation` 写，**结构完全一样**：

1. 函数 `def <family>(seed: int) -> dict`，第一行 `rng = random.Random(f'<family>:{seed}')`。所有随机都用这个 rng，不准用全局 `random`。
2. 返回字典的键固定：`family`、`instruction`、`file`、`function`、`initial_source`、`cases`、`params`。
   - `initial_source`：桩函数，例如 `def {fn}(rows):\n    return []\n`，**必须让所有用例失败**。
   - `cases`：列表，每项 `{'args': [...], 'expected': ...}`，或者要求抛错的 `{'args': [...], 'raises': 'ValueError'}`。值必须能 JSON 序列化（不要 tuple、set）。至少 5 个随机用例 + 卡片里列出的边界用例。
   - `expected` 一律由模块里的参考实现 `_<family>_reference(...)` 算出，不要手写。
   - `params`：生成时抽到的参数（给测试用，**不会**给模型看）。
3. 指令 3 种句式，每种都要写清：文件名、函数签名、输入格式、输出格式、边界规则（卡片里给了必须提到的规则）、保存文件。
4. 随机项至少包括：函数名（≥4 个候选）、文件名（≥3 个候选）、卡片指定的变化维度。
5. 在 `FAMILIES` 字典里注册。只用于评测的族（F5、F6）不需要特殊处理，由 W1-9 冻结清单时决定放哪。

## 测试写法（照 `tests/test_stream_tasks.py`）
新建 `tests/test_stream_<family>.py`：
- `test_deterministic`：同 seed 结果相同，不同 seed 不同。
- `test_reference_passes_stub_fails`：对 seed 1000–1029，写入 `initial_source` → `check_python_function` 得 0.0；写入「参考解源码」（在测试文件里用字符串模板，按 `params` 填参数）→ 得 1.0。
- `test_variety`：60 个 seed 里，句式开头 ≥3 种，函数名 ≥4 种。
- 卡片额外列出的测试。

命令：`~/kvenv/bin/python -m pytest -q -p no:cacheprovider tests/test_stream_<family>.py tests/test_stream_tasks.py`
