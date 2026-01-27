# pyright: reportGeneralTypeIssues=false
import asyncio
import json
import traceback
import random
import time
import re
import threading
import subprocess
from urllib.parse import quote
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
        self.motion_groups = {
            "Idle": 3,
            "Tap": 2,
        }
        self.motion_group_weights = {
            "Idle": 1,
            "Tap": 3,
        }
        self.motion_emotion_weights = {
            "happy": {"Idle": 1, "Tap": 5},
            "surprised": {"Idle": 1, "Tap": 4},
            "sad": {"Idle": 4, "Tap": 1},
            "angry": {"Idle": 2, "Tap": 3},
        }
        self.motion_cooldown_sec = 4.0
        self.motion_cooldown_min_sec = 2.5
        self.motion_cooldown_max_sec = 6.0
        self._last_motion_time = 0.0
        self.expression_duration_base_sec = 2.5
        self.expression_duration_per_char = 0.04
        self.expression_duration_min_sec = 2.0
        self.expression_duration_max_sec = 6.0
        self.expression_map = {
            "neutral": "f05",
            "happy": {
                "choices": ["f00", "f01"],
                "weights": [3, 1],
            },
            "sad": "f03",
            "angry": "f07",
            "fear": "f06",
            "surprised": "f02",
        }
        self._fast_cache = {}
        threading.Thread(target=self._prefetch_local_city, daemon=True).start()
        print("✅ Kage Server Ready!")

    # ... (Rest of KageServer methods - same as before) ...
    async def connect(self, websocket: WebSocket):
        if self.active_websocket and self.active_websocket is not websocket:
            try:
                await self.active_websocket.close()
            except Exception:
                pass
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

        # 会话状态
        in_conversation = False  # 是否在对话中
        conversation_timeout = 30  # 对话超时秒数
        last_interaction_time = 0
        
        while self.is_running:
            try:
                # 检查是否需要等待唤醒词
                if not in_conversation:
                    # 0. Wake Word Phase (待机模式)
                    await self.send_state("IDLE")
                    wakeword_detected = await asyncio.to_thread(self.ears.wait_for_wakeword, 300)
                    
                    if not wakeword_detected:
                        # 超时，继续等待
                        continue
                    
                    # 唤醒成功，播放提示音 (只在首次唤醒时)
                    await self.send_message("expression", {"name": "f02", "duration": 1.5})  # surprised
                    await self.mouth_speak("嘣？主人叫我？", "surprised")
                    in_conversation = True
                    last_interaction_time = asyncio.get_event_loop().time()
                
                # 1. Listening Phase (已在对话中)
                await self.send_state("LISTENING")
                
                # Run blocking Listen in thread
                listen_result = await asyncio.to_thread(self.ears.listen)
                
                user_input = ""
                voice_emotion = "neutral"

                if isinstance(listen_result, tuple):
                    user_input, voice_emotion = listen_result
                else:
                    user_input = listen_result
                
                if not user_input:
                    # 检查会话是否超时
                    current_time = asyncio.get_event_loop().time()
                    if in_conversation and (current_time - last_interaction_time) > conversation_timeout:
                        print("⌛ Conversation timeout, returning to sleep mode")
                        in_conversation = False
                    await self.send_state("IDLE")
                    await asyncio.sleep(0.1)
                    continue
                
                # 更新最后交互时间
                last_interaction_time = asyncio.get_event_loop().time()

                print(f"👤 Master: {user_input}")
                await self.send_message("transcription", {"text": user_input})

                # 2. Thinking Phase
                await self.send_state("THINKING")

                # 1️⃣ 最高优先级: 直接命令匹配 (最快)
                fast_response = await asyncio.to_thread(self._fast_command, user_input)
                if fast_response:
                    print("⚡ Fast path: direct command")
                    final_speech = str(fast_response)
                    print(f"👻 Kage: {final_speech}")
                    await self.mouth_speak(final_speech, "neutral")
                    # 保持在对话中，不回到待机
                    continue

                # 2️⃣ 次优先级: 技能触发器 (复杂功能)
                quick_trigger = await asyncio.to_thread(self.tools.execute_trigger, user_input)
                if quick_trigger is not None:
                    print("⚡ Fast path: skill trigger")
                    final_speech = str(quick_trigger)
                    print(f"👻 Kage: {final_speech}")
                    await self.mouth_speak(final_speech, "neutral")
                    await self.send_state("IDLE")
                    continue

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
                         continue

                mode = "action" if is_command else "chat"

                # 注意：trigger 已在上面第2优先级检查过，这里不再重复调用
                
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

        self._update_motion_cooldown(text)
        await self._send_random_motion(emotion)
        
        # 1. Send Expression (Emotion)
        exp_value = self.expression_map.get(emotion, "f05")
        if isinstance(exp_value, dict):
            choices = exp_value.get("choices") or []
            weights = exp_value.get("weights")
            if choices:
                if weights and len(weights) == len(choices):
                    exp_name = random.choices(choices, weights=weights, k=1)[0]
                else:
                    exp_name = random.choice(choices)
            else:
                exp_name = "f05"
        elif isinstance(exp_value, list):
            exp_name = random.choice(exp_value) if exp_value else "f05"
        else:
            exp_name = exp_value
        await self.send_message("expression", {
            "name": exp_name,
            "duration": self._compute_expression_duration(text),
        })

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
        else:
            await self.send_state("IDLE")

    async def _send_random_motion(self, emotion: str | None = None):
        if not self.motion_groups:
            return
        now = time.monotonic()
        if now - self._last_motion_time < self.motion_cooldown_sec:
            return
        self._last_motion_time = now
        emotion_key = emotion or ""
        weights_map = self.motion_emotion_weights.get(emotion_key, self.motion_group_weights)
        groups = list(weights_map.keys())
        weights = list(weights_map.values())
        group = random.choices(groups, weights=weights, k=1)[0]
        max_index = self.motion_groups.get(group, 0)
        if max_index <= 0:
            return
        index = random.randrange(max_index)
        await self.send_message("motion", {"group": group, "index": index})

    def _update_motion_cooldown(self, text: str):
        if not text:
            return
        duration = self.expression_duration_base_sec + len(text) * 0.06
        self.motion_cooldown_sec = max(
            self.motion_cooldown_min_sec,
            min(duration, self.motion_cooldown_max_sec),
        )

    def _compute_expression_duration(self, text: str) -> float:
        if not text:
            return self.expression_duration_base_sec
        duration = self.expression_duration_base_sec + len(text) * self.expression_duration_per_char
        return max(
            self.expression_duration_min_sec,
            min(duration, self.expression_duration_max_sec),
        )

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

    def _fast_command(self, user_input: str):
        text = (user_input or "").strip()
        if not text:
            return None

        lower_text = text.lower()
        if "打开浏览器" in text or "打开chrome" in lower_text or "打开safari" in lower_text or "打开谷歌浏览器" in text:
            print("🧭 Direct: open_app -> browser")
            if "chrome" in lower_text or "谷歌" in text:
                return self.tools.open_app("Google Chrome")
            return self.tools.open_app("Safari")

        if "亮度" in text:
            action = "up"
            if any(token in text for token in ["低", "暗", "小", "降低", "调低", "调暗"]):
                action = "down"
            print("🧭 Direct: system_control -> brightness")
            return self.tools.system_control("brightness", action)

        # 独立的静音命令
        if "静音" in text or "mute" in lower_text:
            action = "unmute" if "取消" in text or "un" in lower_text else "mute"
            print("🧭 Direct: system_control -> mute")
            return self.tools.system_control("volume", action)

        if "音量" in text or "声音" in text:
            action = "up"
            if any(token in text for token in ["小", "低", "降低", "调低"]):
                action = "down"
            print("🧭 Direct: system_control -> volume")
            return self.tools.system_control("volume", action)

        # 媒体控制 - 扩展关键词匹配
        media_keywords = ["播放", "暂停", "继续", "下一首", "下一曲", "上一首", "上一曲", 
                          "放音乐", "放歌", "听歌", "听音乐", "停止播放", "停止音乐"]
        if any(token in text for token in media_keywords):
            action = "playpause"
            if "下一" in text:
                action = "next"
            elif "上一" in text:
                action = "previous"
            elif "暂停" in text:
                action = "pause"
            elif "继续" in text or "播放" in text:
                action = "play"
            print("🧭 Direct: media_control")
            preferred_apps = []
            if "网易云" in text or "云音乐" in text:
                preferred_apps = ["NeteaseMusic", "网易云音乐"]
            elif "spotify" in lower_text:
                preferred_apps = ["Spotify"]
            return self._media_control(action, preferred_apps)

        if "蓝牙" in text:
            action = "off" if any(token in text for token in ["关", "关闭", "关掉"] ) else "on"
            print("🧭 Direct: system_control -> bluetooth")
            return self.tools.system_control("bluetooth", action)

        if "wifi" in lower_text or "无线" in text or "网络" in text:
            action = "off" if any(token in text for token in ["关", "关闭", "关掉"] ) else "on"
            print("🧭 Direct: system_control -> wifi")
            return self.tools.system_control("wifi", action)

        if "打开百度" in text or "百度一下" in text:
            print("🧭 Direct: open_url -> baidu")
            return self.tools.open_url("https://www.baidu.com")

        if "打开知乎" in text or "知乎" in text:
            print("🧭 Direct: open_url -> zhihu")
            return self.tools.open_url("https://www.zhihu.com")

        if "打开b站" in lower_text or "b站" in text or "哔哩哔哩" in text:
            print("🧭 Direct: open_url -> bilibili")
            return self.tools.open_url("https://www.bilibili.com")

        url_match = re.search(r"https?://\S+", text)
        if "打开" in text and url_match:
            print("🧭 Direct: open_url -> explicit url")
            return self.tools.open_url(url_match.group(0))

        app_match = re.search(r"(?:打开|启动|开启)(.+)", text)
        if app_match:
            app_name = app_match.group(1)
            for token in ["应用", "程序", "软件", "一下", "吧", "请"]:
                app_name = app_name.replace(token, "")
            app_name = app_name.strip(" ：:，,。\n\t")
            if app_name and all(key not in app_name for key in ["网页", "网址", "链接"]):
                print(f"🧭 Direct: open_app -> {app_name}")
                return self.tools.open_app(app_name)

        if "天气" in text:
            city = self._extract_city(text)
            if not city:
                city = self._get_local_city() or "Beijing"
                cached_weather = self._get_fast_cache("weather:local", ttl=600)
                if cached_weather:
                    return cached_weather
            city_map = {"尼斯": "Nice"}
            city = city_map.get(city, city)
            print("🧭 Direct: run_cmd -> wttr.in")
            return self._fetch_weather(city)

        if "几点" in text or "时间" in text:
            print("🧭 Direct: get_time")
            return self._persona_wrap(self.tools.get_time(), "time")

        if "截图" in text or "截屏" in text:
            print("🧭 Direct: take_screenshot")
            return self._persona_wrap(self.tools.take_screenshot(), "screenshot")

        if "电量" in text or "电池" in text:
            print("🧭 Direct: battery_status")
            result = self.tools.run_terminal_cmd("pmset -g batt | grep -Eo '[0-9]+%'")
            battery = self._strip_cmd_output(result)
            return self._persona_wrap(f"电量 {battery}", "battery")

        return None

    def _persona_wrap(self, result: str, cmd_type: str = "default") -> str:
        """给快速命令结果添加 persona 风格"""
        import random
        
        # 根据命令类型选择回复风格
        templates = {
            "time": ["现在是 {r} 哒～", "{r} 了哦✨", "时间是 {r} 💖"],
            "weather": ["天气: {r} 捏～", "{r} ☀️", "查到了: {r} 哒"],
            "screenshot": ["截好啦 {r} ✨", "咔嚓！{r} 💖", "截图完成 {r} 哒"],
            "battery": ["{r} 还有电哦～", "{r} 💖", "电量 {r} 哒"],
            "volume": ["{r}", "好嘞～{r}", "{r} 💖"],
            "brightness": ["{r}", "调好啦～{r}", "{r} ✨"],
            "media": ["{r} 🎵", "好嘞～{r}", "{r} 哒"],
            "app": ["{r}", "打开啦～{r}", "{r} ✨"],
            "default": ["{r}", "{r} 哒", "{r} ✨"],
        }
        
        # 获取模板并格式化
        template_list = templates.get(cmd_type, templates["default"])
        template = random.choice(template_list)
        return template.format(r=str(result).strip())

    def _get_local_city(self):
        cached = self._get_fast_cache("local_city", ttl=86400)
        if cached:
            return cached
        result = self.tools.run_terminal_cmd("curl -s --max-time 4 https://ipinfo.io/city")
        city = self._strip_cmd_output(result).strip()
        if city:
            self._set_fast_cache("local_city", city)
            return city
        return ""

    def _prefetch_local_city(self):
        try:
            self._get_local_city()
        except Exception:
            pass

    def _get_fast_cache(self, key: str, ttl: int):
        entry = self._fast_cache.get(key)
        if not entry:
            return ""
        if time.time() - entry["timestamp"] > ttl:
            self._fast_cache.pop(key, None)
            return ""
        return entry["value"]

    def _set_fast_cache(self, key: str, value: str):
        self._fast_cache[key] = {"timestamp": time.time(), "value": value}

    def _strip_cmd_output(self, result) -> str:
        text = str(result).strip()
        if text.startswith("命令执行成功"):
            parts = text.splitlines()
            return parts[-1] if parts else ""
        return text

    def _fetch_weather(self, city: str) -> str:
        local_city = self._get_local_city() or ""
        cache_key = "weather:local" if city == local_city else f"weather:{city.lower()}"
        cached_weather = self._get_fast_cache(cache_key, ttl=600)
        if cached_weather:
            return cached_weather
        result = self.tools.run_terminal_cmd(
            f"curl -s --max-time 5 'wttr.in/{quote(city)}?format=3'"
        )
        weather = self._strip_cmd_output(result)
        if weather:
            self._set_fast_cache(cache_key, weather)
            return weather
        fallback = self._get_fast_cache(cache_key, ttl=86400)
        return fallback or "天气查询失败，请稍后再试"

    def _extract_city(self, text: str) -> str:
        cleaned = text
        stopwords = [
            "天气", "怎么样", "如何", "今天", "现在", "查询", "查", "一下", "看看", "帮我",
            "的", "吗", "么", "呀", "啊", "呢", "是不是", "想", "告诉我",
        ]
        for word in stopwords:
            cleaned = cleaned.replace(word, "")
        cleaned = cleaned.strip(" ：:，,。\n\t")
        if not cleaned:
            return ""
        matches = re.findall(r"[A-Za-z\u4e00-\u9fff]+", cleaned)
        if not matches:
            return ""
        return max(matches, key=len)

    def _get_running_music_app(self) -> str | None:
        """检测正在运行的音乐应用"""
        # 常见音乐应用列表（按优先级排序）
        music_apps = [
            ("NeteaseMusic", "网易云音乐"),
            ("Spotify", "Spotify"),
            ("Music", "Apple Music"),
            ("QQMusic", "QQ音乐"),
            ("Kugou", "酷狗音乐"),
            ("VLC", "VLC"),
        ]
        
        for app_name, _ in music_apps:
            try:
                result = subprocess.run(
                    ["pgrep", "-x", app_name], 
                    capture_output=True, 
                    timeout=1
                )
                if result.returncode == 0:
                    return app_name
            except Exception:
                continue
        return None

    def _media_control(self, action: str, preferred_apps: list[str]) -> str:
        """
        智能媒体控制：
        1. 如果有正在运行的播放器 -> 控制它
        2. 如果是播放命令且没有播放器 -> 打开默认播放器并播放
        3. 优先使用系统媒体键
        """
        # 检测正在运行的播放器
        running_app = self._get_running_music_app()
        
        # 如果是 "播放" 命令且没有播放器运行 -> 打开默认播放器
        if action in ["play", "playpause"] and not running_app:
            # 优先使用用户偏好的 app，否则用 Apple Music
            default_app = preferred_apps[0] if preferred_apps else "Music"
            print(f"🎵 No music app running, opening {default_app}...")
            self.tools.open_app(default_app)
            import time
            time.sleep(1)  # 等待 app 启动
        
        # 使用系统媒体键控制（适用于所有播放器）
        result = self._send_system_media_key(action)
        if result:
            return result
        
        # 回退：尝试 AppleScript 直接控制特定 app
        command_map = {
            "playpause": "playpause",
            "play": "play",
            "pause": "pause",
            "next": "next track",
            "previous": "previous track",
        }
        osascript_cmd = command_map.get(action, "playpause")
        
        # 构建候选列表：运行中的 app > 用户偏好 > 默认
        app_candidates = []
        if running_app:
            app_candidates.append(running_app)
        app_candidates.extend(preferred_apps)
        app_candidates.extend(["Music", "Spotify"])
        
        for app in app_candidates:
            script = f'tell application "{app}" to {osascript_cmd}'
            try:
                subprocess.run(["osascript", "-e", script], check=True)
                return f"已控制 {app} 播放 {action}"
            except Exception:
                continue
        return "未找到可控制的播放器"

    def _send_system_media_key(self, action: str) -> str:
        """
        使用 macOS 系统级媒体键事件，适用于任意播放器（网易云、Spotify、Music 等）
        通过 Quartz 框架发送 NX_KEYTYPE 事件
        """
        # macOS 媒体键 key code (NX_KEYTYPE_*)
        # NX_KEYTYPE_PLAY = 16, NX_KEYTYPE_NEXT = 17, NX_KEYTYPE_PREVIOUS = 18
        keytype_map = {
            "playpause": 16,  # NX_KEYTYPE_PLAY
            "play": 16,
            "pause": 16,
            "next": 17,       # NX_KEYTYPE_NEXT
            "previous": 18,   # NX_KEYTYPE_PREVIOUS
        }
        keytype = keytype_map.get(action)
        if keytype is None:
            return ""
        
        # 使用 Python Quartz 绑定发送媒体键事件
        try:
            import Quartz
            
            def send_media_key(key):
                # Key down
                ev = Quartz.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                    Quartz.NSEventTypeSystemDefined,  # 14
                    (0, 0),
                    0xa00,  # NX_KEYDOWN << 8
                    0,
                    0,
                    0,
                    8,  # NX_SUBTYPE_AUX_CONTROL_BUTTONS
                    (key << 16) | (0xa << 8),  # key << 16 | NX_KEYDOWN << 8
                    -1
                )
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev.CGEvent())
                
                # Key up
                ev = Quartz.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                    Quartz.NSEventTypeSystemDefined,
                    (0, 0),
                    0xb00,  # NX_KEYUP << 8
                    0,
                    0,
                    0,
                    8,
                    (key << 16) | (0xb << 8),  # key << 16 | NX_KEYUP << 8
                    -1
                )
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev.CGEvent())
            
            send_media_key(keytype)
            action_name = {"playpause": "播放/暂停", "play": "播放", "pause": "暂停", "next": "下一曲", "previous": "上一曲"}
            return f"{action_name.get(action, action)} 🎵"
        except ImportError:
            # Quartz 未安装，回退到 osascript 方式
            return ""
        except Exception as e:
            print(f"Media key error: {e}")
            return ""

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
