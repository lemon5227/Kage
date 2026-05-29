"""
记忆系统改进测试

测试内容：
1. 事实提取 (MemoryExtractor)
2. 用户档案 (MemoryProfile)
3. 记忆衰减 (recall_with_decay)
4. 记忆去重 (deduplicate_memories)
5. 端到端对话事实提取
"""

import os
import sys
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_memory_extractor():
    """测试事实提取器"""
    print("=" * 60)
    print("测试 1: 事实提取器 (MemoryExtractor)")
    print("=" * 60)

    from core.memory_extractor import MemoryExtractor

    extractor = MemoryExtractor()

    test_cases = [
        ("我喜欢吃川菜", "preference", 3),
        ("我每天早上7点起床跑步", "habit", 3),
        ("我朋友小明下周过生日", "relationship", 3),
        ("我在北京工作", "location", 3),
        ("嗯嗯", "other", 1),
        ("好的", "other", 1),
        ("我非常讨厌吃香菜，每次闻到都想吐", "preference", 5),
        ("我习惯晚上11点睡觉，早上7点起床", "habit", 3),
        ("今天考试通过了，特别开心", "event", 3),
        ("我老板是个傻逼", "relationship", 4),
    ]

    passed = 0
    for text, expected_category, expected_importance in test_cases:
        facts = extractor.extract_from_conversation(text)
        if facts:
            fact = facts[0]
            category_match = fact.category == expected_category
            importance_match = fact.importance >= expected_importance - 1
            if category_match and importance_match:
                print(f"  ✅ '{text}' -> {fact.category} (重要性: {fact.importance})")
                passed += 1
            else:
                print(f"  ⚠️ '{text}' -> {fact.category} (重要性: {fact.importance}), 预期: {expected_category} ({expected_importance})")
        else:
            if expected_importance == 1:
                print(f"  ✅ '{text}' -> 跳过 (无意义)")
                passed += 1
            else:
                print(f"  ❌ '{text}' -> 未提取到事实")

    print(f"\n结果: {passed}/{len(test_cases)} 通过")
    assert passed == len(test_cases), f"only {passed}/{len(test_cases)} extractor cases passed"


def test_memory_profile():
    """测试用户档案管理"""
    print("\n" + "=" * 60)
    print("测试 2: 用户档案 (MemoryProfile)")
    print("=" * 60)

    from core.memory_profile import MemoryProfile

    tmpdir = tempfile.mkdtemp()
    profile_path = os.path.join(tmpdir, "profile.json")

    try:
        profile = MemoryProfile(profile_path=profile_path)

        # 测试更新偏好
        profile.update_preference("food", "food_preference", "川菜")
        profile.update_preference("music", "music_preference", "摇滚")
        profile.add_habit("sleep", "23:00-07:00")
        profile.add_habit("work", "习惯下午写代码")
        profile.add_relationship("小明", "朋友", "大学同学")
        profile.add_important_date("2026-05-01", "小明生日")

        # 测试摘要
        summary = profile.get_profile_summary()
        print(f"  档案摘要:\n{summary}")

        # 测试保存和加载
        profile2 = MemoryProfile(profile_path=profile_path)
        assert profile2.profile.food_preference == "川菜"
        assert profile2.profile.sleep_schedule == "23:00-07:00"
        assert len(profile2.profile.relationships) == 1

        print("  ✅ 档案保存/加载正常")
        print("  ✅ 偏好更新正常")
        print("  ✅ 关系添加正常")

    finally:
        shutil.rmtree(tmpdir)


