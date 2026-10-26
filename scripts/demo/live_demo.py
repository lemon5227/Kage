"""Live desktop-assistant demo (D6): type requests into the running Kage server and show its replies.

  KAGE_TEXT_ONLY=1 python main.py            # server, no speech models
  python scripts/demo/live_demo.py [--lines FILE] [--dry]

Each line is typed out character by character (so a screen recording reads naturally), sent to
ws://127.0.0.1:12345/ws as a text message, and Kage's spoken reply is printed. Nothing is replayed: every reply
comes from the live server, the real apps and the real sites. Use test content only (the default lines send to
the user's own 文件传输助手 / second account).
"""
import argparse
import asyncio
import json
import sys
import subprocess
import time

import websockets

LINES = [
    '明儿个忙不忙',
    '知乎热榜前三是什么',
    '知乎上大家在聊什么',
    '明天会下雨吗',
    'B站是哪一年成立的',
    '打开计算器',
    '跟wenbo yen说一声：Kage 演示：名字说错了也能找到人',
    '确认',
]
AFTER = {'打开计算器': ['osascript', '-e', 'tell application "Calculator" to quit']}
BOLD, DIM, CYAN, GREEN, RESET = '\033[1m', '\033[2m', '\033[36m', '\033[32m', '\033[0m'


def type_out(text: str, delay: float) -> None:
    sys.stdout.write(f'{BOLD}{CYAN}你 ›{RESET} ')
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write('\n')


async def ask(ws, text: str, timeout: float) -> str:
    await ws.send(json.dumps({'type': 'text_input', 'text': text}))
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=end - time.monotonic()))
        except asyncio.TimeoutError:
            break
        if msg.get('type') == 'speech' and msg.get('text'):
            return str(msg['text'])
    return '（超时没有回复）'


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--lines', help='file with one request per line')
    parser.add_argument('--dry', action='store_true', help='no typing effect or pauses')
    parser.add_argument('--pause', type=float, default=3.0)
    args = parser.parse_args()
    lines = [l.strip() for l in open(args.lines, encoding='utf-8')] if args.lines else LINES
    stamp = time.strftime('%H:%M')                    # a message identical to an older one is harder to verify
    lines = [l.replace('Kage 演示：', f'Kage 演示 {stamp}：') for l in lines]
    print(f'{BOLD}Kage 桌面助手 · 实时演示{RESET}  {DIM}本地 4B 模型 · 命令行优先 · 所有回复来自实时运行{RESET}\n')
    async with websockets.connect('ws://127.0.0.1:12345/ws', max_size=None) as ws:
        for line in [l for l in lines if l]:
            type_out(line, 0 if args.dry else 0.06)
            started = time.monotonic()
            reply = await ask(ws, line, timeout=240)
            print(f'{BOLD}{GREEN}Kage ›{RESET} {reply}')
            print(f'{DIM}（{time.monotonic() - started:.1f} 秒）{RESET}\n')
            if line in AFTER and not args.dry:
                time.sleep(2.5)                       # show the opened app, then close it so it covers nothing
                subprocess.run(AFTER[line], capture_output=True)
            if not args.dry:
                time.sleep(args.pause)


if __name__ == '__main__':
    asyncio.run(main())
