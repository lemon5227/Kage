import asyncio

from core.realtime_handlers import (
    extract_video_followup_correction_text,
    is_open_only_followup_text,
    is_video_intent,
    normalize_video_query_for_search,
    preprocess_video_followup_turn,
    undo_fastpath,
    weather_fastpath,
)


class DummyToolExecutor:
    def __init__(self, success=True, error_message="boom"):
        self.success = success
        self.error_message = error_message

    async def execute(self, name, arguments):
        class Result:
            pass

        r = Result()
        r.success = self.success
        r.error_message = self.error_message
        return r


class DummyAgenticLoop:
    def _extract_weather_city(self, user_input):
        return "巴黎"

    def _extract_weather_day_offset(self, user_input):
        return 0

    def _normalize_city_for_weather_api(self, city):
        return "Paris"

    def _format_weather_from_wttr_result(self, tc, city_raw, day_offset):
        return f"{city_raw}: 晴"


def test_is_video_intent():
    assert is_video_intent("帮我找最新视频")
    assert is_video_intent("open youtube video")
    assert not is_video_intent("帮我调高音量")


def test_normalize_video_query_for_search():
    assert normalize_video_query_for_search("看看雷军最新视频然后打开") == "看看雷军最新视频"


def test_video_followup_helpers():
    assert is_open_only_followup_text("就这个，打开")
    assert extract_video_followup_correction_text("不是这个，是雷军") == "雷军"


def test_preprocess_video_followup_turn_cancel():
    result = preprocess_video_followup_turn("取消")

    assert result.consume_turn is True
    assert result.clear_pending is True
    assert "先不继续找" in result.speech


def test_preprocess_video_followup_turn_correction():
    result = preprocess_video_followup_turn("不是这个，是雷军")

    assert result.consume_turn is False
    assert result.clear_pending is True
    assert result.corrected_input == "雷军 最新视频"


def test_undo_fastpath_success():
    reply = asyncio.run(undo_fastpath(DummyToolExecutor(success=True)))
    assert "撤销了" in reply


def test_weather_fastpath_uses_cache_when_present():
    cache = {"weather_fast:巴黎:0": "巴黎: 多云"}

    result = asyncio.run(
        weather_fastpath(
            "巴黎天气",
            agentic_loop=DummyAgenticLoop(),
            get_fast_cache=lambda key, ttl: cache.get(key),
            set_fast_cache=lambda key, value: cache.__setitem__(key, value),
            fetch_open_meteo=lambda city, day: "should not be used",
            fetch_metno=lambda city: "should not be used",
            fetch_weather_tool_call_quick=lambda city: None,
            log_fn=lambda *args, **kwargs: None,
        )
    )

    assert result == "巴黎: 多云"
