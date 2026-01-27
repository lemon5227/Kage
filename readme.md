# Project Kage (影) - Intelligent Desktop Assistant

**核心定义**：Kage 是一个运行在 Apple Silicon (Mac M4) 上的本地化智能助手。它采用微内核架构，强调极速响应、隐私安全，并拥有生动的 Live2D 形象。

🚀 **v4.0 性能飞跃 (2026.01)**: 
- 意图识别从 1400ms 降至 **<1ms**
- 工具调用从 17s 降至 **1.4s**
- 常用命令（时间/音量/截图）响应 **<500ms**

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
* **大脑 (Inference)**: Apple MLX 框架 + `Phi-4-mini-instruct-4bit`
* **三层思考架构 (Three-Layer Thinking)**:
    1.  **Fast Path (<50ms)**: 规则匹配常用命令 (打开App/静音/截图/时间/亮度)，绕过 LLM 直接执行。
    2.  **Skill Trigger (<100ms)**: 关键词触发 Python 技能脚本 (计算/笑话/剪贴板/文件操作)。
    3.  **Brain Inference (1.4s)**: LLM 深度思考，处理复杂意图和模糊指令。

## 2. 交互层 (Interaction)
* **听觉**: `OpenWakeWord` (唤醒词 "Hey Kage") + `FunASR` (高精度中文识别 + 情绪检测)。
* **躯体**: `Tauri v2` + `PixiJS Live2D` (Haru 模型)
    *   **透明窗口**: 无边框，支持拖拽。
    *   **LipSync**: 音画同步算法 (Sine Wave + WebSocket Signal)。
* **嘴巴**: `Edge-TTS` (Azure Speech)
* **系统控制**: 基于 `Quartz` 的底层控制 (音量/媒体键/截图)，支持原生系统 HUD。

## 3. 扩展机制
* **Skills**: 在 `skills/` 目录下添加 Python 脚本即可扩展能力。自动注册，无需配置。
* **Persona**: 快速命令注入了 Kage 的傲娇人设回复，不再是冷冰冰的机器。

## 4. 目录结构
```
/kage_project
├── /core           # 大脑核心 (Brain, Memory, Router, Tools, Mouth, Ears)
├── /config         # 配置文件 (Persona)
├── /skills         # 技能脚本 (自动加载)
├── /data           # 记忆存储
├── /kage-avatar    # 前端工程 (Tauri + Vue/Vanilla TS)
└── main.py         # 启动入口
```

## 5. 关键技术突破 (v4.0 Updates)
### 5.1 极速意图路由 (Zero-Latency Router)
移除了基于 LLM 的意图分类，改用高效的规则匹配引擎。将 Router 延迟从 1.4s 降至 0ms，同时保持了闲聊和命令的准确区分。

### 5.2 智能 Action Prompt
大幅精简了传给 LLM 的工具描述，将 Prompt Token 数虽然减少但保留了核心语义。配合 Fast Path，使得复杂工具调用的端到端延迟降低了 12 倍 (17s -> 1.4s)。

### 5.3 统一系统控制 (Unified Control)
重构了所有系统控制命令（音量、亮度、媒体），统一使用 macOS `Quartz` 事件服务。这不仅大大提高了响应速度，还使得 Kage 的操作能触发系统的原生屏幕指示器 (HUD)。