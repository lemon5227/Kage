"""
测试记忆系统第七轮新增功能：
1. 档案版本历史
2. 记忆遗忘机制
3. 记忆合并
4. API 端点验证
"""

import sys
import os
import tempfile
import shutil
import json
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_profile_version_history():
    """测试档案版本历史"""
    print("=" * 60)
    print("测试: 档案版本历史")
    print("=" * 60)

    from core.memory_profile import MemoryProfile

    tmpdir = tempfile.mkdtemp()
    profile_path = os.path.join(tmpdir, "profile.json")

    try:
        profile = MemoryProfile(profile_path=profile_path)

        # 初始版本
        assert profile.profile.version == 1

        # 更新几次
        profile.update_preference("food", "food_preference", "川菜")
        profile.update_preference("music", "music_preference", "摇滚")
        profile.add_habit("sleep", "23:00-07:00")

        # 检查版本历史
        versions = profile.get_version_history()
        print(f"  版本数: {len(versions)}")
        for v in versions:
            print(f"    v{v['version']}: {v['last_updated']}")

        assert len(versions) >= 3, f"Should have at least 3 versions, got {len(versions)}"

        # 测试恢复
        old_version = versions[0]["version"]
        success = profile.restore_version(old_version)
        assert success is True, "Should restore version successfully"
        print(f"  恢复版本 v{old_version}: ✅")

        # 验证恢复后的内容
        assert profile.profile.version > old_version, "Version should increment after restore"
        print(f"  当前版本: {profile.profile.version}")

        print("  ✅ 通过")

    finally:
        shutil.rmtree(tmpdir)


def test_memory_forget():
    """测试记忆遗忘机制"""
    print("\n" + "=" * 60)
    print("测试: 记忆遗忘机制")
    print("=" * 60)

    from core.memory import MemorySystem

    tmpdir = tempfile.mkdtemp()
    try:
        memory = MemorySystem(workspace_dir=tmpdir)

        now = datetime.datetime.now()

        # 添加不同年龄和重要性的记忆
        test_entries = [
            # (age_days, importance, content)
            (1, 1, "今天的闲聊"),           # 新 + 低重要性 → 保留
            (5, 1, "昨天的废话"),           # 新 + 低重要性 → 保留
            (10, 2, "我喜欢吃川菜"),        # 中 + 中重要性 → 保留
            (30, 1, "无意义的对话"),        # 中 + 低重要性 → 遗忘
            (60, 2, "普通记忆"),            # 老 + 中重要性 → 保留
            (100, 1, "很旧的废话"),         # 很老 + 低重要性 → 遗忘
            (120, 3, "重要但旧的记忆"),     # 很老 + 高重要性 → 保留（重要性 >= 4 才永不遗忘）
            (200, 4, "非常重要的记忆"),     # 极老 + 极高重要性 → 永不遗忘
        ]

        for age_days, importance, content in test_entries:
            entry = {
                "id": f"test-{age_days}",
                "timestamp": (now - datetime.timedelta(days=age_days)).isoformat(),
                "content": content,
                "emotion_data": {"emotion": "neutral", "emotion_conf": 1.0},
                "type": "chat",
                "importance": importance,
            }
            memory._entries.append(entry)
            memory._corpus_tokens.append(memory._tokenize(content) if hasattr(memory, '_tokenize') else [content])

        memory._rebuild_bm25()

        print(f"  遗忘前: {len(memory._entries)} 条记忆")
        for e in memory._entries:
            age = (now - datetime.datetime.fromisoformat(e["timestamp"])).days
            print(f"    {e['content'][:15]}: age={age}d, imp={e['importance']}")

        # 执行遗忘
        forgotten = memory.forget_old_memories(
            max_age_days=90,
            min_importance=2,
            keep_recent_days=7,
        )

        print(f"\n  遗忘后: {len(memory._entries)} 条记忆 (遗忘 {forgotten} 条)")
        for e in memory._entries:
            age = (now - datetime.datetime.fromisoformat(e["timestamp"])).days
            print(f"    {e['content'][:15]}: age={age}d, imp={e['importance']}")

        # 验证遗忘逻辑
        remaining_contents = {e["content"] for e in memory._entries}
        assert "今天的闲聊" in remaining_contents, "Recent memory should be kept"
        assert "昨天的废话" in remaining_contents, "Recent memory should be kept"
        assert "无意义的对话" not in remaining_contents, "Old + low importance should be forgotten"
        assert "很旧的废话" not in remaining_contents, "Very old + low importance should be forgotten"
        assert "非常重要的记忆" in remaining_contents, "High importance should never be forgotten"

        print("  ✅ 通过")

    finally:
        shutil.rmtree(tmpdir)


def test_memory_merge():
    """测试记忆合并"""
    print("\n" + "=" * 60)
    print("测试: 记忆合并")
    print("=" * 60)

    from core.memory import MemorySystem

    tmpdir = tempfile.mkdtemp()
    try:
        memory = MemorySystem(workspace_dir=tmpdir)

        # 添加相似记忆
        similar_facts = [
            ("我喜欢吃川菜", 4),
            ("我爱吃川菜", 3),
            ("川菜是我的最爱", 5),
            ("我讨厌吃香菜", 4),
            ("香菜太难吃了", 3),
        ]

        for content, importance in similar_facts:
            memory.add_memory(content, importance=importance)

        print(f"  合并前: {len(memory._entries)} 条记忆")
        for e in memory._entries:
            print(f"    {e['content'][:20]} (imp={e['importance']})")

        # 执行合并
        merged = memory.merge_similar_facts(similarity_threshold=0.6)

        print(f"\n  合并后: {len(memory._entries)} 条记忆 (合并 {merged} 组)")
        for e in memory._entries:
            merged_from = e.get("merged_from", 1)
            print(f"    {e['content'][:20]} (imp={e['importance']}, merged_from={merged_from})")

        # 验证合并结果
        assert len(memory._entries) < len(similar_facts), "Should have fewer entries after merge"
        assert merged >= 1, "Should have merged at least 1 group"

        print("  ✅ 通过")

    finally:
        shutil.rmtree(tmpdir)


def test_memory_stats():
    """测试记忆统计接口"""
    print("\n" + "=" * 60)
    print("测试: 记忆统计接口")
    print("=" * 60)

    from core.memory import MemorySystem

    tmpdir = tempfile.mkdtemp()
    try:
        memory = MemorySystem(workspace_dir=tmpdir)

        # 添加一些记忆
        for i in range(5):
            memory.add_memory(f"测试记忆 {i}", importance=i+1)

        stats = memory.get_stats()
        print(f"  统计: {stats}")

        assert stats["total_entries"] == 5
        assert stats["bm25_ready"] is True

        print("  ✅ 通过")

    finally:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    results = {}
    results["档案版本历史"] = test_profile_version_history()
    results["记忆遗忘机制"] = test_memory_forget()
    results["记忆合并"] = test_memory_merge()
    results["记忆统计接口"] = test_memory_stats()

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    for name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {name}: {status}")

    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\n总计: {passed}/{total} 通过")
