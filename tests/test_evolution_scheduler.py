"""T09: idle-time self-evolution is opt-in, failure-triggered and budget-capped."""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

from core.evolution.scheduler import EvolutionScheduler, subprocess_launcher

ROOT = Path(__file__).resolve().parents[1]


import pytest


@pytest.fixture(autouse=True)
def _private_ledger(tmp_path, monkeypatch):
    # The scheduler now charges the global teacher ledger; never touch the real one in tests.
    monkeypatch.setenv("KAGE_TEACHER_LEDGER", str(tmp_path / "teacher-ledger.sqlite"))


def _session(last=None):
    s = MagicMock()
    s.get_last_user_time.return_value = last
    return s


def _fake_launcher(calls, *, cost=0.01, promoted=True, raise_exc=None):
    async def launcher(config_path, provider, runner, timeout_s):
        calls.append({"config": json.loads(Path(config_path).read_text()), "provider": provider, "runner": runner})
        if raise_exc:
            raise raise_exc
        out = Path(config_path).parent / "fixture" / "pilot" / "seed-42"
        out.mkdir(parents=True)
        (out / "report.json").write_text(json.dumps({
            "stop_reason": "dev_passed", "estimated_cost_usd": cost,
            "comparisons": [{"promoted": promoted}],
            "active_candidate": {"candidate_id": "skill-x", "digest": "d" * 64},
        }))
        return {"returncode": 0}
    return launcher


def _scheduler(tmp_path, calls, clock, last=None, **cfg):
    config = {"auto": True, "idle_minutes": 30, **cfg}
    return EvolutionScheduler(config, _session(last), workspace_dir=str(tmp_path),
                              launcher=_fake_launcher(calls, **{k: v for k, v in cfg.items() if k in ()}),
                              now_fn=lambda: clock[0])


def _run_to_end(scheduler):
    async def scenario():
        run_id = scheduler.start()
        if scheduler._task:
            await scheduler._task
        return run_id
    return asyncio.run(scenario())


def test_disabled_by_default(tmp_path):
    s = EvolutionScheduler(None, _session(), workspace_dir=str(tmp_path))
    assert s.should_run() == (False, "disabled")


def test_requires_idle_user_and_new_failures(tmp_path):
    clock = [1_800_000_000.0]
    calls = []
    s = _scheduler(tmp_path, calls, clock, last=clock[0] - 60)
    s.note_failure({"task_id": "preferences_dev", "run_id": "r1", "status": "failed"})
    assert s.should_run() == (False, "user_active")
    s.session.get_last_user_time.return_value = clock[0] - 3600
    assert s.should_run() == (True, "")
    s2 = _scheduler(tmp_path / "other", calls, clock)
    assert s2.should_run() == (False, "no_new_failures")


def test_run_records_outcome_consumes_failures_and_caps_budget(tmp_path):
    clock = [1_800_000_000.0]
    calls = []
    s = _scheduler(tmp_path, calls, clock, daily_budget_usd=0.03)
    s.note_failure({"task_id": "t", "run_id": "r1", "status": "unknown"})
    assert _run_to_end(s)
    assert calls[0]["config"]["budget"]["max_cost_usd"] <= 0.03
    assert calls[0]["config"]["output_dir"].startswith(str(tmp_path))
    finished = [r for r in s.runs() if r["event"] == "finished"][0]
    assert finished["promoted"] is True and finished["cost_usd"] == 0.01
    assert finished["active_candidate"]["candidate_id"] == "skill-x"
    assert s._state()["pending_failures"] == []
    started = [r for r in s.runs() if r["event"] == "started"][0]
    assert started["failures"][0]["task_id"] == "t"


def test_daily_run_limit_and_budget(tmp_path):
    clock = [1_800_000_000.0]
    calls = []
    s = _scheduler(tmp_path, calls, clock, max_runs_per_day=1)
    s.note_failure({"task_id": "t"})
    _run_to_end(s)
    s.note_failure({"task_id": "t2"})
    assert s.should_run() == (False, "daily_run_limit")
    clock[0] += 24 * 3600
    assert s.should_run() == (True, "")

    s3 = _scheduler(tmp_path / "b", calls, clock, max_runs_per_day=5, daily_budget_usd=0.01)
    s3.note_failure({"task_id": "t"})
    _run_to_end(s3)  # fake run reports $0.01
    s3.note_failure({"task_id": "t"})
    assert s3.should_run() == (False, "daily_budget")


