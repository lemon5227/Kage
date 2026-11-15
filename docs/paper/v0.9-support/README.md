# v0.9 支撑包：遗忘修复（R3 → R3g → R3f → R3fg）

给论文 v0.9 用的材料，正文由用户写。v0.8 正文停在“发现遗忘、三个训练 seed 复现”；本包补上 11 月的修复链。

```
python3 docs/paper/v0.9-support/make_support.py
```
产出（全部由各报告的 `analysis.json` 生成，没有手填的数）：
- `forgetting-fix.md`：总表 + 误用 + 读回后改写 + 题级对比（可直接转成论文表 10）。
- `forgetting-fix.json`：同样的数，机器可读。
- `fig5_forgetting_fix.pdf/.png`：三联图（学过 / 留出 / 读回），一个点 = 一个训练 seed 的 3 次评测；虚线是第二轮进入门槛（55/72、12/36）。

## 数字出处
| 内容 | 重算脚本 | 原始包 |
|---|---|---|
| 原学生、R3 三个 seed | `evidence/reports/r3t-seeds/analyze.py` | `evidence/kaggle/v26…`、`v41-results.tar.gz` |
| R3h 门控（未入总表，离线合成） | `evidence/reports/r3h/analyze.py` | 同上 + v32 |
| R3g | `evidence/reports/r3g/analyze.py` | `evidence/kaggle/v44-results.tar.gz` |
| R3f | `evidence/reports/r3f/analyze.py` | `evidence/colab/r3f-eval-results.tar.gz` |
| R3fg | `evidence/reports/r3fg/analyze.py` | `evidence/colab/r3fg-eval-results.tar.gz` |

## 这条链能支持的论点（建议写法）
1. **遗忘是数据形状造成的，可分解。** R3 的提升和留出题崩塌来自同一批“直接写答案”的样本（R3b–R3e 消融，v0.8 已有）。11 月把它拆成两个独立原因并分别修复：
   - 丢了“写完读回”的习惯 → 在训练轨迹里插回读回步骤（R3g）：读回 0 → 100%，但留出仍 5/36。**读回不是留出题崩塌的原因。**
   - 丢了“写对没见过的代码”的能力 → 回放 363 条原学生自己在**别的**编程族上写对的代码（R3f）：留出 0–2/36 → 15、18/36（对 R3 seed 1–2：+0.43，10 升 0 降，p = 1/512）。
2. **两个修复可叠加。** R3fg 同时满足：学过 65、63/72，留出 19、13/36，读回 203/208；与 R3f 相比学过 +0.04（p = 109/256）、留出 −0.01，无差别。
3. **门控（R3h）能绕开但不是修复**：推理时按任务相似度决定是否加载适配器，能力题零路由错误，但模型本身没变。

## 必须同时写的限制
- **留出只回到原学生水平，没有超过**：对 v26 原学生 fg0 +0.11（p = 17/32）、fg1 −0.06（p = 111/128）。能说“不再遗忘”，不能说“产生迁移”。
- **读回是轨迹形状，不是自检**：R3fg 留出题 59 次读回后改写 0 次（R3g 72 次读回改写 2 次，通过 0）。
- **负例误用未消除**：`lookalike_readonly-10502` 在 R3 seed 1–2（1/72）、R3f（3/72，seed 0）、R3fg（3/72，seed 1）都出现；R3g 为 0/72。
- **评测环境不完全一致**：R3/R3g 在 Kaggle T4，R3f/R3fg 在免费 Colab T4（同型号，同一份预编译 llama-server）；每次评测都带同会话原学生锚点（1 次），锚点留出 5–8/12，波动不小。
- 两个训练 seed；p 为名义值，未做多重比较校正。
- R3f 的后半段训练在 Modal A100 上完成（fp16 配方相同），R3fg 全程 Kaggle T4。
