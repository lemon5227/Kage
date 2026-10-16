import pytest

from core.evolution.budget import BudgetExhaustedError
from core.evolution.teacher_budget import global_teacher_budget, remaining_usd


def test_ledger_is_shared_and_cap_survives_new_trackers(tmp_path, monkeypatch):
    monkeypatch.setenv('KAGE_TEACHER_LEDGER', str(tmp_path / 'ledger.sqlite'))
    first = global_teacher_budget()
    rid = first.reserve(200_000, 200_000, call_type='optimizer')   # reserve $0.30
    first.settle(rid, {'input_tokens': 200_000, 'output_tokens': 200_000})
    second = global_teacher_budget()                                 # new experiment, same ledger
    assert remaining_usd(second) == pytest.approx(3.70)                # user cap US$4 since 2026-10-16
    with pytest.raises(BudgetExhaustedError):
        second.reserve(3_000_000, 3_000_000)                          # +$4.50 would exceed $4
    assert second.can_reserve(100_000, 100_000)


def test_cap_cannot_exceed_user_authorisation(tmp_path, monkeypatch):
    monkeypatch.setenv('KAGE_TEACHER_LEDGER', str(tmp_path / 'l.sqlite'))
    with pytest.raises(ValueError):
        global_teacher_budget(4.5)


def test_charge_external_counts_against_the_global_cap(tmp_path, monkeypatch):
    from core.evolution.teacher_budget import charge_external, global_teacher_budget, remaining_usd
    monkeypatch.setenv('KAGE_TEACHER_LEDGER', str(tmp_path / 'ledger.sqlite'))
    charge_external(global_teacher_budget(), 0.05, run_id='scheduler-run-1')
    assert abs(remaining_usd(global_teacher_budget()) - 3.95) < 1e-4
    charge_external(global_teacher_budget(), 0.0, run_id='free')
    assert abs(remaining_usd(global_teacher_budget()) - 3.95) < 1e-4


def test_remote_allocation_cap_from_env(tmp_path, monkeypatch):
    from core.evolution.teacher_budget import global_teacher_budget, remaining_usd
    monkeypatch.setenv('KAGE_TEACHER_LEDGER', str(tmp_path / 'remote.sqlite'))
    monkeypatch.setenv('KAGE_TEACHER_CAP_USD', '0.4')
    assert abs(remaining_usd(global_teacher_budget()) - 0.4) < 1e-9
