from core.audio_orchestrator import AudioListenOutcome, AudioOrchestrator


class EarsStub:
    def __init__(self, wakeword_enabled: bool):
        self.wakeword_enabled = wakeword_enabled

    @staticmethod
    def detect_voice_activity(timeout_sec: float, consecutive_chunks: int) -> bool:
        return False


def test_always_listen_mode_when_wakeword_disabled():
    orchestrator = AudioOrchestrator(wakeword_enabled_cfg=False)

    assert orchestrator.is_always_listen_mode(EarsStub(wakeword_enabled=True)) is True


def test_should_wait_for_wakeword_only_when_not_in_conversation():
    orchestrator = AudioOrchestrator(wakeword_enabled_cfg=True)
    ears = EarsStub(wakeword_enabled=True)

    assert orchestrator.should_wait_for_wakeword(in_conversation=False, ears=ears) is True
    assert orchestrator.should_wait_for_wakeword(in_conversation=True, ears=ears) is False


def test_normalize_listen_result_accepts_tuple():
    outcome = AudioOrchestrator.normalize_listen_result(("你好", "happy"))

    assert outcome == AudioListenOutcome(text="你好", emotion="happy")
    assert outcome.has_input is True


def test_decide_after_empty_input_returns_idle_when_not_always_listen():
    orchestrator = AudioOrchestrator(wakeword_enabled_cfg=True)
    decision = orchestrator.decide_after_empty_input(
        in_conversation=True,
        ears=EarsStub(wakeword_enabled=True),
    )

    assert decision.next_ui_state == "IDLE"
    assert decision.keep_in_conversation is False


def test_should_interrupt_for_text_input_only_while_speaking():
    assert AudioOrchestrator.should_interrupt_for_text_input("SPEAKING") is True
    assert AudioOrchestrator.should_interrupt_for_text_input("LISTENING") is False


def test_should_enable_voice_barge_in_requires_ears():
    assert AudioOrchestrator.should_enable_voice_barge_in(text_only_mode=False, ears=EarsStub(True)) is True
    assert AudioOrchestrator.should_enable_voice_barge_in(text_only_mode=True, ears=EarsStub(True)) is False
    assert AudioOrchestrator.should_enable_voice_barge_in(text_only_mode=False, ears=None) is False
