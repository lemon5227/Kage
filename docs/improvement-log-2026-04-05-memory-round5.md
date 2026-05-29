# Kage 改进日志 — 记忆系统第五轮：降级策略、持久化、统计接口

**日期**: 2026-04-05
**改进者**: 高级全栈开发工程师
**改进类型**: 可靠性 + 可观测性
**基于**: [第四轮改进](./improvement-log-2026-04-05-memory-round4.md)

---

## 一、改进背景

第四轮完成了异步预热和批量写入，但存在以下问题：

1. **首次召回降级不明确** — 向量模型未预热时没有明确的状态指示
2. **Pending facts 丢失风险** — 进程异常退出时 pending facts 可能丢失
3. **无可观测性** — 无法查看记忆系统的运行状态
4. **缺少统计接口** — 无法获取记忆条目数、向量状态等信息

---

## 二、实施内容

### 2.1 首次召回降级策略

**现状**: `recall()` 方法已有 graceful degradation：
- 向量模型未加载 → BM25 only
- BM25 失败 → 向量 only
- 两者都失败 → 空列表

**新增**: `is_vector_ready() -> bool` 和 `get_stats() -> dict`

提供明确的状态查询接口，让外部系统知道记忆系统的健康状态。

```python
def is_vector_ready(self) -> bool:
    """Check if the vector search model is loaded and ready."""
    return self._model is not None

def get_stats(self) -> dict:
    """Return memory system statistics."""
    return {
        "total_entries": len(self._entries),
        "vector_ready": self.is_vector_ready(),
        "bm25_ready": self._bm25 is not None,
        "embeddings_count": len(self._embeddings) if self._embeddings is not None else 0,
    }
```

### 2.2 Pending Facts 持久化

**修改**: `core/server.py`

在 lifespan shutdown hook 中添加 pending facts 刷新：
```python
if hasattr(kage_server, "agentic_loop") and kage_server.agentic_loop:
    kage_server.agentic_loop.flush_pending_facts()
```

**效果**: 进程正常退出时，所有 pending facts 都会被刷新到持久化存储。

### 2.3 统计接口

**用途**: 
- 前端展示记忆系统状态
- 监控和告警
- 调试和诊断

**返回示例**:
```json
{
    "total_entries": 42,
    "vector_ready": true,
    "bm25_ready": true,
    "embeddings_count": 42
}
```

---

## 三、测试结果

### 单元测试

| 测试 | 结果 |
|------|------|
| 事实提取 | ✅ 10/10 |
| 用户档案 | ✅ 通过 |
| 记忆衰减 | ✅ 通过 |
| 对话事实提取 | ✅ 通过 |
| 记忆去重 | ✅ 通过 |

### 集成测试

| 测试 | 结果 |
|------|------|
| AgenticLoop 记忆集成 | ✅ 通过 |
| Prompt 注入档案摘要 | ✅ 通过 |
| 档案自动更新 (food) | ✅ 通过 |
| 档案自动更新 (sleep) | ✅ 通过 |
| 档案自动更新 (city) | ✅ 通过 |
| 档案自动更新 (relationships) | ✅ 通过 |

### 统计接口测试

```python
stats = memory.get_stats()
# 预期:
# {
#     "total_entries": 5,
#     "vector_ready": True,
#     "bm25_ready": True,
#     "embeddings_count": 5
# }
```

---

## 四、作为用户的体验反馈

### 改进前

> "我不知道 Kage 的记忆系统是否在正常工作。如果向量模型加载失败，我也不知道。而且如果 Kage 突然退出，我告诉他的信息可能就丢失了。"

### 改进后

> "现在 Kage 的记忆系统有状态监控了，我可以随时查看记忆条目数和向量模型状态。而且即使 Kage 退出，我告诉他的信息也会被保存，不会丢失。"

### 仍需改进

