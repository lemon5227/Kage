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
                    "name": "system_control",
                    "description": "Unified system control - control volume, brightness, wifi, bluetooth, and apps",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string", "enum": ["volume", "brightness", "wifi", "bluetooth", "app"], "description": "What to control"},
                            "action": {"type": "string", "enum": ["up", "down", "on", "off", "open", "close", "mute", "unmute"], "description": "Action to perform"},
                            "value": {"type": "string", "description": "Optional value (e.g., app name for app control)"}
                        },
                        "required": ["target", "action"]
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
4. **必须只用中文回复**，绝对禁止输出英文、法语或其他外语！
5. 回复简短（30字以内），不要啰嗦。
"""
        elif mode == "report":
            # --- REPORT MODE (Feedback Loop) ---
            system_content = f"""{base_persona}
【任务】汇报工具执行结果
Master心情: {current_emotion}

要求:
1. 根据工具输出，用中文简短汇报（20字内）。
2. 语气俏皮，严禁输出 >>>ACTION:。
3. 严禁使用 hashtag (#) 或无意义的英文后缀。
4. 说完结果就结束，不要加戏。

开始汇报：
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
1. **系统控制 (统一入口)**:
   - 调音量 → `>>>ACTION: system_control("volume", "up")` 或 `system_control("volume", "down")`
   - 小声一点 → `>>>ACTION: system_control("volume", "down")`
   - 静音 → `>>>ACTION: system_control("volume", "mute")`
   - 调亮度 → `>>>ACTION: system_control("brightness", "up")` 或 `system_control("brightness", "down")`
   - 亮一点 → `>>>ACTION: system_control("brightness", "up")`
   - 暗一点 → `>>>ACTION: system_control("brightness", "down")`
   - WiFi → `>>>ACTION: system_control("wifi", "on")` 或 `system_control("wifi", "off")`
   - 打开应用 → `>>>ACTION: system_control("app", "open", "Safari")`
   - 关闭应用 → `>>>ACTION: system_control("app", "close", "Safari")`

2. **Shell 命令**:
   - 查IP → `>>>ACTION: run_cmd("curl -s https://api.ipify.org")`
   - 查天气 → `>>>ACTION: run_cmd("curl -s 'wttr.in/Beijing?format=3'")`
   - 查网页状态 → `>>>ACTION: run_cmd("curl -s -I https://www.google.com | head -n 1")`
   - 查时间 → `>>>ACTION: get_time()`

3. **其他**:
   - 静音 → `>>>ACTION: system_control("volume", "mute")`
   - 打开备忘录 → `>>>ACTION: open_app("Notes")`
   - 打开音乐 → `>>>ACTION: open_app("Music")`
    - 打开邮件 → `>>>ACTION: open_app("Mail")`
    - 关闭Safari → `>>>ACTION: system_control("app", "close", "Safari")`
    - 关闭计算器 → `>>>ACTION: system_control("app", "close", "Calculator")`
    - 打开谷歌浏览器 → `>>>ACTION: open_app("Google Chrome")`

【注意】
- 查IP 必须用 `run_cmd("curl -s https://api.ipify.org")`，不要用其他 API！
- 查天气时，必须使用 `wttr.in` 域名 (绝对不要用 wttr.ina)！根据用户说的城市动态替换，如"深圳天气" → `run_cmd("curl -s 'wttr.in/Shenzhen?format=3'")`

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
