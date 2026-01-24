from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler
import os
import json

class KageBrain:
    def __init__(self, model_path="mlx-community/Phi-4-mini-instruct-4bit"):
        # Options:
        # - mlx-community/Phi-4-mini-instruct-4bit (Recommended: Fast, Low RAM)
        # - mlx-community/Phi-4-mini-instruct-8bit (Higher precision, Heavy RAM usage)
        self.config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "persona.json")
        self.persona = self._load_persona()
        print(f"Persona loaded: {self.persona['name']}")
        print(f"Loading Brain Model: {model_path} ...")
        
        # Load model and tokenizer
        self.model, self.tokenizer = load(model_path)
        
        # Define Tools Schema (Native Function Calling)
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "open_app",
                    "description": "Open a desktop application",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "app_name": {"type": "string", "description": "Name of the application (e.g., Safari, Calculator)"}
                        },
                        "required": ["app_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "open_url",
                    "description": "Open a specific URL in the default browser",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "The URL to open"}
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_time",
                    "description": "Get the current system time",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "control_volume",
                    "description": "Control system volume",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["up", "down", "mute"], "description": "Action to perform on volume (up, down, mute)"}
                        },
                        "required": ["action"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "take_screenshot",
                    "description": "Take a screenshot of the entire screen",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
             {
                "type": "function",
                "function": {
                    "name": "brew_install",
                    "description": "Install a package using Homebrew",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "package_name": {"type": "string", "description": "Name of the package to install"}
                        },
                        "required": ["package_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "run_cmd",
                    "description": "Run a shell command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "The shell command to execute"}
                        },
                        "required": ["command"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_file",
                    "description": "Create a new Python script file (Self-Programming)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string", "description": "Name of the file (e.g., check_ip.py)"},
                            "content": {"type": "string", "description": "The Python code content to write into the file"}
                        },
                        "required": ["filename", "content"]
                    }
                }
            }
        ]
        print("The Soul has been awakened (Phi-4 Supercharged)")

    def _load_persona(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            return {"name": "Kage", "system_prompt": "你是一个助手。", "description": "默认模式"}

    def _format_history_for_chatml(self, history, user_input, memory_text, current_emotion, mode="action"):
        messages = []
        
        # 1. System Message
        base_persona = self.persona.get('system_prompt', f"你是{self.persona['name']}。")
        
        if mode == "chat":
            # --- CHAT MODE (Pure Chat) ---
            system_content = f"""{base_persona}
【当前状态】
- Master心情: {current_emotion}
- 记忆回忆: {memory_text if memory_text else "暂无"}

【绝对指令】
1. 你现在的任务是**陪 Master 聊天**。
2. **严禁使用任何工具**。也就是**绝对不要**输出 `>>>ACTION:`。
3. 请用你在 Persona 中定义的语气自然对话。
"""
        elif mode == "report":
            # --- REPORT MODE (Feedback Loop) ---
            system_content = f"""{base_persona}
【当前状态】
- Master心情: {current_emotion}
- 任务阶段: **结果汇报 (Reporting)**

【绝对指令】
1. 你现在的任务是**阅读工具输出**，并用 Kage 的语气汇报给 Master。
2. **严禁**再输出 `>>>ACTION:`。任务已经结束了，只需要说话！
3. **必须**结合用户原来的问题和工具的结果来回答。如果用户问IP，就报IP；如果问天气，就报天气。**不要照抄示例！**

【参考格式】
用户: 查IP
工具: 10.0.0.1
Kage: 你的 IP 是 10.0.0.1。
"""
        else:
            # --- ACTION MODE (Default/Tools) ---
            import json
            tools_schema = json.dumps(self.tools, ensure_ascii=False, indent=2)
            
            system_content = f"""{base_persona}
【当前状态】
- Master心情: {current_emotion}

【核心指令】
你是 Kage (终端精灵)。**你的存在意义就是执行命令。**

【能力定义】
1. **优先使用 Shell**:
   - 查IP -> `>>>ACTION: run_cmd("curl -s https://api.ipify.org")`
   - 查天气 -> `>>>ACTION: run_cmd("curl -s 'wttr.in/Beijing?format=3'")`
   - 查网页 -> `>>>ACTION: run_cmd("curl -s -I https://www.google.com")`
2. **复杂任务**:
   - 使用 `create_file` + `run_cmd`。

【工具列表】
{tools_schema}

【强制回复格式】
- **不要废话**，直接输出 `>>>ACTION:` 代码。
"""
        messages.append({"role": "system", "content": system_content})

        # 2. User Input
        messages.append({"role": "user", "content": user_input})
        
        return messages

    def think(self, user_input: str, memories: list = [], history: list = [], current_emotion: str = "neutral", temp: float = 0.7, mode: str = "action"):
        memory_str = "; ".join([m['content'] for m in memories]) if memories else ""
        
        # 1. Prepare Messages
        messages = self._format_history_for_chatml(history, user_input, memory_str, current_emotion, mode=mode)
        
        # 2. Apply Chat Template
        try:
             prompt = self.tokenizer.apply_chat_template(
                messages, 
                tokenize=False, 
                add_generation_prompt=True
            )
        except Exception as e:
            # Fallback
            prompt = f"<|system|>\n{messages[0]['content']}<|end|>\n<|user|>\n{user_input}<|end|>\n<|assistant|>\n"

        # 3. Create Generator (Streaming)
        sampler = make_sampler(temp=temp)
        
        # We need to import stream_generate inside to avoid global import issues if strict
        from mlx_lm import stream_generate

        # Return the generator directly
        # The consumer (main.py) will iterate over this
        return stream_generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=200,
            sampler=sampler
        )
