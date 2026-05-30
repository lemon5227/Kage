"""Companion-assistant: fast-command path scenarios.

Kage uses a deterministic fast path for high-confidence commands so the
user gets sub-500ms feedback without a model round-trip. These tests pin
the contract of `_fast_command`:

  - Returns a string for high-confidence commands → server bypasses agent loop.
  - Returns None for ambiguous / chat-y inputs → server routes to agent loop.
  - Calls the right tool with the right arguments (no hallucination).
  - NEVER invokes the LLM (verified via tool-call records, no model stub).
"""

from __future__ import annotations

from core.server import KageServer
from core.session_state import SessionState


# ---------------------------------------------------------------------------
# Stub tools — record every call so we can assert what fast_command did
# ---------------------------------------------------------------------------

class _RecordingTools:
    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        return f"{name}:{','.join(str(a) for a in args)}"

    def system_control(self, target, action, value=None):
        return self._record("system_control", target, action, value)

    def open_url(self, url):
        return self._record("open_url", url)

    def open_app(self, app_name):
        return self._record("open_app", app_name)

    def open_website(self, site):
        return self._record("open_website", site)

    def get_time(self):
        return self._record("get_time")

    def take_screenshot(self):
        return self._record("take_screenshot")

    def smart_search(self, query, max_results=5):
        return self._record("smart_search", query, max_results)

    def web_search(self, query, max_results=5):
        return self._record("web_search", query, max_results)


def _make_server():
    """Build a partial KageServer with just enough stubs for _fast_command."""
    s = object.__new__(KageServer)
    s.tools = _RecordingTools()
    s.session = SessionState()
    s._fast_cache = {}
    s._get_effective_city = lambda: "Beijing"
    s._fetch_weather = lambda city: f"{city}: sunny 25C"
    s._media_control = lambda action, preferred_apps=None: f"media:{action}"
    return s


# ---------------------------------------------------------------------------
# 1. Empty/None input
# ---------------------------------------------------------------------------

class TestFastCommandEmptyInput:
    def test_empty_returns_none(self):
        s = _make_server()
        assert s._fast_command("") is None
        assert s._fast_command("   ") is None
        assert s._fast_command(None) is None


# ---------------------------------------------------------------------------
# 2. Volume control
# ---------------------------------------------------------------------------

class TestFastCommandVolume:
    def test_volume_up(self):
        s = _make_server()
        out = s._fast_command("音量调大")
        assert out is not None, "high-confidence volume command must short-circuit"
        # Must have called system_control with volume target
        sc_calls = [c for c in s.tools.calls if c[0] == "system_control"]
        assert sc_calls, f"expected system_control call, got: {s.tools.calls}"
        target, action = sc_calls[0][1][0], sc_calls[0][1][1]
        assert target == "volume"
        assert action == "up"

    def test_volume_down(self):
        s = _make_server()
        s._fast_command("音量小一点")
        sc = [c for c in s.tools.calls if c[0] == "system_control"][0]
        assert sc[1][0] == "volume"
        assert sc[1][1] == "down"

    def test_mute(self):
        s = _make_server()
        s._fast_command("静音")
        sc = [c for c in s.tools.calls if c[0] == "system_control"][0]
        assert sc[1][0] == "volume"
        assert sc[1][1] == "mute"

    def test_unmute(self):
        s = _make_server()
        s._fast_command("取消静音")
        sc = [c for c in s.tools.calls if c[0] == "system_control"][0]
        assert sc[1][0] == "volume"
        assert sc[1][1] == "unmute"


# ---------------------------------------------------------------------------
# 3. Brightness
# ---------------------------------------------------------------------------

class TestFastCommandBrightness:
    def test_brightness_up(self):
        s = _make_server()
        s._fast_command("屏幕亮度调高")
        sc = [c for c in s.tools.calls if c[0] == "system_control"][0]
        assert sc[1][0] == "brightness"
        assert sc[1][1] == "up"

    def test_brightness_down(self):
        s = _make_server()
        s._fast_command("亮度调暗一点")
        sc = [c for c in s.tools.calls if c[0] == "system_control"][0]
        assert sc[1][0] == "brightness"
        assert sc[1][1] == "down"


# ---------------------------------------------------------------------------
# 4. Weather fast path
# ---------------------------------------------------------------------------

