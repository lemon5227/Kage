"""Real Page demonstrations must survive corrections and replay on fresh forms."""
import asyncio
import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from core.computer_use.demonstration import BrowserDemonstrationRecorder, demonstration_tasks
from core.computer_use.demonstration_compiler import compile_demonstration
from core.computer_use.browser import BrowserAdapter
from core.computer_use.episodes import generation_feedback
from core.computer_use.experiment import CheckpointExecutor
from core.computer_use.skills import BrowserPrimitiveQuota, BrowserSkillCatalog
from core.computer_use.task_environment import browser_task_server, checkpoint
from core.evolution.archive import ExperienceArchive
from core.evolution.contracts import RunResult
from core.evolution.journal import Journal
from core.evolution.runner import Evaluator
from core.tool_registry import ToolRegistry


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


async def teach(page, family, *, save=True):
    if family == 'profile':
        await page.get_by_label('Name', exact=True).fill('Mistake')
        await page.get_by_label('Email', exact=True).fill('demo@example.test')
        await page.get_by_label('Name', exact=True).fill('Kage Demo')
    else:
        # Corrections are real separate clicks, including fast consecutive events.
        await page.get_by_label('Email notifications', exact=True).click()
        await page.get_by_label('Email notifications', exact=True).click()
        await page.get_by_label('Email notifications', exact=True).click()
        await page.get_by_label('SMS notifications', exact=True).click()
    if save:
        await page.get_by_role('button', name='Save profile' if family == 'profile' else 'Save settings', exact=True).click()
        await page.wait_for_function('document.querySelector("[data-result]").textContent.length > 0')


def archive(task, workspace, tmp_path, *, source='automation'):
    result = RunResult(task['task_id'] + '-0', 'passed', Evaluator.score(task, workspace),
                       str(workspace / 'trace.jsonl'), final_state_path=str(workspace),
                       metadata={'environment_kind': 'resettable-local-http-browser',
                                 'demonstration_source': source})
    store = ExperienceArchive(Journal(tmp_path / 'journal.sqlite'))
    store.record(task, result)
    return store.retrieve(task['family'])[0]


