"""
Unit and integration tests for Kage EvoLab Fixed Kernel (E0 package).
Validates contracts, budget reservation/settlement, journal resume idempotency,
workspace fixture reset, stagnation observation, and CLI baseline execution.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core.evolution.budget import BudgetConfig, BudgetExhaustedError, BudgetTracker
from core.evolution.contracts import Candidate, RunSpec
from core.evolution.journal import Journal
from core.evolution.progress import ProgressTracker
from core.evolution.runner import EvolutionRunner, FakeEvolutionProvider
from scripts.kage_evolve import run_baseline


class SlowProvider:
    def generate_step(self, task_def, step, history, workspace_dir):
        time.sleep(2)
        return {"action": {"name": "finish"}, "usage": {"input_tokens": 1, "output_tokens": 1}}


class InspectingProvider:
    def generate_step(self, task_def, step, history, workspace_dir):
        assert "scoring_criteria" not in task_def
        assert "expected_output_file" not in task_def
        return {"action": {"name": "finish"}, "usage": {"input_tokens": 0, "output_tokens": 0}}


class CrashingProvider:
    def generate_step(self, task_def, step, history, workspace_dir):
        raise RuntimeError("provider failed")


class DescendantProvider:
    def generate_step(self, task_def, step, history, workspace_dir):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (workspace_dir / "descendant.pid").write_text(str(child.pid))
        return {"action": {"name": "finish"}, "usage": {"input_tokens": 1, "output_tokens": 1}}


def _candidate(tmp_path):
    return Candidate("review_candidate", (), "workflow", str(tmp_path), "sha256:review")


def test_fake_provider_uses_fixture_instead_of_hardcoded_answer(tmp_path):
    task = {
        "task_id": "smoke_normalize_fields",
        "initial_files": {"raw_records.json": '[{"ID": 7, "Full_Name": "Eve", "Points": 13}]'},
        "scoring_criteria": {"type": "json_exact_match", "file": "normalized_records.json", "expected": [{"id": 7, "name": "Eve", "score": 13}]},
    }
    runner = EvolutionRunner(Journal(tmp_path / "journal.db"), BudgetTracker(), tmp_path / "ws")
    result = runner.run(_candidate(tmp_path), task, RunSpec("variable_fixture", "review_candidate", task["task_id"]))
    assert result.status == "passed"


def test_provider_cannot_see_scoring_answer(tmp_path):
    task = {"task_id": "private", "initial_files": {}, "scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": {}}}
    runner = EvolutionRunner(Journal(tmp_path / "journal.db"), BudgetTracker(), tmp_path / "ws", InspectingProvider())
    assert runner.run(_candidate(tmp_path), task, RunSpec("hidden_answer", "review_candidate", "private")).status == "failed"


def test_slow_provider_is_stopped_by_timeout(tmp_path):
    task = {"task_id": "slow", "initial_files": {}, "scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": {}}}
    runner = EvolutionRunner(Journal(tmp_path / "journal.db"), BudgetTracker(), tmp_path / "ws", SlowProvider())
    start = time.monotonic()
    result = runner.run(_candidate(tmp_path), task, RunSpec("slow_run", "review_candidate", "slow", timeout_s=0.1))
    assert result.status == "timeout"
    assert time.monotonic() - start < 1.0
    assert result.usage["input_tokens"] == 2000
    assert result.usage["output_tokens"] == 1000


def test_crashed_call_reports_conservative_usage(tmp_path):
    task = {"task_id": "crash", "initial_files": {}, "scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": {}}}
    runner = EvolutionRunner(Journal(tmp_path / "journal.db"), BudgetTracker(), tmp_path / "ws", CrashingProvider())
    result = runner.run(_candidate(tmp_path), task, RunSpec("crashed_run", "review_candidate", "crash"))
    assert result.status == "crashed"
    assert result.usage["input_tokens"] == 2000


def test_task_run_id_cannot_escape_workspace_root(tmp_path):
    task = {"task_id": "escape", "initial_files": {}, "scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": {}}}
    runner = EvolutionRunner(Journal(tmp_path / "journal.db"), BudgetTracker(), tmp_path / "ws")
    with pytest.raises(ValueError, match="run_id"):
        runner.run(_candidate(tmp_path), task, RunSpec("../escape", "review_candidate", "escape"))


def test_provider_descendants_stopped_after_success(tmp_path):
    task = {"task_id": "child", "initial_files": {}, "scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": {}}}
    runner = EvolutionRunner(Journal(tmp_path / "journal.db"), BudgetTracker(), tmp_path / "ws", DescendantProvider())
    result = runner.run(_candidate(tmp_path), task, RunSpec("descendant_run", "review_candidate", "child"))
    pid = int((Path(result.final_state_path) / "descendant.pid").read_text())
    def still_running() -> bool:
        state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="],
                               capture_output=True, text=True).stdout.strip()
        return bool(state) and not state.startswith("Z")
    try:
        for _ in range(20):
            if not still_running():
                break
            time.sleep(0.02)
        assert not still_running()
    finally:
        if still_running():
            os.kill(pid, signal.SIGKILL)


def test_budget_persists_settlement_and_conservative_pending(tmp_path):
    path = tmp_path / "budget.db"
    config = BudgetConfig(max_input_tokens_total=100, max_output_tokens_total=100, max_api_calls=2)
    budget = BudgetTracker(config, db_path=path)
    settled = budget.reserve(20, 10)
    budget.settle(settled, {"input_tokens": 0, "output_tokens": 0})
    pending = budget.reserve(30, 15)
    assert pending
    restarted = BudgetTracker(config, db_path=path)
    assert restarted.total_input_tokens == 30
    assert restarted.total_output_tokens == 15
    assert restarted.total_api_calls == 2
    assert not restarted.can_reserve(1, 1)


def test_reported_provider_usage_above_estimate_is_not_truncated():
    budget = BudgetTracker(BudgetConfig(max_input_tokens_total=300, max_output_tokens_total=300))
    reservation = budget.reserve(100, 100)
    budget.settle(reservation, {"input_tokens": 140, "output_tokens": 120})
    assert budget.total_input_tokens == 140
    assert budget.total_output_tokens == 120


def test_malformed_provider_usage_is_charged_conservatively():
    budget = BudgetTracker()
    reservation = budget.reserve(100, 50)
    budget.settle(reservation, {"input_tokens": "unknown", "output_tokens": 2})
    assert budget.total_input_tokens == 100
    assert budget.total_output_tokens == 50


def test_run_id_cannot_reuse_different_task_definition(tmp_path):
    journal = Journal(tmp_path / "journal.db")
    runner = EvolutionRunner(journal, BudgetTracker(), tmp_path / "ws")
    task = {"task_id": "same", "initial_files": {}, "scoring_criteria": {"type": "json_exact_match", "file": "x.json", "expected": {}}}
    spec = RunSpec("same_run", "review_candidate", "same")
    runner.run(_candidate(tmp_path), task, spec)
    changed = dict(task, initial_files={"new.txt": "changed"})
    with pytest.raises(ValueError, match="run_id"):
        runner.run(_candidate(tmp_path), changed, spec)


def test_duplicate_items_cannot_inflate_partial_score(tmp_path):
    from core.evolution.runner import Evaluator
    (tmp_path / "out.json").write_text('[{"x": 1}, {"x": 1}, {"x": 1}]')
    task = {"scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": [{"x": 1}, {"x": 2}]}}
    assert Evaluator.score(task, tmp_path) <= 0.5


def test_partial_match_never_counts_as_exact_pass(tmp_path):
    from core.evolution.runner import Evaluator
    (tmp_path / "out.json").write_text('[{"x": 1}, {"x": 2}, {"x": 3}]')
    task = {"scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": [{"x": 1}, {"x": 2}]}}
    assert Evaluator.score(task, tmp_path) < 1.0


def test_cli_live_mode_requires_credentials_and_does_not_fall_back(tmp_path):
    """Live mode is wired to the real chain: without credentials it must exit 2
    and never silently substitute the fake provider."""
    smoke_suite = Path(__file__).resolve().parent.parent / "eval" / "evolution" / "smoke.json"
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({
        "model": {"cloud_api": {"api_key": "", "provider_type": "openai"},
                  "broker": {"background_provider": "cloud"}}
    }), encoding="utf-8")
    out_dir = tmp_path / "cli"

    code = run_baseline(smoke_suite, provider_name="live", output_dir=out_dir,
                        config_path=str(config), api_key_env="KAGE_TEST_ABSENT_KEY",
                        quiet=True)

    assert code != 0
    # Nothing may have executed, and no report may claim a live result.
    from core.evolution.journal import Journal
    assert Journal(out_dir / "journal.db").get_completed_run_ids() == set()
    assert not (out_dir / "report.json").exists()


@pytest.fixture
def budget():
    return BudgetTracker(
        BudgetConfig(
            max_input_tokens_total=1000,
            max_output_tokens_total=200,
            max_api_calls=5,
        )
    )


def test_budget_refuses_overcommit(budget):
    """Verify that budget refuses reservations that exceed configured caps."""
    res_id = budget.reserve(input_cap=800, output_cap=100)
    assert res_id is not None
    assert budget.can_reserve(input_cap=800, output_cap=100) is False

    with pytest.raises(BudgetExhaustedError):
        budget.reserve(input_cap=800, output_cap=100)


def test_budget_settlement_and_conservative_crashed_handling(budget):
    """Verify settlement with actual usage and conservative settlement for crashed calls."""
    # 1. Normal settlement with actual usage
    res1 = budget.reserve(input_cap=500, output_cap=100)
    budget.settle(res1, {"input_tokens": 120, "output_tokens": 30})
    assert budget.total_input_tokens == 120
    assert budget.total_output_tokens == 30

    # 2. Conservative settlement for failed/crashed call (None usage)
    res2 = budget.reserve(input_cap=400, output_cap=50)
    budget.settle(res2, None)
    # Conservatively charged full 400 + 50
    assert budget.total_input_tokens == 120 + 400
    assert budget.total_output_tokens == 30 + 50


def test_resume_skips_finished_run(tmp_path):
    """Verify that resuming an experiment skips already-completed runs without duplicate calls."""
    db_path = tmp_path / "journal.db"
    journal = Journal(db_path)
    budget = BudgetTracker(BudgetConfig(max_input_tokens_total=50_000, max_output_tokens_total=10_000))
    provider = FakeEvolutionProvider(mode="baseline")

    runner = EvolutionRunner(
        journal=journal,
        budget=budget,
        base_dir=tmp_path / "workspaces",
        provider=provider,
    )

    candidate = Candidate(
        candidate_id="c_test_0",
        parent_ids=(),
        target="workflow",
        bundle_path=str(tmp_path),
        digest="sha256:abc12345",
    )
    task_def = {
        "task_id": "smoke_normalize_fields",
        "initial_files": {"raw_records.json": "[]"},
        "scoring_criteria": {"type": "json_exact_match", "file": "normalized_records.json", "expected": []},
    }
    spec = RunSpec(run_id="run_resume_test_1", candidate_id=candidate.candidate_id, task_id="smoke_normalize_fields")

    # Run once
    result1 = runner.run(candidate, task_def, spec)
    assert result1 is not None
    initial_calls = provider.calls
    assert initial_calls > 0
    assert journal.is_run_completed(spec.run_id) is True

    # Run a second time with identical run_id
    result2 = runner.run(candidate, task_def, spec)
    assert result2.run_id == result1.run_id
    # Provider was NOT invoked again
    assert provider.calls == initial_calls


def test_deterministic_tasks_fixture_reset_no_leakage(tmp_path):
    """Verify that each task run gets a clean workspace without residue from previous runs."""
    journal = Journal(tmp_path / "journal.db")
    budget = BudgetTracker(BudgetConfig(max_input_tokens_total=50_000, max_output_tokens_total=10_000))
    runner = EvolutionRunner(journal=journal, budget=budget, base_dir=tmp_path / "workspaces")

    candidate = Candidate(
        candidate_id="c_test_fixture",
        parent_ids=(),
        target="skill",
        bundle_path=str(tmp_path),
        digest="sha256:fix12345",
    )

    task1 = {
        "task_id": "task_1",
        "initial_files": {"task1_only.txt": "hello from task 1"},
        "scoring_criteria": {"type": "json_exact_match", "file": "task1_out.json", "expected": {}},
    }
    task2 = {
        "task_id": "task_2",
        "initial_files": {"task2_only.txt": "hello from task 2"},
        "scoring_criteria": {"type": "json_exact_match", "file": "task2_out.json", "expected": {}},
    }

    res1 = runner.run(candidate, task1, RunSpec(run_id="run_leak_1", candidate_id=candidate.candidate_id, task_id="task_1"))
    res2 = runner.run(candidate, task2, RunSpec(run_id="run_leak_2", candidate_id=candidate.candidate_id, task_id="task_2"))

    ws1 = Path(res1.final_state_path)
    ws2 = Path(res2.final_state_path)

    assert (ws1 / "task1_only.txt").exists()
    assert not (ws1 / "task2_only.txt").exists()

    assert (ws2 / "task2_only.txt").exists()
    assert not (ws2 / "task1_only.txt").exists()


def test_progress_tracker_stagnation_detection():
    """Verify that repeated identical actions and observations trigger stagnation."""
    tracker = ProgressTracker(stagnation_threshold=3)

    action = {"name": "read_file", "path": "test.txt"}
    obs = {"status": "ok", "content": "same content"}

    # Step 1: new evidence
    res1 = tracker.observe(action, obs)
    assert res1["new_evidence"] is True
    assert res1["stagnant"] is False

    # Step 2: repeat, no new evidence
    res2 = tracker.observe(action, obs)
    assert res2["repeated_cycle"] is True
    assert res2["stagnant"] is False
    assert res2["repeat_count"] == 2

    # Step 3: repeat reaches threshold of 3 -> stagnation!
    res3 = tracker.observe(action, obs)
    assert res3["repeated_cycle"] is True
    assert res3["stagnant"] is True
    assert res3["repeat_count"] == 3

    # Step 4: new observation breaks stagnation
    new_obs = {"status": "ok", "content": "brand new information!"}
    res4 = tracker.observe(action, new_obs)
    assert res4["new_evidence"] is True
    assert res4["stagnant"] is False


def test_budget_exhaustion_halts_runner(tmp_path):
    """Verify that running out of budget immediately records budget_stop and halts cleanly."""
    journal = Journal(tmp_path / "journal.db")
    # Tiny budget that allows 0 reservations
    budget = BudgetTracker(BudgetConfig(max_input_tokens_total=10, max_output_tokens_total=10))
    runner = EvolutionRunner(journal=journal, budget=budget, base_dir=tmp_path / "workspaces")

    candidate = Candidate(
        candidate_id="c_exhaust",
        parent_ids=(),
        target="recovery",
        bundle_path=str(tmp_path),
        digest="sha256:exhaust1",
    )
    task_def = {
        "task_id": "task_exhaust",
        "initial_files": {},
        "scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": {}},
    }
    spec = RunSpec(run_id="run_exhaust_test", candidate_id=candidate.candidate_id, task_id="task_exhaust")

    res = runner.run(candidate, task_def, spec)
    assert res.status == "budget_exhausted"

    events = journal.get_events(spec.run_id)
    assert any(e.event_type == "budget_stop" for e in events)


def test_cli_baseline_execution(tmp_path):
    """Verify that CLI run_baseline executes cleanly on smoke suite."""
    smoke_suite = Path(__file__).resolve().parent.parent / "eval" / "evolution" / "smoke.json"
    assert smoke_suite.exists(), f"Suite missing at {smoke_suite}"

    out_dir = tmp_path / "cli_run"
    db_path = out_dir / "journal.db"

    exit_code = run_baseline(
        suite_path=smoke_suite,
        provider_name="fake",
        db_path=db_path,
        output_dir=out_dir,
    )
    assert exit_code == 0
    assert db_path.exists()

    journal = Journal(db_path)
    completed = journal.get_completed_run_ids()
    assert len(completed) == 2
    assert any(run.startswith("run_smoke_normalize_fields_baseline_") for run in completed)
    assert any(run.startswith("run_smoke_missing_field_baseline_") for run in completed)
