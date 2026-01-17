# Project Kage (影) - Intelligent Desktop Assistant

**核心定义**：Kage 是一个运行在 Apple Silicon (Mac M4) 上的本地化智能助手。它采用微内核架构，强调隐私、记忆迁移能力和插件化扩展。

## 1. 核心架构 (The Core)
* **硬件平台**: Mac M4 (16GB RAM)
* **开发语言**: Python 3.10+
* **大脑 (Inference)**: Apple MLX 框架 + `Phi-3.5-mini-instruct-4bit` (3.8B 参数)
* **记忆 (Memory)**: 双层存储策略
    * L1: `JSONL` 原始日志 (Source of Truth, 用于迁移)
    * L2: `ChromaDB` 向量索引 (Vector Index, 用于 RAG 检索)

## 2. 交互层 (Interaction)
* **听觉**: `Faster-Whisper` (Local ASR)
* **视觉**: `Electron` + `PixiJS` (渲染 Live2D 模型)
* **通信**: `FastAPI` + `WebSocket` (实现前后端实时状态同步)

## 3. 扩展机制 (The "Limbs")
* **插件系统**: 基于 `Pydantic` 定义标准接口。
* **热重载**: `Watchdog` 监控 `/skills` 目录，实现 Python 脚本拖入即用。

## 4. 目录结构规范
/kage_project
├── /core           # 大脑核心 (LLM, RAG, Router)
├── /skills         # 插件目录 (用户自定义脚本)
├── /data           # 记忆存储 (JSONL + ChromaDB)
├── /interface      # 前端代码 (Electron/Vue)
└── main.py         # 启动入口

## 5. Prompt Engineering (针对 Phi-3.5 小模型优化)
由于我们使用的是 3.8B 参数量的小模型，为了解决“人称混淆”和“金鱼记忆”问题，采用了以下特殊架构：

### 5.1 Chain-of-Thought (思维链)
引入 `<think>` 标签，强制模型在输出回复前进行内部推理。
- **作用**: 提高对上下文的理解力，大幅减少幻觉。
- **流程**: `Input -> <think>Analyze Context...</think> -> Final Output`

### 5.2 Dialogue Transcript (剧本模式)
将历史对话格式化为标准剧本模式 (`Master: ... \n Kage: ...`)。
- **作用**: 根除“人称代词混淆”问题（例如把“我”理解成模型自己）。

### 5.3 Short-term Context Buffer
在 Prompt 中直接拼入最近 10 轮对话历史。
- **作用**: 弥补 RAG (检索增强生成) 在回顾最近对话时的不准确性（Recall Contamination）。