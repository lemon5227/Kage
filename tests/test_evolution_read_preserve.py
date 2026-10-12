"""Read-preserve checks require actual successful reads and reject every skill attempt."""
import hashlib
import json
from pathlib import Path

import pytest

from core.evolution.runner import Evaluator, EvolutionRunner
from core.evolution.agent_provider import KageChainProvider
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate, RunSpec
from core.evolution.journal import Journal
from core.evolution.recovery_loop import visible_feedback
from core.model_provider import ModelProvider, ModelResponse

SOURCE = 'def discounted(price, percent):\n    return price * (1 - percent / 100)\n'
DIGEST = hashlib.sha256(SOURCE.encode()).hexdigest()


def task():
    return {'task_id': 'read_pricing', 'instruction': 'Read pricing.py and keep it unchanged.',
            'initial_files': {'pricing.py': SOURCE},
            'scoring_criteria': {'type': 'read_preserve', 'file': 'pricing.py', 'sha256': DIGEST}}


def read_row(path='pricing.py', observation=None, *, nested=True):
    action = {'name': 'read_file'}
    action.update({'arguments': {'path': path}} if nested else {'path': path})
    return {'action': action, 'observation': observation if observation is not None else {'status': 'ok'}}


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / 'pricing.py').write_bytes(SOURCE.encode())
    return tmp_path


@pytest.mark.parametrize('nested', [True, False])
def test_exact_bytes_and_actual_successful_read_pass(workspace, nested):
    assert Evaluator.score(task(), workspace, history=[read_row(nested=nested)]) == 1.0


@pytest.mark.parametrize('history', [None, [], [read_row('other.py')], [read_row('../pricing.py')],
    [read_row(observation={'status': 'error'})], [read_row(observation={})],
    [read_row(observation={'status': 'unknown_action'})],
    [read_row(observation={'status': 'ok', 'success': False})],
    [read_row(observation={'status': 'ok', 'tool_reported_success': False})],
    [read_row(observation={'status': 'ok', 'outcome': 'error'})],
    [read_row(), None], [read_row(), {'action': None}], 'bad'])
def test_missing_failed_unknown_or_malformed_trace_fails_closed(workspace, history):
    assert Evaluator.score(task(), workspace, history=history) == 0.0


@pytest.mark.parametrize('actor', ['student', 'recovery_policy', 'other'])
def test_failed_no_effect_skill_attempt_by_any_actor_is_rejected(workspace, actor):
    history = [read_row(), {'action': {'name': 'skill_call', 'arguments': {}},
                           'observation': {'status': 'error', 'success': False, 'actor': actor}}]
    assert Evaluator.score(task(), workspace, history=history) == 0.0
    assert (workspace / 'pricing.py').read_bytes() == SOURCE.encode()


@pytest.mark.parametrize('criteria', [None, [], {},
    {'type': 'read_preserve', 'file': '../pricing.py', 'sha256': DIGEST},
    {'type': 'read_preserve', 'file': '/tmp/pricing.py', 'sha256': DIGEST},
    {'type': 'read_preserve', 'file': 1, 'sha256': DIGEST},
    {'type': 'read_preserve', 'file': 'pricing.py', 'sha256': DIGEST.upper()},
    {'type': 'read_preserve', 'file': 'pricing.py', 'sha256': 1},
    {'type': 'read_preserve', 'file': 'pricing.py', 'sha256': DIGEST, 'extra': True}])
def test_invalid_schema_and_paths_return_zero(workspace, criteria):
    value = task(); value['scoring_criteria'] = criteria
    assert Evaluator.score(value, workspace, history=[read_row()]) == 0.0


def test_changed_bytes_missing_directory_and_external_symlink_fail(workspace, tmp_path):
    target = workspace / 'pricing.py'
    target.write_bytes(SOURCE.encode() + b'\r\n')
    assert Evaluator.score(task(), workspace, history=[read_row()]) == 0.0
    target.unlink()
    assert Evaluator.score(task(), workspace, history=[read_row()]) == 0.0
    target.mkdir()
    assert Evaluator.score(task(), workspace, history=[read_row()]) == 0.0
    target.rmdir()
    outside = tmp_path.parent / (tmp_path.name + '-outside'); outside.write_text(SOURCE)
    target.symlink_to(outside)
    assert Evaluator.score(task(), workspace, history=[read_row()]) == 0.0


class ControlledModel(ModelProvider):
    def __init__(self, skill_attempt=False):
        self.calls = 0
        self.seen = []
        self.skill_attempt = skill_attempt

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        self.calls += 1
        self.seen.extend(messages)
        if self.calls == 1:
            calls = [{'name': 'read_file', 'arguments': {'path': 'pricing.py'}}]
        elif self.calls == 2 and self.skill_attempt:
            calls = [{'name': 'skill_call', 'arguments': {'skill_id': 'unavailable'}}]
        else:
            calls = []
        return ModelResponse(text='' if calls else 'Done.', tool_calls=calls,
                             usage={'input_tokens': 10, 'output_tokens': 10})


def make_runner(tmp_path, provider):
    db = tmp_path / 'journal.db'
    return EvolutionRunner(Journal(db), BudgetTracker(BudgetConfig(
        max_input_tokens_total=100000, max_output_tokens_total=100000, max_api_calls=20), db_path=db),
        base_dir=tmp_path / 'workspaces', provider=provider, step_isolation='inline')


@pytest.mark.parametrize('skill_attempt,expected', [(False, 1.0), (True, 0.0)])
def test_real_chain_runner_records_actual_read_and_excludes_hidden_criteria(tmp_path, skill_attempt, expected):
    model = ControlledModel(skill_attempt)
    provider = KageChainProvider(model, provider_mode='chain-fixture', model_label='controlled')
    runner = make_runner(tmp_path, provider)
    candidate = Candidate('candidate', (), 'workflow', str(tmp_path), 'sha256:fixture')
    result = runner.run(candidate, task(), RunSpec('run', candidate.candidate_id, 'read_pricing'))
    assert result.score == expected
    rows = [json.loads(line) for line in Path(result.trace_path).read_text().splitlines()]
    assert rows[0]['action']['name'] == 'read_file'
    assert rows[0]['observation']['success'] is True
    if skill_attempt:
        assert any(row['action']['name'] == 'skill_call' and row['observation']['success'] is False for row in rows)
    assert (Path(result.final_state_path) / 'pricing.py').read_bytes() == SOURCE.encode()
    for exposed in [model.seen, visible_feedback(task(), result)]:
        serialized = json.dumps(exposed)
        assert 'scoring_criteria' not in serialized
        assert DIGEST not in serialized
        assert 'read_preserve' not in serialized


def test_old_criteria_keeps_two_argument_custom_evaluator_contract(tmp_path):
    class Provider:
        def generate_step(self, task_view, step, history, ws):
            return {'action': {'name': 'finish'}, 'usage': {}}
    class CustomEvaluator:
        def score(self, task_def, workspace_dir):
            return 0.75
    runner = make_runner(tmp_path, Provider()); runner.evaluator = CustomEvaluator()
    candidate = Candidate('candidate', (), 'workflow', str(tmp_path), 'sha256:fixture')
    old = {'task_id': 'old', 'scoring_criteria': {'type': 'json_exact_match', 'file': 'out.json', 'expected': []}}
    assert runner.run(candidate, old, RunSpec('run', 'candidate', 'old')).score == 0.75