@pytest.mark.parametrize('family,source', [('profile', 'automation'), ('preferences', 'automation')])
def test_record_archive_compile_and_reuse_actual_form(tmp_path, family, source):
    async def run():
        tasks = demonstration_tasks()
        task, reuse = tasks['demo_' + family], tasks['reuse_' + family]
        workspace = tmp_path / 'record'; workspace.mkdir()
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                with browser_task_server(task['fixture'], workspace) as (url, state):
                    page = await browser.new_page(); await page.goto(url)
                    recorder = BrowserDemonstrationRecorder(page, workspace, source_kind=source)
                    initial = await recorder.start()
                    await teach(page, family)
                    summary = await recorder.stop()
                    assert summary['success'] and summary['event_count'] >= 4
                    assert (await checkpoint(page, url, workspace))['readback_matches_backend']
                    assert state['posts'] == 1 and Evaluator.score(task, workspace) == 1
                    captured = rows(workspace / 'demonstration-events.jsonl')
                    assert [e['seq'] for e in captured] == list(range(1, len(captured) + 1))
                    assert all(e['before']['source'] == e['after']['source'] == 'dom' for e in captured)
                    assert all('isTrusted' in e and e['source'] == source for e in captured)
                    if family == 'profile':
                        values = [e['arguments'].get('value') for e in captured if e['arguments']['operation'] == 'fill']
                        assert values == ['Mistake', 'demo@example.test', 'Kage Demo']
                        assert initial['targets'][0]['value'] == ''
                    else:
                        email = [e for e in captured if e['target']['label'] == 'Email notifications']
                        assert [e['after']['targets'][0]['checked'] for e in email] == [True, False, True]
                    count = len(captured)
                    await page.get_by_label('Name' if family == 'profile' else 'Email notifications', exact=True).click()
                    assert len(rows(workspace / 'demonstration-events.jsonl')) == count
                    episode = archive(task, workspace, tmp_path, source=source)
                    kind = 'automation_demonstration' if source == 'automation' else 'human_demonstration_declared'
                    assert episode['browser']['source_kind'] == kind
                    assert episode['browser']['student']['external_passed'] is None
                    assert not episode['browser']['teacher']['attempted']
                    assert episode['browser']['actor_segments'] == [{'actor': 'automation' if source == 'automation' else 'human', 'tool_calls': count}]
                    lesson = compile_demonstration(episode, tmp_path / 'candidate', skill_id='form-demo')
                    assert lesson['source_kind'] == kind
                    descriptor = json.loads((Path(lesson['bundle_path']) / 'manifest.json').read_text())['skills'][0]
                    assert set(descriptor) == {'skill_id', 'description', 'parameters', 'workflow', 'digest'}
                    assert set(descriptor['parameters']['required']) == set(lesson['arguments'])
                    assert descriptor['parameters']['additionalProperties'] is False
                    assert 'Mistake' not in json.dumps(descriptor) and 'demo@example.test' not in json.dumps(descriptor)
                    assert lesson['source_hashes']['demonstration-events.jsonl']
                    assert lesson['source_hashes']['final-observation.json']
                    args = dict(lesson['arguments'])
                    desired = {'Name': 'Kage Reuse', 'Email': 'reuse@example.test'} if family == 'profile' else {
                        'Email notifications': False, 'SMS notifications': True, 'Weekly digest': True}
                    for step in descriptor['workflow'][:-1]:
                        args[step.get('value_param') or step['checked_param']] = desired[args[step['label_param']]]
                    await page.close()
                fresh = tmp_path / 'reuse'; fresh.mkdir()
                with browser_task_server(reuse['fixture'], fresh) as (url, state):
                    page = await browser.new_page(); await page.goto(url)
                    adapter, quota, registry = BrowserAdapter(page), BrowserPrimitiveQuota(), ToolRegistry()
                    adapter.register_tools(registry, quota=quota)
                    executor = CheckpointExecutor(registry, fresh, page, url, settle_saves=True)
                    BrowserSkillCatalog.from_bundle(lesson['bundle_path']).register_tools(registry, adapter, executor, fresh, quota)
                    result = await executor.execute('skill_call', {'skill_id': 'form-demo', 'digest': lesson['digest'], 'arguments': args})
                    assert result.success and quota.used <= 16
                    assert (await executor.checkpoint())['readback_matches_backend']
                    assert state['posts'] == 1 and Evaluator.score(reuse, fresh) == 1
                changed = 'demonstration-events.jsonl' if family == 'profile' else 'demonstration-inputs.jsonl'
                with (workspace / changed).open('a') as stream:
                    stream.write('{}\n')
                resumed = ExperienceArchive(Journal(tmp_path / 'journal.sqlite'))
                assert resumed.retrieve(family) == []
                assert resumed.list_episodes()[0]['status'] == 'stale'
            finally:
                await browser.close()
    asyncio.run(run())


@pytest.mark.parametrize('mutation,error', [
    ('no_save', 'save action'), ('duplicate', 'label'), ('multiple', 'form'),
    ('unsupported', 'unsupported'), ('too_many', '16'), ('tamper', 'evidence changed'),
    ('after_save', 'changed after save'), ('bad_id', 'skill_id')])
