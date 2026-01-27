# Kage 技术演进与优化记录

这里记录了 Kage 从 v1.0 到 v4.0 的关键技术选型和优化经验。

## v3.0: Dual-Layer Architecture (双层架构)
**时间**: 2026.01
**背景**: 为了解决 LLM 容易混淆“聊天”与“指令”的问题，引入了轻量级路由层。

### 1. Dual-Layer Router (双层脑)
- **Chat Mode**: 纯对话，载入记忆，**严禁使用工具**。
- **Command Mode**: 纯执行，不载入杂乱记忆，**能够使用工具**。
*(注: v4.0 已升级为 <1ms 的 Rule-Based Router)*

### 2. Feedback Loop (反馈闭环)
Kage 拥有自我纠错能力：
1. **Action**: 执行 Shell 命令。
2. **Observation**: 读取命令输出结果。
3. **Report**: 结合用户问题，用自然语言汇报结果 (Prompt 强力约束，防止幻觉)。

### 3. Streaming & Latency
- 迁移至 `MLX` 框架，在 M4 芯片上实现 Token 秒出。
- Router 耗时 <20ms，用户无感切换模式。

---

## v2.0: Prompt Engineering (针对 Phi-3.5 小模型优化)
**时间**: 2025.12
**背景**: 使用 3.8B 参数量的小模型时，为了解决“人称混淆”和“金鱼记忆”问题，采用了特殊架构。

### 1. Chain-of-Thought (思维链)
引入 `<think>` 标签，强制模型在输出回复前进行内部推理。
- **作用**: 提高对上下文的理解力，大幅减少幻觉。
- **流程**: `Input -> <think>Analyze Context...</think> -> Final Output`

### 2. Dialogue Transcript (剧本模式)
将历史对话格式化为标准剧本模式 (`Master: ... \n Kage: ...`)。
- **作用**: 根除“人称代词混淆”问题（例如把“我”理解成模型自己）。

### 3. Short-term Context Buffer
在 Prompt 中直接拼入最近 10 轮对话历史。
- **作用**: 弥补 RAG (检索增强生成) 在回顾最近对话时的不准确性（Recall Contamination）。
