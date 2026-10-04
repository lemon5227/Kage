"""Browser experiment HTTP and Launcher behavior with a real scripted worker."""
import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_browser_task_service import model_server, config

pytest.importorskip('playwright.async_api')


@pytest.fixture
def client(tmp_path, model_server, monkeypatch):
    import core.server as server
    import core.routes.browser_tasks as routes

    monkeypatch.setenv('KAGE_MODE', 'control')
    monkeypatch.setenv('KAGE_BROWSER_RUNS_DIR', str(tmp_path))
    monkeypatch.setenv('KAGE_BROWSER_PYTHON', str(Path(__file__).resolve().parents[1] / '.venv-computer-use/bin/python'))
    monkeypatch.setattr(server, '_load_effective_config', lambda: config(model_server))
    routes._service = None
    with TestClient(server.app) as http:
        yield http
    assert routes._service is None


def wait_for(client, run_id, expected, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f'/api/browser/tasks/{run_id}')
        assert response.status_code == 200
        job = response.json()
        if job['status'] in {'completed', 'failed', 'unknown', 'stopped'}:
            assert job['status'] == expected
            return job
        time.sleep(.05)
    raise AssertionError(f'job did not terminate: {job}')


@pytest.mark.parametrize('task_id,mode,status,passed', [
    ('preferences_dev', 'save', 'completed', True),
    ('preferences_dev', 'done', 'failed', False),
    ('preferences_unchecked', 'done', 'unknown', None),
])
def test_control_http_real_worker_and_artifacts(client, model_server, tmp_path, task_id, mode, status, passed):
    model_server.mode = mode
    catalog = client.get('/api/browser/catalog')
    assert catalog.status_code == 200
    assert task_id in {item['task_id'] for item in catalog.json()['tasks']}
    created = client.post('/api/browser/tasks', json={'task_id': task_id, 'max_loop_steps': 5})
    assert created.status_code == 202
    job = created.json()
    assert job['status'] in {'queued', 'running'}
    run_id = job['run_id']
    assert any(item['run_id'] == run_id for item in client.get('/api/browser/tasks').json())
    final = wait_for(client, run_id, status)
    assert final['result']['task_status'] == status
    assert final['result']['check_passed'] is passed
    assert final['result']['model_name'] == 'scripted-http'
    check = next(item for item in final['result']['artifacts'] if item['name'] == 'browser-check.json')
    evidence = client.get(check['url'])
    assert evidence.status_code == 200
    assert json.loads(evidence.content)['posts'] == (1 if status == 'completed' else 0)
    if status == 'completed':
        # Task 1 currently emits flat files. Add one to the real run's index to
        # exercise the route's path converter and the service's index guard.
        import core.routes.browser_tasks as routes
        name = 'nested/evidence.txt'
        nested_path = tmp_path / f'run_{run_id}' / name
        nested_path.parent.mkdir()
        nested_path.write_text('saved evidence')
        indexed = {**final['result'], 'artifacts': [*final['result']['artifacts'],
                   {'name': name, 'url': f'/api/browser/tasks/{run_id}/artifacts/{name}'}]}
        routes._service._results[run_id] = indexed
        assert client.get(f'/api/browser/tasks/{run_id}/artifacts/{name}').text == 'saved evidence'
    assert client.get(f'/api/browser/tasks/{run_id}/artifacts/not-indexed.txt').status_code == 404
    assert client.get(f'/api/browser/tasks/missing/artifacts/{check["name"]}').status_code == 404
    assert client.get('/api/browser/tasks/missing').status_code == 404
    assert client.post('/api/browser/tasks/missing/stop').status_code == 404


def test_runtime_notification_failure_does_not_strand_worker(client, model_server):
    import core.server as server

    class BrokenRuntime:
        async def _notify_job_event(self, _event, _job):
            raise RuntimeError('synthetic disconnected UI')

    server.kage_server = BrokenRuntime()
    try:
        created = client.post('/api/browser/tasks', json={'task_id': 'preferences_dev'}).json()
        assert wait_for(client, created['run_id'], 'completed')['result']['check_passed'] is True
    finally:
        server.kage_server = None