def test_compilation_rejects_actual_ambiguous_or_unsaved_demonstration(tmp_path, mutation, error):
    async def run():
        task = demonstration_tasks()['demo_profile']
        workspace = tmp_path / 'record'; workspace.mkdir()
        with browser_task_server(task['fixture'], workspace) as (url, _):
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(); await page.goto(url)
                    if mutation == 'duplicate':
                        await page.evaluate("document.querySelector('form').insertAdjacentHTML('beforeend','<input aria-label=Name name=duplicate>')")
                    elif mutation == 'multiple':
                        await page.evaluate("document.body.insertAdjacentHTML('beforeend','<form><input aria-label=Other name=other></form>')")
                    elif mutation == 'unsupported':
                        await page.evaluate("document.querySelector('form').insertAdjacentHTML('beforeend','<select aria-label=Choice><option>A</option></select>')")
                    elif mutation == 'too_many':
                        await page.evaluate("for(let i=0;i<14;i++)document.querySelector('form').insertAdjacentHTML('beforeend',`<input aria-label=Extra${i} name=extra${i}>`)")
                    recorder = BrowserDemonstrationRecorder(page, workspace, source_kind='automation')
                    await recorder.start()
                    # Exact first targets allow the intentionally ambiguous page to be recorded.
                    await page.get_by_label('Name', exact=True).first.fill('Kage Demo')
                    await page.get_by_label('Email', exact=True).fill('demo@example.test')
                    if mutation != 'no_save':
                        await page.get_by_role('button', name='Save profile', exact=True).click()
                        await page.wait_for_function('document.querySelector("[data-result]").textContent.length > 0')
                    if mutation == 'after_save':
                        await page.get_by_label('Name', exact=True).fill('Unsaved edit')
                    summary = await recorder.stop()
                    await checkpoint(page, url, workspace)
                    # The checker independently verifies the real saved record. For no_save,
                    # a prior verified save supplies proof but no demonstration save action.
                    if mutation == 'no_save':
                        await page.get_by_role('button', name='Save profile', exact=True).click()
                        await page.wait_for_function('document.querySelector("[data-result]").textContent.length > 0')
                        await checkpoint(page, url, workspace)
                    if mutation in {'duplicate', 'too_many', 'multiple'}:
                        # Additional visible inputs are independently part of this controlled task.
                        backend = json.loads((workspace / 'backend.json').read_text())['record']
                        task['scoring_criteria']['expected']['record'] = backend
                    episode = archive(task, workspace, tmp_path)
                    if mutation == 'tamper':
                        (workspace / 'demonstration-events.jsonl').write_text('{}\n')
                    with pytest.raises(ValueError, match=error):
                        compile_demonstration(episode, tmp_path / 'candidate', skill_id='../bad' if mutation == 'bad_id' else 'form-demo')
                    assert not (tmp_path / 'candidate' / 'manifest.json').exists()
                    assert summary['success']
                finally:
                    await browser.close()
    asyncio.run(run())


def test_typed_edits_are_committed_once_with_actual_before_dom(tmp_path):
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content('<form><label>Email<input></label><label>Enabled<input type=checkbox></label><button>Save</button></form><p>Before</p>')
                recorder = BrowserDemonstrationRecorder(page, tmp_path, source_kind='automation')
                await recorder.start()
                await page.evaluate("document.querySelector('p').textContent='Updated before edit'")
                await page.get_by_label('Email', exact=True).press_sequentially('long-typed-address@example.test')
                await page.get_by_label('Enabled', exact=True).click()
                summary = await recorder.stop()
                captured = rows(tmp_path / 'demonstration-events.jsonl')
                assert summary['success'] and summary['event_count'] == 2
                assert captured[0]['arguments']['value'] == 'long-typed-address@example.test'
                assert 'Updated before edit' in captured[0]['before']['text']
                assert len(captured[0]['input_samples']) >= 30
                assert captured[1]['before']['targets'][1]['checked'] is False
                assert captured[1]['after']['targets'][1]['checked'] is True
            finally:
                await browser.close()
    asyncio.run(run())


def test_real_write_failure_preserves_prior_records_and_fails_closed(tmp_path):
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content('<form><label>Name<input></label><label>Email<input></label><button>Save</button></form>')
                recorder = BrowserDemonstrationRecorder(page, tmp_path, source_kind='automation')
                await recorder.start()
                await page.get_by_label('Name').fill('Original')
                await page.get_by_label('Email').fill('email@example.test')
                await page.evaluate('() => window.__kageDemonstration.chain')
                original = (tmp_path / 'actor-tools.jsonl').read_text()
                (tmp_path / 'actor-tools.jsonl').rename(tmp_path / 'preserved-actor-tools.jsonl')
                (tmp_path / 'actor-tools.jsonl').mkdir()
                summary = await recorder.stop()
                assert not summary['success'] and summary['error'] == 'CaptureFlushFailed'
                assert (tmp_path / 'preserved-actor-tools.jsonl').read_text() == original
                assert rows(tmp_path / 'demonstration-events.jsonl')[-1]['arguments']['value'] == 'email@example.test'
                assert not json.loads((tmp_path / 'demonstration-summary.json').read_text())['success']
            finally:
                await browser.close()
    asyncio.run(run())


