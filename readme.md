# Project Kage (影) - Intelligent Desktop Assistant

**核心定义**：Kage 是一个运行在 Apple Silicon (Mac M4) 上的本地化智能助手。它采用微内核架构，强调隐私、记忆迁移能力和插件化扩展。

## 1. 核心架构 (The Core)
* **硬件平台**: Mac M4 (16GB RAM)
* **开发语言**: Python 3.10+
* **大脑 (Inference)**: Apple MLX 框架 + `Phi-4-mini-instruct-4bit` (原生 Tool Use 支持)
* **双层思考 (Dual-Layer Thinking)**:
    *   **Layer 1 (Router)**: 极速意图判断 (Chat vs Command)
    *   **Layer 2 (Brain)**: 深度思考与执行
* **记忆 (Memory)**: 双层存储策略 (L1 JSONL + L2 ChromaDB)

## 2. 交互层 (Interaction)
* **听觉**: `FunASR` (Paraformer) - 高精度中文识别
* **视觉**: (Future) `Electron` + `PixiJS` (渲染 Live2D 模型)
* **嘴巴**: `Edge-TTS` (Azure Speech)

## 3. 扩展机制 (The "Limbs")
* **Self-Programming**: 通过 `create_file` 能力，Kage 可以编写 Python 脚本来扩展自己的技能树 (`abilities/` 目录)。
* **Native Tools**: 内置 `curl`, `grep`, `open_app` 等系统级工具。

## 4. 目录结构规范
```
/kage_project
├── /core           # 大脑核心 (Brain, Memory, Router, Tools)
├── /config         # 配置文件 (Persona)
├── /abilities      # Kage 自我编写的技能脚本
├── /data           # 记忆存储
└── main.py         # 启动入口 (双层循环逻辑)
```

## 5. 关键技术突破 (v2.0 Updates)
### 5.1 Dual-Layer Router (双层脑)
为了解决 LLM 容易混淆“聊天”与“指令”的问题，我们引入了轻量级路由层。
- **Chat Mode**: 纯对话，载入记忆，**严禁使用工具**。
- **Command Mode**: 纯执行，不载入杂乱记忆，**能够使用工具**。

### 5.2 Feedback Loop (反馈闭环)
Kage 拥有自我纠错能力：
1. **Action**: 执行 Shell 命令。
2. **Observation**: 读取命令输出结果。
3. **Report**: 结合用户问题，用自然语言汇报结果 (Prompt 强力约束，防止幻觉)。

### 5.3 Streaming & Latency
- 迁移至 `MLX` 框架，在 M4 芯片上实现 Token 秒出。
- Router 耗时 <20ms，用户无感切换模式。