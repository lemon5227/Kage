"""Cancellation of speech playback without a real TTS or audio device."""
import asyncio
import threading

from core.server import KageServer
from core.speech_engine import _monitor_voice_barge_in, mouth_speak
import core.routes.browser_tasks as browser_routes


class FakeAvatar:
    def update_motion_cooldown(self, _text):
        pass

    def select_motion(self, _emotion):
        return None

    def select_expression(self, _emotion):
        return 'neutral'

    def calculate_expression_duration(self, _text):
        return 1


class FakeAudio:
    def should_enable_voice_barge_in(self, **_kwargs):
        return False


class FakeMouth:
    def __init__(self):
        self.started = {'old': threading.Event(), 'new': threading.Event()}
        self.released = {'old': threading.Event(), 'new': threading.Event()}
        self.finished = {'old': threading.Event(), 'new': threading.Event()}
        self.stop_calls = 0

    async def generate_speech_file(self, text, _emotion):
        return 'old' if 'old' in text else 'new'

    def play_audio_file(self, path):
        self.started[path].set()
        self.released[path].wait(5)
        self.finished[path].set()

    def stop_playback(self):
        self.stop_calls += 1
        self.released['old'].set()
        self.released['new'].set()
        return True


def fake_server():
    server = object.__new__(KageServer)
    server._speech_revision = 0
    server._ui_state = 'IDLE'
    server._text_only_mode = False
    server.mouth = FakeMouth()
    server.avatar_animation = FakeAvatar()
    server.audio_orchestrator = FakeAudio()
    server.ears = None
    server.active_websocket = object()
    states = []

    async def send_message(_kind, _payload):
        pass

    async def send_state(value):
        server._ui_state = value
        states.append(value)

    server.send_message = send_message
    server.send_state = send_state
    server._job_event_payload = lambda event, job: {'event': event, 'job': job}
    server._log_server_event = lambda *args, **kwargs: None
    return server, states


async def wait_thread(event):
    assert await asyncio.wait_for(asyncio.to_thread(event.wait, 3), 4)


def test_cancel_current_speech_stops_playback_and_restores_idle():
    async def scenario():
        server, states = fake_server()
        task = asyncio.create_task(mouth_speak(server, 'old speech'))
        try:
            await wait_thread(server.mouth.started['old'])
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert server.mouth.stop_calls == 1
            assert server._ui_state == 'IDLE'
            assert states == ['SPEAKING', 'IDLE']
            await wait_thread(server.mouth.finished['old'])
        finally:
            server.mouth.released['old'].set()

    asyncio.run(scenario())


def test_cancel_old_speech_does_not_stop_or_reset_newer_revision():
    async def scenario():
        server, states = fake_server()
        old = asyncio.create_task(mouth_speak(server, 'old speech'))
        new = None
        try:
            await wait_thread(server.mouth.started['old'])
            new = asyncio.create_task(mouth_speak(server, 'new speech'))
            await wait_thread(server.mouth.started['new'])
            old.cancel()
            try:
                await old
            except asyncio.CancelledError:
                pass
            assert server.mouth.stop_calls == 0
            assert server._ui_state == 'SPEAKING'
            assert states == ['SPEAKING', 'SPEAKING']
            server.mouth.released['old'].set()
            server.mouth.released['new'].set()
            await new
            assert states == ['SPEAKING', 'SPEAKING', 'IDLE']
        finally:
            server.mouth.released['old'].set()
            server.mouth.released['new'].set()
            if new is not None and not new.done():
                new.cancel()

    asyncio.run(scenario())


def test_ordinary_speech_and_barge_helper_keep_their_behavior():
    async def scenario():
        server, states = fake_server()
        server.mouth.released['old'].set()
        await mouth_speak(server, 'old speech')
        assert states == ['SPEAKING', 'IDLE']
        assert server.mouth.stop_calls == 0

        class BargeAudio:
            def check_voice_barge_in(self):
                return True

        server.ears = object()
        server.audio_orchestrator = BargeAudio()
        revision = server._speech_revision
        await _monitor_voice_barge_in(server, revision)
        assert server._speech_revision == revision + 1

    asyncio.run(scenario())


def test_browser_notification_timeout_cleans_up_real_speech(monkeypatch):
    monkeypatch.setattr(browser_routes, 'NOTIFICATION_TIMEOUT_SECONDS', .1)

    async def scenario():
        server, states = fake_server()
        job = {'task_type': 'browser_experiment', 'status': 'completed',
               'result': {'task_status': 'completed', 'check_available': True, 'check_passed': True}}
        try:
            await browser_routes._deliver_notification(server, 'completed', job)
            await asyncio.sleep(.02)
            assert server.mouth.started['new'].is_set()
            assert server.mouth.stop_calls == 1
            assert server._ui_state == 'IDLE'
            assert states == ['SPEAKING', 'IDLE']
            await wait_thread(server.mouth.finished['new'])
            await browser_routes.close_service()
            assert all(task.done() for task in browser_routes._notification_tasks)
        finally:
            server.mouth.released['new'].set()

    asyncio.run(scenario())
