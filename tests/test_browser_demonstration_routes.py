"""Product teaching uses the child worker's actual Page, never fabricated events."""
import asyncio
import json
import os
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient
from playwright.async_api import async_playwright

BASE = '/api/browser/demonstrations'
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    import core.server as server
    monkeypatch.setenv('KAGE_MODE', 'control')
    monkeypatch.setenv('KAGE_BROWSER_DEMONSTRATIONS_DIR', str(tmp_path))
    monkeypatch.setenv('KAGE_BROWSER_PYTHON', str(ROOT / '.venv-computer-use/bin/python'))
    monkeypatch.setenv('KAGE_BROWSER_DEMONSTRATION_HEADLESS', '1')
    monkeypatch.setattr(server, '_load_effective_config', lambda: (_ for _ in ()).throw(AssertionError('no model config')))
    with TestClient(server.app) as http:
        yield http


def wait_job(client, run_id, statuses, timeout=25):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        response = client.get(f'{BASE}/{run_id}')
        assert response.status_code == 200
        job = response.json()
        if job['status'] in statuses:
            return job
        if job['status'] in {'failed', 'stopped', 'incomplete'}:
            raise AssertionError(job)
        time.sleep(.05)
    raise AssertionError(job)


async def operate(job, family, save=True):
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(job['automation_cdp_endpoint'])
        page = browser.contexts[0].pages[0]
        if family == 'profile':
            await page.get_by_label('Name', exact=True).fill('Correction')
            await page.get_by_label('Email', exact=True).fill('demo@example.test')
            await page.get_by_label('Name', exact=True).fill('Kage Demo')
        else:
            for _ in range(3):
                await page.get_by_label('Email notifications', exact=True).click()
            await page.get_by_label('SMS notifications', exact=True).click()
        if save:
            await page.get_by_role('button', name='Save profile' if family == 'profile' else 'Save settings').click()
        # Detach Playwright; the browser remains owned by the worker.


@pytest.mark.parametrize('family', ['profile', 'preferences'])
def test_actual_api_capture_candidate_and_edited_fresh_replay(client, tmp_path, family):
    assert client.get(BASE + '/catalog').status_code == 200
    created = client.post(BASE, json={'task_id': 'demo_' + family, 'source_kind': 'automation'})
    assert created.status_code == 202
    run_id = created.json()['run_id']
    assert client.post(BASE, json={'task_id': 'demo_profile'}).status_code == 409
    ready = wait_job(client, run_id, {'recording'})
    assert ready['ready'] and ready['source_kind'] == 'automation'
    asyncio.run(operate(ready, family))
    assert client.post(f'{BASE}/{run_id}/finish').status_code == 200
    assert client.post(f'{BASE}/{run_id}/finish').status_code == 200
    final = wait_job(client, run_id, {'verified'})
    assert final['check_passed'] is True and final['event_count'] >= 4
    result = final['result']
    assert result['usage']['api_calls'] == 0 and result['unpromoted']
    assert result['candidate']['digest']
    for name in ('episode.json', 'feedback.json', 'candidate/manifest.json', 'parameters.json', 'browser-check.json'):
        assert client.get(f'{BASE}/{run_id}/artifacts/{name}').status_code == 200
    assert client.get(f'{BASE}/{run_id}/artifacts/../run_other/result.json').status_code == 404
    assert client.get(f'{BASE}/{run_id}/artifacts/unindexed').status_code == 404
    args = dict(result['candidate']['arguments'])
    args.update({'field_1_value': 'Kage Reuse', 'field_2_value': 'reuse@example.test'} if family == 'profile' else
                {'field_1_value': False, 'field_2_value': True, 'field_3_value': True})
    assert client.post(f'{BASE}/{run_id}/replay', json={'task_id': 'reuse_' + family, 'arguments': {}}).status_code == 422
    other = 'reuse_preferences' if family == 'profile' else 'reuse_profile'
    assert client.post(f'{BASE}/{run_id}/replay', json={'task_id': other, 'arguments': args}).status_code == 409
    # Restart must retain the candidate and not restore its closed Page.
    import core.routes.browser_demonstrations as routes
    client.portal.call(routes.close_service)
    assert client.get(f'{BASE}/{run_id}').json()['status'] == 'verified'
    replay = client.post(f'{BASE}/{run_id}/replay', json={'task_id': 'reuse_' + family, 'arguments': args})
    assert replay.status_code == 202
    reused = wait_job(client, replay.json()['run_id'], {'completed'})
    assert reused['result']['check_passed'] and reused['executor'] == 'workflow_engine'
    assert reused['result']['primitive_calls'] <= 16
    episode = client.get(f"{BASE}/{reused['run_id']}/artifacts/episode.json").json()
    assert episode['browser']['source_kind'] == 'workflow_engine_replay'
    assert episode['browser']['failure_status'] == 'workflow_replay_verified'
    from core.computer_use.demonstration_compiler import compile_demonstration
    with pytest.raises(ValueError, match='demonstration episode'):
        compile_demonstration(episode, tmp_path / 'bad-replay-candidate', skill_id='replay-candidate')
    assert episode['browser']['student']['external_passed'] is None
    assert episode['browser']['actor_segments'][0]['actor'] == 'workflow_engine'
    import hashlib
    for job in (final, reused):
        for artifact in job['artifacts']:
            response = client.get(artifact['url'])
            assert response.status_code == 200
            assert hashlib.sha256(response.content).hexdigest() == artifact['sha256']
    evidence = client.get(f"{BASE}/{reused['run_id']}/artifacts/browser-check.json").json()
    assert evidence['posts'] == 1 and evidence['readback_matches_backend']
    assert evidence['record'] == ({'name': 'Kage Reuse', 'email': 'reuse@example.test'} if family == 'profile' else
                                  {'email': False, 'sms': True, 'weekly': True})
    assert client.get(f"{BASE}/{run_id}/artifacts/../run_{reused['run_id']}/browser-check.json").status_code == 404
    source = tmp_path / f'run_{run_id}/demonstration-events.jsonl'
    source.write_text(source.read_text() + ' ')
    assert client.post(f'{BASE}/{run_id}/replay', json={'task_id': 'reuse_' + family, 'arguments': args}).status_code == 409