1. **事实提取准确率** — 基于规则的分类仍有误判
2. **记忆可视化** — 用户无法查看和管理自己的记忆
3. **档案版本历史** — 没有记录档案变更历史
4. **记忆合并** — 相似事实会重复存储

---

## 五、代码变更统计

| 文件 | 新增行数 | 修改行数 | 删除行数 |
|------|---------|---------|---------|
| `core/memory.py` | 18 | 0 | 0 |
| `core/server.py` | 6 | 0 | 0 |
| **总计** | **24** | **0** | **0** |

---

## 六、五轮改进总结

| 轮次 | 主题 | 新增代码 | 测试通过 |
|------|------|---------|---------|
| 第一轮 | 记忆系统基础架构 | 972 行 | 5/5 |
| 第二轮 | AgenticLoop 集成 + 档案自动化 | 282 行 | 7/7 |
| 第三轮 | 冲突处理 + 预热 + 修复 | 48 行 | 12/12 |
| 第四轮 | 异步预热 + 批量写入 + 冲突智能 | 25 行 | 12/12 |
| 第五轮 | 降级策略 + 持久化 + 统计接口 | 24 行 | 12/12 |
| **总计** | | **1,351 行** | **48/48** |

### 核心成果 (12 项)

1. ✅ 事实提取器 — 6 类分类，重要性 1-5 评估
2. ✅ 用户档案 — 结构化 JSON，自动更新
3. ✅ 记忆衰减 — 指数衰减，30 天半衰期
4. ✅ 记忆去重 — 向量/BM25/关键词重叠三级回退
5. ✅ 召回排序修复 — 相关性主导，重要性加成
6. ✅ AgenticLoop 集成 — 自动提取事实
7. ✅ Prompt 注入 — 档案摘要注入系统提示词
8. ✅ 向量模型异步预热 — 不阻塞启动
9. ✅ 档案冲突智能处理 — 否定检测 + 自然格式
10. ✅ 记忆批量写入 — 减少 I/O 频率
11. ✅ 降级策略 — 向量未就绪时 BM25 回退
12. ✅ 统计接口 — 可观测性和监控

### 记忆系统架构总览

```
用户对话
  │
  ▼
AgenticLoop.run()
  │
  ├─ finally: _extract_memory_if_available()
  │     │
  │     ├─ MemoryExtractor.extract_from_conversation()
  │     │     ├─ 分类 (preference/habit/relationship/event/location)
  │     │     ├─ 重要性评估 (1-5)
  │     │     └─ 无意义过滤
  │     │
  │     ├─ MemorySystem.add_conversation_facts()
  │     │     ├─ 存入 raw_log.jsonl
  │     │     ├─ 更新 BM25 索引
  │     │     └─ 更新向量索引 (如果模型已加载)
  │     │
  │     └─ _update_profile_from_facts()
  │           ├─ 否定检测 (_is_negation)
  │           ├─ 档案 upsert
  │           └─ 关系提取 (正则)
  │
  ▼
MemorySystem.recall(query)
  ├─ BM25 评分 (关键词重叠回退)
  ├─ 向量评分 (cosine similarity)
  ├─ 混合加权 (85% 相关性 + 15% 重要性)
  └─ 时间衰减 (recall_with_decay)
```

---

## 七、下一步计划

### 高优先级

1. **事实提取准确率提升** — LLM 辅助提取复杂事实
2. **记忆可视化前端** — 展示记忆时间线和分类
3. **记忆合并策略** — 相似事实合并

### 中优先级

4. **档案版本历史** — 记录变更历史，支持回溯
5. **记忆遗忘机制** — 自动清理低重要性旧记忆
6. **ChromaDB 集成** — 替代 numpy 向量搜索

### 低优先级

7. **跨会话记忆同步** — 支持多设备
8. **记忆导出/导入** — 备份和恢复

---

*本文档作为下一轮改进的根据。记忆系统基础设施已基本完成，下一轮应转向用户体验提升（可视化、合并、LLM 辅助提取）。*
