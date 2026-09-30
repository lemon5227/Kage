"""E1: candidate-bound executable skills produce real task artifacts."""

import asyncio
import hashlib
import importlib.util
import json

import pytest

from core.agentic_loop import AgenticLoop
from core.evolution.agent_provider import ExperimentIdentityStore, HistorySession
from core.model_provider import ModelResponse
from core.prompt_builder import PromptBuilder
from core.tool_executor import ToolExecutor
from core.tool_registry import ToolRegistry


SCHEMA = {"type": "object", "properties": {
    "records": {"type": "array", "items": {"type": "object"}},
}, "required": ["records"], "additionalProperties": False}
CODE = '''import json
from pathlib import Path
def run(arguments, context):
    rows = [{"id": r["ID"], "name": r["Full_Name"].strip()} for r in arguments["records"]]
    Path(context["workspace_dir"], "normalized.json").write_text(json.dumps(rows))
    return {"success": True, "rows": rows}
'''


def _bundle(path, code=CODE):
    path.mkdir()
    descriptor = {"skill_id": "normalize", "description": "normalize record fields",
                  "parameters": SCHEMA, "entrypoint": "normalize.py:run"}
    digest = hashlib.sha256(
        json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode()
        + b"\n" + code.encode()).hexdigest()
    (path / "normalize.py").write_text(code)
    (path / "manifest.json").write_text(json.dumps({"version": 1, "skills": [
        {**descriptor, "digest": digest}]}))
    return digest


def _catalog(path, timeout_s=2):
    assert importlib.util.find_spec("core.evolution.skills"), "E1 executable skill catalog missing"
    from core.evolution.skills import SkillCatalog
    return SkillCatalog.from_bundle(path, timeout_s=timeout_s)


class _SkillModel:
    def __init__(self, records):
        self.records = records
        self.steps = 0
        self.discovered = None

    def generate(self, messages, tools=None, **kwargs):
        names = {t["function"]["name"] for t in tools or []}
        assert {"skill_search", "skill_call"} <= names
        self.steps += 1
        if self.steps == 1:
            return ModelResponse(text="", tool_calls=[{
                "name": "skill_search", "arguments": {"query": "normalize"}}])
        if self.steps == 2:
            observed = next(m["content"] for m in reversed(messages)
                            if m.get("content", "").startswith("[Tool: skill_search]"))
            self.discovered = json.loads(observed.split("] ", 1)[1])["skills"][0]
            return ModelResponse(text="", tool_calls=[{
                "name": "skill_call", "arguments": {
                    "skill_id": self.discovered["skill_id"], "digest": self.discovered["digest"],
                    "arguments": {"records": self.records}}}])
        return ModelResponse(text="normalized.json written")


def _run(catalog, workspace, rows):
    workspace.mkdir()
    registry = ToolRegistry()
    catalog.register_tools(registry, workspace)
    model = _SkillModel(rows)
    prompt = PromptBuilder(ExperimentIdentityStore(), None, registry,
                           prune_tools=True, memory_cfg={"recall_enabled": False})
    loop = AgenticLoop(model, ToolExecutor(registry, workspace_dir=str(workspace)),
                       prompt, HistorySession([]))
    result = asyncio.run(loop.run("normalize record fields"))
    return result, model


def test_manifest_to_model_to_subprocess_writes_output_and_reuses_on_unseen_input(tmp_path):
    bundle = tmp_path / "candidate"
    digest = _bundle(bundle)
    result, model = _run(_catalog(bundle), tmp_path / "first", [{"ID": 7, "Full_Name": " Ada "}])
    assert json.loads((tmp_path / "first/normalized.json").read_text()) == [{"id": 7, "name": "Ada"}]
    assert model.discovered["parameters"] == SCHEMA
    call = next(tc for tc in result.tool_calls_executed if tc["name"] == "skill_call")
    assert call["success"] and json.loads(call["result"])["digest"] == digest
    _run(_catalog(bundle), tmp_path / "second", [{"ID": 9, "Full_Name": " Grace "}])
    assert json.loads((tmp_path / "second/normalized.json").read_text()) == [{"id": 9, "name": "Grace"}]


def test_candidate_catalog_is_snapshot_and_parent_cannot_call_child_skill(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "manifest.json").write_text('{"version": 1, "skills": []}')
    child = tmp_path / "child"
    digest = _bundle(child)
    child_catalog = _catalog(child)
    (child / "normalize.py").write_text("raise RuntimeError('tampered')")
    workspace = tmp_path / "task"
    workspace.mkdir()
    refused = _catalog(parent).call("normalize", digest, {"records": []}, workspace)
    assert refused["success"] is False and refused["error"] == "UnknownSkill"
    assert child_catalog.call("normalize", digest, {"records": []}, workspace)["success"]
    with pytest.raises(ValueError, match="digest"):
        _catalog(child)


