import os
import subprocess
import datetime
import platform
import importlib.util
import glob

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
        "vscode": "Visual Studio Code",
        "vs code": "Visual Studio Code",
        "代码": "Visual Studio Code",
    }
    
    def __init__(self):
        self.os_type = platform.system()
        self.skills = {}
        self._load_skills()
    
    def _load_skills(self):
        """加载 skills 目录下的所有技能"""
        skills_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")
        if not os.path.exists(skills_dir):
            return
        
        for skill_file in glob.glob(os.path.join(skills_dir, "*.py")):
            if os.path.basename(skill_file).startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location("skill", skill_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                if hasattr(module, "SKILL_INFO") and hasattr(module, "execute"):
                    skill_name = module.SKILL_INFO.get("name", os.path.basename(skill_file))
                    self.skills[skill_name] = {
                        "info": module.SKILL_INFO,
                        "execute": module.execute
                    }
                    print(f"  ✅ Skill 加载: {skill_name}")
            except Exception as e:
                print(f"  ❌ Skill 加载失败 ({skill_file}): {e}")
    
    def execute(self, command: str):
        """Execute a command and return the output"""
        try:
            if "open_app" in command:
                app_name = command.split('("')[1].split('")')[0]
                return self.open_app(app_name)
            elif "open_url" in command:
                url = command.split('("')[1].split('")')[0]
                return self.open_url(url)
            elif "get_time" in command:
                return self.get_time()
            elif "control_volume" in command:
                action = command.split('("')[1].split('")')[0]
                return self.control_volume(action)
            elif "take_screenshot" in command:
                return self.take_screenshot()
            elif "brew_install" in command:
                app = command.split('("')[1].split('")')[0]
                return self.brew_install(app)
            elif "run_cmd" in command:
                cmd = command.split('("')[1].split('")')[0]
                return self.run_terminal_cmd(cmd)
            elif "create_file" in command:
                # create_file("filename", "content")
                # Need to parse carefully as content might contain brackets/quotes
                # Simple extraction assuming the format is correct: create_file("name", "content")
                # This regex/split is fragile for complex code content, but let's try a best effort split
                try:
                    # Remove 'create_file(' prefix and trailing ')'
                    args_part = command[len("create_file("):-1]
                    # Split by first comma
                    parts = args_part.split(',', 1)
                    if len(parts) >= 2:
                        filename = parts[0].strip().strip('"').strip("'")
                        content = parts[1].strip()
                        # Content might be quoted with " or """ or '
                        if content.startswith('"""') and content.endswith('"""'):
                            content = content[3:-3]
                        elif content.startswith('"') and content.endswith('"'):
                            content = content[1:-1]
                        elif content.startswith("'") and content.endswith("'"):
                            content = content[1:-1]
                        
                        # Unescape basic things if needed (like \n)
                        # content = content.encode('utf-8').decode('unicode_escape') 
                        # actually Python string literal might already be handled if passed raw
                        
                        return self.create_file(filename, content)
                except Exception as e:
                    return f"解析 create_file 失败: {e}"

            elif "open_file" in command or "open_screenshot" in command:
                # 调用 open_file skill
                params = ""
                if '("' in command:
                    params = command.split('("')[1].split('")')[0]
                return self.call_skill("open_file", params)
            elif "skill" in command:
                # 通用 skill 调用: skill("skill_name", "params")
                parts = command.split('("')[1].split('")')[0]
                skill_name = parts.split('","')[0] if '","' in parts else parts
                params = parts.split('","')[1] if '","' in parts else ""
                return self.call_skill(skill_name, params)
            else:
                return "Kage 不知道怎么做这个哦~"
        except Exception as e:
            return f"出错了: {e}"
    
    def call_skill(self, skill_name: str, params: str) -> str:
        """调用已加载的 skill"""
        if skill_name in self.skills:
            try:
                return self.skills[skill_name]["execute"](params)
            except Exception as e:
                return f"Skill {skill_name} 执行失败: {e}"
        return f"找不到技能: {skill_name}"   

    def open_app(self, app_name):
        # 尝试将中文名转换为英文名
        english_name = self.APP_NAME_MAP.get(app_name, app_name)
        print(f"正在打开: {app_name} -> {english_name}")
        
        try:
            if self.os_type == "Darwin":
                result = subprocess.run(["open", "-a", english_name], capture_output=True, text=True)
                if result.returncode == 0:
                    return f"已打开 {app_name} ✨"
                else:
                    if "Unable to find application" in result.stderr:
                        return f"找不到 {app_name} 这个软件诶~ 你确定安装了吗？"
                    else:
                        return f"打开 {app_name} 失败了..."
            elif self.os_type == "Windows":
                subprocess.run(["start", "", english_name], shell=True, check=True)
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
    
    def control_volume(self, action):
        """控制音量: up, down, mute"""
        try:
            if self.os_type == "Darwin":
                if action == "up" or action == "加大" or action == "大":
                    subprocess.run(["osascript", "-e", "set volume output volume ((output volume of (get volume settings)) + 10)"], check=True)
                    return "音量已调大 🔊"
                elif action == "down" or action == "减小" or action == "小":
                    subprocess.run(["osascript", "-e", "set volume output volume ((output volume of (get volume settings)) - 10)"], check=True)
                    return "音量已调小 🔉"
                elif action == "mute" or action == "静音":
                    subprocess.run(["osascript", "-e", "set volume with output muted"], check=True)
                    return "已静音 🔇"
                elif action == "unmute" or action == "取消静音":
                    subprocess.run(["osascript", "-e", "set volume without output muted"], check=True)
                    return "已取消静音 🔊"
                else:
                    return f"不认识的音量操作: {action}"
            return "此功能仅支持 Mac"
        except Exception as e:
            return f"音量控制失败: {e}"
    
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
            # Base dir is the project root (where main.py is likely located, parent of core)
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
            # If filename contains a directory part like "abilities/foo.py", respect it if safe
            # Otherwise default to "abilities"
            
            target_dir = os.path.join(root_dir, "abilities") # Default folder
            target_filename = os.path.basename(filename)
            
            if "abilities/" in filename or "scripts/" in filename:
                # User specified a folder, let's try to verify but for now just use the basename to force into abilities
                # Actually user wants "ability" folder. Let's force everything into "abilities" for organization.
                pass

            if not os.path.exists(target_dir):
                os.makedirs(target_dir)
            
            filepath = os.path.join(target_dir, target_filename)
            
            # Handle potential escaped newlines
            content = content.replace("\\n", "\n").replace('\\"', '"')
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
                
            return f"已创建技能: abilities/{target_filename} 📝 (运行: run_cmd('python3 abilities/{target_filename}'))"
            
        except Exception as e:
            return f"创建脚本失败: {e}"