import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, "core"))

from brain import kageBrain
from memory import MemorySystem 

def main():
    print("\n================================================")
    print("   👻 Project Kage (影) - Phase 1: Text Core")
    print("================================================")
    
    kage_memory = MemorySystem()
    kage_brain = kageBrain()

    print("\n------------------------------------------------")
    print(f"💬 {kage_brain.persona['name']} 已上线。")
    print("   (输入 'exit' 退出)")
    print("------------------------------------------------\n")

    history = [] # Short-term memory buffer

    while True:
        try:
            user_input = input("User: ").strip()
            if user_input.lower() in ['exit', 'quit', '推出']:
                break
            if not user_input:
                continue

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
            
            print(f"\n{kage_brain.persona['name']}: {response}\n")

            # Update History (Keep last 10 lines)
            history.append(f"User: {user_input}")
            history.append(f"Kage: {response}")
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