def test_unsaved_capture_incomplete_and_stop_idempotent(client, tmp_path):
    run_id = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    asyncio.run(operate(wait_job(client, run_id, {'recording'}), 'profile', save=False))
    client.post(f'{BASE}/{run_id}/finish')
    final = wait_job(client, run_id, {'incomplete'})
    assert not final['check_passed'] and not final['result'].get('candidate')
    assert final['stop_reason'] == 'check_failed'
    assert client.get(f'{BASE}/{run_id}/artifacts/episode.json').json()['status'] == 'failed'
    assert not (tmp_path / f'run_{run_id}/candidate').exists()
    assert client.post(f'{BASE}/{run_id}/replay', json={'task_id': 'reuse_profile', 'arguments': {}}).status_code == 409
    second = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    wait_job(client, second, {'recording'})
    owner = json.loads((tmp_path / f'run_{second}/worker-owner.json').read_text())
    for _ in range(2):
        assert client.post(f'{BASE}/{second}/stop').json()['status'] == 'stopped'
    with pytest.raises(ProcessLookupError):
        os.kill(owner['pid'], 0)
    assert client.get(f'{BASE}/{second}').json()['stop_reason'] == 'user_stop'


def test_strict_payloads_and_missing_runs(client):
    for payload in ({'task_id': 'reuse_profile'}, {'task_id': 'demo_profile', 'source_kind': 'fake'},
                    {'task_id': 'demo_profile', 'config': {}}, {'task_id': []}):
        assert client.post(BASE, json=payload).status_code == 422
    for suffix in ('', '/finish', '/stop', '/replay'):
        response = client.get(BASE + '/missing') if not suffix else client.post(BASE + '/missing' + suffix, json={})
        assert response.status_code == 404


