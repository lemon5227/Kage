"""A3: real-use teacher calls go through the global ledger and stop at the daily cap."""
import pytest

from core.evolution.real_teacher import DailyCapReached, LedgeredTeacher
from core.evolution.teacher_budget import global_teacher_budget, remaining_usd
from core.model_provider import ModelResponse


class Cloud:
    model_name = 'deepseek-flash'

    def __init__(self):
        self.calls = 0

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        self.calls += 1
        return ModelResponse(text='done', usage={'input_tokens': 1000, 'output_tokens': 200})


def test_calls_are_charged_and_stop_at_the_daily_cap(tmp_path, monkeypatch):
    monkeypatch.setenv('KAGE_TEACHER_LEDGER', str(tmp_path / 'ledger.sqlite'))
    cloud = Cloud()
    t = LedgeredTeacher(daily_usd=0.004, inner=cloud, state_path=tmp_path / 'daily.json')
    before = remaining_usd(global_teacher_budget())
    msgs = [{'role': 'user', 'content': 'x' * 300}]
    with pytest.raises(DailyCapReached):
        for _ in range(20):
            t.generate(messages=msgs, max_tokens=1024)
    assert 1 <= cloud.calls < 20
    spent = before - remaining_usd(global_teacher_budget())
    per_call = (1000 * 0.30 + 200 * 1.20) / 1e6
    assert spent == pytest.approx(cloud.calls * per_call, rel=1e-3)
    assert t.spent_today() == pytest.approx(spent, rel=1e-3) and t.spent_today() <= 0.004


def test_global_ledger_refusal_becomes_daily_cap(tmp_path, monkeypatch):
    monkeypatch.setenv('KAGE_TEACHER_LEDGER', str(tmp_path / 'ledger.sqlite'))
    monkeypatch.setenv('KAGE_TEACHER_CAP_USD', '0.0005')
    t = LedgeredTeacher(daily_usd=1.0, inner=Cloud(), state_path=tmp_path / 'daily.json')
    with pytest.raises(DailyCapReached):
        t.generate(messages=[{'role': 'user', 'content': 'hi'}], max_tokens=1024)
