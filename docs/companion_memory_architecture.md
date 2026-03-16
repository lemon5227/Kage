# Kage 陪伴型记忆架构

## 结论先说

Kage 现在**不是没有记忆**。

它已经有 3 层基础能力：

1. `短期会话记忆`
2. `长期检索记忆`
3. `人格/用户档案持久化`

但它**还不是一个成熟的陪伴型记忆系统**。  
现在更像“技术上已有记忆模块”，还不是“真正服务长期关系和人格成长的 companion memory”。

---

## 当前已经存在的记忆能力

### 1. 短期会话记忆

文件：
- `core/session_state.py`
- `core/session_manager.py`

当前能力：
- 保存最近对话历史
- 支撑多轮 follow-up / confirm / pending action
- 会话可持久化到 `~/.kage/sessions/current.jsonl`

这层本质上是：
- working memory
- interaction memory

适合做：
- 当前轮上下文
- 刚刚说过的话
- 正在等待确认的动作

不适合做：
- 长期偏好
- 人格成长
- 稳定关系记忆

---

### 2. 长期检索记忆

文件：
- `core/memory.py`

当前能力：
- 原始记忆写入 `~/.kage/data/raw_log.jsonl`
- 每日记忆日志 `~/.kage/memory/YYYY-MM-DD.md`
- 长期精选记忆 `~/.kage/memory/MEMORY.md`
- BM25 检索
- embedding + 向量检索
- hybrid recall

这说明 Kage 现在已经具备：
- episodic memory 的原型
- semantic recall 的原型

现状优点：
- 已经是本地持久化，不是纯上下文内临时记忆
- 已经支持 recall，不只是记录
- graceful degradation 做得不错，向量不可用时还能退回 BM25

现状问题：
- `add_memory(...)` 目前偏“原始日志追加”，不是“高质量记忆写入策略”
- 没有清晰区分：
  - 偏好
  - 事实
  - 事件
  - 关系变化
  - 情绪线索
- recall 更偏“搜索”，还不是“陪伴场景下的主动想起”

---

### 3. 人格与用户档案持久化

文件：
- `core/identity_store.py`
- `config/persona.json`

当前能力：
- `SOUL.md` 保存角色人格与行为准则
- `USER.md` 保存用户信息与偏好
- `TOOLS.md` 保存工具备注
- 支持更新用户字段与追加人格调整记录

这层非常重要，因为它已经不是普通聊天系统那种“每次都重来”的人格。

它实际上已经是：
- persona memory
- user profile memory

但目前更像静态档案，不像动态成长档案。

---

## 为什么现在还不够“陪伴型”

陪伴型记忆最关键的不是“能检索”，而是：

1. 记住什么
2. 为什么记住
3. 什么时候想起
4. 想起之后怎么说
5. 哪些东西会慢慢淡化，哪些必须长期保留

Kage 当前缺的主要是这几层：

### 1. 缺少明确的记忆写入策略

现在聊天结束后有这段逻辑：
- chat 场景会写入 memory

但还没有精细区分：
- 临时情绪
- 长期偏好
- 重要关系事件
- 重复出现的习惯
- 用户明确要求记住的事情

如果没有写入策略，就会出现两个问题：
- 噪声过多
- 真正重要的东西没有被提升权重

### 2. 缺少“用户画像层”

`USER.md` 现在更像手工模板，不是自动成长的 profile system。

陪伴型助手至少应该逐步沉淀：
- 作息偏好
- 常用应用
- 沟通风格
- 不喜欢的话题
- 常见情绪触发点
- 长期目标
- 对陪伴关系的期待

### 3. 缺少“关系事件层”

陪伴型系统不能只有“搜索记忆”，还要有 relationship memory。

例如：
- 今天心情很差
- 最近很焦虑
- 刚完成一个重要项目
- 某天和你第一次讨论某个长期目标
- 你说过希望 Kage 更主动一点

这些不只是普通文本片段，而是“关系时间线”。

### 4. 缺少记忆生命周期

不同记忆应该有不同命运：

- 可丢弃：
  - 一次性闲聊
  - 短暂任务上下文

- 应提升：
  - 多次重复出现的偏好
  - 用户明确确认的事实
  - 高情绪强度事件