def test_launcher_real_capture_replay_reload_cancel_and_stale_get(client, monkeypatch):
    async def scenario():
        posts, stopped = [], []
        delayed, release = asyncio.Event(), asyncio.Event()
        captured_old = None
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            async def api(route):
                nonlocal captured_old
                request = route.request
                path = '/api' + request.url.split('/api', 1)[1]
                if request.method == 'OPTIONS':
                    await route.fulfill(status=200, headers={'access-control-allow-origin': '*',
                        'access-control-allow-methods': 'GET, POST, OPTIONS', 'access-control-allow-headers': 'content-type'})
                    return
                response = await asyncio.to_thread(client.request, request.method, path,
                    content=request.post_data if request.method == 'POST' else None,
                    headers={'content-type': 'application/json'} if request.method == 'POST' else None)
                if request.method == 'POST' and path == BASE:
                    posts.append(response.json()['run_id'])
                if request.method == 'POST' and path.endswith('/stop'):
                    stopped.append(path.split('/')[-2])
                if request.method == 'GET' and captured_old and path == BASE + '/' + captured_old and not delayed.is_set():
                    delayed.set()
                    await release.wait()
                await route.fulfill(status=response.status_code, body=response.content,
                    headers={'access-control-allow-origin': '*', 'content-type': response.headers.get('content-type', 'application/json')})

            await page.route('http://127.0.0.1:12345/api/browser/demonstrations**', api)
            await page.goto((ROOT / 'kage-avatar/public/launcher.html').as_uri())
            await page.locator('#demonstration-task').select_option('demo_profile')
            await page.locator('#demonstration-source').select_option('automation')
            await page.locator('#demonstration-start').click()
            while not posts:
                await asyncio.sleep(.02)
            first = posts[0]
            ready = await asyncio.to_thread(wait_job, client, first, {'recording'})
            await page.locator('#demonstration-status').get_by_text('独立教学窗口已就绪', exact=False).wait_for()
            await operate(ready, 'profile')
            await page.locator('#demonstration-finish').click()
            await page.locator('#demonstration-status').get_by_text('候选已生成', exact=False).wait_for(timeout=15000)
            args = json.loads(await page.locator('#demonstration-arguments').input_value())
            args.update(field_1_value='Kage Reuse', field_2_value='reuse@example.test')
            await page.locator('#demonstration-arguments').fill(json.dumps(args))
            await page.locator('#demonstration-replay').click()
            await page.locator('#demonstration-status').get_by_text('复用检查通过', exact=False).wait_for(timeout=15000)
            assert '模型请求: 0' in await page.locator('#demonstration-status').inner_text()
            await page.reload()
            assert await page.locator('#demonstration-replay').is_disabled()
            await page.locator('#demonstration-history').select_option(first)
            await page.locator('#demonstration-status').get_by_text('候选已生成', exact=False).wait_for()
            await page.locator('#demonstration-source').select_option('automation')
            await page.locator('#demonstration-start').click()
            while len(posts) < 2:
                await asyncio.sleep(.02)
            captured_old = posts[1]
            await asyncio.wait_for(delayed.wait(), 15)
            await page.locator('#demonstration-stop').click()
            await page.locator('#demonstration-status').get_by_text('已取消', exact=False).wait_for()
            await page.locator('#demonstration-start').click()
            while len(posts) < 3:
                await asyncio.sleep(.02)
            current = posts[2]
            await page.locator('#demonstration-status').get_by_text(current, exact=False).wait_for()
            release.set()
            await page.wait_for_timeout(700)
            assert current in await page.locator('#demonstration-status').inner_text()
            await page.locator('#demonstration-stop').click()
            await page.locator('#demonstration-status').get_by_text('已取消', exact=False).wait_for()
            await page.evaluate("id => window.dispatchEvent(new CustomEvent('kage:job', {detail:{job:{task_type:'browser_demonstration',run_id:id,status:'recording',ready:true}}}))", current)
            assert '已取消' in await page.locator('#demonstration-status').inner_text()
            assert stopped == [captured_old, current]
            assert await page.locator('#demonstration-finish').is_disabled()
            await page.locator('#demonstration-start').click()
            await page.locator('#demonstration-status').get_by_text('独立教学窗口已就绪', exact=False).wait_for(timeout=15000)
            await page.locator('#demonstration-finish').click()
            await page.locator('#demonstration-status').get_by_text('示范不完整', exact=False).wait_for(timeout=15000)
            assert await page.locator('#demonstration-candidate').is_hidden()
            assert '独立检查: 未通过' in await page.locator('#demonstration-status').inner_text()
            monkeypatch.setenv('KAGE_BROWSER_PYTHON', '/missing/owned-browser-python')
            await page.locator('#demonstration-start').click()
            await page.locator('#demonstration-status').get_by_text('WorkerLaunchError', exact=False).wait_for(timeout=15000)
            assert '独立检查: 待确认' in await page.locator('#demonstration-status').inner_text()
            assert await page.locator('#demonstration-replay').is_disabled()
            await page.unroute_all(behavior='wait')
            await browser.close()
    asyncio.run(scenario())


def test_restart_active_session_stops_owned_worker_and_late_result_is_ignored(client, tmp_path):
    from core.computer_use.demonstration_service import BrowserDemonstrationService
    run_id = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    wait_job(client, run_id, {'recording'})
    workspace = tmp_path / ('run_' + run_id)
    pid = json.loads((workspace / 'worker-owner.json').read_text())['pid']
    restarted = BrowserDemonstrationService(tmp_path, lambda: {})
    job = restarted.get(run_id)
    assert job['status'] == 'stopped' and job['stop_reason'] == 'service_restart'
    assert (workspace / 'stop.requested').exists()
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(.05)
    else:
        raise AssertionError('restarted service left real worker alive')
    # Only the stale-result guard fixture is synthetic; capture tests operate Page.
    (workspace / 'result.json').write_text(json.dumps({'task_status': 'verified', 'check_passed': True}))
    assert restarted.get(run_id)['status'] == 'stopped'
    assert client.get(f'{BASE}/{run_id}').json()['status'] == 'stopped'
    another = BrowserDemonstrationService(tmp_path, lambda: {})
    assert another.get(run_id)['status'] == 'stopped'
    assert another.get(run_id)['stop_reason'] == 'service_restart'


def test_closed_teaching_window_and_crashed_worker_preserve_partial(client, tmp_path):
    async def close_window(job):
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(job['automation_cdp_endpoint'])
            await browser.contexts[0].pages[0].close()
    first = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    asyncio.run(close_window(wait_job(client, first, {'recording'})))
    closed = wait_job(client, first, {'incomplete'})
    assert 'CapturePageClosed' in closed['error']
    assert not closed['result'].get('candidate')
    assert client.get(f'{BASE}/{first}/artifacts/demonstration-summary.json').json()['success'] is False
    second = client.post(BASE, json={'task_id': 'demo_preferences', 'source_kind': 'automation'}).json()['run_id']
    wait_job(client, second, {'recording'})
    pid = json.loads((tmp_path / ('run_' + second) / 'worker-owner.json').read_text())['pid']
    import signal
    os.killpg(pid, signal.SIGKILL)
    crashed = wait_job(client, second, {'failed'})
    assert crashed['stop_reason'] == 'worker_crashed' and not crashed['result'].get('candidate')


