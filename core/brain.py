# type: ignore
from typing import Any
from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler
import os
import json
import importlib.util
import sys

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
        model_bundle: Any = load(model_path)  # type: ignore[assignment]
        self.model = model_bundle[0]
        self.tokenizer = model_bundle[1]
        
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
        self.tools.extend(self._load_skill_tools())
        print("The Soul has been awakened (Phi-4 Supercharged)")

    def _load_persona(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            return {"name": "Kage", "system_prompt": "你是一个助手。", "description": "默认模式"}


    def _load_skill_tools(self):
        tools = []
        try:
            if getattr(sys, 'frozen', False):
                skills_dir = os.path.join(os.path.dirname(sys.executable), "skills")
            else:
                skills_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")

            if not os.path.exists(skills_dir):
                return tools

            for filename in os.listdir(skills_dir):
                if not filename.endswith(".py") or filename.startswith("__"):
                    continue
                filepath = os.path.join(skills_dir, filename)
                module_name = f"skill_{filename[:-3]}"
                spec = importlib.util.spec_from_file_location(module_name, filepath)
                if not spec or not spec.loader:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if not hasattr(module, "SKILL_INFO"):
                    continue
                info = module.SKILL_INFO
                params = info.get("parameters") or {"type": "object", "properties": {}}
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": info.get("name"),
                            "description": info.get("description", ""),
                            "parameters": params,
                        },
                    }
                )
        except Exception:
            return tools
        return tools

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
            tool_list_simple = []
            for tool in self.tools:
                if tool.get("type") == "function":
                    func = tool.get("function", {})
                    tool_list_simple.append({
                        "name": func.get("name"),
                        "description": func.get("description", ""),
                        "parameters": func.get("parameters", {}),
                    })
                else:
                    tool_list_simple.append(tool)
            tools_tag = f"<|tool|>{json.dumps(tool_list_simple, ensure_ascii=False)}<|/tool|>"
            
            system_content = f"""{base_persona}
【当前状态】
- Master心情: {current_emotion}

【核心指令】
你是 Kage (终端精灵)。**你的存在意义就是执行命令。**

【能力定义】
1. **系统控制 (统一入口)**:
   - 调音量 → `>>>ACTION: system_control("volume", "up")`
   - 调亮度 → `>>>ACTION: system_control("brightness", "up")`
   - 打开应用 → `>>>ACTION: system_control("app", "open", "Safari")`

2. **Shell 命令**:
   - 查IP → `>>>ACTION: run_cmd("curl -s https://api.ipify.org")`
   - 查天气 → `>>>ACTION: run_cmd("curl -s 'wttr.in/Beijing?format=3'")`
   - 查时间 → `>>>ACTION: get_time()`

【注意】
- 查IP 只用 `api.ipify.org`；查天气只用 `wttr.in/<城市>?format=3`

【工具列表】
{tools_schema}

{tools_tag}

【强制回复格式】
- 优先输出 `<|tool_call|>[{{"name": "tool_name", "arguments": {{"param": "value"}}}}]<|/tool_call|>`
- 如果无法输出 tool_call，则回退 `>>>ACTION: tool_name("param")`
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
            prompt = f"<|system|>\n{messages[0]['content']}<|end|>\n<|user|>\n{user_input}<|end|>\n<|assistant|>\n"

        # 3. Create Generator (Streaming)
        if mode == "chat":
            temp = min(temp, 0.5)
        sampler = make_sampler(temp=temp)
        from mlx_lm import stream_generate

        # 4. Manual Stop Logic (Prevents Hallucination)
        stop_words = ["User:", "Tool Result:", "Master:", "\n\n\n"]
        current_text = ""
        
        max_tokens = 120 if mode == "action" else 220
        generation_stream = stream_generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            sampler=sampler
        )

        for chunk_obj in generation_stream:
            # Extract text from chunk
            text_chunk = chunk_obj.text if hasattr(chunk_obj, 'text') else str(chunk_obj)
            current_text += text_chunk
            
            # Check for stop words
            should_stop = False
            for sw in stop_words:
                if sw in current_text:
                    # Truncate and stop
                    # Remove the stop word part
                    current_text = current_text.split(sw)[0]
                    should_stop = True
                    break
            
            # Yield the chunk (or cleaned part)
            yield text_chunk 
            
            if should_stop:
                break