def test_stalled_runtime_notification_does_not_delay_worker_stop_or_close(client, model_server):
    import core.server as server
    import core.routes.browser_tasks as routes

    class StalledRuntime:
        def __init__(self):
            self.release = asyncio.Event()
            self.entered = asyncio.Event()

        async def _notify_job_event(self, _event, _job):
            self.entered.set()
            await self.release.wait()

    runtime = StalledRuntime()
    server.kage_server = runtime
    try:
        first = client.post('/api/browser/tasks', json={'task_id': 'preferences_dev'}).json()
        # The real scripted HTTP model must be reached while notification is still stalled.
        deadline = time.monotonic() + 5
        while model_server.calls == 0 and time.monotonic() < deadline:
            time.sleep(.02)
        assert model_server.calls > 0
        assert client.portal.call(runtime.entered.is_set)
        assert not runtime.release.is_set()
        assert wait_for(client, first['run_id'], 'completed')['result']['check_passed'] is True

        model_server.hang = True
        second = client.post('/api/browser/tasks', json={'task_id': 'preferences_dev'}).json()
        assert model_server.entered.wait(25)
        started = time.monotonic()
        assert client.post(f'/api/browser/tasks/{second["run_id"]}/stop').json()['status'] == 'stopped'
        assert time.monotonic() - started < 2
        started = time.monotonic()
        client.portal.call(routes.close_service)
        assert time.monotonic() - started < 2
        assert routes._service is None
        assert client.portal.call(lambda: all(task.done() for task in routes._notification_tasks))
    finally:
        client.portal.call(runtime.release.set)
        model_server.release.set()
        server.kage_server = None


def test_invalid_payload_config_and_stop_preserve_truth(client, model_server):
    assert client.post('/api/browser/tasks', json={'task_id': 'missing'}).status_code == 422
    assert client.post('/api/browser/tasks', json={'task_id': 'preferences_dev', 'instruction': 'other'}).status_code == 422
    assert client.post('/api/browser/tasks', json={'task_id': 'preferences_dev', 'executor': 'cloud'}).status_code in {409, 422}
    model_server.hang = True
    first = client.post('/api/browser/tasks', json={'task_id': 'preferences_dev'}).json()
    assert model_server.entered.wait(25)
    second = client.post('/api/browser/tasks', json={'task_id': 'preferences_dev'}).json()
    assert client.post(f'/api/browser/tasks/{second["run_id"]}/stop').json()['status'] == 'stopped'
    assert client.post(f'/api/browser/tasks/{first["run_id"]}/stop').json()['status'] == 'stopped'
    model_server.release.set()
    assert wait_for(client, first['run_id'], 'stopped')['result']['stop_reason'] == 'user_stop'
    assert wait_for(client, second['run_id'], 'stopped')['status'] == 'stopped'
    time.sleep(.2)
    assert client.get(f'/api/browser/tasks/{first["run_id"]}').json()['status'] == 'stopped'


