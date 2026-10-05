"""Model-free teaching capture and workflow replay in an owned child process."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time

from core.computer_use.browser import BrowserAdapter
from core.computer_use.demonstration import BrowserDemonstrationRecorder, demonstration_tasks
from core.computer_use.demonstration_compiler import compile_demonstration
from core.computer_use.episodes import generation_feedback
from core.computer_use.experiment import CheckpointExecutor
from core.computer_use.skills import BrowserPrimitiveQuota, BrowserSkillCatalog
from core.computer_use.task_environment import atomic_json, browser_task_server
from core.evolution.archive import ExperienceArchive
from core.evolution.contracts import RunResult
from core.evolution.journal import Journal
from core.evolution.runner import Evaluator
from core.tool_registry import ToolRegistry


def artifacts(workspace, run_id):
    return [{'name': str(path.relative_to(workspace)),
             'url': f'/api/browser/demonstrations/{run_id}/artifacts/{path.relative_to(workspace)}',
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(workspace.rglob('*')) if path.is_file() and not path.name.endswith('.tmp')
            and path.name not in {'result.json', 'status.json', 'finish.requested', 'stop.requested'} and not path.name.endswith(('-shm', '-wal'))]


async def run(request):
    run_id = request['run_id']
    workspace = Path(request['run_root']) / ('run_' + run_id)
    workspace.mkdir(parents=True, exist_ok=True)
    task = demonstration_tasks()[request['task_id']]
    operation, source = request['operation'], request['source_kind']
    stop = workspace / 'stop.requested'
    state = {'status': 'starting', 'ready': False, 'event_count': 0}
    result = {'task_status': 'failed', 'check_available': True, 'check_passed': None,
              'usage': {'api_calls': 0}, 'usage_status': 'no_requests', 'unpromoted': True,
              'executor': request['executor'], 'source_kind': source, 'operation': operation,
              'cost': {'amount_usd': 0, 'source': 'local_api_only'}, 'event_count': 0,
              'error': None, 'stop_reason': None}
    recorder = None
    atomic_json(workspace / 'status.json', state)
    try:
        from playwright.async_api import async_playwright
        if stop.exists():
            return
        with browser_task_server(task['fixture'], workspace) as (url, backend):
            atomic_json(workspace / 'backend.json', {'record': backend['saved'], 'posts': backend['posts']})
            async with async_playwright() as p:
                args = []
                endpoint = None
                if source == 'automation' and operation == 'demonstration':
                    with socket.socket() as sock:
                        sock.bind(('127.0.0.1', 0))
                        port = sock.getsockname()[1]
                    args = [f'--remote-debugging-port={port}', '--remote-debugging-address=127.0.0.1']
                    endpoint = f'http://127.0.0.1:{port}'
                browser = await p.chromium.launch(headless=(source == 'automation' and
                    os.environ.get('KAGE_BROWSER_DEMONSTRATION_HEADLESS') == '1'), args=args)
                try:
                    page = await browser.new_page()
                    await page.goto(url)
                    adapter, quota, registry = BrowserAdapter(page, trace_path=workspace / 'browser.jsonl'), BrowserPrimitiveQuota(16), ToolRegistry()
                    adapter.register_tools(registry, quota=quota)
                    executor = CheckpointExecutor(registry, workspace, page, url, settle_saves=True)
                    if operation == 'demonstration':
                        recorder = BrowserDemonstrationRecorder(page, workspace, source_kind=source)
                        await recorder.start()
                        deadline = time.monotonic() + 900
                        state.update(status='recording', ready=True, automation_cdp_endpoint=endpoint)
                        atomic_json(workspace / 'status.json', state)
                        while not (workspace / 'finish.requested').exists():
                            if stop.exists():
                                await recorder.stop()
                                return
                            if page.is_closed() or not browser.is_connected():
                                raise RuntimeError('CapturePageClosed: teaching window was closed')
                            if recorder.capture_error:
                                raise RuntimeError('CaptureFlushFailed: ' + recorder.capture_error)
                            if recorder.event_count > 64:
                                raise RuntimeError('CaptureLimitExceeded: more than 64 actions')
                            if time.monotonic() >= deadline:
                                raise RuntimeError('CaptureLimitExceeded: 900-second deadline')
                            state['event_count'] = recorder.event_count
                            atomic_json(workspace / 'status.json', state)
                            await asyncio.sleep(.1)
                        summary = await recorder.stop()
                        result['event_count'] = summary['event_count']
                        if not summary['success']:
                            raise RuntimeError(summary['error'] + ': ' + str(summary.get('capture_error') or 'capture incomplete'))
                    else:
                        atomic_json(workspace / 'initial-observation.json', await adapter.observe())
                        executor.actor = 'workflow_engine'
                        candidate = request['candidate']
                        catalog = BrowserSkillCatalog.from_bundle(candidate['bundle_path'])
                        catalog.register_tools(registry, adapter, executor, workspace, quota)
                        executed = await executor.execute('skill_call', {'skill_id': candidate['skill_id'],
                            'digest': candidate['digest'], 'arguments': request['arguments']})
                        result.update(workflow_digest=candidate['digest'], primitive_calls=quota.used,
                                      source_run_id=request['source_run_id'])
                        atomic_json(workspace / 'workflow-result.json', asdict(executed))
                        atomic_json(workspace / 'final-observation.json', await adapter.observe())
                        if not executed.success:
                            raise RuntimeError('WorkflowExecutionFailed: ' + str(executed.error_message or executed.result))
                    state.update(status='finalizing', ready=False, event_count=result['event_count'], automation_cdp_endpoint=None)
                    atomic_json(workspace / 'status.json', state)
                    if stop.exists():
                        return
                    await executor.checkpoint()
                    score = Evaluator.score(task, workspace)
                    result['check_passed'] = score >= 1
                    scored = RunResult(run_id, 'passed' if score >= 1 else 'failed', score,
                        str(workspace / 'trace.jsonl'), final_state_path=str(workspace),
                        usage={'api_calls': 0}, metadata={'environment_kind': 'resettable-local-http-browser',
                        **({'demonstration_source': source} if operation == 'demonstration' else {'executor': 'workflow_engine'})})
                    (workspace / 'trace.jsonl').touch(exist_ok=True)
                    atomic_json(workspace / 'run-result.json', asdict(scored))
                    archive = ExperienceArchive(Journal(Path(request['run_root']) / (run_id + '-journal.sqlite')))
                    episode_id = archive.record(task, scored)
                    episode = next(ep for ep in archive.list_episodes() if ep['episode_id'] == episode_id)
                    atomic_json(workspace / 'episode.json', episode)
                    if operation == 'demonstration' and score >= 1:
                        if stop.exists():
                            return
                        try:
                            atomic_json(workspace / 'feedback.json', generation_feedback(episode))
                            candidate = compile_demonstration(episode, workspace / 'candidate', skill_id='form-' + task['family'])
                            atomic_json(workspace / 'parameters.json', {'parameters': candidate['parameters'], 'arguments': candidate['arguments']})
                            atomic_json(workspace / 'candidate.json', candidate)
                            result.update(task_status='verified', candidate=candidate)
                        except Exception as exc:
                            result.update(task_status='failed', candidate_error=f'{type(exc).__name__}: {exc}',
                                          error=f'CandidateCompilationFailed: {exc}', stop_reason='candidate_failed')
                    elif operation == 'demonstration':
                        result.update(task_status='incomplete', error='Saved form did not pass the independent check', stop_reason='check_failed')
                    else:
                        result.update(task_status='completed' if score >= 1 else 'failed',
                                      error=None if score >= 1 else 'Replay did not pass the independent check',
                                      stop_reason=None if score >= 1 else 'check_failed')
                finally:
                    await browser.close()
    except Exception as exc:
        if recorder is not None and recorder.started:
            summary = await recorder.stop()
            result['event_count'] = summary['event_count']
        result.update(task_status='incomplete' if recorder else 'failed', error=f'{type(exc).__name__}: {exc}',
                      stop_reason='capture_failed' if recorder else 'browser_unavailable')
    if not stop.exists():
        result['artifacts'] = artifacts(workspace, run_id)
        atomic_json(workspace / 'result.json', result)
    return result


def main():
    request = json.loads(sys.stdin.buffer.read())
    asyncio.run(run(request))


if __name__ == '__main__':
    main()
