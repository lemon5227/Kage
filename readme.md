<div align="center">

# Kage (影)
### Your Intelligent Desktop Companion
#### 傲娇又元气的二次元终端精灵

[🌐 官方网站](https://kage.lemony.eu.org) | [📖 文档](https://github.com/lemon5227/Kage) | [🐛 报告问题](https://github.com/lemon5227/Kage/issues)

---

**Kage** 不仅仅是一个桌面助手，她是你的数字伙伴。
运行在 Apple Silicon (Mac) 本地，拥有极速的响应能力、生动的 Live2D 形象和独特的个性。
她能听懂你的语音，管理你的系统，陪你聊天，甚至编写代码——而且这一切都完全在本地运行，保护你的隐私。

</div>

## ✨ 核心特性 (Features)

### 🚀 极速响应 (Zero Latency)
告别等待。Kage 采用独创的三层思考架构：
- **<1ms** 意图识别：瞬间听懂你的指令。
- **<500ms** 快速操作：调整音量、截图、看时间，比你动手还快。
- **1.4s** 深度思考：处理复杂任务也无需久等。

### 💖 鲜活个性 (Vivid Persona)
Kage 拒绝冷冰冰的机器回复。
- **傲娇人设**：她会撒娇，会吐槽，也会在你工作时默默陪伴。
- **沉浸体验**：所有快速命令都注入了灵魂回复 ("咔嚓！截图好啦💖")。
- **Live2D 形象**：基于 Haru 模型，表情丰富，动作灵动，支持口型同步 (LipSync)。

### 🔒 隐私优先 (Privacy First)
- **完全本地化**：基于 Apple MLX 框架，搭载 Phi-4 模型，无需联网也能思考。
- **数据安全**：你的对话、记忆、屏幕截图永远只留在你的 Mac 上。

### �️ 强大能力 (Powerful Skills)
- **系统掌控**：原生级控制音量、亮度、媒体播放、Wi-Fi/蓝牙。
- **效率工具**：剪贴板管理、文件操作、天气/汇率查询。
- **无限扩展**：内置 Python 解释器，Kage 可以通过编写 `skills` 脚本自我进化。

---

## 📥 快速开始 (Get Started)

### 环境要求
- **硬件**: Mac with Apple Silicon (M1/M2/M3/M4)
- **系统**: macOS 14.0+
- **环境**: Python 3.10+, Node.js 18+

### 安装运行

**1. 启动大脑 (Backend)**
```bash
conda activate kage
python main.py
```

**2. 唤醒躯体 (Frontend)**
```bash
cd kage-avatar
npm run tauri dev
```

现在，试着对她说："Hey Kage, 帮我截个图！" ✨

---

## 🏗️ 技术架构

Kage 是 AI Agent 技术的集大成者：
*   **Brain**: Apple MLX + Phi-4-mini (4-bit Quantized)
*   **Ears**: FunASR (Paraformer + Emotion2Vec) + OpenWakeWord
*   **Body**: Tauri v2 + PixiJS Live2D
*   **Control**: Quartz Event Services + Native macOS APIs

## 📄 License

MIT License © 2026 Kage Project