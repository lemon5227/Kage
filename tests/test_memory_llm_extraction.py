"""
测试 LLM 辅助事实提取
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockModelProvider:
    """模拟模型提供者，返回 JSON 格式的事实"""

    def __init__(self, response_text=None):
        self.response_text = response_text or """[
  {"content": "我喜欢吃川菜", "category": "preference", "importance": 4, "negated": false}
]"""

    def generate(self, messages, max_tokens=200):
        class Response:
            def __init__(self, text):
                self.text = text
                self.tool_calls = []
        return Response(self.response_text)


def test_llm_extractor_basic():
    """测试 LLM 提取器基本功能"""
    print("=" * 60)
    print("测试: LLM 事实提取器")
    print("=" * 60)

    import asyncio
    from core.memory_llm_extractor import LLMFactExtractor

    # 测试 1: 正常提取
    model = MockModelProvider()
    extractor = LLMFactExtractor(model_provider=model)

    result = asyncio.run(extractor.extract_facts("我喜欢吃川菜，越辣越好", ""))
    print(f"  测试 1 (正常提取): {len(result)} 个事实")
    if result:
        print(f"    内容: {result[0]['content']}")
        print(f"    分类: {result[0]['category']}")
        print(f"    重要性: {result[0]['importance']}")
    assert len(result) >= 1, f"Should extract at least 1 fact, got {len(result)}"
    print("  ✅ 通过")

    # 测试 2: 否定检测
    model2 = MockModelProvider("""[
  {"content": "我不吃川菜了", "category": "preference", "importance": 4, "negated": true}
]""")
    extractor2 = LLMFactExtractor(model_provider=model2)
    result2 = asyncio.run(extractor2.extract_facts("我不吃川菜了", ""))
    print(f"  测试 2 (否定检测): {len(result2)} 个事实")
    if result2:
        print(f"    negated: {result2[0]['negated']}")
    assert len(result2) >= 1, "Should extract negated fact"
    assert result2[0]["negated"] is True, "Should detect negation"
    print("  ✅ 通过")

    # 测试 3: 无效 JSON 回退
    model3 = MockModelProvider("这不是 JSON")
    extractor3 = LLMFactExtractor(model_provider=model3)
    result3 = asyncio.run(extractor3.extract_facts("你好", ""))
    print(f"  测试 3 (无效 JSON): {len(result3)} 个事实")
    assert len(result3) == 0, "Should return empty for invalid JSON"
    print("  ✅ 通过")

    # 测试 4: 合并策略
    llm_facts = [{"content": "LLM 提取的事实", "category": "preference", "importance": 4, "negated": False, "source": "llm"}]
    rule_facts = [{"content": "规则提取的事实", "category": "preference", "importance": 3}]
    merged = extractor.merge_with_rule_facts(llm_facts, rule_facts)
    print(f"  测试 4 (合并策略): {len(merged)} 个事实")
    assert len(merged) == 1, "Should prefer LLM facts"
    assert merged[0]["source"] == "llm", "Should use LLM facts"
    print("  ✅ 通过")

    # 测试 5: 无 LLM 时回退到规则
    extractor_no_llm = LLMFactExtractor(model_provider=None)
    result5 = asyncio.run(extractor_no_llm.extract_facts("我喜欢川菜", ""))
    print(f"  测试 5 (无 LLM 回退): {len(result5)} 个事实")
    assert len(result5) == 0, "Should return empty without LLM"
    print("  ✅ 通过")

    print("\n  结果: 5/5 通过")
    return True


def test_llm_integration_with_agentic_loop():
    """测试 LLM 提取器与 AgenticLoop 集成"""
    print("\n" + "=" * 60)
    print("测试: LLM + AgenticLoop 集成")
    print("=" * 60)

    import asyncio
    import tempfile
    import shutil
    from core.memory import MemorySystem
    from core.memory_profile import MemoryProfile
    from core.agentic_loop import AgenticLoop
    from core.prompt_builder import PromptBuilder

    tmpdir = tempfile.mkdtemp()
    profile_path = os.path.join(tmpdir, "profile.json")

    try:
        memory = MemorySystem(workspace_dir=tmpdir)
        profile = MemoryProfile(profile_path=profile_path)

        # Create mock components
        class MockModel:
            def generate(self, messages, max_tokens=200, tools=None):
                class R:
                    def __init__(self):
                        self.text = "好的"
                        self.tool_calls = []
                return R()

        class MockTools:
            def parse_tool_calls(self, text):
                return []

        class MockRegistry:
            def get_all_schemas(self):
                return []

        class MockIdentity:
            def load_soul(self):
                return "你是 Kage"
            def load_user(self):
                return ""
            def ensure_files_exist(self):
                pass

        class MockSession:
            def get_history(self):
                return []

        prompt_builder = PromptBuilder(
            identity_store=MockIdentity(),
            memory_system=memory,
            tool_registry=MockRegistry(),
            prune_tools=True,
            memory_profile=profile,
        )

        loop = AgenticLoop(
            model_provider=MockModel(),
            tool_executor=MockTools(),
            prompt_builder=prompt_builder,
            session_manager=MockSession(),
            memory_system=memory,
            memory_profile=profile,
        )

        # Run a conversation
        result = asyncio.run(loop.run("我喜欢吃川菜，越辣越好"))
        print(f"  对话回复: {result.final_text}")
        print(f"  记忆条目: {len(memory._entries)}")
        print(f"  Pending facts: {len(loop._pending_facts)}")

        assert len(memory._entries) >= 1, "Should have at least 1 memory entry"
        print("  ✅ 通过")

        return True

    finally:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    results = {}
    results["LLM 提取器基本功能"] = test_llm_extractor_basic()
    results["LLM + AgenticLoop 集成"] = test_llm_integration_with_agentic_loop()

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    for name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {name}: {status}")
