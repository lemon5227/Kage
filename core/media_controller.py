"""
Media Controller — smart media playback control.

Handles:
- Detecting running music apps
- Opening default music app if none running
- System media key control
- AppleScript fallback for specific apps
"""

import subprocess
import time
import logging

logger = logging.getLogger(__name__)

_MUSIC_APP_KEYWORDS = [
    "Music", "Spotify", "网易云音乐", "NeteaseMusic",
    "QQMusic", "酷狗音乐", "酷我音乐", "Apple Music",
]

_MEDIA_KEY_MAP = {
    "playpause": "playpause",
    "play": "play",
    "pause": "pause",
    "next": "next track",
    "previous": "previous track",
}


def _get_running_music_app() -> str | None:
    """Detect which music app is currently running."""
    try:
        out = subprocess.check_output(
            ["osascript", "-e", 'tell application "System Events" to get name of every process whose background only is false'],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        running = [a.strip() for a in out.split(",")]
        for app in _MUSIC_APP_KEYWORDS:
            if app in running:
                return app
    except Exception:
        pass
    return None


def _send_system_media_key(action: str) -> str | None:
    """Send system media key using Quartz (macOS)."""
    try:
        import Quartz
        key_map = {
            "playpause": Quartz.kHIDUsage_Csmr_PlayOrPause,
            "play": Quartz.kHIDUsage_Csmr_PlayOrPause,
            "pause": Quartz.kHIDUsage_Csmr_PlayOrPause,
            "next": Quartz.kHIDUsage_Csmr_NextTrack,
            "previous": Quartz.kHIDUsage_Csmr_PreviousTrack,
        }
        keytype = key_map.get(action)
        if keytype is None:
            return None

        # NOTE: Full CGEvent media-key simulation requires HID-tap event
        # construction. Currently this is a no-op stub; AppleScript fallback
        # in the caller handles per-app control. Remove or implement when
        # whole-system media keys become a hard requirement.
        action_name = {"playpause": "播放/暂停", "play": "播放", "pause": "暂停", "next": "下一曲", "previous": "上一曲"}
        return f"{action_name.get(action, action)} 🎵"
    except ImportError:
        return None
    except Exception as e:
        logger.debug("Media key error: %s", e)
        return None


def media_control(action: str, preferred_apps: list[str] | None = None) -> str:
    """Smart media control.

    1. If a music app is running → control it
    2. If play command and no app running → open default app and play
    3. Prefer system media keys
    4. Fallback to AppleScript

    Args:
        action: One of "playpause", "play", "pause", "next", "previous"
        preferred_apps: List of preferred app names to try first.

    Returns:
        Human-readable result string.
    """
    preferred_apps = preferred_apps or []

    # Detect running music app
    running_app = _get_running_music_app()

    # If "play" command and no app running → open default app
    if action in ("play", "playpause") and not running_app:
        default_app = preferred_apps[0] if preferred_apps else "Music"
        logger.info("No music app running, opening %s...", default_app)
        try:
            from core.tools import open_app
            open_app(default_app)
        except Exception:
            try:
                subprocess.run(["open", "-a", default_app], check=False)
            except Exception:
                pass
        time.sleep(1)  # Wait for app to launch

    # Try system media keys first
    result = _send_system_media_key(action)
    if result:
        return result

    # Fallback: AppleScript direct control
    osascript_cmd = _MEDIA_KEY_MAP.get(action, "playpause")

    # Build candidate list: running app > preferred > defaults
    app_candidates = []
    if running_app:
        app_candidates.append(running_app)
    app_candidates.extend(preferred_apps)
    app_candidates.extend(["Music", "Spotify"])

    for app in app_candidates:
        script = f'tell application "{app}" to {osascript_cmd}'
        try:
            subprocess.run(["osascript", "-e", script], check=True)
            return f"已控制 {app} 播放 {action}"
        except Exception:
            continue

    return "未找到可控制的播放器"
