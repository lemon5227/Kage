# pyright: reportMissingImports=false
"""
Kage 统一配置管理模块
集中管理所有配置，避免硬编码
"""
import os
from dataclasses import dataclass, field
from typing import Any, List
import json


@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = "127.0.0.1"
    port: int = 12345
    websocket_path: str = "/ws"
    api_prefix: str = "/api"
    log_level: str = "warning"
    
    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"
    
    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}{self.websocket_path}"


@dataclass
class ModelConfig:
    """模型配置"""
    default_model: str = "Qwen/Qwen3-4B-GGUF"
    available_models: List[str] = field(default_factory=lambda: [
        "Qwen/Qwen3-4B-GGUF",
        "Qwen/Qwen3-8B-GGUF",
    ])
    temperature: float = 0.7
    max_tokens: int = 120
    top_p: float = 0.9
    
    
@dataclass
class VoiceConfig:
    """语音配置"""
    tts_enabled: bool = True
    tts_voice: str = "zh-CN-XiaoyiNeural"
    available_voices: List[str] = field(default_factory=lambda: [
        "zh-CN-XiaoyiNeural",
        "zh-CN-XiaoxiaoNeural",
        "zh-CN-YunxiNeural",
    ])
    speed: float = 1.0
    volume: float = 1.0
    
    
@dataclass
class WakeWordConfig:
    """唤醒词配置"""
    enabled: bool = True
    keyword: str = "kage"
    sensitivity: str = "medium"  # low, medium, high
    timeout_seconds: int = 300


@dataclass
class AudioConfig:
    """音频配置"""
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024
    threshold: int = 1200  # 语音检测阈值
    silence_timeout: float = 2.0  # 静音检测超时（秒）
    

@dataclass
class WindowConfig:
    """窗口配置"""
    width: int = 350
    height: int = 550
    always_on_top: bool = True
    transparent: bool = True
    decorations: bool = False
    resizable: bool = False
    shadow: bool = False
    

@dataclass
class Live2DConfig:
    """Live2D配置"""
    model_path: str = "./models/haru/haru_greeter_t03.model3.json"
    scale: float = 0.13
    x_offset: int = -50
    y_offset: int = -20
    motion_cooldown_ms: int = 4000
    expression_neutral: str = "f05"


class Config:
    """全局配置单例"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # 从环境变量读取配置
        self.server = ServerConfig(
            host=os.getenv("KAGE_HOST", "127.0.0.1"),
            port=int(os.getenv("KAGE_PORT", "12345")),
        )
        
        self.model = ModelConfig()
        self.voice = VoiceConfig()
        self.wakeword = WakeWordConfig()
        self.audio = AudioConfig()
        self.window = WindowConfig()
        self.live2d = Live2DConfig()
        
        # 从配置文件加载（如果存在）
        self._load_from_file()
        
        self._initialized = True
    
    def _load_from_file(self):
        """从配置文件加载覆盖"""
        config_paths = [
            "config/settings.json",
            os.path.expanduser("~/.kage/config.json"),
        ]
        
        for path in config_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self._apply_config(data)
                        print(f"✅ Loaded config from {path}")
                        break
                except Exception as e:
                    print(f"⚠️ Failed to load config from {path}: {e}")
    
    def _apply_config(self, data: dict):
        """应用配置数据"""
        if "server" in data:
            self.server.port = data["server"].get("port", self.server.port)
        
        if "model" in data:
            self.model.default_model = data["model"].get("path", self.model.default_model)
            self.model.temperature = data["model"].get("temperature", self.model.temperature)
            self.model.max_tokens = data["model"].get("max_tokens", self.model.max_tokens)
        
        if "voice" in data:
            self.voice.tts_voice = data["voice"].get("tts_voice", self.voice.tts_voice)
            self.voice.speed = data["voice"].get("speed", self.voice.speed)
            self.voice.volume = data["voice"].get("volume", self.voice.volume)
        
        if "wakeword" in data:
            self.wakeword.enabled = data["wakeword"].get("enabled", self.wakeword.enabled)
            self.wakeword.sensitivity = data["wakeword"].get("sensitivity", self.wakeword.sensitivity)


def _get_nested_val(data: dict, key: str) -> Any:
    """Look up key in dict, supporting dotted paths and searching common sections."""
    if not isinstance(data, dict):
        return None
    if key in data and data[key] is not None:
        return data[key]
    if "." in key:
        cur = data
        parts = key.split(".")
        for part in parts:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur is not None:
            return cur
    for section in ("tools", "model", "voice", "server", "wakeword", "window", "live2d", "advanced"):
        sec_dict = data.get(section)
        if isinstance(sec_dict, dict) and key in sec_dict and sec_dict[key] is not None:
            return sec_dict[key]
    return None


def get_config(key: str, default: Any = None) -> Any:
    """Retrieve config value by key, checking env vars, user config, and repository settings.
    
    Resolution order:
    1. Environment variable: KAGE_<KEY> or <KEY> (upper-cased, '.' replaced by '_')
    2. ~/.kage/config.json or config/settings.json
       - Direct dotted path: e.g. 'tools.tavily_api_key'
       - Flat key in top-level: e.g. 'tavily_api_key'
       - Common section search: e.g. tools.tavily_api_key
    3. default value
    """
    key_clean = str(key or "").strip()
    if not key_clean:
        return default

    # 1. Environment variables
    env_candidates = []
    env_suffix = key_clean.replace(".", "_").upper()
    env_candidates.extend([f"KAGE_{env_suffix}", env_suffix])
    if "." in key_clean:
        last_seg = key_clean.split(".")[-1].upper()
        env_candidates.extend([f"KAGE_{last_seg}", last_seg])
    for env_var in env_candidates:
        val = os.environ.get(env_var)
        if val is not None and val != "":
            return val

    # 2. File-based settings
    candidate_paths = [
        os.path.expanduser("~/.kage/config.json"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "settings.json"),
        "config/settings.json",
    ]
    for p in candidate_paths:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
                    val = _get_nested_val(cfg_data, key_clean)
                    if val is not None and val != "":
                        return val
            except Exception:
                continue

    return default


# 全局配置实例
config = Config()

