# Kage Roadmap (发展路线图)

## 🟢 Phase 1: The Brain (已完成)
- [x] **Core LLM**: 迁移至 MLX + Phi-4。
- [x] **Router**: 实现 Dual-Layer 意图分流 (Chat/Command)。
- [x] **Tools**: 实现基础 Shell 工具与 Self-Programming (create_file)。
- [x] **Memory**: 基础 ChromaDB 向量记忆。

## 🟡 Phase 2: The Body (进行中)
- [ ] **Live2D GUI**: 使用 Electron/Tauri接管前端，展示 Kage 的形象。
- [ ] **Emotion Sync**: 将 TTS 的情绪与 Live2D 动作绑定 (开心时大笑)。
- [ ] **Vision**: 集成 `moondream` 或 `llava`，让 Kage 能“看”屏幕截图。

## 🔵 Phase 3: The Soul (长期规划)
- [ ] **Deep Memory**: 优化记忆衰减算法，不再只是简单的 RAG，而是有“遗忘”和“提炼”。
- [ ] **Autonomous Agent**: 允许 Kage 在后台默默工作 (如：每晚自动整理桌面、通过 rss 总结新闻)。
- [ ] **Multi-Modal Input**: 支持摄像头输入，甚至能“看”到 Master 的表情。