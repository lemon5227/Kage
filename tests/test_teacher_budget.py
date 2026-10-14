import pytest

from core.evolution.budget import BudgetExhaustedError
from core.evolution.teacher_budget import global_teacher_budget, remaining_usd


def test_ledger_is_shared_and_cap_survives_new_trackers(tmp_path, monkeypatch):
    monkeypatch.setenv('KAGE_TEACHER_LEDGER', str(tmp_path / 'ledger.sqlite'))
    first = global_teacher_budget()
    rid = first.reserve(200_000, 200_000, call_type='optimizer')   # reserve $0.30
    first.settle(rid, {'input_tokens': 200_000, 'output_tokens': 200_000})
    second = global_teacher_budget()                                 # new experiment, same ledger
    assert remaining_usd(second) == pytest.approx(0.70)
    with pytest.raises(BudgetExhaustedError):
        second.reserve(1_000_000, 500_000)                            # +$0.90 would exceed $1
    assert second.can_reserve(100_000, 100_000)


def test_cap_cannot_exceed_user_authorisation(tmp_path, monkeypatch):
    monkeypatch.setenv('KAGE_TEACHER_LEDGER', str(tmp_path / 'l.sqlite'))
    with pytest.raises(ValueError):
        global_teacher_budget(5.0)