def test_capture_limit_page_close_and_stop_flush_preserve_evidence(tmp_path):
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                for mode in ('limit', 'closed', 'unblurred'):
                    root = tmp_path / mode
                    page = await browser.new_page()
                    await page.set_content('<form><label>Name<input></label><button>Save</button></form>')
                    recorder = BrowserDemonstrationRecorder(page, root, source_kind='automation')
                    await recorder.start()
                    for i in range(65 if mode == 'limit' else 1):
                        await page.get_by_label('Name').fill(str(i))
                        if mode == 'limit':
                            await page.get_by_label('Name').press('Tab')
                    if mode == 'closed':
                        await page.close()
                    summary = await recorder.stop()
                    captured = rows(root / 'demonstration-events.jsonl')
                    assert rows(root / 'demonstration-inputs.jsonl')[0]['target']['value'] == '0'
                    if mode != 'closed':
                        assert captured[0]['arguments']['value'] == '0'
                    if mode == 'unblurred':
                        assert summary['success'] and summary['event_count'] == 1
                        assert summary['final_observation']['targets'][0]['value'] == '0'
                    else:
                        assert not summary['success']
                        assert summary['error'] == ('CaptureLimitExceeded' if mode == 'limit' else 'CapturePageClosed')
                    if mode == 'limit':
                        assert summary['event_count'] == 65 and captured[-1]['arguments']['value'] == '64'
                    assert await recorder.stop() == summary
            finally:
                await browser.close()
    asyncio.run(run())


def test_trusted_tasks_are_fresh_copies_of_dev_only_manifest():
    tasks = demonstration_tasks()
    assert set(tasks) == {'demo_profile', 'reuse_profile', 'demo_preferences', 'reuse_preferences'}
    assert all(t['split'] == 'dev' for t in tasks.values())
    tasks['demo_profile']['fixture']['fields'][0]['label'] = 'Tampered'
    assert demonstration_tasks()['demo_profile']['fixture']['fields'][0]['label'] == 'Name'


def test_page_capture_deadline_flushes_pending_edit_then_stops_accepting(tmp_path):
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content('<form><label>Name<input></label><button>Save</button></form>')
                await page.clock.install()
                recorder = BrowserDemonstrationRecorder(page, tmp_path, source_kind='automation')
                await recorder.start()
                await page.get_by_label('Name').fill('Before deadline')
                await page.clock.fast_forward(900001)
                await page.get_by_label('Name').fill('After deadline')
                summary = await recorder.stop()
                assert not summary['success'] and summary['error'] == 'CaptureLimitExceeded'
                assert summary['event_count'] == 1
                assert rows(tmp_path / 'demonstration-events.jsonl')[0]['arguments']['value'] == 'Before deadline'
            finally:
                await browser.close()
    asyncio.run(run())


@pytest.mark.parametrize('source,kind', [('human_declared', 'human_demonstration_declared'),
                                        ('automation', 'automation_demonstration')])
def test_source_declaration_projection_does_not_claim_student_teacher_success(tmp_path, source, kind):
    # A narrow projection unit fixture, never an asserted human browser acceptance trace.
    from core.computer_use.episodes import normalize_browser_episode
    task = {'task_id': 'projection', 'split': 'dev', 'family': 'profile'}
    for name in ('initial-observation.json', 'final-observation.json', 'backend.json'):
        (tmp_path / name).write_text('{}')
    (tmp_path / 'browser-check.json').write_text('{"readback_matches_backend":true}')
    (tmp_path / 'demonstration-summary.json').write_text(json.dumps({'success': True, 'error': None,
                                                                  'event_count': 2, 'source_kind': source}))
    for name in ('browser.jsonl', 'trace.jsonl', 'demonstration-events.jsonl', 'demonstration-inputs.jsonl'):
        (tmp_path / name).write_text('')
    (tmp_path / 'actor-tools.jsonl').write_text('\n'.join(json.dumps({'actor': actor, 'name': 'browser_act', 'outcome': 'ok'})
                                                         for actor in ('human', 'automation')) + '\n')
    result = RunResult('projection-0', 'passed', 1, str(tmp_path / 'trace.jsonl'),
                       metadata={'demonstration_source': source})
    normalized = normalize_browser_episode(task, result, tmp_path)
    assert normalized['source_kind'] == kind
    assert normalized['student']['external_passed'] is None
    assert not normalized['teacher']['attempted'] and normalized['teacher']['actual_actions'] == 0
    assert normalized['actor_segments'] == [{'actor': 'human', 'tool_calls': 1}, {'actor': 'automation', 'tool_calls': 1}]
    assert normalized['verification'] == 'final_verified'
    (tmp_path / 'demonstration-summary.json').write_text(json.dumps({'success': False, 'error': 'CaptureFlushFailed',
                                                                  'event_count': 2, 'source_kind': source}))
    assert normalize_browser_episode(task, result, tmp_path)['verification'] == 'not_verified'
