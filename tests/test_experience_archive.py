"""Only verified dev evidence with intact artifacts can enter student retrieval."""
from pathlib import Path
from core.evolution.archive import ExperienceArchive
from core.evolution.contracts import RunResult
from core.evolution.journal import Journal


def result(workspace, run_id="r", status="passed", score=1):
    trace = workspace / f"{run_id}.jsonl"
    trace.write_text('{"action":{"name":"write_file"},"observation":{"success":true}}\n')
    return RunResult(run_id, status, score, str(trace), final_state_path=str(workspace), metadata={"model": "fixture"})


def test_restart_deduplicates_and_never_retrieves_failed_or_holdout_evidence(tmp_path):
    archive = ExperienceArchive(Journal(tmp_path / "journal.sqlite"))
    ws = tmp_path / "workspace"; ws.mkdir(); (ws / "out.json").write_text("[2]")
    archive.record({"task_id": "dev", "family": "csv", "split": "dev", "instruction": "Transform"}, result(ws))
    archive.record({"task_id": "dev", "family": "csv", "split": "dev", "instruction": "Transform"}, result(ws))
    archive.record({"task_id": "test", "family": "csv", "split": "holdout"}, result(ws, "h"))
    archive.record({"task_id": "failed", "family": "csv", "split": "dev"}, result(ws, "f", "failed", 0))
    archive.record({"task_id": "dev", "family": "csv", "split": "dev", "instruction": "Transform"}, result(ws, "r2"))
    resumed = ExperienceArchive(Journal(tmp_path / "journal.sqlite"))
    assert [x["task_id"] for x in resumed.retrieve("csv")] == ["dev"]
    assert len(resumed.list_episodes()) == 4


def test_changed_or_missing_evidence_is_stale_and_not_used_for_learning(tmp_path):
    archive = ExperienceArchive(Journal(tmp_path / "journal.sqlite"))
    ws = tmp_path / "workspace"; ws.mkdir(); (ws / "out.json").write_text("[2]")
    archive.record({"task_id": "dev", "family": "csv", "split": "dev"}, result(ws))
    (ws / "out.json").write_text("[9]")
    assert archive.retrieve("csv") == []
    assert archive.list_episodes()[0]["status"] == "stale"


def test_retrieval_requires_matching_failure_and_environment_when_requested(tmp_path):
    archive = ExperienceArchive(Journal(tmp_path / "journal.sqlite"))
    for run_id, failure, platform in [("a", "call_limit", "mac-v1"), ("b", "incomplete", "mac-v2"), ("c", "call_limit", "mac-v2")]:
        ws = tmp_path / run_id; ws.mkdir(); (ws / "out.json").write_text("[2]")
        run = result(ws, run_id)
        run.metadata.update(environment={"platform": platform}, chain=[{"takeover": {"student_check": {"status": failure}}}])
        archive.record({"task_id": run_id, "family": "code", "split": "dev"}, run)
    matches = archive.retrieve("code", failure_status="call_limit", environment={"platform": "mac-v2"})
    assert [e["task_id"] for e in matches] == ["c"]


def test_existing_file_episode_setup_does_not_change_with_browser_extension(tmp_path):
    archive=ExperienceArchive(Journal(tmp_path/'journal.sqlite'))
    workspace=tmp_path/'file-run';workspace.mkdir();(workspace/'out.json').write_text('{}')
    run=result(workspace)
    task={'task_id':'legacy','family':'code','split':'dev','instruction':'write file'}
    episode_id=archive.record(task,run)
    assert archive.record({**task,'scoring_criteria':{'type':'json_exact_match'}},run)==episode_id
