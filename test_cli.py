#!/usr/bin/env python3
"""CLI 测试客户端 — 通过 WebSocket 与 Kage 交互（无需前端）

用法: python test_cli.py
"""

import asyncio
import json
import websockets


async def main():
    uri = "ws://127.0.0.1:12345/ws"
    print(f"🔌 连接 {uri} ...")

    try:
        async with websockets.connect(uri) as ws:
            print("✅ 已连接！输入消息发送给 Kage，输入 q 退出\n")

            # Background task to print incoming messages
            async def receiver():
                try:
                    async for raw in ws:
                        msg = json.loads(raw)
                        msg_type = msg.get("type", "")

                        if msg_type == "state":
                            state = msg.get("state", "")
                            icon = {"IDLE": "💤", "LISTENING": "👂", "THINKING": "🤔", "SPEAKING": "🗣️"}.get(state, "❓")
                            print(f"  {icon} [{state}]")

                        elif msg_type == "speech":
                            text = msg.get("text", "")
                            emotion = msg.get("emotion", "")
                            emo_str = f" ({emotion})" if emotion else ""
                            print(f"\n  👻 Kage{emo_str}: {text}\n")

                        elif msg_type == "transcription":
                            print(f"  📝 ASR: {msg.get('text', '')}")

                        elif msg_type == "expression":
                            print(f"  🎭 表情: {msg.get('name', '')} ({msg.get('duration', '')}s)")

                        elif msg_type == "motion":
                            print(f"  💃 动作: {msg.get('group', '')}/{msg.get('index', '')}")

                        else:
                            print(f"  📨 {msg_type}: {json.dumps(msg, ensure_ascii=False)[:120]}")

                except websockets.ConnectionClosed:
                    print("\n🔌 连接已断开")

            recv_task = asyncio.create_task(receiver())

            # Send loop
            while True:
                try:
                    user_input = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input("你> ")
                    )
                except (EOFError, KeyboardInterrupt):
                    break

                if user_input.strip().lower() in ("q", "quit", "exit"):
                    break

                if not user_input.strip():
                    continue

                # Send as text message (simulating what the frontend sends)
                payload = json.dumps({
                    "type": "text_input",
                    "text": user_input,
                })
                await ws.send(payload)

            recv_task.cancel()
            print("👋 再见！")

    except ConnectionRefusedError:
        print("❌ 连接失败 — 确保 Kage 服务器正在运行 (KAGE_NO_TRAY=1 python main.py)")
    except Exception as e:
        print(f"❌ 错误: {e}")


if __name__ == "__main__":
    asyncio.run(main())
