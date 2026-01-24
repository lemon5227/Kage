# Kage Project Roadmap

## Phase 1: The Brain (Completed ✅)
- [x] Integrate `Apple MLX` for local inference.
- [x] Implement Basic Memory (JSONL).
- [x] Design Core Tools (Shell, App Control).

## Phase 2: The Logic (Completed ✅)
- [x] Implement Dual-Layer Router (Chat vs Command).
- [x] Add Feedback Loop (Action -> Observation -> Report).
- [x] System Control integration (Mac Volume, Brightness).

## Phase 3: The Senses (Completed ✅)
- [x] **Hearing**: Integrate `FunASR` (Paraformer) for high-accuracy STT.
- [x] **Emotion**: Integrate `Emotion2Vec` for voice emotion detection.
- [x] **Speech**: Integrate `Edge-TTS` for natural voice synthesis.

## Phase 4: The Body (Completed ✅)
- [x] **Framework**: Setup `Tauri v2` + `Vite` + `TypeScript`.
- [x] **Rendering**: Implement `PixiJS v6` + `pixi-live2d-display` (Cubism 4).
- [x] **Window**: Implement Transparent Window & Dragging (Mac Trackpad Optimized).
- [x] **Link**: Establish WebSocket connection (Python <-> Tauri).
- [x] **Expression**: Backend sends Emotion -> Live2D Face Change (`f01`..`f05`).
- [x] **LipSync**: Backend Audio/Motion Signal Sync -> Frontend Mouth Animation.

## Phase 5: The Soul (Next Steps 🚧)
- [ ] **Long-term Memory**: Vector Database (ChromaDB) for semantic recall.
- [ ] **Personality Training**: Fine-tune LoRA for a specific character persona (Tsundere/Maid).
- [ ] **Vision Capability**: Integrate `Llava` or Screenshot Analysis (Kage can "see" your screen).
- [ ] **Music/Media**: A dedicated Music Player UI inside the Tauri window.

## Phase 6: Deployment (Future 📦)
- [ ] **Python Freeze**: Use `PyInstaller` to bundle `kage-server` binary.
- [ ] **Sidecar Setup**: Configure Tauri to manage the Python process.
- [ ] **Installer**: Build signed `.dmg` for macOS distribution.
**: 支持摄像头输入，甚至能“看”到 Master 的表情。