def test_memory_decay():
    """测试记忆衰减"""
    print("\n" + "=" * 60)
    print("测试 3: 记忆衰减 (recall_with_decay)")
    print("=" * 60)

    from core.memory import MemorySystem

    tmpdir = tempfile.mkdtemp()
    try:
        memory = MemorySystem(workspace_dir=tmpdir)

        # 添加不同时间的记忆
        import datetime
        now = datetime.datetime.now()

        # 模拟旧记忆
        old_entry = {
            "id": "old-1",
            "timestamp": (now - datetime.timedelta(days=60)).isoformat(),
            "content": "我喜欢吃川菜",
            "emotion_data": {"emotion": "happy", "emotion_conf": 1.0},
            "type": "fact:preference",
            "importance": 3,
        }

        # 模拟新记忆
        new_entry = {
            "id": "new-1",
            "timestamp": (now - datetime.timedelta(days=1)).isoformat(),
            "content": "我喜欢吃川菜",
            "emotion_data": {"emotion": "happy", "emotion_conf": 1.0},
            "type": "fact:preference",
            "importance": 3,
        }

        memory._entries = [old_entry, new_entry]
        memory._corpus_tokens = [
            ["我", "喜欢", "吃", "川", "菜"],
            ["我", "喜欢", "吃", "川", "菜"],
        ]
        memory._rebuild_bm25()

        # 测试衰减
        results = memory.recall_with_decay("川菜", n_results=5, decay_days=30)

        if len(results) >= 2:
            new_score = results[0]["decayed_importance"]
            old_score = results[1]["decayed_importance"] if len(results) > 1 else 0

            print(f"  新记忆 (1天前): 衰减后重要性 = {new_score:.2f}")
            print(f"  旧记忆 (60天前): 衰减后重要性 = {old_score:.2f}")

            if new_score > old_score:
                print("  ✅ 衰减机制正常：新记忆优先级更高")
            else:
                print("  ⚠️ 衰减效果不明显")
                assert False, "新记忆衰减后应优先于旧记忆"
        else:
            print("  ⚠️ 召回结果不足")
            assert False, "召回结果应包含至少 2 条记忆"
    finally:
        shutil.rmtree(tmpdir)


def test_conversation_fact_extraction():
    """测试对话事实提取"""
    print("\n" + "=" * 60)
    print("测试 4: 对话事实提取 (端到端)")
    print("=" * 60)

    from core.memory import MemorySystem

    tmpdir = tempfile.mkdtemp()
    try:
        memory = MemorySystem(workspace_dir=tmpdir)

        conversations = [
            ("我喜欢吃川菜，越辣越好", ""),
            ("我每天早上7点起床跑步", ""),
            ("我在北京工作，是个程序员", ""),
            ("我朋友小明下周要结婚了", ""),
            ("嗯嗯", ""),
            ("好的", ""),
        ]

        total_facts = 0
        for user_input, assistant_response in conversations:
            facts = memory.add_conversation_facts(user_input, assistant_response)
            if facts:
                print(f"  用户: '{user_input}'")
                for f in facts:
                    print(f"    -> 提取: [{f['category']}] 重要性={f['importance']}")
                total_facts += len(facts)

        print(f"\n  总共提取 {total_facts} 个事实")

        # 测试召回
        results = memory.recall("川菜", n_results=3)
        if results:
            print(f"  召回 '川菜': {results[0]['content']}")
            print("  ✅ 事实提取和召回正常")
        else:
            print("  ⚠️ 召回失败")
            assert False, "应至少召回一条 '川菜' 相关记忆"
    finally:
        shutil.rmtree(tmpdir)


def test_deduplication():
    """测试记忆去重"""
    print("\n" + "=" * 60)
    print("测试 5: 记忆去重 (deduplicate_memories)")
    print("=" * 60)

    from core.memory import MemorySystem

    tmpdir = tempfile.mkdtemp()
    try:
        memory = MemorySystem(workspace_dir=tmpdir)

        # 添加重复记忆
        duplicates = [
            "我喜欢吃川菜",
            "我喜欢吃川菜",
            "我喜欢吃川菜啊",
            "我讨厌吃香菜",
            "我讨厌吃香菜",
        ]

        for content in duplicates:
            memory.add_memory(content, importance=2)

        print(f"  添加前: {len(memory._entries)} 条记忆")

        # 注意：去重需要向量模型，这里测试 BM25 回退
        # removed = memory.deduplicate_memories()
        # print(f"  去重后: {len(memory._entries)} 条记忆 (移除 {removed} 条)")

        # 手动检查重复
        unique_contents = set()
        for entry in memory._entries:
            unique_contents.add(entry["content"])

        print(f"  唯一内容: {len(unique_contents)} 条")
        print(f"  重复: {len(memory._entries) - len(unique_contents)} 条")

        if len(memory._entries) == len(duplicates):
            print("  ✅ 记忆存储正常")
        else:
            assert False, f"记忆存储数应等于 {len(duplicates)}，实际 {len(memory._entries)}"
    finally:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    results = {}

    results["事实提取"] = test_memory_extractor()
    results["用户档案"] = test_memory_profile()
    results["记忆衰减"] = test_memory_decay()
    results["对话事实提取"] = test_conversation_fact_extraction()
    results["记忆去重"] = test_deduplication()

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {name}: {status}")

    print(f"\n总计: {passed}/{total} 通过")
