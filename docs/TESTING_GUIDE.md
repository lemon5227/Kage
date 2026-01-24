# Kage 迭代测试指南

## 概述

本文档描述如何对 Kage AI 助手进行迭代测试和改进。

## 测试流程

### 1. 运行测试脚本

```bash
cd /Users/wenbo/Kage
python3 scripts/test_comprehensive.py   # 综合测试
python3 scripts/test_round6.py          # 泛化测试
```

### 2. 分析 Kage 回复

观察以下关键点：

| 观察项 | 正常表现 | 异常示例 |
|--------|----------|----------|
| 意图判断 | `[意图判断]: COMMAND` | 应该是 COMMAND 但显示 CHAT |
| Action 格式 | `>>>ACTION: system_control("volume", "up")` | 格式混乱或函数名错误 |
| 执行结果 | `🔧 [工具输出]: 音量已调大 🔊` | 命令执行失败 |
| Kage 回复 | 简洁中文，符合人设 | 乱码、英文、hashtag |

### 3. 常见问题和修复位置

| 问题 | 修复文件 | 修复方法 |
|------|----------|----------|
| 意图分类错误 | `core/router.py` | 添加示例到 few-shot prompt |
| Action 格式错误 | `core/brain.py` | 在【能力定义】部分添加示例 |
| 工具执行失败 | `core/tools.py` | 修复对应的内部方法 |
| 回复有乱码/外语 | `core/brain.py` | 在 Report 模式加强中文指令 |

### 4. 修改后重新测试

修改代码后立即运行测试验证效果。

---

## 核心文件结构

```
core/
├── router.py    # 意图分类 (COMMAND vs CHAT)
├── brain.py     # LLM 提示词 (Action/Chat/Report 模式)
├── tools.py     # 工具执行 (system_control, open_app 等)
└── memory.py    # 对话记忆

scripts/
├── test_comprehensive.py  # 综合测试 (17 场景)
├── test_round6.py         # 泛化测试 (不同表达方式)
└── ...
```

---

## 已验证的能力

| 能力 | 触发示例 | Action |
|------|----------|--------|
| 音量调大 | "大声点"、"声音大点" | `system_control("volume", "up")` |
| 音量调小 | "小声点"、"声音小点" | `system_control("volume", "down")` |
| 静音 | "静音" | `system_control("volume", "mute")` |
| 亮度调高 | "亮一点"、"屏幕亮点" | `system_control("brightness", "up")` |
| 亮度调低 | "暗一点"、"屏幕暗点" | `system_control("brightness", "down")` |
| 打开应用 | "打开计算器"、"打开备忘录" | `open_app("Calculator")` |
| 关闭应用 | "关掉计算器" | `system_control("app", "close", "Calculator")` |
| 查 IP | "查我IP" | `run_cmd("curl -s https://api.ipify.org")` |
| 查时间 | "几点了" | `get_time()` 或 `run_cmd("date")` |
| 打开网页 | "打开百度" | `open_url("https://www.baidu.com")` |

---

## 待解决问题

1. **音量 GUI 不显示**: 当前使用 `set volume` 不显示系统 OSD，需要找到正确的 key code
2. **天气查询 URL 错误**: LLM 偶尔输出 `wttr.ina` 而不是 `wttr.in`
3. **时间查询不稳定**: 有时用 `get_time()`，有时用 `run_cmd("date")`

---

## 迭代方法

1. **运行测试** → 观察输出
2. **识别异常** → 确定是哪个环节的问题
3. **修改代码** → router.py / brain.py / tools.py
4. **重新测试** → 验证修复效果
5. **重复** → 直到所有场景正常
