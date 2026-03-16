"""
Kage System Tray Module (macOS 优化版)
使用 rumps 库实现原生 macOS 菜单栏图标
"""
import os
import sys
import webbrowser
import json

def _get_base_path():
    """获取基础路径 (支持 PyInstaller 打包)"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _load_settings():
    """加载设置"""
    settings_path = os.path.join(_get_base_path(), "config", "settings.json")
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save_settings(settings):
    """保存设置"""
    settings_path = os.path.join(_get_base_path(), "config", "settings.json")
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


class KageTray:
    def __init__(self, on_quit=None, on_toggle_window=None, on_toggle_voice=None):
        self.on_quit = on_quit
        self.on_toggle_window = on_toggle_window
        self.on_toggle_voice = on_toggle_voice
        self.settings = _load_settings()
        self._voice_enabled = True
        self.app = None
        
    def _get_icon_path(self):
        """获取托盘图标路径"""
        return os.path.join(_get_base_path(), "assets", "tray_icon.png")
    
    def run(self):
        """运行托盘 (阻塞)"""
        import rumps
        
        # 创建菜单项
        version = self.settings.get("version", "1.0.0")
        
        # 模型子菜单
        available_models = self.settings.get("model", {}).get("available_models", [])
        current_model = self.settings.get("model", {}).get("path", "")
        model_menu = rumps.MenuItem("切换模型")
        for model in available_models:
            model_name = model.split("/")[-1]
            item = rumps.MenuItem(model_name, callback=lambda sender, m=model: self._switch_model(m))
            if model == current_model:
                item.state = 1  # 勾选当前模型
            model_menu.add(item)
        
        # Live2D 子菜单
        live2d_menu = rumps.MenuItem("Live2D 角色")
        live2d_menu.add(rumps.MenuItem("Booth 模型商店", callback=lambda _: webbrowser.open("https://booth.pm/zh-cn/search/Live2D")))
        live2d_menu.add(rumps.MenuItem("Live2D 官方示例", callback=lambda _: webbrowser.open("https://www.live2d.com/en/download/sample-data/")))
        live2d_menu.add(rumps.separator)
        live2d_menu.add(rumps.MenuItem("导入本地模型...", callback=lambda _: self._import_live2d()))
        
        # 创建应用
        self.app = rumps.App(
            "Kage",
            icon=self._get_icon_path(),
            template=True,  # 关键：使用模板模式，图标会自动适应浅色/深色菜单栏
            menu=[
                rumps.MenuItem(f"👻 Kage v{version}", callback=None),
                rumps.separator,
                rumps.MenuItem("显示/隐藏窗口", callback=lambda _: self._toggle_window()),
                rumps.MenuItem("🎤 语音开关", callback=lambda _: self._toggle_voice()),
                rumps.separator,
                model_menu,
                live2d_menu,
                rumps.separator,
                rumps.MenuItem("打开设置文件", callback=lambda _: self._open_settings()),
                rumps.MenuItem("查看日志", callback=lambda _: self._open_logs()),
                rumps.separator,
                rumps.MenuItem("退出 Kage", callback=lambda _: self._quit()),
            ]
        )
        self.app.run()
    
    def _toggle_window(self):
        """切换窗口显示"""
        if self.on_toggle_window:
            self.on_toggle_window()
    
    def _toggle_voice(self):
        """切换语音"""
        self._voice_enabled = not self._voice_enabled
        if self.on_toggle_voice:
            self.on_toggle_voice(self._voice_enabled)
        import rumps
        rumps.notification("Kage", "", "语音已开启" if self._voice_enabled else "语音已关闭")
    
    def _switch_model(self, model_path):
        """切换 LLM 模型"""
        self.settings["model"]["path"] = model_path
        _save_settings(self.settings)
        import rumps
        rumps.notification("Kage", "模型切换", f"已切换为 {model_path.split('/')[-1]}，重启后生效")
    
    def _import_live2d(self):
        """导入本地 Live2D 模型"""
        models_dir = os.path.join(_get_base_path(), self.settings.get("live2d", {}).get("models_dir", "kage-avatar"))
        webbrowser.open(f"file://{models_dir}")
    
    def _open_settings(self):
        """打开设置文件"""
        settings_path = os.path.join(_get_base_path(), "config", "settings.json")
        webbrowser.open(f"file://{settings_path}")
    
    def _open_logs(self):
        """打开日志目录"""
        log_dir = os.path.join(_get_base_path(), "logs")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        webbrowser.open(f"file://{log_dir}")
    
    def _quit(self):
        """退出程序"""
        if self.on_quit:
            self.on_quit()
        import rumps
        rumps.quit_application()
    
    def stop(self):
        """停止托盘"""
        import rumps
        rumps.quit_application()


# 测试代码
if __name__ == "__main__":
    def on_quit():
        print("Quit requested")
        sys.exit(0)
    
    tray = KageTray(on_quit=on_quit)
    print("🎯 托盘已启动")
    tray.run()
