import json
from mlx_lm import generate
from mlx_lm.sample_utils import make_sampler

class KageRouter:
    def __init__(self, model, tokenizer):
        self.model = model
        self.tokenizer = tokenizer
        
    def classify(self, user_input: str) -> str:
        """
        Classify the user input as 'CHAT' or 'COMMAND'.
        CHAT: Casual conversation, questions, compliments, jokes.
        COMMAND: Requests to perform an action (open app, check website, check IP, calculate, screenshot).
        """
        
        # Fast, low-temp generation for classification
        prompt = f"""<|system|>
Classify the user input into exactly one category: [CHAT] or [COMMAND].

Rules:
- [COMMAND]: User asks to PERFORM an action (check status, open app, get IP, weather, create file).
- [CHAT]: User asks a question (knowledge), says hello, gives feedback ("Good job"), or chats.

Examples:
User: "Hello" -> [CHAT]
User: "Check Google status" -> [COMMAND]
User: "Open Safari" -> [COMMAND]
User: "Who are you?" -> [CHAT]
User: "My IP?" -> [COMMAND]
User: "Good job" -> [CHAT]
User: "Calculate 2+2" -> [COMMAND]
User: "Volume down" -> [COMMAND]
User: "Brightness up" -> [COMMAND]
User: "Make it louder" -> [COMMAND]
User: "北京天气" -> [COMMAND]
User: "今天天气怎么样" -> [COMMAND]
User: "查IP" -> [COMMAND]
User: "我的IP是多少" -> [COMMAND]
User: "屏幕太暗了" -> [COMMAND]
User: "屏幕太亮了" -> [COMMAND]
User: "声音大一点" -> [COMMAND]
User: "打开计算器" -> [COMMAND]
User: "现在几点" -> [COMMAND]
User: "现在什么时间" -> [COMMAND]
User: "几点了" -> [COMMAND]
User: "今天几号" -> [COMMAND]
User: "今天星期几" -> [COMMAND]
User: "静音" -> [COMMAND]
User: "小声一点" -> [COMMAND]
<|end|>
<|user|>
{user_input}
<|end|>
<|assistant|>
"""
        # Use very low temp for deterministic classification
        sampler = make_sampler(temp=0.0)
        
        response = generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=10, 
            verbose=False,
            sampler=sampler
        )
        
        result = response.strip().upper()
        
        # Fallback heuristic if model output is messy
        if "COMMAND" in result:
            return "COMMAND"
        return "CHAT"