def test_launcher_error_is_recorded_not_raised(tmp_path):
    clock = [1_800_000_000.0]
    s = EvolutionScheduler({"auto": True}, _session(), workspace_dir=str(tmp_path),
                           launcher=_fake_launcher([], raise_exc=RuntimeError("docker missing")),
                           now_fn=lambda: clock[0])
    s.note_failure({"task_id": "t"})
    _run_to_end(s)
    finished = [r for r in s.runs() if r["event"] == "finished"][0]
    assert "docker missing" in finished["error"] and finished["promoted"] is False


def test_only_one_run_at_a_time(tmp_path):
    clock = [1_800_000_000.0]
    gate = asyncio.Event

    async def scenario():
        release = gate()

        async def slow(config_path, provider, runner, timeout_s):
            await release.wait()
            return {"returncode": 0}

        s = EvolutionScheduler({"auto": True, "max_runs_per_day": 5}, _session(), workspace_dir=str(tmp_path),
                               launcher=slow, now_fn=lambda: clock[0])
        s.note_failure({"task_id": "a"})
        assert s.start()
        s.note_failure({"task_id": "b"})
        assert s.should_run() == (False, "running")
        release.set()
        await s._task

    asyncio.run(scenario())


def test_real_subprocess_launcher_runs_fixture_search(tmp_path):
    """End-to-end with the real CLI on the trusted fixture provider (no Docker)."""
    clock = [1_800_000_000.0]
    s = EvolutionScheduler({"auto": True, "provider": "fixture", "runner": "process", "run_timeout_s": 120},
                           _session(), workspace_dir=str(tmp_path), launcher=subprocess_launcher,
                           now_fn=lambda: clock[0])
    s.note_failure({"task_id": "t"})
    _run_to_end(s)
    finished = [r for r in s.runs() if r["event"] == "finished"][0]
    assert finished["returncode"] == 0, finished
    assert finished["promoted"] is True
    assert finished["report_path"].startswith(str(tmp_path))


# ---------------------------------------------------------------------------
# T11: report what was practiced, including runs without improvement
# ---------------------------------------------------------------------------

def _finished(s, clock, run_id, **fields):
    clock[0] += 1
    s._log({"event": "finished", "run_id": run_id, **fields})


def test_report_summarises_new_runs_once_and_offers_adoption(tmp_path):
    clock = [1_800_000_000.0]
    s = EvolutionScheduler({"auto": True}, _session(), workspace_dir=str(tmp_path), now_fn=lambda: clock[0])
    assert s.report_notifications() == []
    _finished(s, clock, "r1", returncode=0, promoted=False)
    _finished(s, clock, "r2", returncode=0, promoted=True)
    _finished(s, clock, "r3", returncode=None, error="timeout", promoted=False)
    [note] = s.report_notifications()
    assert "练习了 3 次" in note["content"]
    assert "1 次找到了" in note["content"] and "1 次没有比原来更好" in note["content"] and "1 次没跑完" in note["content"]
    assert note["action"] == {"type": "adopt_skill", "run_id": "r2"}
    assert s.report_notifications() == []  # announced once


def test_report_without_promotion_has_no_action(tmp_path):
    clock = [1_800_000_000.0]
    s = EvolutionScheduler({"auto": True}, _session(), workspace_dir=str(tmp_path), now_fn=lambda: clock[0])
    _finished(s, clock, "r1", returncode=0, promoted=False)
    [note] = s.report_notifications()
    assert "action" not in note and "没有比原来更好" in note["content"]


def test_collect_reports_through_heartbeat(tmp_path):
    from core.heartbeat import Heartbeat

    clock = [1_800_000_000.0]
    s = EvolutionScheduler({"auto": False}, _session(), workspace_dir=str(tmp_path), now_fn=lambda: clock[0])
    _finished(s, clock, "r9", returncode=0, promoted=True)
    delivered = []

    async def deliver(notes):
        delivered.extend(notes)

    hb = Heartbeat(MagicMock(), _session(), workspace_dir=str(tmp_path), on_notifications=deliver, sources=[s])
    asyncio.run(hb._run_once())
    assert [n["type"] for n in delivered] == ["evolution_report"]


def test_runs_are_capped_by_and_charged_to_the_global_ledger(tmp_path):
    from core.evolution.teacher_budget import global_teacher_budget, remaining_usd
    calls, clock = [], [10_000.0]
    sched = _scheduler(tmp_path, calls, clock, daily_budget_usd=5.0)
    sched.note_failure({"task_id": "t", "run_id": "r1", "status": "unknown"})
    assert _run_to_end(sched)
    assert calls[0]["config"]["budget"]["max_cost_usd"] <= 1.0          # global remainder, not the daily 5.0
    assert abs(remaining_usd(global_teacher_budget()) - 3.99) < 1e-4    # fake run cost 0.01 charged (cap US$4)
