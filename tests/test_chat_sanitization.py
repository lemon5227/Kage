"""Unit tests for chat cleanliness and intent routing.

These tests validate post-processing behavior without loading heavy ML models.
"""

import sys
import os
import unittest


# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


from core.router import KageRouter
from core.server import KageServer


class TestChatSanitization(unittest.TestCase):
    def setUp(self):
        # Create an uninitialized instance to access pure string helpers
        self.server = object.__new__(KageServer)

    def test_polish_removes_capability_brags(self):
        raw = "💖你好！我能做3项事：系统控制、计算、文件工具哒！ 😤 你还哒"
        out = self.server._polish_chat_response(raw)
        self.assertNotIn("我能做", out)

    def test_polish_strips_filler_particles(self):
        self.assertEqual(self.server._polish_chat_response("好的哒！"), "好的")
        self.assertEqual(self.server._polish_chat_response("嗯哒"), "嗯")
        self.assertEqual(self.server._polish_chat_response("哇哇！💖你今天高兴吗？哒"), "哇哇！💖你今天高兴吗？")

    def test_sanitize_for_speech_removes_system_blocks(self):
        raw = "你好<system-reminder>SECRET\nLINE</system-reminder>世界"
        out = self.server._sanitize_for_speech(raw)
        self.assertEqual(out, "你好世界")

    def test_polish_strips_thinking_process_preamble(self):
        raw = "Thinking Process:\n\n1. analyze\n2. answer"
        out = self.server._polish_chat_response(raw)
        self.assertEqual(out, "嗯")

    def test_sanitize_for_speech_prefers_final_answer_after_thinking(self):
        raw = "Thinking Process:\n1. analyze\nFinal Answer: smoke ok"
        out = self.server._sanitize_for_speech(raw)
        self.assertEqual(out, "smoke ok")


class TestIntentRouting(unittest.TestCase):
    def setUp(self):
        self.router = KageRouter()

    def test_open_app_variants_are_commands(self):
        for text in ["开王云", "开 网易云", "开启网易云音乐", "打开Safari", "开 safari"]:
            with self.subTest(text=text):
                self.assertEqual(self.router.classify(text), "COMMAND")


    def test_screenshot_variants_are_commands(self):
        for text in ["截图", "截屏", "截个屏"]:
            with self.subTest(text=text):
                self.assertEqual(self.router.classify(text), "COMMAND")


class TestWeatherParsing(unittest.TestCase):
    def setUp(self):
        self.server = object.__new__(KageServer)

    def test_extract_city_ignores_filler(self):
        self.assertEqual(self.server._extract_city("嗯，今天天气怎么样？"), "")
        self.assertEqual(self.server._extract_city("我说今天晚上天气怎么样？"), "")
        self.assertEqual(self.server._extract_city("帮我查一下当地天气。"), "")
        self.assertEqual(self.server._extract_city("所以我现在天气怎么样？"), "")
        self.assertEqual(self.server._extract_city("我去查尼斯的天气怎么样？"), "尼斯")
        self.assertEqual(self.server._extract_city("网络搜一下尼斯的天气。"), "尼斯")
        self.assertEqual(self.server._extract_city("北京今天晚上天气怎么样？"), "北京")

    def test_location_override_affects_effective_city(self):
        self.server._fast_cache = {}
        self.server._set_location_override("尼斯")
        self.assertEqual(self.server._get_effective_city(), "尼斯")


if __name__ == "__main__":
    unittest.main(verbosity=2)
