"""Recovery changes must execute through the real loop and original tool executor."""
import asyncio
from pathlib import Path

from core.agentic_loop import AgenticLoop
from core.model_provider import ModelResponse
from test_agentic_loop_multistep import make_loop, call


class Policy:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []
    def recover(self, error, history, checkpoints):
        self.calls.append((error, history, checkpoints))
        return self.decision


def configured_loop(path, responses, policy):
    original, model, _ = make_loop(path, responses)
    loop = AgenticLoop(model, original.tools, original.prompt, original.session, recovery_policy=policy)
    return loop, model


def test_recovery_executes_real_write_then_read_in_same_step_budget(tmp_path):
    (tmp_path / 'input.txt').write_text('7')
    policy = Policy({'action': 'switch_tool', 'tool_call': {'name': 'write_file', 'arguments': {'path': 'out.txt', 'content': '14'}}})
    loop, model = configured_loop(tmp_path, [call('read_file', path='input.txt'), ModelResponse(text='Need to compute'), call('read_file', path='out.txt'), ModelResponse(text='Done')], policy)
    result = asyncio.run(loop.run('Read input.txt and write double into out.txt file.'))
    assert (tmp_path / 'out.txt').read_text() == '14'
    assert [r['name'] for r in result.tool_calls_executed] == ['read_file', 'write_file', 'read_file']
    assert result.tool_calls_executed[1]['actor'] == 'recovery_policy'
    assert len(policy.calls) == 1 and len(model.messages) == 4 and result.steps == 4
    assert policy.calls[0][1][0]['arguments'] == {'path': 'input.txt'}


def test_stop_unknown_and_exception_do_not_fabricate_completion(tmp_path):
    for decision in [{'action': 'stop'}, {'action': 'imaginary'}, {'action': 'switch_tool', 'tool_call': {'name': 'write_file', 'arguments': 'bad'}}]:
        policy = Policy(decision)
        loop, _ = configured_loop(tmp_path, [call('list_files'), ModelResponse(text='Done')], policy)
        result = asyncio.run(loop.run('Inspect files and write out.txt.'))
        assert len(result.tool_calls_executed) == 1
        assert not (tmp_path / 'out.txt').exists()
    class Broken(Policy):
        def recover(self, *args):
            raise ValueError('broken policy')
    loop, _ = configured_loop(tmp_path, [call('list_files'), ModelResponse(text='Done')], Broken(None))
    result = asyncio.run(loop.run('Inspect files and write out.txt.'))
    assert len(result.tool_calls_executed) == 1
    assert loop.recovery_events[-1]['error'] == 'ValueError: broken policy'


def test_recovery_is_disabled_by_default_and_never_runs_without_evidence(tmp_path):
    loop, _ , _ = make_loop(tmp_path, [call('list_files'), ModelResponse(text='Done')])
    result = asyncio.run(loop.run('Inspect files and write out.txt.'))
    assert len(result.tool_calls_executed) == 1 and loop.recovery_events == []
    policy = Policy({'action': 'stop'})
    loop, _ = configured_loop(tmp_path, [ModelResponse(text='Hello')], policy)
    asyncio.run(loop.run('Hello'))
    assert policy.calls == []


def write_bundle(root, code):
    import hashlib, json
    root.mkdir()
    (root / 'recovery.py').write_text(code)
    digest = hashlib.sha256(code.encode()).hexdigest()
    (root / 'manifest.json').write_text(json.dumps({'version': 1, 'skills': [], 'modules': {'recovery': {'entrypoint': 'recovery.py:recover', 'digest': digest}}}))
    return digest


