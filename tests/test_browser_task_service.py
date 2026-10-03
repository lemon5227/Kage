"""End-to-end browser jobs against a scripted HTTP model endpoint."""
import asyncio
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time

import pytest

from core.computer_use.task_service import BrowserTaskService

pytest.importorskip('playwright.async_api')


class ScriptedModel(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        server = self.server
        server.calls += 1
        server.requests.append(request)
        if server.hang:
            server.entered.set()
            server.release.wait(30)
        messages = request['messages']
        observation = None
        for message in messages:
            content = message.get('content') or ''
            if not isinstance(content, str):
                continue
            if 'Initial browser observation supplied by runtime:\n' in content:
                observation = json.loads(content.split('Initial browser observation supplied by runtime:\n', 1)[1])
            elif message['role'] == 'tool' and '{' in content:
                payload = json.loads(content[content.index('{'):])
                observation = payload.get('observation', observation)
        action = None
        if server.mode == 'save':
            for label in ('Email notifications', 'SMS notifications', 'Save settings'):
                target = next((target for target in observation['targets'] if target.get('label') == label), None)
                if target is None:
                    continue
                if label == 'Email notifications' and target.get('checked') is True:
                    continue
                if label == 'SMS notifications' and target.get('checked') is False:
                    continue
                if label == 'Save settings' and server.calls < 3:
                    continue
                action = {'name': 'browser_act', 'arguments': {
                    'observation_id': observation['observation_id'],
                    'target_ref': target['target_ref'], 'operation': 'click'}}
                break
        message = {'role': 'assistant', 'content': 'Done.'}
        if action:
            message['tool_calls'] = [{'id': f'call-{server.calls}', 'type': 'function',
                                      'function': {'name': action['name'], 'arguments': json.dumps(action['arguments'])}}]
            message['content'] = None
        body = json.dumps({'choices': [{'message': message, 'finish_reason': 'tool_calls' if action else 'stop'}],
                           'usage': {'prompt_tokens': 3, 'completion_tokens': 2}}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def model_server():
    server = ThreadingHTTPServer(('127.0.0.1', 0), ScriptedModel)
    server.calls = 0
    server.requests = []
    server.mode = 'save'
    server.hang = False
    server.entered = threading.Event()
    server.release = threading.Event()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.release.set()
    server.shutdown()
    thread.join(timeout=3)
    server.server_close()


def config(server):
    return {'model': {'local_runtime': {'host': '127.0.0.1', 'port': server.server_port,
                                       'model_name': 'scripted-http', 'timeout_sec': 30}}}


async def terminal(service, run_id, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = service.get(run_id)
        if job['status'] in {'completed', 'failed', 'stopped', 'unknown'}:
            return job
        await asyncio.sleep(.05)
    raise AssertionError(f'run {run_id} did not finish: {service.get(run_id)}')


@pytest.mark.parametrize('task_id,mode,expected_status,passed,posts', [
    ('preferences_dev', 'save', 'completed', True, 1),
    ('preferences_dev', 'done', 'failed', False, 0),
    ('preferences_unchecked', 'done', 'unknown', None, 0),
])
def test_real_worker_http_model_page_and_checker(tmp_path, model_server, monkeypatch,
                                                 task_id, mode, expected_status, passed, posts):
    monkeypatch.setenv('KAGE_BROWSER_PYTHON', str(Path(__file__).resolve().parents[1] / '.venv-computer-use/bin/python'))
    model_server.mode = mode

    async def scenario():
        service = BrowserTaskService(tmp_path, lambda: config(model_server))
        try:
            job = await service.submit({'task_id': task_id, 'executor': 'local'})
            final = await terminal(service, job['run_id'])
            assert final['status'] == expected_status
            assert final['result']['check_passed'] is passed
            check = json.loads(service.artifact(job['run_id'], 'browser-check.json').read_text())
            assert check['posts'] == posts
            if passed:
                assert check == {'record': {'email': True, 'sms': False, 'weekly': False},
                                 'posts': 1, 'readback_matches_backend': True}
            assert all('scoring_criteria' not in json.dumps(request) for request in model_server.requests)
        finally:
            await service.close()

    asyncio.run(scenario())


def test_stop_running_worker_kills_descendants_and_preserves_stopped(tmp_path, model_server, monkeypatch):
    monkeypatch.setenv('KAGE_BROWSER_PYTHON', str(Path(__file__).resolve().parents[1] / '.venv-computer-use/bin/python'))
    model_server.hang = True

    async def scenario():
        service = BrowserTaskService(tmp_path, lambda: config(model_server))
        try:
            first = await service.submit({'task_id': 'preferences_dev'})
            await asyncio.wait_for(asyncio.to_thread(model_server.entered.wait), 25)
            processes = tmp_path / f"run_{first['run_id']}" / 'worker-processes.json'
            assert processes.exists()
            owned = json.loads(processes.read_text())
            second = await service.submit({'task_id': 'preferences_dev'})
            await service.stop(second['run_id'])
            await service.stop(first['run_id'])
            model_server.release.set()
            assert (await terminal(service, first['run_id']))['status'] == 'stopped'
            assert service.get(second['run_id'])['status'] == 'stopped'
            assert service.get(first['run_id'])['result']['task_status'] == 'stopped'
            assert service.get(first['run_id'])['result']['model_name'] == 'scripted-http'
            assert service.artifact(first['run_id'], 'model-calls.jsonl') is not None
            assert service.artifact(first['run_id'], '../../settings.json') is None
            assert service.get(second['run_id'])['result']['task_status'] == 'stopped'
            assert model_server.calls == 1
            await asyncio.sleep(.2)
            assert service.get(first['run_id'])['status'] == 'stopped'
            for pid in owned:
                with pytest.raises(ProcessLookupError):
                    os.kill(pid, 0)
            model_server.hang = False
            third = await service.submit({'task_id': 'preferences_dev'})
            assert (await terminal(service, third['run_id']))['status'] == 'completed'
        finally:
            await service.close()

    asyncio.run(scenario())


def test_unchecked_task_rejects_teacher_and_invalid_payload(tmp_path, model_server):
    async def scenario():
        service = BrowserTaskService(tmp_path, lambda: config(model_server))
        try:
            with pytest.raises(ValueError, match='independent check'):
                await service.submit({'task_id': 'preferences_unchecked', 'executor': 'local_teacher'})
            with pytest.raises(ValueError):
                await service.submit({'task_id': 'preferences_dev', 'instruction': 'change goal'})
            with pytest.raises(ValueError):
                await service.submit({'task_id': 'preferences_dev', 'max_loop_steps': True})
            assert model_server.calls == 0
        finally:
            await service.close()
    asyncio.run(scenario())


def test_catalog_and_cloud_validation_do_not_expose_key(tmp_path, model_server):
    settings = config(model_server)
    settings['model']['cloud_api'] = {'provider_type': 'openai', 'base_url': 'http://127.0.0.1:9999/v1',
                                      'api_key': 'TOP-SECRET-KEY', 'model_name': 'remote-model'}

    async def scenario():
        service = BrowserTaskService(tmp_path, lambda: settings)
        try:
            catalog = service.catalog()
            assert 'TOP-SECRET-KEY' not in json.dumps(catalog)
            assert next(task for task in catalog['tasks'] if task['task_id'] == 'preferences_unchecked')['check_available'] is False
            assert next(item for item in catalog['executors'] if item['id'] == 'cloud')['configured'] is False
            with pytest.raises(ValueError, match='remote HTTPS'):
                await service.submit({'task_id': 'preferences_dev', 'executor': 'cloud'})
            assert model_server.calls == 0
        finally:
            await service.close()
    asyncio.run(scenario())


def test_cloud_wire_budget_rejects_before_request_and_redacts_response(tmp_path):
    from core.computer_use.task_worker import RecordedProvider
    from core.model_provider import OpenAICompatibleProvider, ModelResponse

    class NoNetwork(OpenAICompatibleProvider):
        def __init__(self):
            super().__init__(api_key='TOP-SECRET-KEY', model_name='scripted', base_url='https://example.test/v1')
            self.calls = 0

        def generate(self, **kwargs):
            self.calls += 1
            return ModelResponse(text='TOP-SECRET-KEY', raw_output='TOP-SECRET-KEY',
                                 usage={'input_tokens': 1, 'output_tokens': 1})

    model = NoNetwork()
    trace = tmp_path / 'calls.jsonl'
    recorder = RecordedProvider(model, trace, ['TOP-SECRET-KEY'], remote=True)
    with pytest.raises(RuntimeError, match='input byte cap'):
        recorder.generate(messages=[{'role': 'user', 'content': 'x' * 13000}])
    assert model.calls == 0
    recorder.generate(messages=[{'role': 'user', 'content': 'short'}])
    assert model.calls == 1
    assert 'TOP-SECRET-KEY' not in trace.read_text()
    assert '1024' in trace.read_text()


def test_cloud_rejects_all_loopback_addresses_without_network(model_server):
    from core.computer_use.task_worker import _model_config
    settings = config(model_server)
    settings['model']['cloud_api'] = {'provider_type': 'openai', 'base_url': 'https://127.0.0.2/v1',
                                      'api_key': 'TOP-SECRET-KEY'}
    with pytest.raises(ValueError, match='remote HTTPS'):
        _model_config(settings, 'cloud')
