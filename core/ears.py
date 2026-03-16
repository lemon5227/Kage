import pyaudio
import wave
import audioop
import os
import numpy as np
from funasr import AutoModel
# Suppress heavy logging from FunASR/ModelScope
import logging
logging.getLogger('modelscope').setLevel(logging.CRITICAL)

# Vosk for lightweight wake word detection
try:
    from vosk import Model as VoskModel, KaldiRecognizer
    import json as vosk_json
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False
    print("⚠️ Vosk not installed, wake word detection disabled")

class KageEars:
    def __init__(self, model_id="paraformer-zh"):
        print("Loading FunASR model (Paraformer)... please wait")
        # Initialize FunASR AutoModel
        # We use the standard paraformer model for Chinese
        self.model = AutoModel(
            model="paraformer-zh",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            # spk_model="cam++" # speaker verification not needed yet
        )
        print("FunASR (ASR) model loaded!")

        print("Loading FunASR (Emotion) model... please wait")
        self.emotion_model = AutoModel(
            model="emotion2vec_plus_large",
            disable_update=True
        )
        print("FunASR (Emotion) model loaded!")

        # audio setting
        self.chunk=1024
        self.format=pyaudio.paInt16
        self.channels=1
        self.rate=16000
        self.temp_audio_file="temp_kage_listening.wav"

        # parameters for listening threshold
        # 阈值调高可减少环境噪音干扰 (默认 500，建议 1000-1500)
        self.THRESHOLD=1200
        self.SILENCE_DURATION=1.5 # stop recording after silence
        
        # Wake Word Detection (using Vosk English model)
        self.wakeword_enabled = VOSK_AVAILABLE
        # Vosk 常把 "kage" 识别为各种近似词，所以用宽松匹配
        # 精确关键词列表（子串匹配）
        self.wakeword_keywords = [
            "hey kage", "kage", "hey cage", "cage",
            "hey kaj", "kaj", "hey cadge", "cadge",
            "hey page", "hey gage", "gage",
            "hey kate", "hey case",
            "k age", "hey k",
        ]
        # 模糊匹配核心音素：只要文本中包含类似 "kage/cage/kaj" 的音就算命中
        self._wakeword_fuzzy_cores = ["kag", "cag", "kaj", "cadg", "gag", "kej", "kag"]
        self.vosk_model = None
        if self.wakeword_enabled:
            try:
                print("Loading Vosk model for wake word...")
                # 使用英文小模型，更准确识别 "Hey Kage"
                vosk_model_path = os.path.expanduser("~/.vosk/vosk-model-small-en-us-0.15")
                if os.path.exists(vosk_model_path):
                    self.vosk_model = VoskModel(vosk_model_path)
                else:
                    # 尝试下载模型
                    print("ℹ️ Vosk model not found. Please download:")
                    print("ℹ️ https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip")
                    print("ℹ️ Extract to: ~/.vosk/vosk-model-small-en-us-0.15")
                    self.wakeword_enabled = False
                if self.vosk_model:
                    print("✅ Vosk loaded! Say 'Hey Kage' to wake up.")
            except Exception as e:
                print(f"❌ Failed to load Vosk: {e}")
                self.wakeword_enabled = False
    
    def _parse_emotion(self, emo_res):
        """
        Parse raw emotion output from emotion2vec
        Example input:
        [{'key': '...', 'labels': ['生气/angry', '开心/happy', ...], 'scores': [0.001, 0.999, ...]}]
        """
        try:
            if not emo_res or not isinstance(emo_res, list):
                return "neutral"
            
            data = emo_res[0]
            if 'scores' not in data or 'labels' not in data:
                return "neutral"
            
            scores = data['scores']
            labels = data['labels']
            
            # Find index of max score
            max_score = -1
            max_index = -1
            
            for i, score in enumerate(scores):
                if score > max_score:
                    max_score = score
                    max_index = i
            
            if max_index != -1:
                raw_label = labels[max_index] # e.g. "开心/happy"
                # Extract English part
                if "/" in raw_label:
                    label = raw_label.split("/")[-1] # "happy"
                else:
                    label = raw_label
                
                # Map specific labels to Kage's known emotions if needed
                # <unk> -> neutral
                if "<unk>" in label: 
                    return "neutral"
                    
                return label.lower()
                
            return "neutral"
        except Exception as e:
            print(f"Error parsing emotion: {e}")
            return "neutral"
    
    def _match_wakeword(self, text: str) -> bool:
        """Check if text contains a wake word using both exact keywords and fuzzy phoneme matching."""
        t = text.lower().strip()
        if not t:
            return False
        # 1. Exact keyword substring match
        for keyword in self.wakeword_keywords:
            if keyword in t:
                return True
        # 2. Fuzzy phoneme core match — catches Vosk misrecognitions
        # Remove spaces for phoneme matching (e.g. "k age" -> "kage")
        t_nospace = t.replace(" ", "")
        for core in self._wakeword_fuzzy_cores:
            if core in t_nospace:
                return True
        return False

    def wait_for_wakeword(self, timeout_sec: float = 300) -> bool:
        """
        使用 Vosk 低功耗等待唤醒词。
        返回 True 表示检测到唤醒词，False 表示超时或唤醒词功能未启用。
        """
        if not self.wakeword_enabled or not self.vosk_model:
            # 唤醒词未启用，直接返回 True 跳过等待
            return True
        
        print("\n💤 Kage is sleeping... Say 'Hey Kage' to wake up!")
        
        p = pyaudio.PyAudio()
        CHUNK_SIZE = 4000  # 250ms at 16kHz
        
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=CHUNK_SIZE
        )
        
        # 创建 Vosk 识别器
        recognizer = KaldiRecognizer(self.vosk_model, 16000)
        
        chunks_per_second = 16000 / CHUNK_SIZE
        max_chunks = int(timeout_sec * chunks_per_second)
        chunk_count = 0
        
        detected = False
        
        try:
            while chunk_count < max_chunks:
                audio_data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                
                # Vosk 实时识别
                if recognizer.AcceptWaveform(audio_data):
                    result = vosk_json.loads(recognizer.Result())
                    text = result.get("text", "").lower()
                    
                    # DEBUG: 打印识别结果
                    if text:
                        print(f"\n[Vosk] Heard: '{text}'")
                    
                    # 检查是否包含唤醒词
                    if self._match_wakeword(text):
                        print(f"\n🎯 Wake word detected in '{text}'")
                        detected = True
                
                # 也检查部分结果（更快响应）
                partial = vosk_json.loads(recognizer.PartialResult())
                partial_text = partial.get("partial", "").lower()
                
                # DEBUG: 打印部分结果
                if partial_text and len(partial_text) > 2:
                    print(f"\r[Vosk] Partial: '{partial_text}'", end="", flush=True)
                
                if self._match_wakeword(partial_text):
                    print(f"\n🎯 Wake word detected in partial: '{partial_text}'")
                    detected = True
                
                if detected:
                    break
                    
                chunk_count += 1
                
                # 每 10 秒打印一次状态
                if chunk_count % (int(chunks_per_second) * 10) == 0:
                    print(".", end="", flush=True)
                    
        except KeyboardInterrupt:
            print("\n⚠️ Wake word detection interrupted")
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
        
        return detected

    def listen(self):
        # auto stop when long time no sound
        p = pyaudio.PyAudio() # boot up audio driver
        stream = p.open(format=self.format,
                        channels=self.channels,
                        rate=self.rate,
                        input=True,
                        frames_per_buffer=self.chunk)
        
        frames = []
        silence_chunks = 0 # the chunks of silence
        has_started =False # whether we have started recording

        print("\n👂 Kage is listening... (Speak)")

        chunks_per_second = self.rate / self.chunk
        max_silence_chunks = int(self.SILENCE_DURATION * chunks_per_second)

        while True:
            try:
                data = stream.read(self.chunk, exception_on_overflow=False)
                frames.append(data)

                # caculate volume
                rms = audioop.rms(data, 2) 
                
                # simple visualization
                bar = " " * int(rms / 100)
                if rms > self.THRESHOLD:
                     print(f"\rVolume: {rms} {bar}", end="")

                # core logic
                if rms > self.THRESHOLD:
                    # voice enough to start
                    has_started = True
                    silence_chunks = 0
                else:
                    # voice too low
                    if has_started:
                        silence_chunks+=1
                
                # if silence too long, stop recording
                if has_started and silence_chunks > max_silence_chunks:
                    print("\n stop recording")
                    break
                # Only wait 5 seconds max if not started, or 30s if started
                if not has_started and len(frames) > chunks_per_second * 10:
                     print("\n time out (no voice detected)")
                     break
                
                if len(frames) > chunks_per_second * 60:
                     print("\n time out (too long)")
                     break
            
            except KeyboardInterrupt:
                break
        
        # clean resource
        stream.stop_stream()
        stream.close()
        p.terminate()

        if not frames or not has_started:
            return ""
        
        # save files
        wf = wave.open(self.temp_audio_file,'wb')
        wf.setnchannels(self.channels)
        wf.setsampwidth(p.get_sample_size(self.format))
        wf.setframerate(self.rate)
        wf.writeframes(b''.join(frames))
        wf.close()

        # transcribe using FunASR
        print("Transcribing...")
        try:
            # FunASR inference
            res = self.model.generate(input=self.temp_audio_file)
            # Result format: [{'key': 'wav_name', 'text': '你好'}]
            if res and isinstance(res, list) and 'text' in res[0]:
                full_text = res[0]['text']
                
                # Emotion Recognition
                print("Detecting emotion...")
                emo_res = self.emotion_model.generate(
                    input=self.temp_audio_file,
                    output_dir=None,
                    granularity="utterance"
                )
                
                # emo_res structure depends on version, usually: [{'key': '...', 'scores': [...], 'labels': ['happy', ...]}]
                # But for emotion2vec_plus_large, it might return raw feats or label
                # Let's simplify assuming standard FunASR emotion output or just return text if complex
                
                # Parse emotion
                if emo_res and isinstance(emo_res, list):
                    detected_emotion = self._parse_emotion(emo_res)
                    print(f"[Emotion Detected]: {detected_emotion}")
                
                print(f"You said: {full_text}")
                
                # Clean up temp file
                # Clean up temp file
                if os.path.exists(self.temp_audio_file):
                    os.remove(self.temp_audio_file)

                # Return tuple (text, emotion_label)
                # emotion_label is now a simple string, e.g., "happy", "angry"
                return full_text.strip(), detected_emotion
                
            # Clean up temp file
            if os.path.exists(self.temp_audio_file):
                os.remove(self.temp_audio_file)
                
            return "", None
        except Exception as e:
            print(f"Error transcribing: {e}")
            # Clean up temp file even if an error occurred
            if os.path.exists(self.temp_audio_file):
                os.remove(self.temp_audio_file)
            return "", None

    def detect_voice_activity(self, timeout_sec: float = 0.25, consecutive_chunks: int = 2) -> bool:
        """Lightweight VAD-style probe used for barge-in detection.

        It does not transcribe or persist audio. It only checks whether speech
        activity above the configured threshold appears within a short window.
        """
        p = pyaudio.PyAudio()
        stream = p.open(
            format=self.format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.chunk,
        )

        chunks_per_second = max(1, int(self.rate / self.chunk))
        max_chunks = max(1, int(timeout_sec * chunks_per_second))
        hits = 0

        try:
            for _ in range(max_chunks):
                data = stream.read(self.chunk, exception_on_overflow=False)
                rms = audioop.rms(data, 2)
                if rms > self.THRESHOLD:
                    hits += 1
                    if hits >= max(1, int(consecutive_chunks)):
                        return True
                else:
                    hits = 0
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()

        return False


