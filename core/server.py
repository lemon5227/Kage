# pyright: reportGeneralTypeIssues=false
import asyncio
import json
import traceback
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Import Kage Core Components
# Assuming this file is core/server.py, we need to adjust paths if necessary
# But since we run from root usually, we rely on sys.path or relative imports if in package.
# We will setup sys.path in __main__ execution or assume module usage.
import sys
import os

# Ensure we can import from the same directory or parent
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from core.memory import MemorySystem
from core.brain import KageBrain
from core.mouth import KageMouth
from core.ears import KageEars
from core.tools import KageTools
from core.router import KageRouter

from contextlib import asynccontextmanager

# Global Instance (Lazy Load)
kage_server = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Load Models (ONLY in Main Process)
    global kage_server
    if kage_server is None:
        print("🚦 Lifespan Startup: initializing KageServer...")
        kage_server = KageServer()
    yield
    # Shutdown
    if kage_server:
        kage_server.is_running = False
        print("🛑 Lifespan Shutdown: stopping KageServer...")

app = FastAPI(lifespan=lifespan)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class KageServer:
    def __init__(self):
        print("⚙️ Initializing Kage Server (Heavy Load)...")
        self.memory = MemorySystem()
        self.brain = KageBrain()
        self.mouth = KageMouth(voice="zh-CN-XiaoyiNeural")
        self.ears = KageEars(model_id="paraformer-zh")
        self.tools = KageTools()
        self.router = KageRouter(self.brain.model, self.brain.tokenizer)
        
        self.active_websocket: WebSocket | None = None
        self.is_running = True
        print("✅ Kage Server Ready!")

    # ... (Rest of KageServer methods - same as before) ...
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_websocket = websocket
        print("🔌 Client connected!")
        await self.send_state("IDLE")

    async def disconnect(self):
        self.active_websocket = None
        print("🔌 Client disconnected")

    async def send_message(self, type_: str, data: dict):
        if self.active_websocket:
            try:
                payload = {"type": type_, **data}
                await self.active_websocket.send_json(payload)
            except Exception as e:
                print(f"Send Error: {e}")

    async def send_state(self, state: str):
        """States: IDLE, LISTENING, THINKING, SPEAKING"""
        await self.send_message("state", {"state": state})

    async def run_loop(self):
        """The Main Async Event Loop"""
        print("🚀 Starting Main Loop...")
        
        # Initial Greeting
        greeting = "Master，Kage 在这！"
        await self.mouth_speak(greeting)

        while self.is_running:
            try:
                # 1. Listening Phase
                await self.send_state("LISTENING")
                
                # Run blocking Listen in thread
                # We need to run ears.listen() in a thread because it's blocking PyAudio
                listen_result = await asyncio.to_thread(self.ears.listen)
                
                user_input = ""
                voice_emotion = "neutral"

                if isinstance(listen_result, tuple):
                    user_input, voice_emotion = listen_result
                else:
                    user_input = listen_result
                
                if not user_input:
                    await self.send_state("IDLE")
                    await asyncio.sleep(0.1)
                    continue

                print(f"👤 Master: {user_input}")
                await self.send_message("transcription", {"text": user_input})

                # 2. Thinking Phase
                await self.send_state("THINKING")
                
                # Determine Intent
                intent = self.router.classify(user_input)
                print(f"🤔 Intent: {intent}") # Debug Output
                
                # Determine Emotion
                current_emotion: str = "neutral"
                if voice_emotion and voice_emotion != "neutral":
                    current_emotion = str(voice_emotion)
                current_emotion_str = str(current_emotion)

                # Generate Response
                full_response = ""
                
                is_command = (intent == "COMMAND")
                memories = []
                if not is_command:
                     memories = self.memory.recall(user_input, n_result=3)
                     quick_reply = self._quick_chat_response(user_input)
                     if quick_reply:
                         final_speech = quick_reply
                         print(f"👻 Kage: {final_speech}")
                         await self.mouth_speak(final_speech, current_emotion_str)
                         self.memory.add_memory(content=user_input, emotion=current_emotion_str, type="chat")
                         await self.send_state("IDLE")
                         continue

                mode = "action" if is_command else "chat"

                if is_command:
                    trigger_result = await asyncio.to_thread(self.tools.execute_trigger, user_input)
                    if trigger_result is not None:
                        final_speech = str(trigger_result)
                        print(f"👻 Kage: {final_speech}")
                        await self.mouth_speak(final_speech, current_emotion_str)  # type: ignore[arg-type]
                        await self.send_state("IDLE")
                        continue
                
                # Run Thinking in thread
                response_stream = await asyncio.to_thread(  # type: ignore[arg-type]
                    self._think_action,
                    user_input,
                    memories,
                    current_emotion_str,
                    mode,
                )

                # Collect response
                for chunk in response_stream:
                    text = getattr(chunk, "text", str(chunk))
                    full_response += text
                
                # 3. Action / Speech Phase
                await self.send_state("SPEAKING")
                
                final_speech = full_response

                if is_command:
                     tool_calls = self.tools.parse_tool_calls(full_response)
                     if tool_calls:
                        await self._send_quick_ack(current_emotion_str)
                        results = []
                        for call in tool_calls:
                            name = call.get("name")
                            arguments = call.get("arguments") or call.get("parameters")
                            result = await asyncio.to_thread(self.tools.execute_tool_call, name, arguments)
                            results.append(f"{name}: {result}")

                        tool_result = "\n".join(results)
                        final_speech = tool_result
                     elif ">>>ACTION:" in full_response:
                        parts = full_response.split(">>>ACTION:")
                        final_speech = parts[0].strip()
                        raw_cmd = parts[1].strip()
                        await self._send_quick_ack(current_emotion_str)
                        tool_result = await asyncio.to_thread(self.tools.execute, raw_cmd)
                        final_speech = str(tool_result)

                # TTS & LipSync
                print(f"👻 Kage: {final_speech}") 
                await self.mouth_speak(final_speech, current_emotion_str)  # type: ignore[arg-type]
                
                # Save Memory
                if not is_command:
                     self.memory.add_memory(content=user_input, emotion=current_emotion_str, type="chat")  # type: ignore[arg-type]

                await self.send_state("IDLE")

            except Exception as e:
                print(f"❌ Error in loop: {e}")
                traceback.print_exc()
                await asyncio.sleep(1)

    def _think_action(self, user_input: str, memories: list, current_emotion: str, mode: str):
        return self.brain.think(
            user_input=user_input,
            memories=memories,
            current_emotion=current_emotion,
            mode=mode,
        )

    def _think_report(self, report_input: str, current_emotion: str):
        return self.brain.think(
            user_input=report_input,
            memories=[],
            current_emotion=current_emotion,
            temp=0.7,
            mode="report",
        )

    async def _send_quick_ack(self, current_emotion: str):
        await self.mouth_speak("我马上处理~", current_emotion)

    async def mouth_speak(self, text, emotion="neutral"):
        """Speak and allow Frontend to sync lips and expression"""
        if not text: return
        
        # 1. Send Expression (Emotion)
        emo_map = {
            "neutral": "f00", "happy": "f01", "sad": "f02",
            "angry": "f03", "fear": "f04", "surprised": "f05"
        }
        exp_name = emo_map.get(emotion, "f00")
        await self.send_message("expression", {"name": exp_name})

        # 2. Send text to frontend (for speech bubble)
        await self.send_message("speech", {"text": text})
        
        # 3. Audio Generation (Generating... not speaking yet)
        audio_path = await self.mouth.generate_speech_file(text, emotion)
        
        if audio_path:
            # 4. Now we are ready to play. Signal Frontend!
            await self.send_state("SPEAKING")
            # Blocking Playback
            await asyncio.to_thread(self.mouth.play_audio_file, audio_path)
            # Done
            await self.send_state("IDLE")

    def _quick_chat_response(self, user_input: str):
        text = (user_input or "").strip()
        if not text:
            return None

        if "你是谁" in text:
            return "我是Kage，终端精灵哒💖"
        if "你能做什么" in text:
            return "系统控制/计算/文件工具哒💖"
        if "冷笑话" in text or "笑话" in text:
            return self.tools.execute_tool_call("joke")
        return None

    def _polish_chat_response(self, text: str):
        if not text:
            return text
        cleaned = " ".join(text.split())
        cleaned = cleaned.replace("Master心情:", "")
        cleaned = cleaned.replace("Master心情", "")
        cleaned = cleaned.replace("Master 心情:", "")
        cleaned = cleaned.replace("Master 心情", "")
        cleaned = cleaned.replace("@@@", "")
        cleaned = self._filter_chat_text(cleaned)
        cleaned = self._collapse_repeats(cleaned)
        cleaned = cleaned.strip()
        if not cleaned:
            cleaned = "嗯嗯"
        if len(cleaned) < 6:
            cleaned = f"{cleaned} {self._short_care_phrase()}"
        max_len = 30
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len]
        if not any(mark in cleaned for mark in ("✨", "😤", "💖")):
            cleaned += "💖"
        if not cleaned.endswith(("哒", "捏", "哇")):
            cleaned += "哒"
        return cleaned

    def _filter_chat_text(self, text: str):
        if not text:
            return text
        blocked_words = ["neutral", "happy", "sad", "angry", "fear", "surprised"]
        blocked_phrases = ["AIspeak", "cant be", "AIspeak cant be"]
        for word in blocked_words:
            text = text.replace(word, "")
        for phrase in blocked_phrases:
            text = text.replace(phrase, "")
        allowed_emoji = {"✨", "😤", "💖"}
        allowed_punct = set("，。！？!?、,.~:：;；()（）[]【】" )
        output = []
        for ch in text:
            code = ord(ch)
            if ch in allowed_emoji:
                output.append(ch)
                continue
            if ch in allowed_punct:
                output.append(ch)
                continue
            if ch.isalnum() or ch.isspace():
                output.append(ch)
                continue
            if 0x4E00 <= code <= 0x9FFF:
                output.append(ch)
                continue
        return "".join(output)

    def _short_care_phrase(self):
        phrases = [
            "我在这儿陪你哒💖",
            "别担心，我在呢哒😤",
            "我会一直陪你哒✨",
            "有我在就别怕哒💖",
            "我会听你说哒😤",
            "我一直在等你哒✨",
            "我陪你慢慢来哒💖",
            "先深呼吸一下哒😤",
        ]
        return random.choice(phrases)

    def _collapse_repeats(self, text: str):
        if not text:
            return text
        output = []
        last_char = None
        repeat_count = 0
        for ch in text:
            if ch == last_char:
                repeat_count += 1
            else:
                repeat_count = 0
            last_char = ch
            if repeat_count < 2:
                output.append(ch)
        return "".join(output)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global kage_server
    if not kage_server:
        # Fallback if accessed via direct uvicorn without lifespan
        print("⚠️ Lazy Init triggered via Websocket (Fallback)")
        kage_server = KageServer()

    await kage_server.connect(websocket)
    try:
        loop_task = asyncio.create_task(kage_server.run_loop())
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        await kage_server.disconnect()
        pass

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=12345)
