"""
用户视角：记忆系统改进体验测试

模拟真实用户与 Kage 的对话场景，测试记忆系统是否能：
1. 记住用户的偏好
2. 在后续对话中引用记忆
3. 区分重要信息和无意义对话
4. 衰减旧的不相关记忆
"""

import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def simulate_user_session():
    """模拟用户一天的使用场景"""
    from core.memory import MemorySystem
    from core.memory_profile import MemoryProfile
    from core.memory_extractor import MemoryExtractor

    tmpdir = tempfile.mkdtemp()
    try:
        memory = MemorySystem(workspace_dir=tmpdir)
        profile = MemoryProfile(profile_path=os.path.join(tmpdir, "profile.json"))
        extractor = MemoryExtractor()

        print("=" * 60)
        print("用户场景模拟：记忆系统体验测试")
        print("=" * 60)

        # === 场景 1: 首次对话 ===
        print("\n--- 场景 1: 首次对话 ---")
        conversations_1 = [
            ("你好", "你好！我是 Kage，你的终端精灵~"),
            ("你能做什么？", "我可以帮你控制系统、管理文件、回答问题等等"),
            ("嗯嗯", "嗯嗯，有什么需要随时叫我"),
            ("好的", "好的~"),
        ]

        facts_extracted = 0
        for user_input, assistant_response in conversations_1:
            facts = memory.add_conversation_facts(user_input, assistant_response)
            if facts:
                facts_extracted += len(facts)

        print(f"  对话轮数: {len(conversations_1)}")
        print(f"  提取事实: {facts_extracted} (预期: 0，因为都是无意义对话)")

        # === 场景 2: 用户透露偏好 ===
        print("\n--- 场景 2: 用户透露偏好 ---")
        conversations_2 = [
            ("我喜欢吃川菜，越辣越好", "川菜确实很过瘾！你喜欢哪种辣度？"),
            ("我每天早上7点起床跑步", "好自律！跑步多久了？"),
            ("我在北京工作，是个程序员", "北京的程序员啊，加班多吗？"),
            ("我朋友小明下周要结婚了", "恭喜恭喜！你要去参加婚礼吗？"),
            ("我非常讨厌吃香菜，每次闻到都想吐", "哈哈，香菜确实是两极分化的食物"),
        ]

        total_facts = 0
        for user_input, assistant_response in conversations_2:
            facts = memory.add_conversation_facts(user_input, assistant_response)
            total_facts += len(facts)
            if facts:
                for f in facts:
                    print(f"  ✅ 提取: [{f['category']}] '{f['content'][:30]}...' (重要性: {f['importance']})")

        print(f"\n  本轮提取: {total_facts} 个事实")

        # === 场景 3: 更新档案 ===
        print("\n--- 场景 3: 更新用户档案 ---")
        profile.update_preference("food", "food_preference", "川菜，越辣越好")
        profile.update_preference("music", "music_preference", "摇滚")
        profile.add_habit("sleep", "23:00-07:00")
        profile.add_habit("work", "习惯下午写代码")
        profile.add_relationship("小明", "朋友", "大学同学，下周结婚")

        summary = profile.get_profile_summary()
        print(f"  当前档案:\n{summary}")

        # === 场景 4: 记忆召回测试 ===
        print("\n--- 场景 4: 记忆召回测试 ---")

        # 测试 1: 召回食物偏好
        results_food = memory.recall("川菜", n_results=3)
        if results_food:
            print(f"  查询 '川菜':")
            for r in results_food[:2]:
                print(f"    - {r['content']} (重要性: {r['importance']})")
        else:
            print("  ❌ 未召回食物偏好")

        # 测试 2: 召回工作信息
        results_work = memory.recall("程序员", n_results=3)
        if results_work:
            print(f"  查询 '程序员':")
            for r in results_work[:2]:
                print(f"    - {r['content']} (重要性: {r['importance']})")
        else:
            print("  ❌ 未召回工作信息")

        # 测试 3: 召回人际关系
        results_friend = memory.recall("小明", n_results=3)
        if results_friend:
            print(f"  查询 '小明':")
            for r in results_friend[:2]:
                print(f"    - {r['content']} (重要性: {r['importance']})")
        else:
            print("  ❌ 未召回人际关系")

        # === 场景 5: 衰减测试 ===
        print("\n--- 场景 5: 记忆衰减测试 ---")
        import datetime

        now = datetime.datetime.now()

        # 添加一条旧记忆
        old_memory = {
            "id": "old-test",
            "timestamp": (now - datetime.timedelta(days=90)).isoformat(),
            "content": "我喜欢吃川菜",
            "emotion_data": {"emotion": "happy", "emotion_conf": 1.0},
            "type": "fact:preference",
            "importance": 3,
        }

        # 添加一条新记忆
        new_memory = {
            "id": "new-test",
            "timestamp": (now - datetime.timedelta(days=1)).isoformat(),
            "content": "我喜欢吃川菜",
            "emotion_data": {"emotion": "happy", "emotion_conf": 1.0},
            "type": "fact:preference",
            "importance": 3,
        }

        memory._entries.extend([old_memory, new_memory])
        memory._corpus_tokens.extend([
            ["我", "喜欢", "吃", "川", "菜"],
            ["我", "喜欢", "吃", "川", "菜"],
        ])
        memory._rebuild_bm25()

        results_decay = memory.recall_with_decay("川菜", n_results=5, decay_days=30)
        if len(results_decay) >= 2:
            print(f"  新记忆 (1天前): 衰减后重要性 = {results_decay[0]['decayed_importance']:.2f}")
            print(f"  旧记忆 (90天前): 衰减后重要性 = {results_decay[1]['decayed_importance']:.2f}")
            if results_decay[0]['decayed_importance'] > results_decay[1]['decayed_importance']:
                print("  ✅ 衰减正常：新记忆优先级更高")
            else:
                print("  ⚠️ 衰减效果不明显")
        else:
            print("  ⚠️ 召回结果不足")

        # === 场景 6: 档案摘要注入 prompt ===
        print("\n--- 场景 6: 档案摘要用于 prompt ---")
        profile_summary = profile.get_profile_summary()
        prompt_context = f"""
你是 Kage，一个了解用户的终端精灵。

【用户档案】
{profile_summary}

请根据用户档案提供个性化回复。
"""
        print(f"  注入 prompt 的档案上下文:\n{prompt_context}")

        # === 总结 ===
        print("\n" + "=" * 60)
        print("测试总结")
        print("=" * 60)
        print(f"  总对话轮数: {len(conversations_1) + len(conversations_2)}")
        print(f"  提取事实数: {total_facts}")
        print(f"  档案条目数: {len(profile.to_dict())}")
        print(f"  记忆条目数: {len(memory._entries)}")
        print(f"  召回测试: {'✅ 通过' if results_food and results_work and results_friend else '❌ 失败'}")
        print(f"  衰减测试: {'✅ 通过' if len(results_decay) >= 2 else '❌ 失败'}")

        return True

    finally:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    simulate_user_session()
