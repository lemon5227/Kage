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
    
    async def _generate_audio(self, text, emotion="neutral"):
        # Adjust parameters based on emotion
        # EdgeTTS supports rate (speed), pitch (tone), and volume
        rate = "+0%"
        pitch = "+0Hz"
        volume = "+0%"

        if emotion == "happy":
            rate = "+10%"   # Speak a bit faster
            pitch = "+20Hz" # Higher pitch
            volume = "+10%" # Louder
        elif emotion == "sad":
            rate = "-10%"   # Slower
            pitch = "-10Hz" # Lower pitch
            volume = "-20%" # Softer
        elif emotion == "angry":
            rate = "+20%"   # Fast
            pitch = "+0Hz"  # Normal pitch but aggressive
            volume = "+30%" # Very loud
        elif emotion == "fearful":
             rate = "+10%"
             pitch = "+30Hz" # Trembling high pitch
             volume = "-10%"

        # Construct SSML-like adjustment by passing options to communicate if supported, 
        # but standard edge_tts python lib is simpler. 
        # Actually edge_tts Communicate accepts `rate`, `volume`, `pitch` arguments directly in recent versions
        # Let's try passing them.
        
        communicate = edge_tts.Communicate(text, self.voice, rate=rate, volume=volume, pitch=pitch)
        await communicate.save(self.temp_audio_file)
    
    def _clean_text(self, text):
        # Whitelist: Chinese, English, Numbers, Basic Punctuation
        # Filter out emojis (like 😄, ✨) which sound weird in TTS
        cleaned = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s,。.?!，。？！:：;；"\'\-\(\)（）]', '', text)
        return cleaned

    def speak(self, text, emotion="neutral"):
        if not text:
            return 

        # due to main.py is sync, we need to run async function in sync way
        
        try:
            cleaned_text = self._clean_text(text)
            # print(f"(TTS Debug: {cleaned_text} [Emo:{emotion}])") 
            asyncio.run(self._generate_audio(cleaned_text, emotion))

        except Exception as e:
            print(f"Error generating audio:{e}")
            return
        
        # play logic
        try:
            pygame.mixer.music.load(self.temp_audio_file)
            pygame.mixer.music.play()

            # wait until the audio is played
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10) # check 10 times per second
            
            # Unload to release file lock
            pygame.mixer.music.unload()

            # Clean up
            if os.path.exists(self.temp_audio_file):
                os.remove(self.temp_audio_file)
        
        except Exception as e:
            print(f"Error playing audio:{e}")
        
