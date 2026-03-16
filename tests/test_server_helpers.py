import asyncio

from core.dialog_state_machine import DialogStateSnapshot
from core.realtime_handlers import format_video_evidence, video_selection_evidence
from core.server import KageServer, _with_config_defaults


def test_video_selection_evidence_prefers_channel_and_domain():
    ev = video_selection_evidence(
        "曹操说",
        {
            "title": "润不了怎么活？",
            "snippet": "曹操说",
            "url": "https://www.youtube.com/watch?v=abc",
        },
    )
    assert ev["subject_in_channel"] is True
    assert ev["youtube_domain"] is True


def test_format_video_evidence_contains_reason_tokens():
    text = format_video_evidence(
        {
            "subject_in_channel": True,
            "subject_in_title": False,
            "youtube_domain": True,
            "bilibili_domain": False,
        }
    )
    assert "频道名命中" in text
    assert "YouTube来源" in text


def test_with_config_defaults_adds_local_runtime_defaults():
    cfg = _with_config_defaults({"model": {"path": "Qwen/Qwen3-4B-GGUF"}})

    runtime = cfg["model"]["local_runtime"]
    assert runtime["engine"] == "llama.cpp"
    assert runtime["host"] == "127.0.0.1"
    assert runtime["port"] == 8080
    assert runtime["ctx"] == 8192
    assert runtime["reasoning"] == "off"
    broker = cfg["model"]["broker"]
    assert broker["routing_provider"] == "local"
    assert broker["background_provider"] == "local"
    assert len(cfg["model"]["local_profiles"]) >= 2
    assert cfg["model"]["local_profiles"][0]["model"] == "Qwen/Qwen3-4B-GGUF"


def test_with_config_defaults_preserves_overrides():
    cfg = _with_config_defaults({"model": {"local_runtime": {"port": 9009, "ngl": 42}}})

    runtime = cfg["model"]["local_runtime"]
    assert runtime["port"] == 9009
    assert runtime["ngl"] == 42
    assert runtime["engine"] == "llama.cpp"


def test_with_config_defaults_preserves_existing_profiles():
    cfg = _with_config_defaults(
        {
            "model": {
                "local_profiles": [
                    {"id": "custom", "label": "Custom", "model": "foo/bar"}
                ]
            }
        }
    )

    assert cfg["model"]["local_profiles"] == [{"id": "custom", "label": "Custom", "model": "foo/bar"}]


def test_state_payload_includes_dialog_snapshot():
    server = object.__new__(KageServer)

    class DialogStateStub:
        @staticmethod
        def snapshot():
            return DialogStateSnapshot(
                pending_action=object(),
                pending_kind="confirm_tool",
            )

    server.dialog_state = DialogStateStub()

    payload = server._state_payload("THINKING")

    assert payload == {
        "state": "THINKING",
        "dialog_phase": "awaiting_confirmation",
        "pending_kind": "confirm_tool",
    }


def test_log_turn_done_includes_dialog_snapshot(monkeypatch):
    server = object.__new__(KageServer)

    class DialogStateStub:
        @staticmethod
        def snapshot():
            return DialogStateSnapshot(
                pending_action=object(),
                pending_kind="chat_followup",
            )

    captured = {}

    def fake_log(component, event, **fields):
        captured["component"] = component
        captured["event"] = event
        captured["fields"] = fields

    monkeypatch.setattr("core.server.log", fake_log)
    server.dialog_state = DialogStateStub()

    server._log_turn_done(path="agentic_loop", route="chat", elapsed_ms="12.3")

    assert captured["component"] == "server"
    assert captured["event"] == "turn.done"
    assert captured["fields"]["dialog_phase"] == "awaiting_followup"
    assert captured["fields"]["pending_kind"] == "chat_followup"
    assert captured["fields"]["path"] == "agentic_loop"


def test_job_event_payload_includes_dialog_snapshot():
    server = object.__new__(KageServer)

    class DialogStateStub:
        @staticmethod
        def snapshot():
            return DialogStateSnapshot(
                pending_action=None,
                pending_kind="",
            )

    server.dialog_state = DialogStateStub()

    payload = server._job_event_payload("created", {"job_id": "j1", "status": "queued"})

    assert payload == {
        "event": "created",
        "job": {"job_id": "j1", "status": "queued"},
        "dialog_phase": "idle",
        "pending_kind": "",
    }


