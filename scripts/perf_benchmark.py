"""Benchmark for performance optimizations.

Run with: python scripts/perf_benchmark.py
"""
import sys
import os
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def bench(name: str, n: int, fn) -> float:
    # Warmup
    for _ in range(min(10, n // 10)):
        fn()
    start = time.perf_counter()
    for _ in range(n):
        fn()
    elapsed = time.perf_counter() - start
    per_call_us = (elapsed / n) * 1_000_000
    print(f"  {name:50s} {per_call_us:>10.2f} µs/call  ({n:,} iters)")
    return per_call_us


def benchmark_tokenize():
    print("\n=== _tokenize (memory.py) ===")
    from core.memory import _tokenize
    text = "今天上海天气怎么样 should be sunny and 25 degrees with light wind"
    bench("_tokenize mixed Chinese/English", 100_000, lambda: _tokenize(text))


def benchmark_polish():
    print("\n=== polish_chat_response (chat_polisher.py) ===")
    from core.chat_polisher import polish_chat_response
    text = "💖你好！我能做3项事：系统控制、计算、文件工具哒！😤 用户：测试 助手：好的"
    bench("polish_chat_response typical reply", 10_000, lambda: polish_chat_response(text))


def benchmark_filter():
    print("\n=== filter_chat_text (chat_polisher.py) ===")
    from core.chat_polisher import filter_chat_text
    text = "你好<system-reminder>SECRET</system-reminder>今天 neutral happy 文件工具哒 测试" * 3
    bench("filter_chat_text with blocked content", 10_000, lambda: filter_chat_text(text))


def benchmark_detect_repetition():
    print("\n=== detect_repetition (agentic_loop.py) ===")
    from core.agentic_loop import detect_repetition
    short = "Hello world this is a normal response"
    long_no_rep = "x" * 50 + "y" * 50 + "z" * 50
    long_with_rep = "abcdefghij" * 10 + "xyz" * 50
    bench("detect_repetition short text", 100_000, lambda: detect_repetition(short))
    bench("detect_repetition 150-char no rep", 10_000, lambda: detect_repetition(long_no_rep))
    bench("detect_repetition 150-char with rep", 10_000, lambda: detect_repetition(long_with_rep))


def benchmark_extract_city():
    print("\n=== _extract_city (server.py) ===")
    # Avoid loading full server — just test the regex directly
    import re
    from core.server import _CITY_STOPWORDS_RE, _CITY_TOKEN_RE
    text = "网络查询尼斯天气怎么样？我想看看今天的天气"

    def old_impl():
        stopwords = [
            "天气", "怎么样", "如何", "今天", "现在", "查询", "查", "一下", "看看", "帮我",
            "的", "吗", "么", "呀", "啊", "呢", "是不是", "想", "告诉我",
            "我说", "我想", "我问", "我", "说", "问",
            "晚上", "今晚上", "今晚", "明天", "后天", "上午", "下午", "早上", "中午",
            "嗯", "嗯嗯", "额", "呃", "唉", "em",
            "当地", "本地", "这里", "我这", "我们这",
            "所以", "那", "然后", "不过", "就是", "此刻",
            "去", "去查", "去看看", "去问", "帮我查", "帮我问",
            "网络", "网上", "搜索", "搜", "搜下", "搜一下", "网络搜", "网络查询", "网络搜一下",
        ]
        cleaned = text
        for word in sorted(stopwords, key=len, reverse=True):
            cleaned = cleaned.replace(word, "")
        return re.findall(r"[A-Za-z\u4e00-\u9fff]+", cleaned)

    def new_impl():
        cleaned = _CITY_STOPWORDS_RE.sub("", text)
        return _CITY_TOKEN_RE.findall(cleaned)

    bench("OLD: 50+ str.replace + re.findall", 10_000, old_impl)
    bench("NEW: single regex.sub + cached findall", 10_000, new_impl)


def benchmark_memory_ops():
    print("\n=== Memory operations (memory.py) ===")
    from core.memory import MemorySystem
    with tempfile.TemporaryDirectory() as tmp:
        mem = MemorySystem(workspace_dir=tmp, max_entries=1000)

        # Pre-populate
        for i in range(100):
            mem.add_memory(f"entry number {i} with some content about topic {i % 10}",
                          importance=i % 5)

        bench("add_memory (with batched BM25 rebuild)", 1000,
              lambda: mem.add_memory("new test entry about something", importance=2))

        bench("bm25_search 5 results from 1000 entries", 1000,
              lambda: mem.bm25_search("topic content", n_results=5))


def benchmark_route_classifier():
    print("\n=== route_classifier (route_classifier.py) ===")
    from core.route_classifier import is_route_ambiguous, should_try_tools
    text_chat = "今天天气真好啊"
    text_command = "帮我打开浏览器"
    text_info = "查一下今天的新闻"

    bench("is_route_ambiguous chat", 100_000, lambda: is_route_ambiguous(text_chat, "chat"))
    bench("should_try_tools command", 100_000, lambda: should_try_tools(text_command))


def benchmark_prompt_builder_classify():
    print("\n=== prompt_builder.classify_route ===")
    # Create a minimal builder without full deps
    from core.prompt_builder import PromptBuilder

    class Stub:
        def __getattr__(self, n): return self
        def __call__(self, *a, **kw): return None

    pb = object.__new__(PromptBuilder)

    text = "帮我打开 Safari 浏览器并搜索一下今天的新闻"
    bench("classify_route command+info", 100_000, lambda: pb.classify_route(text))


if __name__ == "__main__":
    print("=" * 70)
    print("Kage Performance Benchmark")
    print("=" * 70)
    benchmark_tokenize()
    benchmark_polish()
    benchmark_filter()
    benchmark_detect_repetition()
    benchmark_extract_city()
    benchmark_route_classifier()
    benchmark_prompt_builder_classify()
    benchmark_memory_ops()
    print("\n" + "=" * 70)
    print("Done.")