def test_worker_launch_error_and_no_config_loading(client, monkeypatch):
    monkeypatch.setenv('KAGE_BROWSER_PYTHON', '/missing/owned-browser-python')
    run_id = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    failed = wait_job(client, run_id, {'failed'})
    assert failed['check_passed'] is None
    assert 'WorkerLaunchError' in failed['error'] and failed['result']['usage']['api_calls'] == 0


def test_check_pass_with_unsupported_visible_control_is_candidate_failure(client, tmp_path):
    async def unsupported(job):
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(job['automation_cdp_endpoint'])
            page = browser.contexts[0].pages[0]
            await page.get_by_label('Name').fill('Kage Demo')
            await page.get_by_label('Email').fill('demo@example.test')
            await page.get_by_label('Name').evaluate('el => el.disabled = true')
            await page.get_by_role('button', name='Save profile').click()
    run_id = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    asyncio.run(unsupported(wait_job(client, run_id, {'recording'})))
    client.post(f'{BASE}/{run_id}/finish')
    failed = wait_job(client, run_id, {'failed'})
    assert failed['check_passed'] is True and failed['result']['candidate_error']
    assert 'unsupported disabled' in failed['error'] and not failed['result'].get('candidate')
    assert not (tmp_path / f'run_{run_id}/candidate').exists()


def test_demonstration_notification_sends_event_without_speech():
    from core.server import KageServer
    server = object.__new__(KageServer)
    from core.dialog_state_machine import DialogStateMachine
    from core.session_state import SessionState
    server.dialog_state = DialogStateMachine(SessionState())
    events = []
    async def send(kind, payload):
        events.append((kind, payload))
    async def speech(*_args):
        raise AssertionError('browser teaching must not speak')
    server.send_message, server.mouth_speak = send, speech
    server._log_server_event = lambda *_args, **_kwargs: None
    asyncio.run(server._notify_job_event('completed', {'task_type': 'browser_demonstration',
                'job_id': 'notification', 'status': 'verified', 'result': {'task_status': 'verified'}}))
    assert events[0][0] == 'job' and events[0][1]['job']['task_type'] == 'browser_demonstration'


def test_verified_bytes_from_abnormal_worker_exit_are_not_a_usable_candidate(client, tmp_path, monkeypatch):
    wrapper = tmp_path / 'abnormal-python'
    wrapper.write_text('#!' + str(ROOT / '.venv-computer-use/bin/python') + '\n'
        'import os, runpy, sys\n'
        'sys.path.insert(0, os.getcwd())\n'
        'sys.argv = ["task_bootstrap", *sys.argv[3:]]\n'
        'runpy.run_module("core.computer_use.task_bootstrap", run_name="__main__")\n'
        'os._exit(1)\n')
    wrapper.chmod(0o755)
    monkeypatch.setenv('KAGE_BROWSER_PYTHON', str(wrapper))
    run_id = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    asyncio.run(operate(wait_job(client, run_id, {'recording'}), 'profile'))
    client.post(f'{BASE}/{run_id}/finish')
    final = wait_job(client, run_id, {'failed'})
    assert final['stop_reason'] == 'worker_crashed'
    assert not final['result'].get('candidate')
    assert client.post(f'{BASE}/{run_id}/replay', json={'task_id': 'reuse_profile', 'arguments': {}}).status_code == 409


def test_overall_deadline_failure_stays_failed_after_restart(client):
    import core.routes.browser_demonstrations as routes
    routes._get_service().RUN_DEADLINE_SECONDS = .05
    run_id = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    final = wait_job(client, run_id, {'failed'})
    assert final['stop_reason'] == 'timeout'
    client.portal.call(routes.close_service)
    restored = client.get(f'{BASE}/{run_id}').json()
    assert restored['status'] == 'failed' and restored['stop_reason'] == 'timeout'


