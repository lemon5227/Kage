"""Companion-assistant: pending-action state machine scenarios.

A multi-turn assistant must survive these patterns:

  Confirm flow:    Kage proposes action → user says "对/嗯/确认" → action runs.
  Cancel flow:     Kage proposes action → user says "算了" → action discarded.
  Correction flow: Kage proposes wrong target → user says "不是这个，是..." →
                   Kage retries with the corrected target.
  Open-only:       Video search returned a candidate → user says "打开" alone
                   → Kage opens the last result without re-searching.

These tests verify the pending-state contracts without hitting an LLM.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from core.interaction_state import (
    make_pending_chat_followup,
    make_pending_confirm_inferred_command,
    make_pending_confirm_tool,
    make_pending_video_followup,
    pending_kind,
    pending_requires_thinking,
)
from core.realtime_lane import (
    extract_correction_text,
    is_cancel_text,
    is_confirm_text,
)
from core.session_state import SessionState


# ---------------------------------------------------------------------------
# Stub tool executor — record calls and return a synthetic result
# ---------------------------------------------------------------------------

@dataclass
class _ToolResult:
    success: bool
    result: str = ""


class _RecordingExec:
    """Minimal async tool executor stub for state-machine tests."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self._next: dict[str, _ToolResult] = {}

    def queue(self, name: str, success: bool = True, result: str = "") -> None:
        self._next[name] = _ToolResult(success, result)

    async def execute(self, name: str, args: dict, **_kw) -> _ToolResult:
        # Accept extra kwargs (e.g. require_confirmation) so we mirror the real
        # ToolExecutor.execute() signature without forcing every test to pass them.
        self.calls.append((name, args))
        return self._next.get(name, _ToolResult(success=True, result="ok"))


# ---------------------------------------------------------------------------
# 1. Pending action lifecycle on SessionState
# ---------------------------------------------------------------------------

class TestPendingActionLifecycle:
    """SessionState must store/clear pending actions across turns."""

    def test_no_pending_initially(self):
        ss = SessionState()
        assert ss.has_pending_action() is False
        assert ss.pending_action is None

    def test_set_pending_then_has_pending(self):
        ss = SessionState()
        pending = make_pending_confirm_tool("fs_trash", {"path": "/tmp/x"})
        ss.set_pending_action(pending)
        assert ss.has_pending_action() is True
        assert ss.pending_action is pending

    def test_clear_pending_resets_state(self):
        ss = SessionState()
        ss.set_pending_action(make_pending_confirm_tool("fs_trash", {"path": "/tmp/x"}))
        ss.clear_pending_action()
        assert ss.has_pending_action() is False

    def test_pending_kind_dispatch(self):
        cases = [
            (make_pending_video_followup(), "video_followup"),
            (make_pending_confirm_inferred_command("foo", {}), "confirm_inferred_command"),
            (make_pending_confirm_tool("fs_trash", {}), "confirm_tool"),
            (make_pending_chat_followup(), "chat_followup"),
            (None, "unknown"),
            ("not a pending object", "unknown"),
        ]
        for pending, expected in cases:
            assert pending_kind(pending) == expected, f"{pending!r} → {expected!r}"

    def test_pending_requires_thinking_only_for_action_pendings(self):
        """Chat follow-ups don't need re-thinking; action confirmations do."""
        assert pending_requires_thinking(make_pending_video_followup()) is True
        assert pending_requires_thinking(make_pending_confirm_inferred_command("foo", {})) is True
        assert pending_requires_thinking(make_pending_confirm_tool("foo", {})) is True
        # Chat follow-up: just plain conversation, no special routing
        assert pending_requires_thinking(make_pending_chat_followup()) is False
        assert pending_requires_thinking(None) is False


# ---------------------------------------------------------------------------
# 2. Confirm / cancel text classification
# ---------------------------------------------------------------------------

class TestConfirmCancelClassification:
    """The realtime lane must reliably tell affirmative replies from
    cancellations. These are user-facing colloquial phrases."""

    @pytest.mark.parametrize("text", [
        "好",
        "嗯",
        "对",
        "确认",
        "yes",
        "ok",
        "可以",
        "行",
    ])
    def test_recognises_confirmation(self, text):
        assert is_confirm_text(text) is True, f"{text!r} should be confirm"

    @pytest.mark.parametrize("text", [
        "不",
        "不要",
        "算了",
        "取消",
        "no",
    ])
    def test_recognises_cancellation(self, text):
        assert is_cancel_text(text) is True, f"{text!r} should be cancel"

    @pytest.mark.parametrize("text", [
        "你帮我看一下天气",
        "帮我打开 Safari",
        "今天好累啊",
    ])
    def test_normal_chat_is_neither(self, text):
        assert is_confirm_text(text) is False
        assert is_cancel_text(text) is False


