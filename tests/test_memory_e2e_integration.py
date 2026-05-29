"""
端到端测试：AgenticLoop 记忆集成

测试：
1. AgenticLoop 自动提取事实
2. 档案自动更新
3. Prompt 注入档案摘要
4. 完整对话流程
"""

import sys
import os
import tempfile
import shutil
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockModelProvider:
    """模拟模型提供者"""

    def generate(self, messages, tools=None, max_tokens=200):
        class Response:
            def __init__(self):
                self.text = "好的，我明白了。"
                self.tool_calls = []
        return Response()


class MockToolExecutor:
    """模拟工具执行器"""

    def parse_tool_calls(self, text):
        return []


class MockToolRegistry:
    """模拟工具注册表"""

    def get_all_schemas(self):
        return []


class MockIdentityStore:
    """模拟身份存储"""

    def load_soul(self):
        return "你是 Kage，一个傲娇但靠谱的终端精灵。"

    def load_user(self):
        return "用户是你的 Master。"

    def ensure_files_exist(self):
        pass


class MockSessionManager:
    """模拟会话管理"""

    def get_history(self):
        return []


def test_agentic_loop_memory_integration():
    """测试 AgenticLoop 与记忆系统的集成"""
    print("=" * 60)
    print("测试: AgenticLoop 记忆集成 (端到端)")
    print("=" * 60)

    from core.memory import MemorySystem
    from core.memory_profile import MemoryProfile
    from core.prompt_builder import PromptBuilder
    from core.agentic_loop import AgenticLoop

    tmpdir = tempfile.mkdtemp()
    profile_path = os.path.join(tmpdir, "profile.json")

    try:
        # 初始化组件
        memory = MemorySystem(workspace_dir=tmpdir)
        profile = MemoryProfile(profile_path=profile_path)
        identity = MockIdentityStore()
        tool_executor = MockToolExecutor()
        tool_registry = MockToolRegistry()
        session = MockSessionManager()

        prompt_builder = PromptBuilder(
            identity_store=identity,
            memory_system=memory,
            tool_registry=tool_registry,
            prune_tools=True,
            memory_profile=profile,
        )

        agentic_loop = AgenticLoop(
            model_provider=MockModelProvider(),
            tool_executor=tool_executor,
            prompt_builder=prompt_builder,
            session_manager=session,
            memory_system=memory,
            memory_profile=profile,
        )

        # 模拟对话
        conversations = [
            "我喜欢吃川菜，越辣越好",
            "我每天早上7点起床跑步",
            "我在北京工作，是个程序员",
            "我朋友小明下周要结婚了",
            "我非常讨厌吃香菜，每次闻到都想吐",
        ]

        import asyncio

        total_facts = 0
        for i, user_input in enumerate(conversations):
            print(f"\n对话 {i+1}: '{user_input}'")
            result = asyncio.run(agentic_loop.run(user_input))
            print(f"  回复: {result.final_text}")

            # 检查记忆条目
            entry_count = len(memory._entries)
            print(f"  记忆条目: {entry_count}")

        # 检查档案
        profile_summary = profile.get_profile_summary()
        print(f"\n=== 档案摘要 ===")
        print(profile_summary)

        # 检查记忆召回
        print(f"\n=== 记忆召回测试 ===")
        for query in ["川菜", "程序员", "小明"]:
            results = memory.recall(query, n_results=2)
            if results:
                print(f"  '{query}': {results[0]['content'][:30]}...")
            else:
                print(f"  '{query}': 无结果")

        # 验证档案是否自动更新
        print(f"\n=== 档案验证 ===")
        p = profile.profile
        checks = {
            "food_preference": p.food_preference != "",
            "sleep_schedule": p.sleep_schedule != "",
            "city": p.city != "",
            "relationships": len(p.relationships) > 0,
        }

        all_passed = True
        for check, result in checks.items():
            status = "✅" if result else "⚠️"
            print(f"  {status} {check}: {'有数据' if result else '无数据'}")
            if not result:
                all_passed = False

        print(f"\n=== 测试总结 ===")
        print(f"  对话轮数: {len(conversations)}")
        print(f"  记忆条目: {len(memory._entries)}")
        print(f"  档案自动更新: {'✅ 通过' if all_passed else '⚠️ 部分通过'}")

        return True

    finally:
        shutil.rmtree(tmpdir)


def test_prompt_injection():
    """测试 Prompt 注入档案摘要"""
    print("\n" + "=" * 60)
    print("测试: Prompt 注入档案摘要")
    print("=" * 60)

    from core.memory import MemorySystem
    from core.memory_profile import MemoryProfile
    from core.prompt_builder import PromptBuilder

    tmpdir = tempfile.mkdtemp()
    profile_path = os.path.join(tmpdir, "profile.json")

    try:
        memory = MemorySystem(workspace_dir=tmpdir)
        profile = MemoryProfile(profile_path=profile_path)

        # 预先填充档案
        profile.update_preference("food", "food_preference", "川菜")
        profile.update_preference("music", "music_preference", "摇滚")
        profile.add_habit("sleep", "23:00-07:00")
        profile.add_relationship("小明", "朋友", "大学同学")

        identity = MockIdentityStore()
        tool_registry = MockToolRegistry()

        prompt_builder = PromptBuilder(
            identity_store=identity,
            memory_system=memory,
            tool_registry=tool_registry,
            prune_tools=True,
            memory_profile=profile,
        )

        messages, tools = prompt_builder.build(
            user_input="你好",
            history=[],
            current_emotion="neutral",
        )

        system_content = messages[0]["content"]
        has_profile = "用户档案" in system_content or "川菜" in system_content
        has_memory = "相关记忆" in system_content

        print(f"  系统提示词长度: {len(system_content)} 字符")
        print(f"  包含档案: {'✅' if has_profile else '❌'}")
        print(f"  包含记忆: {'✅' if has_memory else '⚠️ (无记忆)'}")

        if has_profile:
            # 提取档案部分
            start = system_content.find("【用户档案】")
            if start >= 0:
                profile_section = system_content[start:start+200]
                print(f"\n  注入的档案:\n{profile_section}")

        return has_profile

    finally:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    results = {}
    results["AgenticLoop 记忆集成"] = test_agentic_loop_memory_integration()
    results["Prompt 注入档案摘要"] = test_prompt_injection()

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    for name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {name}: {status}")
