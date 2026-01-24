import asyncio
import json
import traceback
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
                current_emotion = voice_emotion if voice_emotion != "neutral" else "neutral"

                # Generate Response
                full_response = ""
                
                is_command = (intent == "COMMAND")
                memories = []
                if not is_command:
                     memories = self.memory.recall(user_input, n_result=3)

                mode = "action" if is_command else "chat"
                
                # Run Thinking in thread
                response_stream = await asyncio.to_thread(
                    self.brain.think, 
                    user_input, 
                    memories, 
                    current_emotion, 
                    mode=mode
                )

                # Collect response
                for chunk in response_stream:
                    if hasattr(chunk, 'text'): text = chunk.text
                    else: text = str(chunk)
                    full_response += text
                
                # 3. Action / Speech Phase
                await self.send_state("SPEAKING")
                
                final_speech = full_response

                if is_command:
                     if ">>>ACTION:" in full_response:
                        parts = full_response.split(">>>ACTION:")
                        final_speech = parts[0].strip()
                        raw_cmd = parts[1].strip()
                        
                        tool_result = await asyncio.to_thread(self.tools.execute, raw_cmd)
                        
                        # Report back
                        report_input = f"User: {user_input}\nTool Result: {tool_result}\nReport back to user."
                        report_stream = await asyncio.to_thread(
                            self.brain.think, report_input, [], current_emotion, temp=0.7, mode="report"
                        )
                        final_speech = ""
                        for chunk in report_stream:
                             if hasattr(chunk, 'text'): t = chunk.text
                             else: t = str(chunk)
                             final_speech += t

                # TTS & LipSync
                print(f"👻 Kage: {final_speech}") 
                await self.mouth_speak(final_speech, current_emotion)
                
                # Save Memory
                if not is_command:
                     self.memory.add_memory(content=user_input, emotion=current_emotion, type="chat")

                await self.send_state("IDLE")

            except Exception as e:
                print(f"❌ Error in loop: {e}")
                traceback.print_exc()
                await asyncio.sleep(1)

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
