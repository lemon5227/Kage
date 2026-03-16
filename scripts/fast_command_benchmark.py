import os
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

from core.server import KageServer


def run_case(server: KageServer, text: str):
    start = time.perf_counter()
    result = server._fast_command(text)
    elapsed = (time.perf_counter() - start) * 1000
    return result, elapsed


def main():
    server = KageServer()
    cases = [
        "打开浏览器",
        "打开Safari",
        "打开谷歌浏览器",
        "打开知乎",
        "打开b站",
        "打开 https://example.com",
        "今天尼斯天气怎么样",
        "天气怎么样",
        "几点了",
        "打开微信",
        "启动网易云音乐",
        "播放",
        "暂停",
        "下一首",
        "上一首",
    ]

    print("Fast command benchmark (ms):")
    for text in cases:
        result, elapsed = run_case(server, text)
        print(f"- {text}: {elapsed:.2f} ms -> {result}")


if __name__ == "__main__":
    main()