def test_invalid_arguments_and_wrong_digest_never_execute_skill(tmp_path):
    bundle = tmp_path / "candidate"
    digest = _bundle(bundle)
    catalog = _catalog(bundle)
    workspace = tmp_path / "task"
    workspace.mkdir()
    assert catalog.call("normalize", "wrong", {"records": []}, workspace)["error"] == "DigestMismatch"
    assert catalog.call("normalize", digest, {}, workspace)["error"] == "InvalidArgument"
    assert not (workspace / "normalized.json").exists()


def test_timeout_does_not_poison_next_skill_invocation(tmp_path):
    bundle = tmp_path / "candidate"
    code = 'def run(arguments, context):\n    if arguments["records"]:\n        while True: pass\n    return {"success": True, "value": 23}\n'
    digest = _bundle(bundle, code)
    catalog = _catalog(bundle, timeout_s=0.3)
    workspace = tmp_path / "task"
    workspace.mkdir()
    timed_out = catalog.call("normalize", digest, {"records": [{}]}, workspace)
    assert timed_out["success"] is False and timed_out["error"] == "Timeout"
    assert catalog.call("normalize", digest, {"records": []}, workspace)["value"] == 23


def test_e0_chain_provider_uses_candidate_catalog_and_records_digest(tmp_path):
    from core.evolution.agent_provider import KageChainProvider
    bundle = tmp_path / "candidate"
    digest = _bundle(bundle)
    catalog = _catalog(bundle)
    provider = KageChainProvider(_SkillModel([{"ID": 11, "Full_Name": " Lin "}]),
                                 provider_mode="test", skill_catalog=catalog)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = provider.generate_step({"task_id": "reuse", "instruction": "normalize record fields"},
                                    1, [], workspace)
    assert json.loads((workspace / "normalized.json").read_text()) == [{"id": 11, "name": "Lin"}]
    skill_call = next(tc for tc in result["tool_results"] if tc["name"] == "skill_call")
    assert json.loads(skill_call["result"])["digest"] == digest
    assert provider.metadata()["skills"] == {"normalize": digest}


def test_external_scoring_and_resume_bind_to_actual_skill_version(tmp_path):
    from core.evolution.agent_provider import KageChainProvider
    from core.evolution.budget import BudgetTracker
    from core.evolution.contracts import Candidate, RunSpec
    from core.evolution.journal import Journal
    from core.evolution.runner import EvolutionRunner
    bundle = tmp_path / "candidate"
    digest = _bundle(bundle)
    journal = Journal(tmp_path / "journal.sqlite")
    budget = BudgetTracker()
    task = {"task_id": "normalize", "instruction": "normalize record fields",
            "scoring_criteria": {"type": "json_exact_match", "file": "normalized.json",
                                 "expected": [{"id": 31, "name": "Edsger"}]}}
    candidate = Candidate("child", (), "skill", str(bundle), digest)
    spec = RunSpec("child-1", "child", "normalize")
    provider = KageChainProvider(_SkillModel([{"ID": 31, "Full_Name": " Edsger "}]),
                                 provider_mode="test", skill_catalog=_catalog(bundle))
    runner = EvolutionRunner(journal, budget, tmp_path / "runs", provider, step_isolation="inline")
    result = runner.run(candidate, task, spec)
    assert result.status == "passed" and result.score == 1.0
    assert result.metadata["skills"] == {"normalize": digest}
    calls = provider.calls
    assert runner.run(candidate, task, spec) == result and provider.calls == calls
    provider.skill_catalog.runner.timeout_s = 4
    with pytest.raises(ValueError, match="different"):
        runner.run(candidate, task, spec)
    provider.skill_catalog.runner.timeout_s = 2

    other = tmp_path / "other"
    _bundle(other, CODE + "\n# different candidate code\n")
    runner.provider = KageChainProvider(_SkillModel([]), provider_mode="test", skill_catalog=_catalog(other))
    with pytest.raises(ValueError, match="different"):
        runner.run(candidate, task, spec)


@pytest.mark.parametrize('skill_id,digest,error', [
    ('missing', 'wrong', 'UnknownSkill'), ('normalize', 'wrong', 'DigestMismatch'),
])
def test_invalid_skill_selection_is_a_rejection_not_an_execution_crash(tmp_path, skill_id, digest, error):
    bundle = tmp_path / 'bundle'
    _bundle(bundle)
    registry = ToolRegistry()
    workspace = tmp_path / 'workspace'
    _catalog(bundle).register_tools(registry, workspace)
    result = asyncio.run(ToolExecutor(registry, str(workspace)).execute('skill_call', {
        'skill_id': skill_id, 'digest': digest, 'arguments': {'records': []}}))
    assert not result.success and result.outcome == 'rejected'
    assert result.error_type == error
    assert not (workspace / 'normalized.json').exists()