def test_launcher_click_status_evidence_and_stop(client, model_server):
    from playwright.sync_api import sync_playwright
    launcher = Path(__file__).resolve().parents[1] / 'kage-avatar/public/launcher.html'
    model_server.mode = 'done'
    requests = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()

        def api_route(route):
            request = route.request
            path = request.url.split('/api', 1)[1]
            if path.startswith('/browser/'):
                requests.append((request.method, path))
            if request.method == 'OPTIONS':
                route.fulfill(status=200, headers={'access-control-allow-origin': '*',
                                                    'access-control-allow-methods': 'GET, POST, OPTIONS',
                                                    'access-control-allow-headers': 'content-type'})
                return
            response = client.request(request.method, '/api' + path,
                                      content=request.post_data if request.method == 'POST' else None,
                                      headers={'content-type': 'application/json'} if request.method == 'POST' else None)
            route.fulfill(status=response.status_code, body=response.content,
                          headers={'access-control-allow-origin': '*', 'content-type': response.headers.get('content-type', 'application/json')})

        page.route('http://127.0.0.1:12345/api/browser/**', api_route)
        page.goto(launcher.as_uri())
        page.locator('#browser-task-id').select_option('preferences_unchecked')
        page.locator('#browser-start').click()
        page.locator('#browser-job-status').get_by_text('待确认', exact=False).wait_for(timeout=35000)
        assert page.locator('#browser-job-status').get_by_text('通过').count() == 0
        assert page.locator('#browser-artifacts a').count() > 0
        assert len([r for r in requests if r == ('POST', '/browser/tasks')]) == 1
        page.reload()
        page.locator('#browser-job-status').get_by_text('待确认', exact=False).wait_for(timeout=10000)
        page.evaluate("""() => window.dispatchEvent(new CustomEvent('kage:job', {detail: {
          event: 'completed', job: {task_type: 'browser_experiment', run_id: document.querySelector('#browser-job-status').textContent.match(/运行 ID: ([^\\n]+)/)[1],
          status: 'unknown', result: {task_status: 'unknown', final_text: '<img src=x onerror=alert(1)>'}}
        }}))""")
        assert page.locator('#browser-experiment img').count() == 0
        assert '<img src=x onerror=alert(1)>' in page.locator('#browser-job-status').inner_text()

        page.locator('#browser-task-id').select_option('preferences_dev')
        page.locator('#browser-start').click()
        page.locator('#browser-job-status').get_by_text('未通过', exact=False).wait_for(timeout=35000)
        assert '检查: 未通过' in page.locator('#browser-job-status').inner_text()
        assert '检查通过' not in page.locator('#browser-job-status').inner_text()

        model_server.hang = True
        page.locator('#browser-start').click()
        assert model_server.entered.wait(25)
        page.locator('#browser-stop').click()
        page.locator('#browser-job-status').get_by_text('已停止', exact=False).wait_for(timeout=10000)
        assert len([r for r in requests if r[0] == 'POST' and r[1].endswith('/stop')]) == 1
        model_server.release.set()
        browser.close()


@pytest.mark.parametrize('task_id,check_text', [
    ('preferences_dev', '检查: 未确认'),
    ('preferences_unchecked', '检查: 未提供'),
])
def test_launcher_shows_unconfirmed_goal_for_worker_launch_error(client, model_server, monkeypatch,
                                                                tmp_path, task_id, check_text):
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv('KAGE_BROWSER_PYTHON', str(tmp_path / 'missing-python'))
    launcher = Path(__file__).resolve().parents[1] / 'kage-avatar/public/launcher.html'

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()

        def api_route(route):
            request = route.request
            path = request.url.split('/api', 1)[1]
            if request.method == 'OPTIONS':
                route.fulfill(status=200, headers={'access-control-allow-origin': '*',
                                                    'access-control-allow-methods': 'GET, POST, OPTIONS',
                                                    'access-control-allow-headers': 'content-type'})
                return
            response = client.request(request.method, '/api' + path,
                                      content=request.post_data if request.method == 'POST' else None,
                                      headers={'content-type': 'application/json'} if request.method == 'POST' else None)
            route.fulfill(status=response.status_code, body=response.content,
                          headers={'access-control-allow-origin': '*',
                                   'content-type': response.headers.get('content-type', 'application/json')})

        page.route('http://127.0.0.1:12345/api/browser/**', api_route)
        page.goto(launcher.as_uri())
        page.locator('#browser-task-id').select_option(task_id)
        page.locator('#browser-start').click()
        page.locator('#browser-job-status').get_by_text('执行失败，目标未确认', exact=False).wait_for(timeout=15000)
        status = page.locator('#browser-job-status').inner_text()
        assert check_text in status
        assert '错误: WorkerLaunchError' in status
        assert '未通过检查' not in status
        assert model_server.calls == 0
        browser.close()