# ---------------------------------------------------------------------------
# 3. Correction extraction
# ---------------------------------------------------------------------------

class TestCorrectionExtraction:
    """Pattern '不是这个，是 X' → extract X as the new target."""

    def test_simple_correction(self):
        assert extract_correction_text("不是这个，是张三的视频") == "张三的视频"

    def test_correction_with_no_comma(self):
        assert extract_correction_text("不是这个 是李四") == "李四"

    def test_correction_strips_trailing_punctuation(self):
        assert extract_correction_text("不是这个，是王五。") == "王五"

    def test_no_correction_returns_empty(self):
        assert extract_correction_text("帮我打开 Safari") == ""
        assert extract_correction_text("好") == ""

    def test_empty_input(self):
        assert extract_correction_text("") == ""


# ---------------------------------------------------------------------------
# 4. Pending video follow-up: "打开" alone reopens last result
# ---------------------------------------------------------------------------

class TestPendingVideoFollowup:
    """After a video search, user often says only "打开" / "点开" — Kage
    must re-use the last URL without searching again."""

    def _make_pending(self, url="https://youtube.com/watch?v=AAA", title="科普视频"):
        return make_pending_video_followup(
            source="youtube", sort="latest",
            last_url=url, last_title=title, last_channel="某频道",
        )

    def test_open_alone_opens_last_url(self):
        from core.pending_handlers import handle_pending_video_followup

        pending = self._make_pending()
        executor = _RecordingExec()
        executor.queue("open_url", success=True)

        result = asyncio.run(handle_pending_video_followup(
            pending,
            user_input="打开",
            current_emotion="neutral",
            tool_executor=executor,
            make_pending_followup=make_pending_video_followup,
        ))

        assert result.handled is True
        assert any(call[0] == "open_url" for call in executor.calls), \
            "should have called open_url with the cached URL"
        # The exact URL used
        url_call = next(c for c in executor.calls if c[0] == "open_url")
        assert url_call[1].get("url") == "https://youtube.com/watch?v=AAA"
        # Title should appear in the speech reply
        assert "科普视频" in result.speech

    def test_open_failure_speech_invites_retry(self):
        """If open_url fails, Kage prompts the user to say '打开' again
        instead of silently swallowing the error."""
        from core.pending_handlers import handle_pending_video_followup

        pending = self._make_pending()
        executor = _RecordingExec()
        executor.queue("open_url", success=False)

        result = asyncio.run(handle_pending_video_followup(
            pending,
            user_input="打开",
            current_emotion="neutral",
            tool_executor=executor,
            make_pending_followup=make_pending_video_followup,
        ))

        assert result.handled is True
        assert "再说一次" in result.speech or "再来" in result.speech or "重试" in result.speech, \
            f"open failure speech should invite retry, got: {result.speech!r}"

    def test_open_alone_with_no_cached_url_does_not_call_tool(self):
        """If the pending state has no cached URL (rare but possible), saying
        '打开' alone should NOT trigger an open_url call with empty URL."""
        from core.pending_handlers import handle_pending_video_followup

        # Empty URL — open shortcut should not fire
        pending = make_pending_video_followup(last_url="", last_title="")
        executor = _RecordingExec()

        asyncio.run(handle_pending_video_followup(
            pending,
            user_input="打开",
            current_emotion="neutral",
            tool_executor=executor,
            make_pending_followup=make_pending_video_followup,
        ))

        # We don't care exactly what handler returns, only that we didn't
        # silently call open_url("") which would crash the browser.
        for call_name, call_args in executor.calls:
            if call_name == "open_url":
                assert call_args.get("url"), \
                    f"open_url called with empty URL: {call_args!r}"


# ---------------------------------------------------------------------------
# 5. Pending video follow-up: "不是这个，是 X" → re-search with X
# ---------------------------------------------------------------------------

