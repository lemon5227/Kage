import asyncio
import edge_tts
import pygame
import os
import re

class KageMouth:
    def __init__(self,voice="zh-CN-XiaoyiNeural"):
        # voice selection
        # zh-CN-XiaoyiNeural (可爱少女，适合机娘)
        # zh-CN-YunxiNeural (活泼少年)
        # zh-CN-XiaoxiaoNeural (温柔女性)
        self.voice = voice
        self.temp_audio_file="temp_kage_speech.mp3"

        # init speaker
        pygame.mixer.init()
    
    async def generate_speech_file(self, text, emotion="neutral"):
        """Generates audio file and returns the path. Does NOT play it."""
        if not text: return None
        
        try:
            cleaned_text = self._clean_text(text)
            
            # Parameters logic (Rate/Pitch/Volume)
            rate = "+0%"
            pitch = "+0Hz"
            volume = "+0%"
    
            if emotion == "happy":
                rate = "+10%"; pitch = "+20Hz"; volume = "+10%"
            elif emotion == "sad":
                rate = "-10%"; pitch = "-10Hz"; volume = "-20%"
            elif emotion == "angry":
                rate = "+20%"; pitch = "+0Hz"; volume = "+30%"
            elif emotion == "fearful":
                 rate = "+10%"; pitch = "+30Hz"; volume = "-10%"
    
            communicate = edge_tts.Communicate(cleaned_text, self.voice, rate=rate, volume=volume, pitch=pitch)
            await communicate.save(self.temp_audio_file)
            return self.temp_audio_file
            
        except Exception as e:
            print(f"Error generating audio: {e}")
            return None

    def play_audio_file(self, file_path):
        """Plays the given audio file (Blocking)"""
        if not file_path or not os.path.exists(file_path): return

        try:
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
            
            pygame.mixer.music.unload()
            
            # Clean up immediately? Or later? 
            # Safe to clean up here as we are blocking.
            try:
                os.remove(file_path)
            except: pass
            
        except Exception as e:
            print(f"Error playing audio: {e}")
    
    def _clean_text(self, text):
        # 1. Replace symbols for better pronunciation
        text = text.replace("°C", "摄氏度").replace("℃", "摄氏度")
        text = text.replace("°", "度")
        
        # 2. Whitelist: Chinese, English, Numbers, Basic Punctuation
        # Filter out emojis (like 😄, ✨) which sound weird in TTS
        # But wait, sometimes we want to keep text structure.
        # Let's just remove specific emoji ranges or non-text content.
        cleaned = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s,。.?!，。？！:：;；"\'\-\(\)（）摄氏度]', '', text)
        
        # 3. Remove repetitive characters (like 🌡️🌡️🌡️ or .......)
        # Collapse 3 or more repeated chars to 1
        cleaned = re.sub(r'(.)\1{2,}', r'\1', cleaned)
        
        # 4. Strictly limit ANY repeated sequence at the end of the string (Emoji spam killer)
        # If the last 5 chars contain repeated chars, chop them
        if len(cleaned) > 20 and cleaned[-1] == cleaned[-2]:
            cleaned = cleaned.rstrip(cleaned[-1]) + cleaned[-1] # Keep only one
            
        return cleaned

    # Legacy wrapper
    def speak(self, text, emotion="neutral"):
        path = asyncio.run(self.generate_speech_file(text, emotion))
        if path:
            self.play_audio_file(path)
