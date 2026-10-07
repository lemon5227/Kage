# Kage 插画与视觉风格

当前 README 封面：[companion-cover.png](companion-cover.png)。它是根据当前演示模型 Haru 生成的概念插画，可以暂时用于项目展示，也作为后续生成的**画风参考**。它不是实际应用截图，也不定义 Kage 的永久角色。

## 保留画风，允许更换人物

Kage 的视觉定位是有陪伴感的二次元个人助手，同时具有电脑操作、记忆与自进化的研究方向。后续封面可以使用全新人物外观；沿用的是插画语言与氛围，不是 Haru 的脸、发型、服装或角色设定。当前封面角色也不约束运行时 Live2D 模型。

- **画法：**精细日系动画插画，柔和线条与细腻上色；人物自然、有亲近感，环境具有层次和生活细节。
- **光线：**明亮窗边、温暖的斜向日光、柔和轮廓光与浅景深。避免沉重暗色科技海报。
- **配色：**米白、暖金、浅蓝与灰蓝；蓝色用于少量科技感点缀。技术图沿用浅底、蓝色连线和深灰文字。
- **场景：**真实感的工作桌、笔记本电脑、书、纸质笔记、杯子、绿植与窗外城市。助手像在一起工作，而不是悬浮在抽象控制台里。
- **陪伴动作：**自然目光、轻松姿态、一起看笔记或递交纸张。人物身份与具体动作可以改变。
- **能力隐喻：**漂浮的记忆纸片、轻微光轨或少量抽象线索；不堆砌 UI 面板、代码、指标与机器人装甲。
- **构图：**宽幅约 2.5:1，左侧留出清晰的品牌文字区，人物与场景主要位于右侧；缩小到 GitHub README 宽度仍易读。
- **文字：**主标题 `KAGE`；副标题 `Your companion. Your evolving agent.`；可选小字 `LIVE2D · VOICE · MEMORY · EVOLUTION`。避免额外文字和伪造功能成绩。

## 后续生成方法

1. 将当前封面作为图片参考提供给生成工具，并明确标注“仅参考画风、光线、配色和构图”。
2. 单独描述新人物的外观、发型、服装与气质；明确要求使用新人物，不沿袭 Haru 的可识别外观。若未来选定其他演示角色，再提供其独立外观参考。
3. 先生成新文件，例如 `companion-cover-v2.png`，预览后再替换 README 引用；保留风格说明与更换记录。
4. 检查人物、手部、文字、缩小后的可读性及与技术图的配色一致性。新封面继续标注为概念插画，不当作运行时截图。

### 可复用提示词

```text
Create a wide README cover for Kage, an anime-style personal assistant
with memory, computer-use capabilities, and an evolving agent research agenda.
Use the supplied cover ONLY as a reference for illustration style, lighting,
palette, atmosphere, and layout. Design a NEW character with this appearance:
[describe the new character here]. Do not copy Haru's recognizable appearance.

Refined Japanese anime illustration, natural approachable expression,
a cozy sunlit workspace, warm rim light, cream and pale blue palette,
subtle depth of field, laptop, books, notes, mug, and greenery.
Small floating memory notes can suggest learning; keep the scene uncluttered.
Wide approximately 2.5:1 composition, clear typography on the left,
new character on the right, readable at GitHub README width.

Exact text: "KAGE" and "Your companion. Your evolving agent."
Optional small text: "LIVE2D · VOICE · MEMORY · EVOLUTION".
No extra copy, fake metrics, dashboard panels, watermarks, or fixed mascot claims.
```

## 变更记录

- **2026-10-07：**采用 Haru 风格参考图作为临时 README 封面。用户明确允许当前人物暂时展示，并要求将画风保存到仓库，未来沿用画风生成新人物。配套架构图与学习层次图使用浅蓝白配色。
