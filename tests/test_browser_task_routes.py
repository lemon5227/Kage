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
        assert '检查通过' not in page.locator('#browser-job-status').inner_text()

        model_server.hang = True
        page.locator('#browser-start').click()
        assert model_server.entered.wait(25)
        page.locator('#browser-stop').click()
        page.locator('#browser-job-status').get_by_text('已停止', exact=False).wait_for(timeout=10000)
        assert len([r for r in requests if r[0] == 'POST' and r[1].endswith('/stop')]) == 1
        model_server.release.set()
        browser.close()