def test_restart_rejects_post_result_worker_before_parent_clean_exit(client, tmp_path, monkeypatch):
    from core.computer_use.demonstration_service import BrowserDemonstrationService
    wrapper = tmp_path / 'delayed-abnormal-python'
    wrapper.write_text('#!' + str(ROOT / '.venv-computer-use/bin/python') + '\n'
        'import os, runpy, sys, time\n'
        'sys.path.insert(0, os.getcwd())\n'
        'sys.argv = ["task_bootstrap", *sys.argv[3:]]\n'
        'runpy.run_module("core.computer_use.task_bootstrap", run_name="__main__")\n'
        'time.sleep(60)\n'
        'os._exit(1)\n')
    wrapper.chmod(0o755)
    monkeypatch.setenv('KAGE_BROWSER_PYTHON', str(wrapper))
    run_id = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    asyncio.run(operate(wait_job(client, run_id, {'recording'}), 'profile'))
    client.post(f'{BASE}/{run_id}/finish')
    workspace = tmp_path / ('run_' + run_id)
    end = time.monotonic() + 10
    while not (workspace / 'result.json').exists() and time.monotonic() < end:
        time.sleep(.02)
    assert json.loads((workspace / 'result.json').read_text())['task_status'] == 'verified'
    assert client.get(f'{BASE}/{run_id}').json()['status'] == 'finalizing'
    restarted = BrowserDemonstrationService(tmp_path, lambda: {})
    final = restarted.get(run_id)
    assert final['status'] == 'stopped' and final['stop_reason'] == 'service_restart'
    assert not final['result'].get('candidate')
    assert (workspace / 'stop.requested').exists()
    pid = json.loads((workspace / 'worker-owner.json').read_text())['pid']
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    time.sleep(.2)
    restored = BrowserDemonstrationService(tmp_path, lambda: {})
    assert restored.get(run_id)['status'] == 'stopped'


def test_restart_terminates_suspended_owner_before_replacement(client, tmp_path):
    from core.computer_use.demonstration_service import BrowserDemonstrationService
    import signal
    run_id = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    wait_job(client, run_id, {'recording'})
    workspace = tmp_path / ('run_' + run_id)
    pid = json.loads((workspace / 'worker-owner.json').read_text())['pid']
    os.killpg(pid, signal.SIGSTOP)
    started = time.monotonic()
    restarted = BrowserDemonstrationService(tmp_path, lambda: {})
    assert time.monotonic() - started < 3
    assert restarted.get(run_id)['stop_reason'] == 'service_restart'
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    async def replace():
        try:
            next_job = await restarted.submit({'task_id': 'demo_profile', 'source_kind': 'automation'})
            assert next_job['run_id'] != run_id
        finally:
            await restarted.close()
    client.portal.call(replace)


def test_restart_pending_real_input_freezes_hashes_after_flush(client, tmp_path):
    from core.computer_use.demonstration_service import BrowserDemonstrationService
    import hashlib
    async def pending(job):
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(job['automation_cdp_endpoint'])
            await browser.contexts[0].pages[0].get_by_label('Name').fill('Correction')
    run_id = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    asyncio.run(pending(wait_job(client, run_id, {'recording'})))
    restarted = BrowserDemonstrationService(tmp_path, lambda: {})
    time.sleep(.7)
    final = restarted.get(run_id)
    assert final['status'] == 'stopped' and final['event_count'] == 1
    assert json.loads((tmp_path / ('run_' + run_id) / 'demonstration-summary.json').read_text())['event_count'] == 1
    for item in final['artifacts']:
        assert hashlib.sha256(restarted.artifact(run_id, item['name']).read_bytes()).hexdigest() == item['sha256']
    restored = BrowserDemonstrationService(tmp_path, lambda: {})
    assert restored.get(run_id)['artifacts'] == final['artifacts']


def test_failed_replay_after_real_partial_action_is_checked_and_archived(client, tmp_path):
    run_id = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    asyncio.run(operate(wait_job(client, run_id, {'recording'}), 'profile'))
    client.post(f'{BASE}/{run_id}/finish')
    candidate = wait_job(client, run_id, {'verified'})['result']['candidate']
    args = {**candidate['arguments'], 'field_1_value': 'Kage Reuse', 'field_2_label': 'Missing visible label'}
    created = client.post(f'{BASE}/{run_id}/replay', json={'task_id': 'reuse_profile', 'arguments': args})
    assert created.status_code == 202
    replay_id = created.json()['run_id']
    final = wait_job(client, replay_id, {'failed'})
    assert final['stop_reason'] == 'workflow_failed'
    assert 'Missing visible label' in final['error'] and final['check_passed'] is False
    scored = client.get(f'{BASE}/{replay_id}/artifacts/run-result.json').json()
    assert scored['status'] == 'failed' and scored['score'] == 0
    episode = client.get(f'{BASE}/{replay_id}/artifacts/episode.json').json()
    assert episode['status'] == 'failed'
    assert episode['browser']['source_kind'] == 'workflow_engine_replay'
    assert episode['browser']['failure_status'] == 'workflow_replay_incomplete'
    assert episode['browser']['student']['external_passed'] is None
    assert episode['browser']['actor_segments'] == [{'actor': 'workflow_engine', 'tool_calls': 3}]
    tools = [json.loads(line) for line in client.get(f'{BASE}/{replay_id}/artifacts/actor-tools.jsonl').text.splitlines()]
    assert any(row['name'] == 'browser_act' and row['success'] and row['arguments'].get('value') == 'Kage Reuse' for row in tools)
    from core.computer_use.demonstration_compiler import compile_demonstration
    with pytest.raises(ValueError):
        compile_demonstration(episode, tmp_path / 'rejected-replay', skill_id='form-rejected')