class TestFastCommandWeather:
    def test_weather_with_city(self):
        s = _make_server()
        out = s._fast_command("上海天气怎么样")
        # Fast path returns the weather string directly without agent loop
        assert out is not None
        # Whatever city was extracted, _fetch_weather was the one called
        # (we can't directly observe it because we patched it as a lambda;
        # the test asserts behavior via output)
        assert ":" in out  # our stub format is "{city}: sunny 25C"

    def test_weather_without_city_uses_effective_city(self):
        s = _make_server()
        out = s._fast_command("今天天气")
        assert out is not None
        # Should fall back to _get_effective_city() = Beijing
        assert "Beijing" in out

    def test_weather_with_search_keyword_uses_smart_search(self):
        """If user asks 网络搜天气 we should NOT do the WiFi toggle confusion;
        instead we route to smart_search."""
        s = _make_server()
        s._fast_command("上网搜一下尼斯天气")
        # Must not have triggered wifi toggle
        sc_calls = [c for c in s.tools.calls if c[0] == "system_control"]
        for c in sc_calls:
            assert c[1][0] != "wifi", \
                f"weather + search must NOT toggle wifi: {c}"


# ---------------------------------------------------------------------------
# 5. Bluetooth
# ---------------------------------------------------------------------------

class TestFastCommandBluetooth:
    def test_bluetooth_on(self):
        s = _make_server()
        s._fast_command("打开蓝牙")
        sc = [c for c in s.tools.calls if c[0] == "system_control"][0]
        assert sc[1][0] == "bluetooth"
        assert sc[1][1] == "on"

    def test_bluetooth_off(self):
        s = _make_server()
        s._fast_command("关闭蓝牙")
        sc = [c for c in s.tools.calls if c[0] == "system_control"][0]
        assert sc[1][0] == "bluetooth"
        assert sc[1][1] == "off"


# ---------------------------------------------------------------------------
# 6. Media control
# ---------------------------------------------------------------------------

class TestFastCommandMedia:
    def test_pause_routes_to_media_control(self):
        s = _make_server()
        # Capture _media_control args
        captured: list[tuple] = []
        s._media_control = lambda action, preferred_apps=None: captured.append((action, preferred_apps)) or "ok"
        s._fast_command("暂停")
        assert captured, "媒体暂停 should hit _media_control"
        assert captured[0][0] == "pause"

    def test_next_track(self):
        s = _make_server()
        captured: list[tuple] = []
        s._media_control = lambda action, preferred_apps=None: captured.append((action, preferred_apps)) or "ok"
        s._fast_command("下一首")
        assert captured[0][0] == "next"

    def test_previous_track(self):
        s = _make_server()
        captured: list[tuple] = []
        s._media_control = lambda action, preferred_apps=None: captured.append((action, preferred_apps)) or "ok"
        s._fast_command("上一首")
        assert captured[0][0] == "previous"

    def test_netease_preferred_when_user_specifies(self):
        s = _make_server()
        captured: list[tuple] = []
        s._media_control = lambda action, preferred_apps=None: captured.append((action, preferred_apps)) or "ok"
        s._fast_command("用网易云放点歌")
        assert "NeteaseMusic" in (captured[0][1] or [])


# ---------------------------------------------------------------------------
# 7. Plain chat falls through (returns None)
# ---------------------------------------------------------------------------

class TestFastCommandFallthrough:
    """For chat-y inputs the fast path must return None so the agent loop
    can take over. Returning a string would short-circuit the LLM."""

    def test_greeting_falls_through(self):
        s = _make_server()
        assert s._fast_command("你好") is None

    def test_open_website_falls_through(self):
        """Opening websites is not a high-confidence fast path —
        the agent loop handles it (because url disambiguation is hard)."""
        s = _make_server()
        assert s._fast_command("帮我打开 youtube 网站") is None

    def test_question_falls_through(self):
        s = _make_server()
        assert s._fast_command("你是谁") is None
        assert s._fast_command("今天感觉怎么样") is None


# ---------------------------------------------------------------------------
# 8. Persona wrapping is applied to fast-command results
# ---------------------------------------------------------------------------

class TestPersonaWrap:
    def test_persona_wrap_inserts_value(self):
        s = _make_server()
        out = s._persona_wrap("12:00", cmd_type="time")
        assert "12:00" in out

    def test_persona_wrap_default_cmd_type(self):
        s = _make_server()
        out = s._persona_wrap("ok", cmd_type="default")
        assert "ok" in out

    def test_persona_wrap_unknown_cmd_type_uses_default(self):
        s = _make_server()
        # Unknown cmd_type should not crash, fall back to default template
        out = s._persona_wrap("hello", cmd_type="never_seen_before")
        assert "hello" in out