def test_loaded_source_decides_real_action_and_records_hash(tmp_path):
    from core.evolution.bundle import RecoveryPolicy
    from core.evolution.agent_provider import KageChainProvider
    from core.evolution.sandbox import ProcessSkillRunner
    code = 'def recover(error, history, checkpoints):\n    return {"action": "switch_tool", "tool_call": {"name": "write_file", "arguments": {"path": "out.txt", "content": "14"}}}\n'
    bundle = tmp_path / 'bundle'
    digest = write_bundle(bundle, code)
    ws = tmp_path / 'task'; ws.mkdir(); (ws / 'input.txt').write_text('7')
    policy = RecoveryPolicy.from_bundle(bundle, runner=ProcessSkillRunner())
    from test_agentic_loop_multistep import SequenceModel
    chain = KageChainProvider(SequenceModel([call('read_file', path='input.txt'), ModelResponse(text='thinking'), ModelResponse(text='Done')]), recovery_policy=policy)
    result = chain.generate_step({'task_id':'r', 'instruction':'Read input.txt and write double into out.txt file.'}, 1, [], ws)
    assert (ws / 'out.txt').read_text() == '14'
    assert result['tool_results'][1]['actor'] == 'recovery_policy'
    assert result['chain']['recovery_trace'][0]['module_sha256'] == digest
    assert result['chain']['recovery_trace'][0]['module_path'] == str((bundle / 'recovery.py').resolve())
    assert chain.cache_identity()['recovery']['module_sha256'] == digest
    assert result['chain']['recovery_events'][0]['decision']['action'] == 'switch_tool'


def test_module_tampering_rejected_before_execution(tmp_path):
    import pytest
    from core.evolution.bundle import RecoveryPolicy
    bundle = tmp_path / 'bundle'
    write_bundle(bundle, 'def recover(error, history, checkpoints):\n    return {"action":"stop"}\n')
    policy = RecoveryPolicy.from_bundle(bundle)
    (bundle / 'recovery.py').write_text('raise RuntimeError("tampered")')
    with pytest.raises(ValueError, match='digest'):
        policy.recover({}, [], [])
    with pytest.raises(ValueError, match='digest'):
        RecoveryPolicy.from_bundle(bundle)


def test_policy_scratch_writes_cannot_modify_task_files(tmp_path):
    from core.evolution.bundle import RecoveryPolicy
    from core.evolution.sandbox import ProcessSkillRunner
    bundle = tmp_path / 'bundle'
    write_bundle(bundle, 'def recover(error, history, checkpoints):\n    from pathlib import Path\n    Path("out.txt").write_text("wrong")\n    return {"action":"stop"}\n')
    policy = RecoveryPolicy.from_bundle(bundle, runner=ProcessSkillRunner())
    assert policy.recover({}, [], []) == {'action':'stop'}
    assert not (tmp_path / 'out.txt').exists()


def test_cloud_patch_keeps_skills_parent_and_reuses_budgeted_proposal(tmp_path):
    import json
    from core.evolution.recovery_mutator import RecoveryMutator
    from core.evolution.mutator import bundle_digest
    from core.evolution.contracts import Candidate
    from core.evolution.budget import BudgetTracker
    from core.evolution.journal import Journal
    from test_evolution_mutation import _Generator
    bundle = tmp_path / 'bundle'
    write_bundle(bundle, 'def recover(error, history, checkpoints):\n    return {"action":"stop"}\n')
    from test_evolution_skills import _bundle
    skill_source = tmp_path / 'skill_source'
    _bundle(skill_source)
    manifest = json.loads((bundle / 'manifest.json').read_text())
    manifest['skills'] = json.loads((skill_source / 'manifest.json').read_text())['skills']
    (bundle / 'normalize.py').write_bytes((skill_source / 'normalize.py').read_bytes())
    (bundle / 'manifest.json').write_text(json.dumps(manifest))
    parent = Candidate('parent', (), 'recovery', str(bundle), bundle_digest(bundle))
    before = (bundle / 'manifest.json').read_bytes()
    code = 'def recover(error, history, checkpoints):\n    return {"action":"stop"}\n'
    model = _Generator([{'hypothesis':'Malformed signature must be repaired', 'code':'def recover():\n    return {}\n'}, {'hypothesis':'Use observed tools', 'code': code}])
    budget = BudgetTracker()
    mutator = RecoveryMutator(model, budget, Journal(tmp_path/'journal.sqlite'), tmp_path/'mutation')
    feedback = {'task_id':'dev', 'trace':[{'expected':'SECRET', 'observation':'actual read'}]}
    child = mutator.propose(parent, feedback)
    assert child.target == 'recovery' and child.parent_ids == ('parent',)
    assert mutator.propose(parent, feedback) == child
    assert budget.total_api_calls == 2 and 'SECRET' not in json.dumps(model.messages)
    assert (bundle / 'manifest.json').read_bytes() == before
    assert json.loads((Path(child.bundle_path)/'manifest.json').read_text())['skills'] == manifest['skills']
    assert (Path(child.bundle_path)/'normalize.py').read_bytes() == (bundle/'normalize.py').read_bytes()