@pytest.mark.parametrize('corruption', ['mismatched_run', 'malformed_json'])
def test_recovery_rejects_mismatched_live_ownership_without_signalling(client, tmp_path, corruption):
    from core.computer_use.demonstration_service import BrowserDemonstrationService
    import signal
    run_id = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    wait_job(client, run_id, {'recording'})
    owner_path = tmp_path / ('run_' + run_id) / 'worker-owner.json'
    owner = json.loads(owner_path.read_text())
    os.killpg(owner['pid'], signal.SIGSTOP)
    # Corrupt only ownership metadata; Page evidence remains genuinely captured.
    owner_path.write_text(json.dumps({**owner, 'run_id': 'different-owned-session'})
                          if corruption == 'mismatched_run' else '{malformed ownership')
    restarted = BrowserDemonstrationService(tmp_path, lambda: {})
    assert 'RecoveryOwnershipUnverified' in restarted.get(run_id)['error']
    assert restarted.get(run_id)['artifacts'] == []
    os.kill(owner['pid'], 0)
    async def rejected():
        with pytest.raises(RuntimeError, match='recovery is incomplete'):
            await restarted.submit({'task_id': 'demo_profile', 'source_kind': 'automation'})
        await restarted.close()
    client.portal.call(rejected)
    # The original parent still owns its actual process handle and can reap it.
    import core.routes.browser_demonstrations as routes
    client.portal.call(routes.close_service)
    with pytest.raises(ProcessLookupError):
        os.kill(owner['pid'], 0)


def test_restart_blocks_surviving_group_when_actual_bootstrap_leader_is_gone(tmp_path):
    from core.computer_use.demonstration_service import BrowserDemonstrationService
    import hashlib
    import signal
    import subprocess
    run_id = 'orphan-production-bootstrap'
    workspace = tmp_path / ('run_' + run_id)
    workspace.mkdir()
    # Only session routing metadata is supplied. The production worker captures
    # all observations and real Page input; no result or evidence is fabricated.
    (workspace / 'session.json').write_text(json.dumps({'job_id': run_id, 'run_id': run_id,
        'status': 'running', 'task_type': 'browser_demonstration', 'operation': 'demonstration',
        'task_id': 'demo_profile', 'source_kind': 'automation', 'executor': 'automation'}))
    proc = subprocess.Popen([str(ROOT / '.venv-computer-use/bin/python'), '-m',
        'core.computer_use.task_bootstrap', str(tmp_path), run_id, 'demonstration_worker'],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, env={**os.environ, 'KAGE_BROWSER_DEMONSTRATION_HEADLESS': '1'})
    services = []

    def members():
        output = subprocess.check_output(['ps', '-axo', 'pid=,pgid=,stat='], text=True)
        return {int(parts[0]): parts[2] for line in output.splitlines()
                if len(parts := line.split()) == 3 and int(parts[1]) == proc.pid}

    async def pending(endpoint):
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(endpoint)
            await browser.contexts[0].pages[0].get_by_label('Name').fill('Correction')

    try:
        proc.stdin.write(json.dumps({'run_id': run_id, 'run_root': str(tmp_path),
            'task_id': 'demo_profile', 'operation': 'demonstration', 'source_kind': 'automation',
            'executor': 'automation', 'config': {}}).encode())
        proc.stdin.close()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = BrowserDemonstrationService._read(workspace / 'status.json')
            if state.get('status') == 'recording':
                break
            time.sleep(.02)
        else:
            raise AssertionError('actual bootstrap never reached recording')
        asyncio.run(pending(state['automation_cdp_endpoint']))
        os.killpg(proc.pid, signal.SIGSTOP)
        os.kill(proc.pid, signal.SIGKILL)
        assert proc.wait(timeout=3) == -signal.SIGKILL
        before = members()
        assert before and all('T' in status for status in before.values())
        restarted = BrowserDemonstrationService(tmp_path, lambda: {})
        services.append(restarted)
        final = restarted.get(run_id)
        assert 'RecoveryOwnershipUnverified' in (final['error'] or '')
        assert final['artifacts'] == [] and final['event_count'] == 0
        assert restarted.artifact(run_id, 'initial-observation.json') is None
        assert members() == before  # No guessed descendant signalling.

        async def reject_replacement():
            with pytest.raises(RuntimeError, match='recovery is incomplete'):
                await restarted.submit({'task_id': 'demo_profile', 'source_kind': 'automation'})
        asyncio.run(reject_replacement())
    finally:
        # This harness owns the process group and performs cleanup explicitly.
        for action in (signal.SIGCONT, signal.SIGKILL):
            try:
                os.killpg(proc.pid, action)
            except ProcessLookupError:
                pass
        if proc.poll() is None:
            proc.wait(timeout=3)
        deadline = time.monotonic() + 3
        while members() and time.monotonic() < deadline:
            time.sleep(.02)
        for service in services:
            asyncio.run(service.close())
        assert not members(), 'harness left an actual owned process group'

    # Once the group is actually absent, a fresh service can freeze evidence.
    recovered = BrowserDemonstrationService(tmp_path, lambda: {})
    final = recovered.get(run_id)
    assert final['error'] is None and final['artifacts']
    for item in final['artifacts']:
        assert hashlib.sha256(recovered.artifact(run_id, item['name']).read_bytes()).hexdigest() == item['sha256']
    asyncio.run(recovered.close())


