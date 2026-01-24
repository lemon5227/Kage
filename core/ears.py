import pyaudio
import wave
import audioop
import os
from funasr import AutoModel
# Suppress heavy logging from FunASR/ModelScope
import logging
logging.getLogger('modelscope').setLevel(logging.CRITICAL)

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
        # parameters for listening threshold
        self.THRESHOLD=500
        self.SILENCE_DURATION=1.5 # stop recording after silence
    
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