class TestPendingVideoCorrection:
    def test_correction_text_triggers_research_with_new_query(self):
        """When the user corrects the target, the handler must invoke
        the search tool with the corrected query (not the original one)."""
        from core.pending_handlers import handle_pending_video_followup
        import json

        pending = make_pending_video_followup(
            last_url="https://youtube.com/watch?v=AAA",
            last_title="科普视频"
        )
        executor = _RecordingExec()
        # Search returns at least one matching item so we can confirm the
        # full re-search loop fired.
        executor.queue("search", success=True, result=json.dumps({
            "items": [
                {"title": "李四的最新视频", "url": "https://youtube.com/watch?v=BBB",
                 "snippet": "李四频道"},
            ]
        }))

        result = asyncio.run(handle_pending_video_followup(
            pending,
            user_input="不是这个，是李四的视频",
            current_emotion="neutral",
            tool_executor=executor,
            make_pending_followup=make_pending_video_followup,
        ))

        assert result.handled is True
        # MUST have called search with the corrected query
        search_calls = [c for c in executor.calls if c[0] == "search"]
        assert len(search_calls) >= 1, "correction must trigger a search"
        # The corrected target name appears in the search query
        query = search_calls[0][1].get("query", "")
        assert "李四" in query, f"search query should contain '李四', got: {query!r}"
        # The new pending should reference the new URL, not the old one
        new_pending = result.set_pending
        if new_pending is not None:
            assert getattr(new_pending, "last_url", "") != "https://youtube.com/watch?v=AAA"

    def test_correction_with_no_search_results_does_not_re_open_old_url(self):
        """Even when re-search returns nothing, the handler must NOT
        fall back to opening the old (wrong) URL."""
        from core.pending_handlers import handle_pending_video_followup
        import json

        pending = make_pending_video_followup(
            last_url="https://youtube.com/watch?v=WRONG",
            last_title="错误的视频"
        )
        executor = _RecordingExec()
        executor.queue("search", success=True, result=json.dumps({"items": []}))

        asyncio.run(handle_pending_video_followup(
            pending,
            user_input="不是这个，是李四的视频",
            current_emotion="neutral",
            tool_executor=executor,
            make_pending_followup=make_pending_video_followup,
        ))

        # Must not have called open_url at all
        assert not any(c[0] == "open_url" for c in executor.calls), \
            f"correction with empty results must NOT open the old URL: {executor.calls}"


# ---------------------------------------------------------------------------
# 6. Pending confirm-tool: user says "好" → tool runs
# ---------------------------------------------------------------------------

class TestPendingConfirmTool:
    def test_confirm_runs_tool(self):
        from core.pending_handlers import handle_pending_confirm_tool

        pending = make_pending_confirm_tool("fs_trash", {"path": "/tmp/x"})
        executor = _RecordingExec()
        executor.queue("fs_trash", success=True, result="moved to trash")

        result = asyncio.run(handle_pending_confirm_tool(
            pending,
            user_input="好",
            current_emotion="neutral",
            tool_executor=executor,
            is_undo_request=lambda _t: False,
        ))

        assert result.handled is True
        assert result.clear_pending is True
        assert any(call[0] == "fs_trash" for call in executor.calls), \
            "confirm should have triggered fs_trash"

    def test_cancel_does_not_run_tool(self):
        from core.pending_handlers import handle_pending_confirm_tool

        pending = make_pending_confirm_tool("fs_trash", {"path": "/tmp/x"})
        executor = _RecordingExec()

        result = asyncio.run(handle_pending_confirm_tool(
            pending,
            user_input="算了",
            current_emotion="neutral",
            tool_executor=executor,
            is_undo_request=lambda _t: False,
        ))

        assert result.handled is True
        assert result.clear_pending is True
        # MUST NOT have called the destructive tool
        assert not any(call[0] == "fs_trash" for call in executor.calls), \
            "cancel must not run the dangerous fs_trash tool"

    def test_undo_short_circuits_to_cancel(self):
        """Saying '撤销' to a pending tool confirmation should cancel,
        not execute. Otherwise destructive ops would run on accident."""
        from core.pending_handlers import handle_pending_confirm_tool

        pending = make_pending_confirm_tool("fs_trash", {"path": "/tmp/x"})
        executor = _RecordingExec()

        result = asyncio.run(handle_pending_confirm_tool(
            pending,
            user_input="撤销",
            current_emotion="neutral",
            tool_executor=executor,
            is_undo_request=lambda t: "撤销" in t,
        ))

        assert result.handled is True
        assert result.clear_pending is True
        assert not any(c[0] == "fs_trash" for c in executor.calls), \
            "undo must not execute the pending dangerous tool"

    def test_unrecognized_reply_does_not_auto_execute(self):
        """If user says something neither confirm/cancel/undo, the pending
        action must NOT auto-execute the destructive tool."""
        from core.pending_handlers import handle_pending_confirm_tool

        pending = make_pending_confirm_tool("fs_trash", {"path": "/tmp/x"})
        executor = _RecordingExec()

        asyncio.run(handle_pending_confirm_tool(
            pending,
            user_input="今天天气怎么样",
            current_emotion="neutral",
            tool_executor=executor,
            is_undo_request=lambda _t: False,
        ))

        assert not any(c[0] == "fs_trash" for c in executor.calls), \
            "unclear reply must not auto-execute the pending dangerous tool"