@pytest.mark.parametrize('exit_code', [0, 1])
def test_public_result_waits_for_actual_worker_settlement(client, tmp_path, monkeypatch, exit_code):
    release = tmp_path / 'release-worker'
    wrapper = tmp_path / 'held-python'
    wrapper.write_text('#!' + str(ROOT / '.venv-computer-use/bin/python') + '\n'
        'import os, runpy, sys, time\nfrom pathlib import Path\n'
        'sys.path.insert(0, os.getcwd())\n'
        'sys.argv = ["task_bootstrap", *sys.argv[3:]]\n'
        'runpy.run_module("core.computer_use.task_bootstrap", run_name="__main__")\n'
        f'while not Path({str(release)!r}).exists(): time.sleep(.02)\n'
        f'os._exit({exit_code})\n')
    wrapper.chmod(0o755)
    monkeypatch.setenv('KAGE_BROWSER_PYTHON', str(wrapper))
    run_id = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    asyncio.run(operate(wait_job(client, run_id, {'recording'}), 'profile'))
    client.post(f'{BASE}/{run_id}/finish')
    workspace = tmp_path / ('run_' + run_id)
    end = time.monotonic() + 10
    while not (workspace / 'result.json').exists() and time.monotonic() < end:
        time.sleep(.02)
    raw = json.loads((workspace / 'result.json').read_text())
    assert raw['task_status'] == 'verified' and raw['candidate']['digest']
    pid = json.loads((workspace / 'worker-owner.json').read_text())['pid']
    os.kill(pid, 0)
    try:
        for job in (client.get(f'{BASE}/{run_id}').json(),
                    next(j for j in client.get(BASE).json() if j['run_id'] == run_id)):
            assert job['status'] == 'finalizing' and job['execution_status'] == 'running'
            assert job['result'] is None and job['check_passed'] is None and job['artifacts'] == []
        assert client.get(f'{BASE}/{run_id}/artifacts/candidate/manifest.json').status_code == 404
        assert not (tmp_path / (run_id + '-acceptance.json')).exists()
    finally:
        release.touch()
    final = wait_job(client, run_id, {'verified' if exit_code == 0 else 'failed'})
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    if exit_code == 0:
        assert final['check_passed'] is True and final['result']['candidate']['digest'] == raw['candidate']['digest']
        assert client.get(f'{BASE}/{run_id}/artifacts/candidate/manifest.json').status_code == 200
    else:
        assert final['stop_reason'] == 'worker_crashed' and not final['result'].get('candidate')
        assert (workspace / 'candidate/manifest.json').is_file()
        assert client.get(f'{BASE}/{run_id}/artifacts/candidate/manifest.json').status_code == 404
        assert client.get(f'{BASE}/{run_id}/artifacts/candidate.json').status_code == 404
        assert client.post(f'{BASE}/{run_id}/replay', json={'task_id': 'reuse_profile', 'arguments': raw['candidate']['arguments']}).status_code == 409


def test_reads_during_delayed_stop_do_not_index_live_worker(client, tmp_path, monkeypatch):
    import hashlib
    import signal
    import threading
    import core.routes.browser_demonstrations as routes
    service = routes._get_service()
    run_id = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    asyncio.run(operate(wait_job(client, run_id, {'recording'}), 'profile', save=False))
    workspace = tmp_path / ('run_' + run_id)
    pid = json.loads((workspace / 'worker-owner.json').read_text())['pid']
    os.killpg(pid, signal.SIGSTOP)
    entered, release = threading.Event(), threading.Event()
    original_kill, original_partial = service._kill, service._partial
    indexed = []

    async def delayed_kill(proc):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(.01)
        await original_kill(proc)

    def count_partial(*args):
        indexed.append(args)
        return original_partial(*args)

    monkeypatch.setattr(service, '_kill', delayed_kill)
    monkeypatch.setattr(service, '_partial', count_partial)
    future = client.portal.start_task_soon(service.stop, run_id)
    try:
        assert entered.wait(5)
        os.kill(pid, 0)
        for _ in range(3):
            job = client.get(f'{BASE}/{run_id}').json()
            assert job['status'] == 'finalizing' and job['result'] is None
            assert job['check_passed'] is None and job['artifacts'] == []
            assert client.get(f'{BASE}/{run_id}/artifacts/initial-observation.json').status_code == 404
            assert next(j for j in client.get(BASE).json() if j['run_id'] == run_id)['artifacts'] == []
        assert indexed == []
        assert not (tmp_path / (run_id + '-acceptance.json')).exists()
    finally:
        os.killpg(pid, signal.SIGCONT)
        release.set()
        final = future.result(timeout=10)
    assert final['status'] == 'stopped' and final['stop_reason'] == 'user_stop'
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert final['result'] and not final['result'].get('candidate')
    for item in final['artifacts']:
        response = client.get(item['url'])
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == item['sha256']


