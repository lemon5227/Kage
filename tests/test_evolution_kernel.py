"""
Unit and integration tests for Kage EvoLab Fixed Kernel (E0 package).
Validates contracts, budget reservation/settlement, journal resume idempotency,
workspace fixture reset, stagnation observation, and CLI baseline execution.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from core.evolution.budget import BudgetConfig, BudgetExhaustedError, BudgetTracker
from core.evolution.contracts import Candidate, RunSpec
from core.evolution.journal import Journal
from core.evolution.progress import ProgressTracker
from core.evolution.runner import EvolutionRunner, FakeEvolutionProvider
from scripts.kage_evolve import run_baseline


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

    res1 = runner.run(candidate, task1, RunSpec(run_id="run_leak_1", candidate_id="c1", task_id="task_1"))
    res2 = runner.run(candidate, task2, RunSpec(run_id="run_leak_2", candidate_id="c1", task_id="task_2"))

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
    assert "run_smoke_normalize_fields_baseline" in completed
    assert "run_smoke_missing_field_baseline" in completed
