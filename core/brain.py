from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler
import os
import json

class kageBrain:
    def __init__(self, model_path="mlx-community/Phi-3.5-mini-instruct-4bit"):
        self.config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "persona.json")
        self.persona = self._load_persona()
        print(f"Persona loaded: {self.persona['name']}")
        self.model, self.tokenizer = load(model_path)
        print("The Soul has been awakened")

    def _load_persona(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            return {"name": "Kage", "system_prompt": "你是一个助手。", "description": "默认模式"}

    def _format_memory_text(self, memories):
        if not memories: return ""
        # 加上 "Master说:" 明确身份
        return "; ".join([f"Master说: {m['content']}" for m in memories])

    def _format_history_text(self, history):
        if not history: return ""
        return "\n".join(history)

    def _build_final_prompt(self, memory_text, history_text, current_emotion):
        # 1. Identity & Persona
        system = f"""You are {self.persona['name']}, {self.persona['description']}.
Your Master is the user. You love Master.
Style: Cute, Tsundere, use Emojis (✨, 😤, 💖), short reply (<30 words).
"""

        # 2. Context Construction (The "Stage")
        context = f"""
[Context Info]
- Mood: {current_emotion}
"""
        if memory_text:
            context += f"- Long-term Memories: {memory_text}\n"

        # 3. Dialogue History (The "Script")
        script = "[Dialogue History]\n"
        if history_text:
            script += history_text + "\n"
        
        # 4. CoT Instruction
        instruction = """
[Instruction]
1. Analyze the 'Dialogue History' and 'Context Info'.
2. If User asks about recent events, TRUST 'Dialogue History' 100%.
3. Think step-by-step inside <think> tag about what to say.
4. Output your final response after the tag.

Examples:
User: 我刚才说了什么
Kage: <think> History shows User said "I ate noodles". I should repeat that. </think> Master 刚才说吃了面条捏！🍜

User: 你好
Kage: <think> User is greeting. I should be happy. </think> 哇！Master 终于理我了！(开心) ✨
"""
        return system + context + script + instruction

    def think(self, user_input: str, memories: list = [], history: list = [], current_emotion: str = "neutral"):
        memory_str = self._format_memory_text(memories)
        history_str = self._format_history_text(history)
        system_prompt = self._build_final_prompt(memory_str, history_str, current_emotion)
        
        # Use simple format for Phi-3
        # System + User -> Assistant
        prompt = f"<|system|>\n{system_prompt}<|end|>\n<|user|>\n{user_input}<|end|>\n<|assistant|>\n"

        sampler = make_sampler(temp=0.7)
        
        response = generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=128, # Increased for <think> block
            verbose=False,
            sampler=sampler
        )
        
        # Post-processing: Extract content AFTER <think>...</think>
        # If no think tag, just use response
        final_response = response
        thought_content = ""
        
        if "</think>" in response:
            parts = response.split("</think>")
            thought_content = parts[0].replace("<think>", "").strip()
            final_response = parts[-1].strip()
        
        # Cleanup
        for stop in ["<|end|>", "<|user|>", "User:", "Master:"]:
            if stop in final_response:
                final_response = final_response.split(stop)[0]
        
        return final_response.strip(), thought_content
