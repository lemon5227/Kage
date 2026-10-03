"""Real page projection and clean cloud execution; scripted actions are engineering checks."""
import asyncio
import json
from pathlib import Path
import pytest

pytest.importorskip('playwright.async_api')
from test_browser_takeover import Actions, task

ROOT = Path(__file__).resolve().parents[1]

def test_explicit_checkbox_states_survive_actions_and_stale_recovery(tmp_path):
    from playwright.async_api import async_playwright
    from core.computer_use.browser import BrowserAdapter
    from core.computer_use.task_environment import browser_task_server
    async def run():
        with browser_task_server(task()['fixture'], tmp_path) as (url, _):
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(); await page.goto(url)
                    adapter = BrowserAdapter(page, compact_observations=True, compact_format='compact-v2')
                    obs = await adapter.observe()
                    states = lambda o: {t['name']: t['checked'] for t in o['targets'] if t.get('input_type') == 'checkbox'}
                    assert states(obs) == {'email': False, 'sms': True, 'weekly': False}
                    email = next(t['target_ref'] for t in obs['targets'] if t.get('name') == 'email')
                    changed = await adapter.act(obs['observation_id'], 'click', email)
                    assert changed['success'] and states(changed['observation'])['email'] is True
                    stale = await adapter.act(obs['observation_id'], 'click', email)
                    assert stale['error'] == 'StaleObservation'
                    assert states(stale['observation']) == {'email': True, 'sms': True, 'weekly': False}
                    assert await page.locator('input[name="email"]').is_checked()
                finally: await browser.close()
    asyncio.run(run())

@pytest.mark.parametrize('projection', ['compact-v1', 'compact-v2'])
def test_cloud_is_only_executor_and_saves_from_clean_page(tmp_path, projection):
    from core.computer_use.experiment import BrowserCloudProvider
    from core.evolution.budget import BudgetConfig, BudgetTracker
    from core.evolution.contracts import Candidate, RunSpec
    from core.evolution.journal import Journal
    from core.evolution.runner import EvolutionRunner
    class CleanCloud(Actions):
        def generate(self, messages, **kwargs):
            if len(self.labels) == 3:
                obs = json.loads(next(m['content'].split('runtime:\n', 1)[1] for m in messages if 'runtime:\n' in m.get('content', '')))
                email = next(t for t in obs['targets'] if t.get('name') == 'email')
                assert obs['observation_format'] == projection
                assert (email.get('checked') is False) if projection == 'compact-v2' else ('checked' not in email)
            if not self.labels: raise AssertionError('external save should stop further requests')
            return super().generate(messages, **kwargs)
    provider = BrowserCloudProvider(CleanCloud(['Email notifications', 'SMS notifications', 'Save settings']), task(),
        model_label='scripted-cloud', provider_mode='cloud', external_completion=True, observation_format=projection)
    runner = EvolutionRunner(Journal(tmp_path/'j.sqlite'), BudgetTracker(BudgetConfig(max_api_calls=6,
        max_input_tokens_total=72000, max_output_tokens_total=6144), tmp_path/'b.sqlite'), tmp_path/'runs', provider)
    result = runner.run(Candidate('browser', (), 'workflow', str(ROOT), 'state-diagnosis'), task(),
        RunSpec('clean-cloud', 'browser', 'preferences_dev', max_steps=1, timeout_s=20))
    assert result.status == 'passed' and result.score == 1
    ws = Path(result.final_state_path)
    check = json.loads((ws/'browser-check.json').read_text())
    assert check['posts'] == 1 and check['record'] == {'email': True, 'sms': False, 'weekly': False}
    assert check['readback_matches_backend']
    assert result.metadata['chain'][0]['actor'] == 'cloud_direct'
    assert result.metadata['chain'][0]['model_calls'] == 3
    assert {json.loads(line)['actor'] for line in (ws/'actor-tools.jsonl').read_text().splitlines()} == {'cloud_direct'}
    assert (ws/'initial-observation.json').exists() and (ws/'loop-result.json').exists()
    assert (ws/'cloud-context-pack.jsonl').exists()
    assert provider.cache_identity()['observation_format'] == projection