def test_launcher_ignores_late_poll_from_previous_run_and_terminal_revival(client, model_server):
    from playwright.async_api import async_playwright

    launcher = Path(__file__).resolve().parents[1] / 'kage-avatar/public/launcher.html'
    model_server.hang = True

    async def scenario():
        post_ids = []
        stopped_ids = []
        seen_a, release_a = asyncio.Event(), asyncio.Event()
        seen_b, release_b = asyncio.Event(), asyncio.Event()

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()

            async def api_route(route):
                request = route.request
                path = request.url.split('/api', 1)[1]
                if request.method == 'OPTIONS':
                    await route.fulfill(status=200, headers={
                        'access-control-allow-origin': '*',
                        'access-control-allow-methods': 'GET, POST, OPTIONS',
                        'access-control-allow-headers': 'content-type',
                    })
                    return
                response = await asyncio.to_thread(
                    client.request, request.method, '/api' + path,
                    content=request.post_data if request.method == 'POST' else None,
                    headers={'content-type': 'application/json'} if request.method == 'POST' else None,
                )
                if request.method == 'POST' and path == '/browser/tasks':
                    post_ids.append(response.json()['run_id'])
                if request.method == 'POST' and path.endswith('/stop'):
                    stopped_ids.append(path.split('/')[3])
                if request.method == 'GET' and len(post_ids) >= 1 and path == f'/browser/tasks/{post_ids[0]}' and not seen_a.is_set():
                    seen_a.set()
                    await release_a.wait()
                if request.method == 'GET' and len(post_ids) >= 2 and path == f'/browser/tasks/{post_ids[1]}' and not seen_b.is_set():
                    seen_b.set()
                    await release_b.wait()
                await route.fulfill(status=response.status_code, body=response.content, headers={
                    'access-control-allow-origin': '*',
                    'content-type': response.headers.get('content-type', 'application/json'),
                })

            await page.route('http://127.0.0.1:12345/api/browser/**', api_route)
            await page.goto(launcher.as_uri())
            await page.locator('#browser-task-id').select_option('preferences_dev')
            await page.locator('#browser-start').click()
            await asyncio.wait_for(seen_a.wait(), 15)
            await page.locator('#browser-start').click()
            while len(post_ids) < 2:
                await asyncio.sleep(.02)
            run_a, run_b = post_ids
            await page.locator('#browser-job-status').get_by_text(run_b, exact=False).wait_for(timeout=10000)

            release_a.set()
            await page.wait_for_timeout(350)
            assert run_b in await page.locator('#browser-job-status').inner_text()
            assert run_a not in await page.locator('#browser-job-status').inner_text()
            await page.evaluate("""runId => window.dispatchEvent(new CustomEvent('kage:job', {
              detail: {event: 'running', job: {task_type: 'browser_experiment', run_id: runId, status: 'running'}}
            }))""", run_a)
            assert run_b in await page.locator('#browser-job-status').inner_text()

            await asyncio.wait_for(seen_b.wait(), 15)
            await page.locator('#browser-stop').click()
            await page.locator('#browser-job-status').get_by_text('已停止', exact=False).wait_for(timeout=10000)
            assert stopped_ids == [run_b]
            release_b.set()
            await page.wait_for_timeout(350)
            assert run_b in await page.locator('#browser-job-status').inner_text()
            assert '已停止' in await page.locator('#browser-job-status').inner_text()
            assert '排队中' not in await page.locator('#browser-job-status').inner_text()
            await page.evaluate("""runId => window.dispatchEvent(new CustomEvent('kage:job', {
              detail: {event: 'running', job: {task_type: 'browser_experiment', run_id: runId, status: 'running'}}
            }))""", run_b)
            assert '已停止' in await page.locator('#browser-job-status').inner_text()
            await asyncio.to_thread(client.post, f'/api/browser/tasks/{run_a}/stop')
            model_server.release.set()
            await browser.close()

    asyncio.run(scenario())
