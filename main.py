import sys
import os
import time

# --- 1. Path Setup ---
# Ensure Python can find the 'core' directory
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, "core"))

# --- 2. Import Core Modules ---
from memory import MemorySystem
from brain import KageBrain
from mouth import KageMouth
from ears import KageEars
from tools import KageTools

def main():
    # --- Startup Display ---
    print("\n================================================")
    print("   👻 Project Kage (Shadow) - Phase 3: The Hands")
    print("================================================")
    print("⚙️  Initializing all systems...")
    
    # --- 3. Initialize Components ---
    try:
        # Initialize Memory (The Hippocampus - RAG)
        kage_memory = MemorySystem()
        
        # Initialize Brain (The LLM - Phi-3/4)
        kage_brain = KageBrain()
        
        # Initialize Mouth (TTS - Edge-TTS)
        kage_mouth = KageMouth(voice="zh-CN-XiaoyiNeural")
        
        # Initialize Ears (ASR - FunASR Paraformer)
        kage_ears = KageEars(model_id="paraformer-zh")
        
        # Initialize Tools (Function Calling capability)
        kage_tools = KageTools()

        # Initialize Router (shared model/tokenizer)
        from router import KageRouter
        kage_router = KageRouter(kage_brain.model, kage_brain.tokenizer)
        
    except Exception as e:
        print(f"❌ Initialization Failed: {e}")
        return

    print("\n------------------------------------------------")
    print(f"💬 {kage_brain.persona['name']} is fully awakened.")
    print("   (Speak directly to interact. Say 'exit' to quit.)")
    print("------------------------------------------------\n")

    # Welcome Message (text only, no voice)
    print("✨ Master，Kage 系统已就绪，随时待命！")
    print("💡 提示：直接输入文字，或按回车切换语音模式\n")

    # --- 4. Main Loop (The Agent Cycle) ---
    while True:
        try:
            # === A. Input (Text or Voice) ===
            print("[输入] (直接回车=语音): ", end="", flush=True)
            text_input = input().strip()
            
            voice_emotion = "neutral"
            
            if text_input:
                # 文字输入模式
                user_input = text_input
            else:
                # 语音输入模式
                listen_result = kage_ears.listen()
                
                if isinstance(listen_result, tuple):
                    user_input, voice_emotion = listen_result
                else:
                    user_input = listen_result
                    voice_emotion = "neutral"
            
            # Skip if input is empty or too short
            if not user_input or len(user_input) < 1:
                continue
                
            print(f"\n👤 Master: {user_input}")

            # Check for exit commands
            if "退出" in user_input or "再见" in user_input or "exit" in user_input.lower():
                bye_text = "收到！系统关闭中... 晚安，Master~ 💤"
                print(f"👻 Kage: {bye_text}")
                kage_mouth.speak(bye_text)
                break

            # === B. Router: Intent Classification ===
            # The Router generates only 1-2 tokens ("CHAT" or "COMMAND"), taking <100ms.
            # This tiny delay prevents the "Brain" from hallucinating commands during chat.
            intent = kage_router.classify(user_input)
            print(f"[意图判断]: {intent}") 

            # === C. Context Retrieval ===
            if voice_emotion and voice_emotion != "neutral":
                current_emotion = voice_emotion
            else:
                current_emotion = "angry" if ("!" in user_input or "生气" in user_input) else "neutral"
            print(f"[情绪: {current_emotion}]")
            
            final_output_for_speech = ""

            # === D. Branching Logic ===
            if intent == "CHAT":
                # --- CHAT MODE (Use Memory, No Action) ---
                # 1. Recall memories
                related_mems = kage_memory.recall(user_input, n_result=3)
                
                # 2. Think (Standard Chat)
                response_stream = kage_brain.think(
                    user_input, 
                    memories=related_mems, 
                    current_emotion=current_emotion,
                    mode="chat" 
                )
                
                print(f"👻 Kage: ", end="", flush=True)
                full_response_text = ""
                for chunk in response_stream:
                    if hasattr(chunk, 'text'): text_part = chunk.text
                    else: text_part = str(chunk)
                    print(text_part, end="", flush=True)
                    full_response_text += text_part
                print()
                
                final_output_for_speech = full_response_text
                
                # 3. Save to Memory (Only for CHAT, keeps DB clean)
                m_type = "important" if "记住" in user_input or "remember" in user_input.lower() else "chat"
                kage_memory.add_memory(content=user_input, emotion=current_emotion, type=m_type)

            elif intent == "COMMAND":
                # --- COMMAND MODE (No Chat Memory, Trigger Action) ---
                # 1. No Memory Recall (Prevent context pollution)
                
                # 2. Think (Action Mode)
                response_stream = kage_brain.think(
                    user_input, 
                    memories=[], 
                    current_emotion=current_emotion,
                    mode="action"
                )
                
                print(f"👻 Kage (Planning): ", end="", flush=True)
                full_response_text = ""
                for chunk in response_stream:
                    if hasattr(chunk, 'text'): text_part = chunk.text
                    else: text_part = str(chunk)
                    print(text_part, end="", flush=True)
                    full_response_text += text_part
                print()

                # 3. Action Logic
                final_output_for_speech = full_response_text 

                # Check for Action
                if ">>>ACTION:" in full_response_text or "open_app(" in full_response_text:
                    if ">>>ACTION:" in full_response_text:
                        raw_cmd = full_response_text.split(">>>ACTION:")[1].strip()
                    else:
                        raw_cmd = full_response_text

                    # Simple parser (same as before)
                    cmd_str = ""
                    valid_tools = ["open_app", "open_url", "get_time", "control_volume", "take_screenshot", "brew_install", "run_cmd", "create_file"]
                    for t in valid_tools:
                        if raw_cmd.startswith(t + "("):
                            start_idx = len(t) + 1
                            end_idx = raw_cmd.rfind(")")
                            if end_idx > start_idx:
                                cmd_str = raw_cmd[:end_idx+1]
                            break
                    
                    if cmd_str:
                        print(f"\n🦾 [执行命令] Kage 正在执行: {cmd_str}")
                        
                        # Execute
                        tool_result = kage_tools.execute(cmd_str)
                        print(f"🔧 [工具输出]: {tool_result[:300]}...") 

                        # Feedback Loop (Report Mode)
                        observation_input = f"""
【系统通知 (System Alert)】
这是工具运行后的最终结果汇报阶段。

用户指令: {user_input}
工具输出: {tool_result}

【你的任务】
请结合"用户指令"和"工具输出"，将结果汇报给 Master。
**注意**: 如果用户问的是谷歌，你就说谷歌；问的是推特，就说推特。不要搞混了！

【绝对禁止 (Forbidden)】
1. **禁止**再次输出 `>>>ACTION:`。
2. **禁止**提及无关信息。
3. **禁止**复述代码。

【正确示范】
用户指令: 查一下谷歌状态码
工具输出: 200...
Kage: 谷歌的状态码是 200，一切正常！
"""
                        print(f"👻 Kage (Result): ", end="", flush=True)
                        final_stream = kage_brain.think(
                            observation_input, 
                            memories=[], 
                            current_emotion=current_emotion,
                            temp=0.1,
                            mode="report" # CRITICAL: Report mode prevents loop
                        )
                        
                        final_explanation = ""
                        for chunk in final_stream:
                            if hasattr(chunk, 'text'): text_part = chunk.text
                            else: text_part = str(chunk)
                            print(text_part, end="", flush=True)
                            final_explanation += text_part
                        print()
                        
                        final_output_for_speech = final_explanation
                        
                        # Safety Clip
                        if ">>>ACTION:" in final_output_for_speech:
                             final_output_for_speech = final_output_for_speech.split(">>>ACTION:")[0].strip()

            # === E. Speak (Output) ===
            import re
            
            # Clean up Speech output
            speech_text = final_output_for_speech
            if ">>>ACTION:" in speech_text:
                 speech_text = speech_text.split(">>>ACTION:")[0].strip()
            
            speech_text = re.sub(r'\([^)]*\)', '', speech_text).strip()
            
            # Remove "Kage:" prefix
            kage_match = re.search(r'(?:^|\n| )Kage[:：]\s*(.*)', speech_text, flags=re.IGNORECASE | re.DOTALL)
            if kage_match:
                speech_text = kage_match.group(1).strip()
            else:
                 speech_text = re.sub(r'^Kage[:：]\s*', '', speech_text, flags=re.IGNORECASE).strip()
            
            # Safety Mute
            if "/bin/sh" in speech_text or "SyntaxError" in speech_text or "traceback" in speech_text.lower():
                 print("(TTS已静音: 检测到报错信息)")
            elif speech_text:
                kage_mouth.speak(speech_text)
            
        except KeyboardInterrupt:
            print("\n⚠️ 强制关闭 (Ctrl+C)。再见！")
            break
        except Exception as e:
            print(f"❌ Runtime Error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(1)

if __name__ == "__main__":
    main()