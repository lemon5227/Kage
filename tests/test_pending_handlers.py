import asyncio

from core.interaction_state import PendingChatFollowup
from core.pending_handlers import (
    handle_pending_action,
    handle_pending_chat_followup,
    handle_pending_confirm_tool,
    handle_pending_inferred_command,
    handle_pending_video_followup,
)


class PendingVideo:
    def __init__(self, **kwargs):
        self.source = kwargs.get("source", "youtube")
        self.sort = kwargs.get("sort", "latest")
        self.last_url = kwargs.get("last_url", "")
        self.last_title = kwargs.get("last_title", "")
        self.last_channel = kwargs.get("last_channel", "")


class PendingCommand:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class PendingChat:
    def __init__(self, topic="", asked=""):
        self.topic = topic
        self.asked = asked


class ToolExecutorStub:
    def __init__(self, mapping):
        self.mapping = mapping

    async def execute(self, name, arguments):
        value = self.mapping[(name, tuple(sorted((arguments or {}).items())))] if (name, tuple(sorted((arguments or {}).items()))) in self.mapping else self.mapping.get(name)
        if callable(value):
            value = value(arguments)
        return value


class Result:
    def __init__(self, success=True, result="", error_message=None, error_type=None):
        self.success = success
        self.result = result
        self.error_message = error_message
        self.error_type = error_type


def test_handle_pending_video_followup_open_last():
    pending = PendingVideo(last_url="https://youtu.be/x", last_title="Title")
    tool_executor = ToolExecutorStub({"open_url": Result(success=True)})

    result = asyncio.run(
        handle_pending_video_followup(
            pending,
            user_input="打开",
            current_emotion="neutral",
            tool_executor=tool_executor,
            make_pending_followup=PendingVideo,
        )
    )

    assert result.handled is True
    assert result.clear_pending is False
    assert "已经为你打开" in result.speech


def test_handle_pending_video_followup_cancel():
    pending = PendingVideo()
    tool_executor = ToolExecutorStub({})

    result = asyncio.run(
        handle_pending_video_followup(
            pending,
            user_input="取消",
            current_emotion="neutral",
            tool_executor=tool_executor,
            make_pending_followup=PendingVideo,
        )
    )

    assert result.handled is True
    assert result.clear_pending is True
    assert "先不继续找" in result.speech


def test_handle_pending_inferred_command_execute():
    pending = PendingCommand("system_control", {"target": "volume", "action": "up"})
    tool_executor = ToolExecutorStub({"system_control": Result(success=True, result="ok")})

    class AgenticLoopStub:
        @staticmethod
        def _command_reply_from_tools(tool_calls):
            return "音量已调高。"

        @staticmethod
        def _fallback_text_from_tools(tool_calls, text):
            return ""

    result = asyncio.run(
        handle_pending_inferred_command(
            pending,
            user_input="确认",
            current_emotion="neutral",
            tool_executor=tool_executor,
            agentic_loop=AgenticLoopStub(),
            classify_route=lambda text: "command",
        )
    )

    assert result.handled is True
    assert result.clear_pending is True
    assert result.speech == "音量已调高。"


def test_handle_pending_inferred_command_fallback_with_correction():
    pending = PendingCommand("system_control", {"target": "volume", "action": "up"})
    tool_executor = ToolExecutorStub({})

    class AgenticLoopStub:
        @staticmethod
        def _command_reply_from_tools(tool_calls):
            return ""

        @staticmethod
        def _fallback_text_from_tools(tool_calls, text):
            return ""

    result = asyncio.run(
        handle_pending_inferred_command(
            pending,
            user_input="不是这个，是调低音量",
            current_emotion="neutral",
            tool_executor=tool_executor,
            agentic_loop=AgenticLoopStub(),
            classify_route=lambda text: "command",
        )
    )

    assert result.handled is False
    assert result.clear_pending is True
    assert result.new_user_input == "调低音量"
    assert result.new_route_hint == "command"


def test_handle_pending_confirm_tool_cancel():
    pending = PendingCommand("fs_apply", {"ops": [{"op": "trash", "path": "/tmp/x"}]})
    tool_executor = ToolExecutorStub({})

    result = asyncio.run(
        handle_pending_confirm_tool(
            pending,
            user_input="取消",
            current_emotion="neutral",
            tool_executor=tool_executor,
            is_undo_request=lambda text: False,
        )
    )

    assert result.handled is True
    assert result.clear_pending is True
    assert result.speech == "好，我不删。"


def test_handle_pending_confirm_tool_preserves_pending_when_unhandled():
    pending = PendingCommand("fs_apply", {"ops": [{"op": "trash", "path": "/tmp/x"}]})

    result = asyncio.run(
        handle_pending_confirm_tool(
            pending,
            user_input="桌面也顺便整理一下",
            current_emotion="neutral",
            tool_executor=ToolExecutorStub({}),
            is_undo_request=lambda text: False,
        )
    )

    assert result.handled is False
    assert result.clear_pending is False
    assert result.preserve_pending is True


