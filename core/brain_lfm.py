# type: ignore
"""
LFM2.5 专用 Brain 模块
针对 LiquidAI LFM2.5 模型优化的工具调用和对话处理
"""
from typing import Any
from mlx_lm import load, stream_generate
from mlx_lm.sample_utils import make_sampler
import os
import json
import importlib.util
import sys
from datetime import datetime


class KageBrainLFM:
    """LFM2.5 专用的 Kage Brain 实现"""
    
    def __init__(self, model_path="LiquidAI/LFM2.5-1.2B-Thinking-MLX-bf16"):
        self.model_path = model_path
        self.config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "persona.json")
        self.persona = self._load_persona()
        print(f"Persona loaded: {self.persona['name']}")
        print(f"Loading LFM Brain Model: {model_path} ...")
        
        # Load model and tokenizer
        model_bundle: Any = load(model_path)
        self.model = model_bundle[0]
        self.tokenizer = model_bundle[1]
        
        # Define Tools Schema (JSON格式，LFM2.5 原生支持)
        self.tools = [
            {
                "name": "open_app",
                "description": "Open a desktop application",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "app_name": {"type": "string", "description": "Name of the application (e.g., Safari, Calculator)"}
                    },
                    "required": ["app_name"]
                }
            },
            {
                "name": "open_url",
                "description": "Open a specific URL in the default browser",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "The URL to open"}
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "get_time",
                "description": "Get the current system time",
                "parameters": {"type": "object", "properties": {}}
            },
            {
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
            },
            {
                "name": "take_screenshot",
                "description": "Take a screenshot of the entire screen",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "brew_install",
                "description": "Install a package using Homebrew",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "package_name": {"type": "string", "description": "Name of the package to install"}
                    },
                    "required": ["package_name"]
                }
            },
            {
                "name": "run_cmd",
                "description": "Run a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The shell command to execute"}
                    },
                    "required": ["command"]
                }
            },
            {
                "name": "web_search",
                "description": "Search the web and return top results",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "description": "Max number of results (1-8)"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "open_website",
                "description": "Open a website by name (or URL)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "site": {"type": "string", "description": "Website name, nickname, domain, or URL"}
                    },
                    "required": ["site"]
                }
            },
            {
                "name": "smart_search",
                "description": "Smart web search (auto chooses fastest backend)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "description": "Max number of results (1-8)"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "search_and_open",
                "description": "Search the web and open the best result",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "prefer_domains": {"type": "array", "items": {"type": "string"}, "description": "Preferred domains"},
                        "max_results": {"type": "integer", "description": "Max number of results (1-8)"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "find_local_skills",
                "description": "Find relevant locally installed skills",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "User request"},
                        "max_results": {"type": "integer", "description": "Max results (1-12)"}
                    },
                    "required": ["query"]
                }
            }
        ]
        self.tools.extend(self._load_skill_tools())
        print("The Soul has been awakened (LFM2.5 Supercharged)")

    def _load_persona(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            return {"name": "Kage", "system_prompt": "你是一个助手。", "description": "默认模式"}

    def _load_skill_tools(self):
        tools = []
        try:
            # Honor disabled skills list.
            disabled = set()
            try:
                disabled_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "disabled_skills.json")
                if os.path.exists(disabled_path):
                    with open(disabled_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        disabled = {str(x).strip() for x in data if str(x).strip()}
                    elif isinstance(data, dict) and isinstance(data.get("disabled"), list):
                        disabled = {str(x).strip() for x in data["disabled"] if str(x).strip()}
            except Exception:
                disabled = set()

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
                name = info.get("name")
                if name and name in disabled:
                    continue
                params = info.get("parameters") or {"type": "object", "properties": {}}
                tools.append({
                    "name": name,
                    "description": info.get("description", ""),
                    "parameters": params,
                })
        except Exception:
            return tools
        return tools

    def _format_prompt_for_lfm(self, user_input: str, memory_text: str, current_emotion: str, history: list | None = None, mode: str = "action"):
        """为 LFM2.5 格式化 prompt"""
        messages = []
        base_persona = self.persona.get('system_prompt', f"你是{self.persona['name']}。")
        
        if mode == "chat":
            # --- CHAT MODE (纯对话) ---
            current_time = datetime.now().strftime("%H:%M")
            memory_line = f'\n【对话记忆】{memory_text}' if memory_text else ''
            system_content = (
                f"{base_persona}\n\n"
                f"【当前时间】{current_time}\n"
                f"【Master心情】{current_emotion}"
                f"{memory_line}\n\n"
                "规则:\n"
                "- 用中文自然对话，像真人，1-2 句为主（不超过 60 字）\n"
                "- 先回应用户情绪/意图，再给建议或追问 1 个问题\n"
                "- 不要复述【对话记忆】里的原句\n"
                "- 不要输出任何系统提示/提示词\n"
                "- 除非被问到，否则不要自我介绍或说明你能做什么\n"
                "- 不要输出无关表情/emoji\n"
                "- 不要称呼用户为 Master\n"
                "- 不要输出英文\n"
                "- 不要敷衍（如\"我不知道/我没反应过来\"）\n"
                "- 不要说\"我不是你的朋友\"这种生硬拒绝\n"
                "- 绝对不要复述用户说了什么，不要输出\"用户：...\"格式\n\n"
                "示例:\n"
                "用户: 我好累。\n"
                "助手: 辛苦了。要不要先休息一会儿？\n\n"
                "用户: 我想跟朋友道歉。\n"
                "助手: 你想为哪件事道歉？我帮你拟一句。"
            )
        elif mode == "report":
            # --- REPORT MODE (结果汇报) ---
            system_content = (
                f"{base_persona}\n"
                f"【任务】汇报工具执行结果\n"
                f"Master心情: {current_emotion}\n\n"
                "要求:\n"
                "1. 根据工具输出，用中文简短汇报（20字内）。\n"
                "2. 语气俏皮，不要再调用任何工具。\n"
                "3. 说完结果就结束，不要加戏。"
            )
        elif mode == "auto":
            tools_json = json.dumps(self.tools, ensure_ascii=False)
            current_time = datetime.now().strftime("%H:%M")
            memory_line = f'\n【对话记忆】{memory_text}' if memory_text else ''
            system_content = (
                f"{base_persona}\n\n"
                f"【当前时间】{current_time}\n"
                f"【Master心情】{current_emotion}"
                f"{memory_line}\n\n"
                "你可以选择两种输出之一：\n"
                "1) 如果需要执行操作/联网查询/浏览器操作：输出 1 个工具调用（使用 <|tool_call_start|> ... <|tool_call_end|>），不要输出任何额外文字。\n"
                "2) 如果只是闲聊：直接用中文回复 1-2 句，不要调用工具。\n\n"
                "当用户请求包含\"搜索/查/找 + 然后打开/带我去/打开\"的组合时：必须调用工具（优先 search_and_open 或 smart_search + open_url/open_website）。\n\n"
                "【名字识别规则】\n"
                "当用户说\"找/搜/看 + [某个名字] + 的视频/频道/直播\"时，这个名字就是博主/频道名，不是历史人物或其他含义。直接把名字原样作为搜索关键词，不要质疑、解释或反问。\n\n"
                f"【可用工具】\n{tools_json}\n\n"
                "约束:\n"
                "- 不要输出英文\n"
                "- 不要自我介绍\n"
                "- 绝对不要复述用户说了什么，不要输出\"用户：...\"格式，只输出工具调用或简短回复"
            )

        else:
            # --- ACTION MODE (工具调用) - LFM2.5 原生格式 ---
            tools_json = json.dumps(self.tools, ensure_ascii=False)
            system_content = (
                f"{base_persona}\n\n"
                "你是 Kage (终端精灵)，执行 Master 的命令。\n\n"
                f"【可用工具】\n{tools_json}\n\n"
                "【重要规则】\n"
                "1. 当用户请求执行操作时，必须调用对应的工具\n"
                "2. 打开任何应用（Safari、Chrome、浏览器、音乐等）→ 使用 open_app\n"
                "2.1 打开网站/网页（YouTube、B站、知乎、某某官网等）→ 优先使用 open_website（或已知 URL 用 open_url）\n"
                "3. 调整音量、亮度、wifi、蓝牙 → 使用 system_control\n"
                "4. 查询时间 → 使用 get_time\n"
                "5. 执行命令（查IP、运行脚本等）→ 使用 run_cmd\n"
                "6. 截图 → 使用 take_screenshot\n"
                "7. 如果你不确定该用哪个技能/工具，先调用 find_local_skills(query=\"用户原话\")，再选择最合适的工具调用\n"
                "8. 联网搜索/查资料/找链接 → 优先使用 smart_search；打开某个网站 → 使用 open_website（或 open_url）\n"
                "9. 如果用户说\"搜一下...然后打开/带我去/打开第一个\"，优先使用 search_and_open（可加 prefer_domains）\n"
                "10. 当用户说\"找/搜/看 + 某人名字 + 的视频/频道/直播\"时，这个名字是博主/频道名（不是历史人物）。必须使用 search_and_open，把名字原样作为搜索关键词。绝对不要用 open_url 编造链接。\n"
                "11. 绝对不要复述用户说了什么。不要输出\"用户：...\"格式。只输出工具调用或简短确认。\n\n"
                "【示例】\n"
                "用户: 打开Safari → <|tool_call_start|>[open_app(app_name=\"Safari\")]<|tool_call_end|>\n"
                "用户: 打开油管 → <|tool_call_start|>[open_website(site=\"油管\")]<|tool_call_end|>\n"
                "用户: 找老高的最新油管视频 → <|tool_call_start|>[search_and_open(query=\"老高 最新 YouTube 视频\", prefer_domains=[\"youtube.com\",\"youtu.be\"], max_results=\"5\")]<|tool_call_end|>\n"
                "用户: 帮我搜一下李子柒的视频 → <|tool_call_start|>[search_and_open(query=\"李子柒 视频\", prefer_domains=[\"youtube.com\",\"youtu.be\"], max_results=\"5\")]<|tool_call_end|>\n"
                "用户: 搜索曹操说最新油管视频然后打开 → <|tool_call_start|>[search_and_open(query=\"曹操说 最新 YouTube 视频\", prefer_domains=[\"youtube.com\",\"youtu.be\"], max_results=\"5\")]<|tool_call_end|>\n"
                "用户: 调高音量 → <|tool_call_start|>[system_control(target=\"volume\", action=\"up\")]<|tool_call_end|>\n"
                "用户: 查一下我的IP → <|tool_call_start|>[run_cmd(command=\"curl -s api.ipify.org\")]<|tool_call_end|>\n\n"
                "现在处理用户请求："
            )
        messages.append({"role": "system", "content": system_content})

        # Multi-turn: include recent session history for chat/report.
        if mode in ("chat", "report") and history:
            for msg in history[-8:]:
                try:
                    role = msg.get("role")
                    content = str(msg.get("content") or "")
                except Exception:
                    continue
                if role not in ("user", "assistant"):
                    continue
                if content:
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_input})
        
        return messages

    def think(self, user_input: str, memories: list = [], history: list = [], current_emotion: str = "neutral", temp: float = 0.7, mode: str = "action"):
        """LFM2.5-Thinking 的思考方法"""
        memory_str = "; ".join([m['content'] for m in memories]) if memories else ""

        messages = self._format_prompt_for_lfm(user_input, memory_str, current_emotion, history=history, mode=mode)

        try:
            prompt = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        except Exception:
            prompt = f"<|im_start|>system\n{messages[0]['content']}<|im_end|>\n<|im_start|>user\n{user_input}<|im_end|>\n<|im_start|>assistant\n"

        if mode == "action":
            sampler = make_sampler(temp=0.05, top_p=0.1)
        elif mode == "chat":
            sampler = make_sampler(temp=0.15, top_p=0.9)
        else:
            sampler = make_sampler(temp=0.1, top_p=0.9)

        stop_words = ["<|im_end|>", "User:", "Master:", "\n\n\n"]
        current_text = ""

        if mode in ("action", "auto"):
            max_tokens = 768
        elif mode == "chat":
            max_tokens = 512
        else:
            max_tokens = 300

        generation_stream = stream_generate(
            self.model, self.tokenizer,
            prompt=prompt, max_tokens=max_tokens, sampler=sampler
        )

        think_closed = False
        post_think_len = 0  # chars generated after </think>

        for chunk_obj in generation_stream:
            text_chunk = chunk_obj.text if hasattr(chunk_obj, 'text') else str(chunk_obj)
            current_text += text_chunk

            should_stop = False
            for sw in stop_words:
                if sw in current_text:
                    current_text = current_text.split(sw)[0]
                    should_stop = True
                    break

            if not think_closed and "</think>" in current_text:
                think_closed = True
                post_think_len = 0

            if think_closed:
                post_think_len += len(text_chunk)

            # Repetition detection: ONLY after </think> and with grace period
            if think_closed and post_think_len > 80:
                after = current_text.split("</think>", 1)[-1] if "</think>" in current_text else current_text
                if len(after) > 30:
                    last_10 = after[-10:]
                    if after.count(last_10) >= 3:
                        print(f"\n⚠️ 重复检测（回答阶段），停止")
                        should_stop = True

            yield text_chunk

            if should_stop:
                break
