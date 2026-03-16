from core.realtime_lane import (
    classify_realtime_task,
    decide_realtime_command,
    describe_command_intent,
    extract_correction_text,
    resolve_pending_inferred_command,
)


def test_classify_realtime_task_for_confirmation():
    result = classify_realtime_task("确认")

    assert result.lane == "realtime"
    assert result.reason == "confirmation"
    assert result.can_background is False


def test_classify_realtime_task_for_background_cleanup():
    result = classify_realtime_task("帮我整理桌面，把截图和文档归类")

    assert result.lane == "background"
    assert result.can_background is True


def test_decide_realtime_command_fast_execute():
    result = decide_realtime_command("帮我调高音量")

    assert result.mode == "execute"
    assert result.tool_name == "system_control"
    assert result.arguments == {"target": "volume", "action": "up"}


def test_decide_realtime_command_confirm_mid_confidence():
    result = decide_realtime_command("蓝牙")

    assert result.mode == "confirm"
    assert result.tool_name == "system_control"
    assert result.arguments == {"target": "bluetooth", "action": "on"}


def test_pending_inferred_command_resolution_with_correction():
    result = resolve_pending_inferred_command(
        "system_control",
        {"target": "volume", "action": "up"},
        "不是这个，是调低音量",
    )

    assert result.action == "fallback"
    assert result.corrected_text == "调低音量"


def test_extract_correction_text():
    assert extract_correction_text("不是这个，是打开微信") == "打开微信"


def test_describe_command_intent():
    text = describe_command_intent("system_control", {"target": "wifi", "action": "off"})
    assert text == "关闭 Wi-Fi"
