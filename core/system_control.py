"""core.system_control

System control backend for Kage.

Goal: provide a unified, structured API for common system actions while keeping
the implementation pragmatic on macOS.

Notes:
- This module does not implement any confirmation logic. The caller (ToolExecutor)
  owns safety gating.
- Best-effort: on failure, return actionable guidance instead of crashing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import shutil
import time
from dataclasses import dataclass


def _env_truthy(name: str) -> bool:
    v = str(os.environ.get(name, "")).strip().lower()
    return v in ("1", "true", "yes", "on")


def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(1, min(120, int(timeout))),
        )
        return int(proc.returncode), proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as exc:
        return 1, "", str(exc)


def _osascript(script: str, timeout: int = 15) -> tuple[int, str, str]:
    return _run(["osascript", "-e", script], timeout=timeout)


def _shortcuts_run(name: str, timeout: int = 30) -> tuple[int, str, str]:
    n = str(name or "").strip()
    if not n:
        return 2, "", "empty shortcut name"
    return _run(["shortcuts", "run", n], timeout=timeout)


_SHORTCUTS_CACHE: dict[str, object] = {
    "ts": 0.0,
    "names": set(),
    "available": None,  # None|bool
}


def _shortcuts_list(timeout: int = 10) -> tuple[int, str, str]:
    return _run(["shortcuts", "list"], timeout=timeout)


def _has_shortcut(name: str) -> bool:
    n = str(name or "").strip()
    if not n:
        return False

    now = time.monotonic()
    ts = float(_SHORTCUTS_CACHE.get("ts") or 0.0)
    available = _SHORTCUTS_CACHE.get("available")
    names = _SHORTCUTS_CACHE.get("names")
    if not isinstance(names, set):
        names = set()
        _SHORTCUTS_CACHE["names"] = names

    # Refresh every 60 seconds.
    if available is None or (now - ts) > 60:
        code, out, _err = _shortcuts_list(timeout=10)
        if code != 0:
            _SHORTCUTS_CACHE["available"] = False
            _SHORTCUTS_CACHE["names"] = set()
            _SHORTCUTS_CACHE["ts"] = now
            return False
        listed = {line.strip() for line in (out or "").splitlines() if line.strip()}
        _SHORTCUTS_CACHE["available"] = True
        _SHORTCUTS_CACHE["names"] = listed
        _SHORTCUTS_CACHE["ts"] = now
        names = listed

    if available is False:
        return False
    return n in names


def _detect_wifi_device() -> str | None:
    # Parse: networksetup -listallhardwareports
    code, out, _err = _run(["networksetup", "-listallhardwareports"], timeout=10)
    if code != 0:
        return None
    lines = (out or "").splitlines()
    # Match block:
    # Hardware Port: Wi-Fi
    # Device: en0
    current_port = ""
    for line in lines:
        line = line.strip()
        m = re.match(r"^Hardware Port:\s*(.+)$", line)
        if m:
            current_port = m.group(1).strip().lower()
            continue
        m = re.match(r"^Device:\s*(\S+)$", line)
        if m and current_port in ("wi-fi", "wifi"):
            return m.group(1).strip()
    return None


@dataclass
class SystemControlResult:
    success: bool
    message: str
    data: dict | None = None

    def to_json(self) -> str:
        return json.dumps(
            {"success": self.success, "message": self.message, "data": self.data or {}},
            ensure_ascii=False,
        )


def system_capabilities() -> str:
    caps = {
        "targets": {
            "volume": ["up", "down", "mute", "unmute", "set"],
            "brightness": ["up", "down"],
            "wifi": ["on", "off"],
            "bluetooth": ["on", "off"],
            "app": ["open", "close"],
        },
        "notes": {
            "shortcuts": "Shortcuts are optional. If shortcuts exist (e.g. kage_wifi_on/off), Kage will use them; otherwise it falls back automatically.",
            "fallback": "Wi-Fi uses networksetup; Bluetooth may require blueutil or will open Settings as fallback.",
        },
    }
    return SystemControlResult(True, "capabilities", caps).to_json()


def system_control(target: str, action: str, value: str | None = None) -> str:
    t = str(target or "").strip().lower()
    a = str(action or "").strip().lower()
    v = str(value or "").strip() if value is not None else ""

    # Benchmark mode: avoid OS-level side effects and variable command latency.
    # This keeps E2E measurements focused on routing/model/tool orchestration.
    if _env_truthy("KAGE_BENCH_TEXT_ONLY"):
        return SystemControlResult(True, f"{t} {a} (bench)").to_json()

    # --- Volume ---
    if t in ("volume", "sound"):
        if a in ("mute",):
            code, _out, err = _osascript("set volume with output muted true")
            ok = code == 0
            return SystemControlResult(ok, "muted" if ok else f"mute failed: {err}").to_json()
        if a in ("unmute",):
            code, _out, err = _osascript("set volume with output muted false")
            ok = code == 0
            return SystemControlResult(ok, "unmuted" if ok else f"unmute failed: {err}").to_json()
        if a in ("set",) and v:
            try:
                n = int(float(v))
            except Exception:
                return SystemControlResult(False, "invalid volume value").to_json()
            n = max(0, min(100, n))
            code, _out, err = _osascript(f"set volume output volume {n}")
            ok = code == 0
            return SystemControlResult(ok, f"volume set to {n}" if ok else f"set failed: {err}").to_json()
        # up/down: step by 6
        if a in ("up", "down"):
            delta = 6 if a == "up" else -6
            script = (
                "set cur to output volume of (get volume settings)\n"
                f"set nv to cur + ({delta})\n"
                "if nv < 0 then set nv to 0\n"
                "if nv > 100 then set nv to 100\n"
                "set volume output volume nv\n"
                "return nv"
            )
            code, out, err = _osascript(script)
            ok = code == 0
            msg = f"volume {a}" if ok else f"volume {a} failed: {err}"
            data = {"value": out.strip()} if ok and out.strip() else {}
            return SystemControlResult(ok, msg, data).to_json()

        return SystemControlResult(False, "unsupported volume action").to_json()

    # --- Brightness ---
    if t in ("brightness", "screen"):
        # Default key codes: 144 (brightness down), 145 (brightness up).
        # Some keyboards/firmware map these inversely. Allow env override:
        #   KAGE_BRIGHTNESS_UP_KEYCODE, KAGE_BRIGHTNESS_DOWN_KEYCODE
        # or swap shortcut:
        #   KAGE_BRIGHTNESS_SWAP=1
        if a in ("up", "down"):
            # Prefer user-defined Shortcuts if present (most reliable across devices)
            sc_name = f"kage_brightness_{a}"
            if _has_shortcut(sc_name):
                code, out, _err = _shortcuts_run(sc_name)
                if code == 0:
                    return SystemControlResult(True, f"brightness {a} (shortcuts)", {"output": out.strip()}).to_json()

            up_code = str(os.environ.get("KAGE_BRIGHTNESS_UP_KEYCODE", "145") or "145").strip()
            down_code = str(os.environ.get("KAGE_BRIGHTNESS_DOWN_KEYCODE", "144") or "144").strip()
            swap = str(os.environ.get("KAGE_BRIGHTNESS_SWAP", "")).strip().lower() in ("1", "true", "yes", "on")
            if swap:
                up_code, down_code = down_code, up_code
            key = up_code if a == "up" else down_code
            code, _out, err = _osascript(f'tell application "System Events" to key code {key}')
            ok = code == 0
            return SystemControlResult(ok, f"brightness {a}" if ok else f"brightness failed: {err}").to_json()
        return SystemControlResult(False, "unsupported brightness action").to_json()

    # --- Wi-Fi ---
    if t in ("wifi", "wi-fi", "network"):
        if a not in ("on", "off"):
            return SystemControlResult(False, "unsupported wifi action").to_json()

        # Prefer Shortcuts if present
        sc_name = f"kage_wifi_{a}"
        if _has_shortcut(sc_name):
            code, out, _err = _shortcuts_run(sc_name)
            if code == 0:
                return SystemControlResult(True, f"wifi {a} (shortcuts)", {"output": out.strip()}).to_json()

        dev = _detect_wifi_device() or "en0"
        code, _out, err2 = _run(["networksetup", "-setairportpower", dev, a], timeout=10)
        ok = code == 0
        return SystemControlResult(ok, f"wifi {a}" if ok else f"wifi failed: {err2}").to_json()

    # --- Bluetooth ---
    if t in ("bluetooth", "bt"):
        if a not in ("on", "off"):
            return SystemControlResult(False, "unsupported bluetooth action").to_json()

        sc_name = f"kage_bluetooth_{a}"
        if _has_shortcut(sc_name):
            code, out, _err = _shortcuts_run(sc_name)
            if code == 0:
                return SystemControlResult(True, f"bluetooth {a} (shortcuts)", {"output": out.strip()}).to_json()

        # Try blueutil if installed
        if shutil.which("blueutil") is not None:
            val = "1" if a == "on" else "0"
            code, _out, err2 = _run(["blueutil", "--power", val], timeout=10)
            ok = code == 0
            return SystemControlResult(ok, f"bluetooth {a}" if ok else f"bluetooth failed: {err2}").to_json()

        # Fallback: open Settings page
        _ = _run(["open", "x-apple.systempreferences:com.apple.Bluetooth"], timeout=5)
        return SystemControlResult(True, f"opened bluetooth settings (manual toggle needed)").to_json()

    # --- App ---
    if t in ("app", "application"):
        if not v:
            return SystemControlResult(False, "missing app name").to_json()
        if a in ("open", "start"):
            code, _out, err = _run(["open", "-a", v], timeout=10)
            ok = code == 0
            return SystemControlResult(ok, f"opened {v}" if ok else f"open failed: {err}").to_json()
        if a in ("close", "quit"):
            code, _out, err = _osascript(f'tell application "{v}" to quit')
            ok = code == 0
            return SystemControlResult(ok, f"quit {v}" if ok else f"quit failed: {err}").to_json()
        return SystemControlResult(False, "unsupported app action").to_json()

    return SystemControlResult(False, "unsupported target").to_json()
