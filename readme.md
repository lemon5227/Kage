# Project Kage (影) - Intelligent Desktop Assistant

**核心定义**：Kage 是一个运行在 Apple Silicon (Mac M4) 上的本地化智能助手。它采用微内核架构，强调隐私、记忆迁移能力，并拥有生动的 Live2D 形象。

## 📥 如何启动 (How to Run)

### 1. 启动大脑与神经 (Python Backend)
负责语音听写、大脑思考、工具调用和情绪分析。
```bash
# 必须先进入 Conda 环境
conda activate kage
# 在根目录运行
python main.py
# (保持此终端开启)
```

### 2. 启动躯体 (Frontend Body)
负责 Live2D 模型渲染、口型同步 (LipSync) 和语音合成播放。
```bash
cd kage-avatar
npm run tauri dev
```

---

## 1. 核心架构 (The Core)
* **硬件平台**: Mac M4 (16GB RAM)
* **开发语言**: Python 3.10+ (Backend) / TypeScript + Rust (Frontend)
* **大脑 (Inference)**: Apple MLX 框架 + `Phi-4-mini-instruct-4bit` (原生 Tool Use 支持)
* **双层思考 (Dual-Layer Thinking)**:
    *   **Layer 1 (Router)**: 极速意图判断 (Chat vs Command)
    *   **Layer 2 (Brain)**: 深度思考与执行
* **记忆 (Memory)**: 双层存储策略 (L1 JSONL + L2 ChromaDB)

## 2. 交互层 (Interaction) - v3.0 Update
* **听觉**: `FunASR` (Paraformer) - 高精度中文识别 + 情绪检测 (Emotion2Vec)
* **躯体**: `Tauri v2` + `PixiJS Live2D` (Haru 模型)
    *   **透明窗口**: 无边框，支持拖拽 (Drag Region)。
    *   **高清渲染**: 适配 Retina 屏幕 (DevicePixelRatio)。
    *   **LipSync**: 音画同步算法 (Sine Wave + WebSocket Signal)。
* **嘴巴**: `Edge-TTS` (Azure Speech)

## 3. 扩展机制 (The "Limbs")
* **Self-Programming**: 通过 `create_file` 能力，Kage 可以编写 Python 脚本来扩展自己的技能树 (`abilities/` 目录)。
* **Native Tools**: 内置 `curl`, `grep`, `open_app` 等系统级工具。

## 4. 目录结构规范
```
/kage_project
├── /core           # 大脑核心 (Brain, Memory, Router, Tools, Mouth, Ears)
├── /config         # 配置文件 (Persona)
├── /abilities      # Kage 自我编写的技能脚本
├── /data           # 记忆存储
├── /kage-avatar    # 前端工程 (Tauri + Vue/Vanilla TS)
└── main.py         # 启动入口 (双层循环逻辑)
```

## 5. 关键技术突破 (v3.0 Updates)
### 5.1 Dual-Layer Router (双层脑)
为了解决 LLM 容易混淆“聊天”与“指令”的问题，我们引入了轻量级路由层。
- **Chat Mode**: 纯对话，载入记忆，**严禁使用工具**。
- **Command Mode**: 纯执行，不载入杂乱记忆，**能够使用工具**。

### 5.2 LipSync & Visual Feedback (音画同步)
- **后端生成**: Edge-TTS 生成音频文件 -> 发送 WebSocket 信号 -> 播放音频。
- **前端响应**: 收到信号 -> 闪红框 (Debug) -> 驱动 Live2D 嘴部参数 (`ParamMouthOpenY`) -> 模型开口。
- **情绪映射**: 语音情绪 (Sad/Happy) -> WebSocket -> Live2D 表情切换 (`f01`, `f02`)。