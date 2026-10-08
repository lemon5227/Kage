"""Controlled real TextEdit pilot. No model score and no direct execution writes.

Run from repo: python -m scripts.experiments.native_ax_pilot --output DIR
Only a dedicated copy of the tracked fixture is opened; AX performs edits/save/close.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from core.computer_use.native_ax import NativeAXAdapter

EXPECTED = 'Kage dedicated native AX pilot fixture.\nStatus: semantic AX edit saved and independently verified.\n'


class CloseCompletionProbeError(RuntimeError):
    def __init__(self, result):
        self.result = result
        super().__init__(f'close completion probe: {result}')


async def wait_window_disappeared(adapter, document_name, attempts=30, interval=0.1):
    for _ in range(attempts):
        identified = await adapter.windows('com.apple.TextEdit')
        if not identified.get('success'):
            raise CloseCompletionProbeError(identified)
        if not any(w['title'] == document_name for w in identified['windows']):
            return True
        await asyncio.sleep(interval)
    return False


async def pilot(output):
    output.mkdir(parents=True, exist_ok=True)
    document = output / ('kage-native-ax-' + output.name + '.txt')
    if document.exists():
        raise ValueError('use a fresh output directory; pilot never overwrites an existing document')
    fixture = Path(__file__).parent/'fixtures'/'kage-native-ax-pilot.txt'
    shutil.copyfile(fixture, document)  # Setup only; execution writes are through AX.
    adapter = NativeAXAdapter(trace_path=output/'trace.jsonl')
    start = time.monotonic()
    report = {'model_driven': False, 'document': str(document.resolve()), 'stages': []}
    async def stage(name, result):
        report['stages'].append({'stage': name, 'elapsed_ms': round((time.monotonic()-start)*1000,3), 'result': result})
        if not result.get('success'):
            raise RuntimeError(f'{name}: {result.get("error")}: {result.get("message")}')
        return result.get('observation')
    async def observe_document():
        for _ in range(30):
            identified = await adapter.windows('com.apple.TextEdit')
            if not identified.get('success'):
                await stage('identify', identified)
            matches = [w for w in identified['windows'] if w['title'] == document.name]
            if len(matches) == 1:
                return await stage('observe', await adapter.observe(matches[0]['window_ref']))
            await asyncio.sleep(0.1)
        raise RuntimeError('dedicated window could not be uniquely identified')
    async def act(obs, target, operation, value=None):
        return await stage(operation, await adapter.act(obs['observation_id'], operation, target['target_ref'], value))
    def unique(obs, predicate):
        matches = [target for target in obs['targets'] if predicate(target)]
        if len(matches) != 1:
            raise RuntimeError('semantic target must match exactly one observed control')
        return matches[0]
    try:
        subprocess.run(['open', '-a', 'TextEdit', str(document.resolve())], check=True, timeout=10)
        await asyncio.sleep(0.3)  # Wait for native open/close menu teardown before querying AX.
        obs = await observe_document()
        target = unique(obs, lambda t: t['role']=='AXTextArea' and 'before semantic edit' in t['value'])
        obs = await act(obs, target, 'fill', EXPECTED)
        # Opening the document menu validates enabled states in TextEdit.
        menu = unique(obs, lambda t: t['role']=='AXMenuBarItem')
        obs = await act(obs, menu, 'press')
        save = unique(obs, lambda t: t.get('command', '').lower()=='s')
        obs = await act(obs, save, 'press')
        for _ in range(30):
            if document.read_text() == EXPECTED: break
            await asyncio.sleep(0.1)
        report['saved_file_matches'] = document.read_text() == EXPECTED
        await asyncio.sleep(0.3)  # Allow asynchronous Save menu teardown.
        obs = await observe_document()
        menu = unique(obs, lambda t: t['role']=='AXMenuBarItem')
        obs = await act(obs, menu, 'press')
        close = unique(obs, lambda t: t.get('command', '').lower()=='w')
        # A successful close has no remaining window observation, but is applied.
        closed = await adapter.act(obs['observation_id'], 'press', close['target_ref'])
        report['stages'].append({'stage': 'close', 'result': closed})
        if closed.get('action_applied') is not True: raise RuntimeError('close was not applied')
        report['window_disappeared_after_close'] = await wait_window_disappeared(adapter, document.name)
        if not report['window_disappeared_after_close']:
            raise RuntimeError('closed window did not disappear before reopen')
        subprocess.run(['open', '-a', 'TextEdit', str(document.resolve())], check=True, timeout=10)
        await asyncio.sleep(0.3)  # Wait for native open/close menu teardown before querying AX.
        obs = await observe_document()
        reread = unique(obs, lambda t: t['role']=='AXTextArea')
        report['reopened_ax_matches'] = reread['value'] == EXPECTED
        report['independent_file_matches'] = document.read_text() == EXPECTED
        # Cleanup only our dedicated reopened document through its AX Close control.
        await asyncio.sleep(0.3)
        obs = await observe_document()
        menu = unique(obs, lambda t: t['role']=='AXMenuBarItem')
        obs = await act(obs, menu, 'press')
        close = unique(obs, lambda t: t.get('command', '').lower()=='w')
        cleaned = await adapter.act(obs['observation_id'], 'press', close['target_ref'])
        report['stages'].append({'stage': 'cleanup_close', 'result': cleaned})
        report['cleanup_close_applied'] = cleaned.get('action_applied') is True
        report['cleanup_window_disappeared'] = await wait_window_disappeared(adapter, document.name)
        report['file_sha256'] = hashlib.sha256(document.read_bytes()).hexdigest()
        report['status'] = 'passed' if all(report[k] for k in ['saved_file_matches','window_disappeared_after_close','reopened_ax_matches','independent_file_matches','cleanup_close_applied','cleanup_window_disappeared']) else 'failed'
    except Exception as exc:
        if isinstance(exc, CloseCompletionProbeError):
            report['stages'].append({'stage': 'close_completion_probe', 'result': exc.result})
        report['status'] = 'blocked' if any(s['result'].get('error') in {'AXPermissionDenied','NotAvailable'} for s in report['stages']) else 'failed'
        report['error'] = f'{type(exc).__name__}: {exc}'
    report['elapsed_ms'] = round((time.monotonic()-start)*1000,3)
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='stages'}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(pilot(args.output))
    raise SystemExit(0 if result['status']=='passed' else 1)
