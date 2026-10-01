"""Changing the experiment prompt must invalidate a journaled run."""
import pytest
from core.evolution.contracts import RunSpec
from test_evolution_agent_chain import _runner, _candidate, _suite, _chain_provider, ScriptedChainModel


def test_prompt_change_cannot_silently_reuse_old_external_score(tmp_path, monkeypatch):
    provider = _chain_provider(ScriptedChainModel())
    runner, _ = _runner(tmp_path, provider, isolation="inline")
    candidate = _candidate(tmp_path)
    task = _suite()["tasks"][0]
    spec = RunSpec("prompt-cache", candidate.candidate_id, task["task_id"])
    first = runner.run(candidate, task, spec)
    assert first.status == "passed"
    import core.evolution.agent_provider as module
    monkeypatch.setattr(module, "EXPERIMENT_SOUL", module.EXPERIMENT_SOUL + "\nNew skill discovery policy.")
    with pytest.raises(ValueError):
        runner.run(candidate, task, spec)
