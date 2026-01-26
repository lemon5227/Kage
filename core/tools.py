import os
import subprocess
import datetime
import platform
import importlib.util
import glob
import sys
import json
import re
import ast
import time

class KageTools:
    # 常用应用中英文映射 (可扩展)
    APP_NAME_MAP = {
        # 计算器
        "计算器": "Calculator",
        "计算机": "Calculator",  # 口语常说 "计算机" 代表计算器
        # 系统工具
        "日历": "Calendar",
        "备忘录": "Notes",
        "提醒事项": "Reminders",
        "访达": "Finder",
        "文件管理": "Finder",
        "系统设置": "System Settings",
        "系统偏好设置": "System Preferences",
        "设置": "System Settings",
        "终端": "Terminal",
        "命令行": "Terminal",
        # 浏览器
        "浏览器": "Safari",
        "safari": "Safari",
        "Safari": "Safari",
        # 媒体
        "音乐": "Music",
        "照片": "Photos",
        "相册": "Photos",
        # 通讯
        "邮件": "Mail",
        "信息": "Messages",
        "短信": "Messages",
        "微信": "WeChat",
        # 其他
        "地图": "Maps",
        "天气": "Weather",
        "时钟": "Clock",
        "app store": "App Store",
        "应用商店": "App Store",
        "appstore": "App Store",
        "vscode": "Visual Studio Code",
        "vs code": "Visual Studio Code",
        "代码": "Visual Studio Code",
    }
    
    def __init__(self):
        self.os_type = platform.system()
        self.skills = {}
        self.skill_triggers = []
        self.cache = {}
        self.cache_ttl = 30
        self._load_skills()
        
        # Auto-Discovery: Scan for installed apps
        self.installed_apps = {} # { "lowercase_name": "Full App Name.app" }
        if self.os_type == "Darwin":
            self._scan_installed_apps()

    def _scan_installed_apps(self):
        """Scans /Applications and ~/Applications to build an app registry"""
        print("  🔍 Scanning for installed applications...")
        search_paths = ["/Applications", "/System/Applications", os.path.expanduser("~/Applications")]
        
        count = 0
        for path in search_paths:
            if not os.path.exists(path):
                continue
            try:
                # Only look at top-level apps to accept speed (depth=2 max)
                # Actually os.listdir is safer than walk for depth control
                for item in os.listdir(path):
                    if item.endswith(".app"):
                        app_name = item[:-4] # Remove .app
                        # Store multiple keys for better matching
                        # 1. Exact lower: "safari" -> "Safari.app"
                        self.installed_apps[app_name.lower()] = item
                        # 2. Chinese mapping (Manual + Common)
                        # TODO: Maybe read Info.plist for CFBundleDisplayName later
                        count += 1
            except Exception as e:
                print(f"  ❌ Error scanning {path}: {e}")
        
        # Manual Aliases (Hardcoded fixes for common apps)
        aliases = {
            "网易云": "NeteaseMusic",
            "网易云音乐": "NeteaseMusic", 
            "music": "Music",
            "音乐": "Music",
            "apple music": "Music",
            "chrome": "Google Chrome",
            "谷歌浏览器": "Google Chrome",
            "vscode": "Visual Studio Code",
            "code": "Visual Studio Code",
            "微信": "WeChat",
            "wechat": "WeChat",
            "qq": "QQ",
        }
        for alias, real_name in aliases.items():
            # Check if we have the real app found? Or just trust the alias?
            # Let's just map alias -> RealName.app (assuming the standard naming)
            # Find the real .app file from our scan if possible
            found_real = None
            for stored_key, stored_val in self.installed_apps.items():
                 if real_name.lower() in stored_val.lower():
                     found_real = stored_val
                     break
            
            if found_real:
                self.installed_apps[alias.lower()] = found_real
            else:
                 # Fallback: Just assume standard name
                 self.installed_apps[alias.lower()] = f"{real_name}.app"

        print(f"  ✅ Found {count} apps. Registry ready.")

    def _load_skills(self):
        """动态加载 skills 目录下的技能"""
        try:
            # Determine Project Root safely (Freeze-aware)
            if getattr(sys, 'frozen', False):
                 # dist/kage-server/skills
                 skills_dir = os.path.join(os.path.dirname(sys.executable), "skills")
            else:
                 # Standard Dev Path
                 skills_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
            
            if not os.path.exists(skills_dir):
                print(f"  ⚠️ Skills directory not found at: {skills_dir}")
                return

            for filename in os.listdir(skills_dir):
                if filename.endswith(".py") and not filename.startswith("__"):
                    try:
                        module_name = filename[:-3]
                        filepath = os.path.join(skills_dir, filename)
                        
                        spec = importlib.util.spec_from_file_location(module_name, filepath)
                        if spec and spec.loader:
                            module = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(module)
                            
                            if hasattr(module, "SKILL_INFO"):
                                skill_name = module.SKILL_INFO["name"]
                                self.skills[skill_name] = module
                                triggers = module.SKILL_INFO.get("triggers", [])
                                for trigger in triggers:
                                    if trigger:
                                        self.skill_triggers.append((trigger.lower(), skill_name))
                                print(f"  + 加载技能: {skill_name}")
                    except Exception as e:
                        print(f"  ❌ 加载技能 {filename} 失败: {e}")
        except Exception as e:
            print(f"  ❌ Error loading skills: {e}")

    def _find_skill_trigger(self, user_input: str):
        if not user_input:
            return None
        text = user_input.lower()
        for trigger, skill_name in self.skill_triggers:
            if trigger in text:
                return skill_name
        return None

    def _cache_key(self, name: str, arguments: dict):
        payload = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
        return f"{name}:{payload}"

    def _get_cache(self, key: str):
        if key not in self.cache:
            return None
        entry = self.cache[key]
        if time.time() - entry["timestamp"] > self.cache_ttl:
            del self.cache[key]
            return None
        return entry["value"]

    def _set_cache(self, key: str, value: str):
        self.cache[key] = {"timestamp": time.time(), "value": value}

    def _is_cacheable(self, name: str, arguments: dict):
        if name == "mcp_fs_list":
            return True
        if name == "run_cmd":
            command = str(arguments.get("command", ""))
            return "wttr.in" in command or "api.ipify.org" in command
        return False

    def execute_trigger(self, user_input: str):
        skill_name = self._find_skill_trigger(user_input)
        if not skill_name:
            return None
        skill = self.skills.get(skill_name)
        if not skill or not hasattr(skill, "execute"):
            return None
        return skill.execute(user_input)

    def parse_tool_calls(self, text: str):
        if not text:
            return []

        tool_call_pattern = r"<\|tool_call\|>\s*(\[.*?\])\s*<\|/tool_call\|>"
        match = re.search(tool_call_pattern, text, re.DOTALL)
        if match:
            content = match.group(1)
            parsed = self._parse_json_payload(content)
            return parsed if isinstance(parsed, list) else []

        stripped = text.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            parsed = self._parse_json_payload(stripped)
            return parsed if isinstance(parsed, list) else []

        fallback_match = re.search(r"(\[.*\])", text, re.DOTALL)
        if fallback_match:
            parsed = self._parse_json_payload(fallback_match.group(1))
            return parsed if isinstance(parsed, list) else []

        return []

    def _parse_json_payload(self, content: str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(content)
                return parsed
            except Exception:
                return None

    def execute_tool_call(self, name: str, arguments=None):
        if not name:
            return "❌ Tool name missing"

        normalized_args = self._normalize_arguments(arguments)

        if self._is_cacheable(name, normalized_args):
            cache_key = self._cache_key(name, normalized_args)
            cached = self._get_cache(cache_key)
            if cached is not None:
                return cached

        if name == "run_cmd":
            result = self.run_terminal_cmd(normalized_args.get("command", ""))
            if self._is_cacheable(name, normalized_args):
                self._set_cache(self._cache_key(name, normalized_args), result)
            return result

        if hasattr(self, name):
            method = getattr(self, name)
            try:
                if not normalized_args:
                    result = method()
                else:
                    result = method(**normalized_args)
                if self._is_cacheable(name, normalized_args):
                    self._set_cache(self._cache_key(name, normalized_args), result)
                return result
            except TypeError:
                return self.execute(self._format_command(name, normalized_args))

        if name in self.skills:
            skill = self.skills[name]
            params = self._skill_params_from_args(normalized_args)
            result = skill.execute(params)
            if self._is_cacheable(name, normalized_args):
                self._set_cache(self._cache_key(name, normalized_args), result)
            return result

        return f"❌ Unknown tool or command: {name}"

    def _normalize_arguments(self, arguments):
        if arguments is None:
            return {}
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str):
            arguments = arguments.strip()
            if not arguments:
                return {}
            try:
                parsed = json.loads(arguments)
                return parsed if isinstance(parsed, dict) else {"value": parsed}
            except json.JSONDecodeError:
                return {"value": arguments}
        return {"value": arguments}

    def _skill_params_from_args(self, arguments: dict):
        if not arguments:
            return ""
        if "params" in arguments:
            return arguments.get("params") or ""
        if len(arguments) == 1:
            return next(iter(arguments.values()))
        return json.dumps(arguments, ensure_ascii=False)

    def _format_command(self, name: str, arguments: dict):
        args = []
        for value in arguments.values():
            if isinstance(value, str):
                args.append(f'"{value}"')
            else:
                args.append(str(value))
        return f"{name}({', '.join(args)})"

    def open_app(self, app_name):
        print(f"正在尝试打开: {app_name}")
        
        # 1. Cleaning
        clean_name = app_name.strip().lower()
        
        # 2. Fuzzy / Registry Match
        target_app = app_name # Default to what user said
        
        # Direct lookup
        if clean_name in self.installed_apps:
            target_app = self.installed_apps[clean_name]
            # Strip .app for the 'open -a' command usually, but full path is safer if we knew it.
            # 'open -a "Full Name.app"' works.
            print(f"  -> Match found in registry: {target_app}")
        else:
            # Partial match (e.g. "网易" -> "NeteaseMusic")
            # This is risky but useful. Let's try simple inclusion.
            for key, val in self.installed_apps.items():
                if clean_name in key or key in clean_name:
                    # Don't match super short keys to avoid false positives
                    if len(key) > 2:
                        target_app = val
                        print(f"  -> Fuzzy match: {clean_name} ~= {val}")
                        break
        
        # Remove .app suffix for display goodness, but keep it for command if needed
        if target_app.endswith(".app"):
            run_name = target_app
        else:
            run_name = target_app

        try:
            if self.os_type == "Darwin":
                # Try 1: Registry Name
                result = subprocess.run(["open", "-a", run_name], capture_output=True, text=True)
                if result.returncode == 0:
                    return f"已打开 {target_app} ✨"
                
                # Try 2: Raw Name (maybe Spotlight finds it)
                if run_name != app_name:
                    result = subprocess.run(["open", "-a", app_name], capture_output=True, text=True)
                    if result.returncode == 0:
                        return f"已打开 {app_name} ✨"

                return f"找不到应用 '{app_name}' (尝试了 '{run_name}')。请确认它已安装在 /Applications 下。"
                
            elif self.os_type == "Windows":
                subprocess.run(["start", "", app_name], shell=True, check=True)
                return f"已打开 {app_name} ✨"
            else:
                return f"不支持的操作系统: {self.os_type}"
        except Exception as e:
            return f"打开 {app_name} 出错了: {e}"
    
    def open_url(self, url):
        """打开网页"""
        try:
            # 确保 URL 有协议前缀
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            
            if self.os_type == "Darwin":
                subprocess.run(["open", url], check=True)
            elif self.os_type == "Windows":
                subprocess.run(["start", url], shell=True, check=True)
            return f"已打开网页 {url} 🌐"
        except Exception as e:
            return f"打开网页失败: {e}"
    
    def get_time(self):
        now = datetime.datetime.now()
        return f"现在是 {now.strftime('%Y年%m月%d日 %H:%M:%S')} ⏰"
    
    # =========================================
    # 统一系统控制入口 (Unified System Control)
    # =========================================
    def system_control(self, target, action, value=None):
        """
        统一的系统控制入口。
        
        Args:
            target: 控制目标 - "volume", "brightness", "wifi", "bluetooth", "app"
            action: 动作 - "up", "down", "on", "off", "open", "close", "mute", "unmute"
            value: 可选值 - 具体数值或应用名称
        
        Examples:
            system_control("volume", "up")
            system_control("brightness", "down")
            system_control("wifi", "off")
            system_control("app", "open", "Safari")
        """
        target = target.lower().strip()
        action = action.lower().strip() if action else ""
        
        # 路由到具体实现
        if target == "volume" or target == "音量":
            return self._control_volume_internal(action)
        
        elif target == "brightness" or target == "亮度":
            return self._control_brightness_internal(action)
        
        elif target == "wifi" or target == "网络":
            return self._control_wifi_internal(action)
        
        elif target == "bluetooth" or target == "蓝牙":
            return self._control_bluetooth_internal(action)
        
        elif target == "app" or target == "应用":
            if action == "open" or action == "打开":
                return self.open_app(value) if value else "需要指定应用名称"
            elif action == "close" or action == "关闭":
                return self._close_app_internal(value) if value else "需要指定应用名称"
            else:
                return f"不支持的应用操作: {action}"
        
        else:
            return f"不支持的控制目标: {target}"
    
    # =========================================
    # 内部实现方法 (Internal Implementations)
    # =========================================
    def _control_volume_internal(self, action):
        """控制音量: up, down, mute"""
        try:
            if self.os_type == "Darwin":
                if action in ["up", "加大", "大"]:
                    script = '''
                    set curVolume to output volume of (get volume settings)
                    set newVolume to curVolume + 12
                    if newVolume > 100 then set newVolume to 100
                    set volume output volume newVolume
                    '''
                    subprocess.run(["osascript", "-e", script], check=True)
                    return "音量已调大 🔊"
                elif action in ["down", "减小", "小"]:
                    script = '''
                    set curVolume to output volume of (get volume settings)
                    set newVolume to curVolume - 12
                    if newVolume < 0 then set newVolume to 0
                    set volume output volume newVolume
                    '''
                    subprocess.run(["osascript", "-e", script], check=True)
                    return "音量已调小 🔉"
                elif action in ["mute", "muted", "静音"]:
                    subprocess.run(["osascript", "-e", "set volume with output muted"], check=True)
                    return "已静音 🔇"
                elif action in ["unmute", "取消静音"]:
                    subprocess.run(["osascript", "-e", "set volume without output muted"], check=True)
                    return "已取消静音 🔊"
                else:
                    return f"不认识的音量操作: {action}"
            return "此功能仅支持 Mac"
        except Exception as e:
            return f"音量控制失败: {e}"
    
    def _control_brightness_internal(self, action):
        """控制屏幕亮度: up, down (使用原生模拟按键)"""
        try:
            if self.os_type == "Darwin":
                # 使用 AppleScript 模拟亮度功能键
                # Key Code 144: Brightness Up
                # Key Code 145: Brightness Down
                
                repeat_times = 2
                
                if action == "up" or "大" in action or "高" in action:
                    script = f'tell application "System Events" to repeat {repeat_times} times\n key code 144\n end repeat'
                    msg = "亮度已调高 ☀️"
                elif action == "down" or "小" in action or "低" in action:
                    script = f'tell application "System Events" to repeat {repeat_times} times\n key code 145\n end repeat'
                    msg = "亮度已调低 🌙"
                else:
                    return f"不认识的亮度操作: {action}"
                
                subprocess.run(["osascript", "-e", script], check=True)
                return msg

            return "此功能仅支持 Mac"
        except Exception as e:
            return f"亮度控制失败: {e}"
    
    def _control_wifi_internal(self, action):
        """控制 WiFi: on, off"""
        try:
            if self.os_type == "Darwin":
                # 使用 networksetup 控制 WiFi
                # 注意: en0 是常见的 WiFi 接口名，但可能因机器而异
                if action == "on" or action == "开" or action == "打开":
                    subprocess.run(["networksetup", "-setairportpower", "en0", "on"], check=True)
                    return "WiFi 已开启 📶"
                elif action == "off" or action == "关" or action == "关闭":
                    subprocess.run(["networksetup", "-setairportpower", "en0", "off"], check=True)
                    return "WiFi 已关闭 📴"
                else:
                    return f"不认识的 WiFi 操作: {action}"
            return "此功能仅支持 Mac"
        except Exception as e:
            return f"WiFi 控制失败: {e}"
    
    def _control_bluetooth_internal(self, action):
        """控制蓝牙: on, off (需要 blueutil)"""
        try:
            if self.os_type == "Darwin":
                # 检查 blueutil 是否安装
                check = subprocess.run(["which", "blueutil"], capture_output=True)
                if check.returncode != 0:
                    return "蓝牙控制需要安装 blueutil (brew install blueutil) 🔧"
                
                if action == "on" or action == "开" or action == "打开":
                    subprocess.run(["blueutil", "-p", "1"], check=True)
                    return "蓝牙已开启 🔵"
                elif action == "off" or action == "关" or action == "关闭":
                    subprocess.run(["blueutil", "-p", "0"], check=True)
                    return "蓝牙已关闭 ⚫"
                else:
                    return f"不认识的蓝牙操作: {action}"
            return "此功能仅支持 Mac"
        except Exception as e:
            return f"蓝牙控制失败: {e}"
    
    def _close_app_internal(self, app_name):
        """关闭应用"""
        try:
            if self.os_type == "Darwin":
                script = f'tell application "{app_name}" to quit'
                subprocess.run(["osascript", "-e", script], check=True)
                return f"已关闭 {app_name} 👋"
            return "此功能仅支持 Mac"
        except Exception as e:
            return f"关闭应用失败: {e}"
    
    def take_screenshot(self):
        """截图保存到桌面"""
        try:
            if self.os_type == "Darwin":
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filepath = os.path.expanduser(f"~/Desktop/kage_screenshot_{timestamp}.png")
                subprocess.run(["screencapture", "-x", filepath], check=True)
                return f"截图已保存到桌面 📸"
            return "此功能仅支持 Mac"
        except Exception as e:
            return f"截图失败: {e}"
    
    def brew_install(self, app_name):
        """通过 Homebrew 安装软件"""
        try:
            if self.os_type == "Darwin":
                print(f"正在通过 Homebrew 安装: {app_name}")
                result = subprocess.run(
                    ["brew", "install", app_name], 
                    capture_output=True, 
                    text=True,
                    timeout=300  # 5分钟超时
                )
                if result.returncode == 0:
                    return f"已安装 {app_name} ✨"
                else:
                    if "already installed" in result.stderr:
                        return f"{app_name} 已经安装过了哦~"
                    return f"安装 {app_name} 失败..."
            return "此功能仅支持 Mac"
        except subprocess.TimeoutExpired:
            return f"安装 {app_name} 超时了..."
        except Exception as e:
            return f"安装出错: {e}"
    
    def run_terminal_cmd(self, cmd):
        """执行终端命令（⚠️ 危险操作，需谨慎）"""
        # HACK: 修复 LLM 常见幻觉
        if "wttr.ina" in cmd:
            cmd = cmd.replace("wttr.ina", "wttr.in")
        if "ipeps.com" in cmd or "ipequip.net" in cmd:
            if "curl" in cmd:
                # 简单替换为可靠的源
                import re
                cmd = re.sub(r'https?://[^\s"\']+', 'https://api.ipify.org', cmd)

        # 安全检查：禁止危险命令
        dangerous_patterns = ["rm -rf", "sudo rm", "mkfs", "dd if=", "> /dev/"]
        for pattern in dangerous_patterns:
            if pattern in cmd:
                return f"检测到危险命令，已拒绝执行 ⚠️"
        
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=False, # Disable auto-decoding to prevent crashes on binary data
                timeout=30
            )
            
            # Manually decode with error handling
            stdout_str = result.stdout.decode('utf-8', errors='replace').strip()
            stderr_str = result.stderr.decode('utf-8', errors='replace').strip()
            
            if result.returncode == 0:
                output = stdout_str[:500]  # LIMIT OUTPUT for TTS sake
                return f"命令执行成功 ✅\n{output}" if output else "命令执行成功 ✅"
            else:
                return f"命令执行失败: {stderr_str[:200]}"
        except subprocess.TimeoutExpired:
            return "命令执行超时..."
        except Exception as e:
            return f"执行出错: {e}"

    def create_file(self, filename, content):
        """创建脚本文件 (用于 Self-Programming/Ability)"""
        try:
            # Fix pathing: allow 'scripts/' or 'abilities/' or just filename
            
            if getattr(sys, 'frozen', False):
                 root_dir = os.path.dirname(sys.executable)
            else:
                 root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
            # Default to skills folder for reusable abilities
            target_dir = os.path.join(root_dir, "skills")
            target_filename = os.path.basename(filename)
            
            if "skills/" in filename or "scripts/" in filename:
                pass

            if not os.path.exists(target_dir):
                os.makedirs(target_dir)
            
            filepath = os.path.join(target_dir, target_filename)
            
            # Handle potential escaped newlines
            content = content.replace("\\n", "\n").replace('\\"', '"')
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
                
            return f"已创建技能: skills/{target_filename} 📝 (重启后即可使用)"
            
        except Exception as e:
            return f"创建脚本失败: {e}"

    def execute(self, cmd_str):
        """Unified Command Dispatcher - 支持多参数解析"""
        try:
            cmd_str = cmd_str.strip()
            
            # HACK: 修复常见 LLM 幻觉
            if "system_-control" in cmd_str:
                cmd_str = cmd_str.replace("system_-control", "system_control")
            if "open_apple" in cmd_str:
                cmd_str = cmd_str.replace("open_apple", "open_app")
            
            if "(" not in cmd_str or not cmd_str.endswith(")"):
                return f"❌ Command format error: {cmd_str}"
            
            func_name = cmd_str.split("(")[0].strip()
            args_str = cmd_str[len(func_name)+1:-1].strip()
            
            # 解析参数列表 (简单版本，处理逗号分隔的带引号参数)
            args = []
            if args_str:
                # 简单分割：按逗号分割，去除引号
                import re
                # 匹配 "xxx" 或 'xxx' 或无引号的参数
                pattern = r'"([^"]*)"|\'([^\']*)\'|([^,\s]+)'
                matches = re.findall(pattern, args_str)
                for m in matches:
                    # 取第一个非空的捕获组
                    arg = m[0] or m[1] or m[2]
                    if arg:
                        args.append(arg.strip())
            
            # --- 特殊处理 system_control ---
            if func_name == "system_control":
                if len(args) >= 2:
                    target = args[0]
                    action = args[1]
                    value = args[2] if len(args) > 2 else None
                    return self.system_control(target, action, value)
                else:
                    return "❌ system_control 需要至少 2 个参数: (target, action)"
            
            # --- Tier 1: Built-in Methods ---
            if hasattr(self, func_name):
                method = getattr(self, func_name)
                if not args:
                    return method()
                elif len(args) == 1:
                    return method(args[0])
                else:
                    return method(*args)
            
            # --- Tier 2: Mapped Aliases ---
            if func_name == "run_cmd":
                return self.run_terminal_cmd(args[0] if args else "")
                
            # --- Tier 3: Skills ---
            if func_name in self.skills:
                skill = self.skills[func_name]
                if hasattr(skill, "execute"):
                    return skill.execute(args[0] if args else "")
            
            return f"❌ Unknown tool or command: {func_name}"
            
        except Exception as e:
            return f"❌ Execution Exception: {e}"
            return f"❌ Execution Exception: {e}"