def test_audio_event_payload_includes_dialog_snapshot():
    server = object.__new__(KageServer)

    class DialogStateStub:
        @staticmethod
        def snapshot():
            return DialogStateSnapshot(
                pending_action=None,
                pending_kind="",
            )

    server.dialog_state = DialogStateStub()

    payload = server._audio_event_payload("speech_activity", source="voice_barge_in")

    assert payload == {
        "event": "speech_activity",
        "source": "voice_barge_in",
        "dialog_phase": "idle",
        "pending_kind": "",
    }


def test_background_ack_text_prefers_human_friendly_message():
    server = object.__new__(KageServer)

    assert "后台处理" in server._background_ack_text("multi_step_or_long_task")


def test_background_completion_notification_only_when_idle():
    server = object.__new__(KageServer)
    server.active_websocket = object()
    server._ui_state = "IDLE"

    text = server._background_completion_notification(
        "completed",
        {"task_type": "multi_step_or_long_task", "notify_on_finish": True},
    )

    assert "完成了" in text

    server._ui_state = "SPEAKING"
    text_busy = server._background_completion_notification(
        "completed",
        {"task_type": "multi_step_or_long_task", "notify_on_finish": True},
    )

    assert text_busy == ""


def test_background_completion_notification_handles_failure():
    server = object.__new__(KageServer)
    server.active_websocket = object()
    server._ui_state = "IDLE"

    text = server._background_completion_notification(
        "failed",
        {"task_type": "cleanup", "notify_on_finish": True},
    )

    assert "失败了" in text


def test_interrupt_speech_updates_state_when_playing():
    server = object.__new__(KageServer)
    server._speech_revision = 0
    server._ui_state = "SPEAKING"

    class MouthStub:
        @staticmethod
        def stop_playback():
            return True

    states = []

    async def fake_send_state(state):
        states.append(state)

    logged = {}

    def fake_log_server_event(event, **fields):
        logged["event"] = event
        logged["fields"] = fields

    server.mouth = MouthStub()
    server.send_state = fake_send_state
    server._log_server_event = fake_log_server_event

    interrupted = asyncio.run(server.interrupt_speech(reason="text_input"))

    assert interrupted is True
    assert states == ["LISTENING"]
    assert logged["event"] == "speech.interrupt"
    assert logged["fields"]["reason"] == "text_input"


def test_monitor_voice_barge_in_interrupts_when_activity_detected():
    server = object.__new__(KageServer)
    server._speech_revision = 1
    server._ui_state = "SPEAKING"
    server._text_only_mode = False
    server._text_input_queue = asyncio.Queue()

    class EarsStub:
        @staticmethod
        def detect_voice_activity(timeout_sec, consecutive_chunks):
            return True

        @staticmethod
        def listen():
            return ("继续说下去", "neutral")

    class AudioStub:
        @staticmethod
        def should_enable_voice_barge_in(*, text_only_mode, ears):
            return True

        @staticmethod
        def normalize_listen_result(result):
            text, emotion = result

            class Outcome:
                def __init__(self, text_value, emotion_value):
                    self.has_input = True
                    self.text = text_value
                    self.emotion = emotion_value

            return Outcome(text, emotion)

    called = {}

    async def fake_interrupt_speech(reason="user_input"):
        called["reason"] = reason
        server._speech_revision += 1
        return True

    audio_events = []
    transcriptions = []

    async def fake_notify_audio_event(event, **fields):
        audio_events.append((event, fields))

    async def fake_send_message(type_, payload):
        transcriptions.append((type_, payload))

    server.ears = EarsStub()
    server.audio_orchestrator = AudioStub()
    server.interrupt_speech = fake_interrupt_speech
    server._notify_audio_event = fake_notify_audio_event
    server.send_message = fake_send_message

    asyncio.run(server._monitor_voice_barge_in(1))

    assert called["reason"] == "voice_barge_in"
    queued = asyncio.run(server._text_input_queue.get())
    assert queued[1] == "继续说下去"
    assert audio_events[0][0] == "speech_activity"
    assert audio_events[1][0] == "barge_in_captured"
    assert transcriptions[0][0] == "transcription"