- 应长期保留：
  - 核心偏好
  - 人格设定反馈
  - 长期关系里程碑

现在这层还没有被明确建模。

### 5. 缺少 companion recall 策略

现在 recall 更偏 prompt 构建时的“相关记忆检索”。

陪伴型 recall 还应该有：
- 主动 recall
- 情绪触发 recall
- 关系触发 recall
- 周期性总结
- 用户状态变化提醒

也就是说，不只是“问到再搜”，而是“在合适的时候自然想起”。

---

## 推荐的陪伴型记忆分层

建议把 Kage 的记忆正式拆成 5 层。

### A. Working Memory

用途：
- 当前对话轮
- pending action
- 当前情绪
- 当前任务上下文

当前基础：
- 已有

主要文件：
- `core/session_state.py`
- `core/dialog_state_machine.py`

---

### B. User Profile Memory

用途：
- 用户稳定偏好
- 长期习惯
- 常用工具/应用
- 沟通偏好

建议存储：
- 结构化 KV / SQLite / Markdown frontmatter

当前基础：
- `USER.md` 已有，但需要升级成可自动维护的 profile layer

---

### C. Persona Memory

用途：
- Kage 自己的人格边界
- 风格调整记录
- 用户对人格的反馈

当前基础：
- `SOUL.md`
- `append_soul_adjustment(...)`

这层其实已经很接近可用，只需要让反馈进入更正式流程。

---

### D. Episodic Memory

用途：
- 发生过的事件
- 情绪强烈的时刻
- 陪伴时间线
- 有时间戳的关系片段

当前基础：
- `raw_log.jsonl`
- daily logs

需要升级：
- 事件提炼
- 重要性评分
- 去噪
- relationship tagging

---

### E. Semantic Memory

用途：
- 对用户长期情况的抽象理解
- 从多次事件中总结规律

例如：
- 用户最近更偏向晚睡
- 用户更喜欢简短安静的回应
- 用户对“被催促”比较敏感

当前基础：
- 基本没有显式层

这层是陪伴型人格非常关键的一步。

---

## 最值得优先做的 5 个改进

### 1. 引入记忆写入策略

建议新增：
- `memory_write_policy.py`

职责：
- 判断这条对话要不要写入
- 写成哪种记忆
- importance 给多少
- 是否要升级为 profile / relation 事件

---

### 2. 区分 memory types

至少先分成：
- `chat_log`
- `preference`
- `fact`
- `relationship_event`
- `emotional_event`
- `task_context`

当前 `type="chat"` 太粗了。

---

### 3. 给 USER.md 增加自动沉淀通路

不要只手工维护 `USER.md`。

应该让系统能逐步提炼：
- 常用应用
- 时间偏好
- 说话风格偏好
- 不喜欢的交互方式

---

### 4. 引入 relationship timeline

建议新增：
- `RELATIONSHIP.md` 或结构化事件存储

专门记录：
- 对用户重要的时刻
- 对 Kage 人格调整的重要反馈
- 陪伴关系中的阶段变化

---

### 5. 引入 companion recall policy

不是所有场景都 recall。

建议：
- command：默认关
- 短实时控制：默认关
- 陪伴闲聊：开
- 情绪支持：强开
- 长期计划讨论：开

这点和你现在“实时性重要”的目标并不冲突，反而更一致。

---

## 对当前项目的判断

所以答案是：

### 你现在的项目有没有记忆功能？

有，而且并不弱。

你已经有：
- 短期记忆
- 检索记忆
- 人格持久化
- 用户档案模板

### 但它是不是已经达到“陪伴型人格记忆”？

还没有。

目前更像：
- assistant memory foundation

还不是：
- companion memory architecture

---

## 下一阶段建议

如果 Kage 的目标是“个人陪伴”，那记忆优先级应该明显上升。

建议接下来的顺序是：

1. 先继续完成前后台任务架构
2. 然后尽快进入 `Memory System Upgrade`
3. 重点不是“多存一点”，而是：
   - 分类型
   - 有写入策略
   - 有关系时间线
   - 有 companion recall policy

---

## 一句话结论

Kage 现在已经有记忆，但还缺“陪伴型记忆的组织方式”。  
你的方向是对的：如果目标是个人陪伴，记忆与人格不是附属功能，而应该成为下一阶段核心主线之一。
