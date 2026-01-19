from core.brain import kageBrain
from core.memory import MemorySystem
from core.mouth import KageMouth
from core.ears import KageEars 

def main():
    print("\n================================================")
    print("   👻 Project Kage (影) - Phase 1: Text Core")
    print("================================================")
    
    kage_memory = MemorySystem()
    kage_brain = kageBrain()
    kage_mouth = KageMouth()
    # Initialize Ears (Lazy load happens inside class usually, but here we init explicitly)
    kage_ears = KageEars(model_id="paraformer-zh")

    print("\n------------------------------------------------")
    print(f"💬 {kage_brain.persona['name']} 已上线。")
    print("   (输入 'exit' 退出，直接回车进入语音模式)")
    print("------------------------------------------------\n")

    history = [] # Short-term memory buffer

    while True:
        try:
            print("\n[Typing] (Press Enter to Speak): ", end="", flush=True)
            user_input = input().strip()
            
            # Voice Mode Trigger
            if not user_input:
                user_input_tuple = kage_ears.listen()
                
                # Check for empty result
                if not user_input_tuple or user_input_tuple == ("", None):
                     continue
                
                # Unpack
                if isinstance(user_input_tuple, tuple):
                    user_input, voice_emotion = user_input_tuple
                else:
                    user_input = user_input_tuple # fallback
                    voice_emotion = "neutral"

                print(f"\nUser (Voice): {user_input} [Emotion: {voice_emotion}]")
                
            else:
                # Text input mode: default emotion is neutral (or inferred from text symbols)
                voice_emotion = None

            if user_input.lower() in ['exit', 'quit', '退出']:
                break
            if not user_input:
                continue

            # Determine Emotion
            # If we have voice emotion (and it's not neutral/unknown), use it. 
            # Otherwise fall back to text heuristic.
            if voice_emotion and voice_emotion != "neutral" and voice_emotion != "other":
                current_emotion = voice_emotion
            else:
                 current_emotion = "angry" if "!" in user_input or "！" in user_input else "neutral"
            related_memories = kage_memory.recall(user_input)
            
            # Debug info
            if related_memories:
                print(f"(RAG Memory: {len(related_memories)})")
            
            # Pass history to brain
            # DEBUG: Print history
            # print(f"DEBUG History: {history}")
            # Pass history to brain
            response, thought = kage_brain.think(user_input, related_memories, history, current_emotion)
            
            # Show "Mind Reading" (The Chain of Thought)
            if thought:
                print(f"\n🧠 Kage's Thought: \033[90m{thought}\033[0m")
            
            print(f"\n{kage_brain.persona['name']} ({current_emotion}): {response}\n")
            
            # Speak!
            kage_mouth.speak(response, current_emotion)

            # Update History (Keep last 10 lines)
            # Update History (Keep last 10 lines)
            # Use strict turn markers to help Brain understand history
            history.append(f"<|user|>\n{user_input}<|end|>")
            history.append(f"<|assistant|>\n{response}<|end|>")
            if len(history) > 10:
                history = history[-10:]

            # Bilateral Memory: Record both user input and Kage's response
            kage_memory.add_memory(content=user_input, emotion=current_emotion, type="chat")
            kage_memory.add_memory(content=f"Kage回复: {response}", emotion="generated", type="reply")
            
        except KeyboardInterrupt:
            print("\nBye!")
            break
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