@pytest.mark.parametrize('mutation', ['start', 'replay'])
@pytest.mark.parametrize('history_outcome', ['success', 'error', 'empty'])
def test_launcher_history_serializes_mutations_and_releases_controls(client, mutation, history_outcome):
    # Real candidate plus real Launcher; defer transport responses only.
    old = client.post(BASE, json={'task_id': 'demo_profile', 'source_kind': 'automation'}).json()['run_id']
    asyncio.run(operate(wait_job(client, old, {'recording'}), 'profile'))
    client.post(f'{BASE}/{old}/finish')
    wait_job(client, old, {'verified'})

    async def scenario():
        history_entered, history_release = asyncio.Event(), asyncio.Event()
        post_entered, post_release = asyncio.Event(), asyncio.Event()
        history_reads, posts = 0, []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            async def api(route):
                nonlocal history_reads
                request = route.request
                path = '/api' + request.url.split('/api', 1)[1]
                headers = {'access-control-allow-origin': '*', 'content-type': 'application/json',
                           'access-control-allow-methods': 'GET, POST, OPTIONS', 'access-control-allow-headers': 'content-type'}
                if request.method == 'OPTIONS':
                    await route.fulfill(status=200, headers=headers)
                    return
                response = await asyncio.to_thread(client.request, request.method, path,
                    content=request.post_data if request.method == 'POST' else None,
                    headers={'content-type': 'application/json'} if request.method == 'POST' else None)
                if request.method == 'GET' and path == BASE + '/' + old:
                    history_reads += 1
                    if history_reads == 2:
                        history_entered.set()
                        await history_release.wait()
                        if history_outcome == 'error':
                            await route.fulfill(status=500, body='{"detail":"history unavailable"}', headers=headers)
                            return
                if request.method == 'POST':
                    posts.append((path, response.json()))
                    post_entered.set()
                    await post_release.wait()
                await route.fulfill(status=response.status_code, body=response.content, headers=headers)

            await page.route('http://127.0.0.1:12345/api/browser/demonstrations**', api)
            try:
                await page.goto((ROOT / 'kage-avatar/public/launcher.html').as_uri())
                await page.locator('#demonstration-history').select_option(old)
                await page.locator('#demonstration-status').get_by_text(old, exact=False).wait_for()
                await page.locator('#demonstration-history').select_option('')
                await page.locator('#demonstration-history').select_option(old)
                await asyncio.wait_for(history_entered.wait(), 5)
                assert await page.locator('#demonstration-start').is_disabled()
                assert await page.locator('#demonstration-replay').is_disabled()
                # Even a queued/programmatic click cannot submit a competing action.
                await page.locator('#demonstration-' + mutation).dispatch_event('click')
                assert posts == []
                if history_outcome == 'empty':
                    await page.locator('#demonstration-history').evaluate("el => {el.value=''; el.dispatchEvent(new Event('change'));}")
                history_release.set()
                await page.wait_for_function("!document.querySelector('#demonstration-start').disabled")
                assert history_reads == 2
                if history_outcome == 'success':
                    assert await page.locator('#demonstration-replay').is_enabled()
                else:
                    if history_outcome == 'error':
                        await page.locator('#demonstration-error').get_by_text('500', exact=False).wait_for()
                    # Select a candidate explicitly again before replay after a failed/empty load.
                    if mutation == 'replay':
                        await page.locator('#demonstration-history').select_option('')
                        await page.locator('#demonstration-history').select_option(old)
                        await page.locator('#demonstration-replay').wait_for(state='visible')
                        await page.wait_for_function("!document.querySelector('#demonstration-replay').disabled")
                await page.locator('#demonstration-task').select_option('demo_profile')
                await page.locator('#demonstration-source').select_option('automation')
                await page.locator('#demonstration-' + mutation).click()
                await asyncio.wait_for(post_entered.wait(), 5)
                assert len(posts) == 1 and posts[0][1]['run_id'] != old
                # A late history selection cannot invalidate an accepted POST owner.
                await page.locator('#demonstration-history').evaluate("el => {el.value=''; el.dispatchEvent(new Event('change'));}")
                post_release.set()
                new_id = posts[0][1]['run_id']
                await page.locator('#demonstration-status').get_by_text(new_id, exact=False).wait_for()
                if mutation == 'start':
                    await page.locator('#demonstration-status').get_by_text('独立教学窗口已就绪', exact=False).wait_for()
                    assert await page.locator('#demonstration-stop').is_enabled()
                    assert await page.locator('#demonstration-finish').is_enabled()
                else:
                    await page.locator('#demonstration-status').get_by_text('执行者: workflow_engine', exact=False).wait_for()
                assert len(posts) == 1
            finally:
                history_release.set()
                post_release.set()
                await page.unroute_all(behavior='wait')
                await browser.close()
    asyncio.run(scenario())
