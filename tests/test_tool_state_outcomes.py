"""State outcomes survive real writes, agent observations and experiment journals."""
import asyncio
import json

import pytest

from core.model_provider import ModelResponse
from core.tool_executor import ToolExecutor
from core.tool_registry import ToolDefinition, ToolRegistry
from core.tools._response import err, ok
from core.tools.skill_ops import skills_save_local


@pytest.mark.parametrize('body,outcome,success,label', [
    ('v1', 'unchanged', True, '未变更'),
    ('v2', 'not_applied', False, '未应用'),
])
def test_skill_save_state_is_preserved_through_agent_and_journal(tmp_path, monkeypatch, body, outcome, success, label):
    from core.evolution import agent_provider
    from core.evolution.agent_provider import KageChainProvider
    from core.evolution.budget import BudgetTracker
    from core.evolution.contracts import Candidate, RunSpec
    from core.evolution.journal import Journal
    from core.evolution.runner import EvolutionRunner
    skills = tmp_path / 'skills'
    skills_save_local('demo', 'd', 'v1', target_dir=str(skills))
    path = skills / 'demo.md'
    before = path.read_bytes()
    # An identical repeat must not perform another write, even of identical bytes.
    before_mtime = path.stat().st_mtime_ns
    build_registry = agent_provider.build_workspace_registry
    def registry(workspace):
        result = build_registry(workspace)
        result.register(ToolDefinition('skills_save_local', 'Save a skill',
            {'type': 'object', 'properties': {'name': {'type': 'string'}, 'description': {'type': 'string'},
                'body': {'type': 'string'}, 'target_dir': {'type': 'string'}}, 'required': ['name', 'description']},
            skills_save_local))
        return result
    monkeypatch.setattr(agent_provider, 'build_workspace_registry', registry)
    class Model:
        def __init__(self): self.observed = []
        def generate(self, messages, **kwargs):
            if not self.observed:
                self.observed = ['called']
                return ModelResponse(text="", tool_calls=[{'name': 'skills_save_local', 'arguments': {
                    'name': 'demo', 'description': 'd', 'body': body, 'target_dir': str(skills)}}],
                    usage={'input_tokens': 10, 'output_tokens': 5})
            self.observed = [m.get('content', '') for m in messages]
            return ModelResponse(text='finished', usage={'input_tokens': 10, 'output_tokens': 5})
    model = Model()
    provider = KageChainProvider(model)
    journal = Journal(tmp_path / 'journal.sqlite')
    runner = EvolutionRunner(journal, BudgetTracker(), tmp_path / 'runs', provider=provider, step_isolation='inline')
    task = {'task_id': 'state', 'instruction': 'Save the local skill.', 'initial_files': {}, 'scoring_criteria': {}}
    candidate = Candidate('baseline', (), 'skill', '', 'digest')
    result = runner.run(candidate, task, RunSpec('state', 'baseline', 'state', 42, 1, 10))
    assert path.read_bytes() == before and path.stat().st_mtime_ns == before_mtime
    assert any(label in line for line in model.observed)
    event = next(e for e in journal.get_events('state') if e.event_type == 'observation' and e.payload['observation'].get('executed_by') == 'kage_chain')
    observation = event.payload['observation']
    assert observation['outcome'] == outcome
    assert observation['status'] == outcome
    assert observation['success'] is success
    assert observation['tool_reported_success'] is success
    assert result.metadata['chain'][0]['tool_calls'] == 1


def test_explicit_outcome_is_validated_without_hiding_failures(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition('state', 'd', {'type': 'object', 'properties': {}},
        lambda: err('CustomConflict', 'not written', outcome='not_applied')))
    result = asyncio.run(ToolExecutor(registry, str(tmp_path)).execute('state', {}))
    assert result.outcome == 'not_applied' and not result.success
    registry = ToolRegistry()
    registry.register(ToolDefinition('bad', 'd', {'type': 'object', 'properties': {}},
        lambda: json.dumps({'success': False, 'error': 'Crash', 'outcome': 'unchanged'})))
    result = asyncio.run(ToolExecutor(registry, str(tmp_path)).execute('bad', {}))
    assert not result.success and result.outcome == 'tool_error'
    assert json.loads(ok(outcome='unchanged'))['outcome'] == 'unchanged'
