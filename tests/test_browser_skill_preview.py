"""A descriptor-only preview must reach the model and execute on the real page."""
import json
from pathlib import Path
import pytest
pytest.importorskip('playwright.async_api')
from test_browser_skills import bundle, TASK


def test_model_binds_preview_and_workflow_saves_without_search(tmp_path):
    from core.computer_use.experiment import BrowserCloudProvider
    from core.evolution.budget import BudgetConfig, BudgetTracker
    from core.evolution.contracts import Candidate, RunSpec
    from core.evolution.journal import Journal
    from core.evolution.runner import EvolutionRunner
    from core.model_provider import ModelProvider, ModelResponse
    path, descriptor = bundle(tmp_path)
    class PreviewModel(ModelProvider):
        def generate(self, messages, **kwargs):
            soul = next(m['content'] for m in messages if m['role'] == 'system')
            preview = json.loads(soul.split('Browser reusable skill preview (descriptors only): ', 1)[1].split('\n', 1)[0])[0]
            assert set(preview) == {'skill_id', 'description', 'digest', 'parameters'}
            assert preview['parameters'] == descriptor['parameters']
            assert 'browser-outcome.json' not in json.dumps(messages) and '"workflow"' not in soul
            return ModelResponse(text='', tool_calls=[{'name': 'skill_call', 'arguments': {
                'skill_id': preview['skill_id'], 'digest': preview['digest'], 'arguments': {
                    'settings': [{'label': 'Email notifications', 'checked': True},
                        {'label': 'SMS notifications', 'checked': False}, {'label': 'Weekly digest', 'checked': False}],
                    'save_label': 'Save settings'}}}], usage={'input_tokens': 5, 'output_tokens': 2})
    provider = BrowserCloudProvider(PreviewModel(), TASK, model_label='scripted-cloud', provider_mode='cloud',
        external_completion=True, browser_skill_bundle=path, observation_format='compact-v2', skill_context_mode='preview')
    runner = EvolutionRunner(Journal(tmp_path/'j.sqlite'), BudgetTracker(BudgetConfig(max_api_calls=6,
        max_input_tokens_total=72000, max_output_tokens_total=6144), tmp_path/'b.sqlite'), tmp_path/'runs', provider)
    result = runner.run(Candidate('preview', (), 'workflow', str(path), 'test-preview'), TASK,
        RunSpec('preview', 'preview', TASK['task_id'], max_steps=1, timeout_s=20))
    assert result.status == 'passed' and result.score == 1
    assert result.metadata['chain'][0]['model_calls'] == 1
    ws = Path(result.final_state_path)
    entries = [json.loads(line) for line in (ws/'actor-tools.jsonl').read_text().splitlines()]
    assert [e['name'] for e in entries].count('skill_call') == 1
    assert all(e['name'] != 'skill_search' for e in entries)
    assert [e['name'] for e in entries].count('browser_act') == 3
    assert all(e['actor'] == 'cloud_direct' for e in entries)
    check = json.loads((ws/'browser-check.json').read_text())
    assert check['posts'] == 1 and check['record'] == {'email': True, 'sms': False, 'weekly': False} and check['readback_matches_backend']
    search = BrowserCloudProvider(PreviewModel(), TASK, browser_skill_bundle=path, skill_context_mode='search')
    assert 'Browser reusable skill preview' not in search._experiment_soul()
    assert provider.cache_identity()['experiment_prompt_sha256'] != search.cache_identity()['experiment_prompt_sha256']