def test_handle_pending_confirm_tool_execute():
    pending = PendingCommand("fs_apply", {"ops": [{"op": "trash", "path": "/tmp/x"}]})

    class ToolExecutorConfirmStub:
        async def execute(self, name, arguments, require_confirmation=None):
            assert arguments["confirmed"] is True
            return Result(success=True, result="ok")

    result = asyncio.run(
        handle_pending_confirm_tool(
            pending,
            user_input="确认",
            current_emotion="neutral",
            tool_executor=ToolExecutorConfirmStub(),
            is_undo_request=lambda text: False,
        )
    )

    assert result.handled is True
    assert result.clear_pending is True
    assert "已经处理好了" in result.speech


def test_handle_pending_chat_followup_structured():
    pending = PendingChat(topic="weather", asked="你是想问天气，还是安排？")

    result = asyncio.run(
        handle_pending_chat_followup(
            pending,
            user_input="我想问天气",
            current_emotion="neutral",
            infer_chat_topic=lambda text: "weather",
            structured_chat_followup=lambda topic, text: "明天会降温，记得加件外套。",
            polish_chat_response=lambda text: f"[{text}]",
            think_action=lambda *_args: [],
            history_provider=lambda: [],
        )
    )

    assert result.handled is True
    assert result.clear_pending is True
    assert result.log_path == "pending_chat_structured"
    assert result.speech == "[明天会降温，记得加件外套。]"


def test_handle_pending_chat_followup_topic_switch_requeues():
    pending = PendingChat(topic="weather", asked="你是想问天气，还是安排？")

    result = asyncio.run(
        handle_pending_chat_followup(
            pending,
            user_input="我想让你帮我安排一下日程",
            current_emotion="neutral",
            infer_chat_topic=lambda text: "planning",
            structured_chat_followup=lambda topic, text: None,
            polish_chat_response=lambda text: text,
            think_action=lambda *_args: [],
            history_provider=lambda: [],
        )
    )

    assert result.handled is False
    assert result.clear_pending is True


def test_handle_pending_chat_followup_model_fallback():
    pending = PendingChat(topic="reply", asked="他发了啥？你想怎么回？")

    class Chunk:
        def __init__(self, text):
            self.text = text

    result = asyncio.run(
        handle_pending_chat_followup(
            pending,
            user_input="你帮我回得礼貌一点",
            current_emotion="calm",
            infer_chat_topic=lambda text: "reply",
            structured_chat_followup=lambda topic, text: None,
            polish_chat_response=lambda text: text.strip(),
            think_action=lambda *_args: [Chunk("可以"), Chunk("，我帮你组织一句更礼貌的回复。")],
            history_provider=lambda: [{"role": "user", "content": "上一轮"}],
        )
    )

    assert result.handled is True
    assert result.clear_pending is True
    assert result.log_path == "pending_chat_model"
    assert "更礼貌的回复" in result.speech


def test_handle_pending_inferred_command_requests_agent_loop():
    pending = PendingCommand("system_control", {"target": "volume", "action": "up"})

    class AgenticLoopStub:
        @staticmethod
        def _command_reply_from_tools(tool_calls):
            return ""

        @staticmethod
        def _fallback_text_from_tools(tool_calls, text):
            return ""

    result = asyncio.run(
        handle_pending_inferred_command(
            pending,
            user_input="不是这个，是调低音量",
            current_emotion="neutral",
            tool_executor=ToolExecutorStub({}),
            agentic_loop=AgenticLoopStub(),
            classify_route=lambda text: "command",
        )
    )

    assert result.handled is False
    assert result.run_agent_loop is True
    assert result.new_user_input == "调低音量"


def test_handle_pending_action_dispatches_chat_recording():
    pending = PendingChatFollowup(topic="reply", asked="他发了啥？你想怎么回？")

    result = asyncio.run(
        handle_pending_action(
            pending,
            user_input="礼貌一点",
            current_emotion="calm",
            tool_executor=ToolExecutorStub({}),
            make_pending_followup=PendingVideo,
            agentic_loop=object(),
            classify_route=lambda text: "chat",
            is_undo_request=lambda text: False,
            infer_chat_topic=lambda text: "reply",
            structured_chat_followup=lambda topic, text: "我帮你润色一下回复。",
            polish_chat_response=lambda text: text,
            think_action=lambda *_args: [],
            history_provider=lambda: [],
        )
    )

    assert result.handled is True
    assert result.record_turn is True
    assert result.speech == "我帮你润色一下回复。"
