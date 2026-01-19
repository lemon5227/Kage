from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler
import os
import json

class kageBrain:
    def __init__(self, model_path="mlx-community/Phi-3.5-mini-instruct-8bit"):
        self.config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "persona.json")
        self.persona = self._load_persona()
        print(f"Persona loaded: {self.persona['name']}")
        print(f"Loading Brain Model: {model_path} ...")
        self.model, self.tokenizer = load(model_path)
        print("The Soul has been awakened")

    def _load_persona(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            return {"name": "Kage", "system_prompt": "你是一个助手。", "description": "默认模式"}

    def _format_history_text(self, history):
        # Format history clearly as a dialogue script
        if not history: return ""
        return "\n".join(history)

    def _build_final_prompt(self, user_input, memory_text, history_text, current_emotion):
        # Clean and direct Prompt Engineering for Phi-3
        
        # 1. System Instruction
        system_content = f"""You are {self.persona['name']}, {self.persona['description']}.
Your Master is the user.
Current Mood: {current_emotion}.
Style: Short (<30 words), Cute, use Emojis.
Important: If User asks "what did I just say", you MUST check the history and repeat it.
"""
        if memory_text:
             system_content += f"\nRelevant Memories:\n{memory_text}"

        # 2. Build the messages list for apply_chat_template (if available) or manual formatting
        # Manual formatting is safer for control 
        
        prompt = f"<|system|>\n{system_content}<|end|>\n"
        
        # 3. Inject History (The most critical part for continuity)
        if history_text:
             # Assuming history is a list of strings like "User: ..." or "Kage: ..."
             # We need to parse it back or just append it as context.
             # Better approach: Append history lines cleanly
             prompt += f"{history_text}\n"

        # 4. Current Turn
        prompt += f"<|user|>\n{user_input}<|end|>\n<|assistant|>\n"
        
        return prompt

    def think(self, user_input: str, memories: list = [], history: list = [], current_emotion: str = "neutral"):
        memory_str = "; ".join([m['content'] for m in memories]) if memories else ""
        history_str = self._format_history_text(history)
        
        # Build prompt
        prompt = self._build_final_prompt(user_input, memory_str, history_str, current_emotion)
        
        # Debug Prompt to see what the brain actually sees
        # print("--- DEBUG PROMPT ---")
        # print(prompt)
        # print("--------------------")

        sampler = make_sampler(temp=0.7)
        
        response = generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=100, 
            verbose=False,
            sampler=sampler
        )
        
        # Clean up response: Remove <|end|>, <|assistant|>, etc.
        # Sometimes small models in loop generate multiple turns. We only want the first one.
        final_response = response.strip()
        
        for stop_token in ["<|end|>", "<|assistant|>", "<|user|>"]:
            if stop_token in final_response:
                 final_response = final_response.split(stop_token)[0].strip()

        return final_response, "" # No think content for now to ensure stability
