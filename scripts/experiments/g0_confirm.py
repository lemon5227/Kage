"""G0 confirmation (pre-registered in docs/plans/g0-confirm-prereg.md): frozen new tasks, arms interleaved in one session.

  python g0_confirm.py --out ~/.kage/g0/confirm [--model-name agents-a1-4b]

X1 interface: the six new TextEdit tasks under v2 (fill) and v4 (line tools), no lessons.
X2 adoption: the twelve new Calculator tasks under v4 in five lesson conditions: none, system, plan-only,
adjacent (lessons next to the task, no planning request) and plan (lessons next to the task + plan).
For every (run, task) all arms of that experiment run back to back in a rotated order, so time-of-day, app state
and server drift spread over the arms. One llama-server for the whole session (owned, stopped at the end).
A cell whose run raised (setup, app or server failure: not a student failure) is logged in infra-errors.jsonl
and rerun, at most twice; the student's own failures are never rerun. The script resumes where it stopped.
"""
from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desktop_run as dr                                                   # noqa: E402
from core.computer_use.desktop_agent import DesktopTools, run_agent      # noqa: E402

MANIFEST = dr.ROOT / 'eval' / 'desktop_v2_confirm' / 'tasks.json'
LESSONS = dr.ROOT / 'evidence' / 'reports' / 'g0' / 'a0-baseline-v1' / 'lessons.json'
EXPERIMENTS = {
    'x1': ('textedit', [('te-v2', 'v2', None), ('te-v4', 'v4', None)]),
    'x2': ('calculator', [('calc-none', 'v4', None), ('calc-system', 'v4', 'system'), ('calc-planonly', 'v4', 'plan-only'),
                          ('calc-adjacent', 'v4', 'adjacent'), ('calc-plan', 'v4', 'plan')]),
}
RETRIES = 2


def done_cells(out):
    cells = set()
    for path in out.glob('*/results.jsonl'):
        for line in path.read_text().splitlines():
            record = json.loads(line)
            cells.add((path.parent.name, record['task_id'], record['run']))
    return cells


def run_cell(model, task, arm_dir, run, interface, mode, lessons):
    run_dir = arm_dir / f"{task['task_id']}-r{run}"
    run_dir.mkdir(parents=True, exist_ok=True)
    environment = dr.ENVIRONMENTS[task['family']](task, run_dir)
    start, record = time.monotonic(), {'task_id': task['task_id'], 'family': task['family'], 'kind': task.get('kind'),
                                       'run': run, 'arm': arm_dir.name, 'interface': interface, 'lesson_mode': mode,
                                       'started': time.strftime('%Y-%m-%dT%H:%M:%S')}
    try:
        ax = environment.setup()
        tools = DesktopTools(ax, task, interface=interface)
        with (run_dir / 'trace.jsonl').open('w', encoding='utf-8') as trace:
            record['agent'] = run_agent(model, tools, task, trace, lessons=lessons if mode else None, mode=mode or 'none')
        record['check'] = environment.check(tools.final)
    except Exception as exc:
        record['error'] = f'{type(exc).__name__}: {exc}'
    try:
        record['cleanup'] = environment.cleanup()
    except Exception as exc:
        record['cleanup'] = {'error': f'{type(exc).__name__}: {exc}'}
    record['seconds'] = round(time.monotonic() - start, 1)
    return record


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--runs', type=int, default=3)
    p.add_argument('--experiments', default='x1,x2')
    p.add_argument('--model-name', default='agents-a1-4b')
    p.add_argument('--port', type=int, default=8091)
    args = p.parse_args(argv)
    manifest = json.loads(MANIFEST.read_text())
    lessons = json.loads(LESSONS.read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    dr.write_json(args.out / 'config.json', {'manifest': manifest['version'], 'manifest_sha256': dr_hash(MANIFEST),
                                             'lessons_sha256': dr_hash(LESSONS), 'lessons': lessons, 'runs': args.runs,
                                             'experiments': {k: EXPERIMENTS[k] for k in args.experiments.split(',')}})
    from local_service import LocalService
    from core.model_provider import OpenAICompatibleProvider
    model = OpenAICompatibleProvider(api_key='local', model_name=args.model_name,
                                     base_url=f'http://127.0.0.1:{args.port}/v1', timeout_sec=180)
    finished = done_cells(args.out)
    with LocalService(args.port, args.out):
        for run in range(1, args.runs + 1):
            for name in args.experiments.split(','):
                family, arms = EXPERIMENTS[name]
                tasks = [t for t in manifest['tasks'] if t['family'] == family]
                for index, task in enumerate(tasks):
                    shift = (run + index) % len(arms)
                    for arm, interface, mode in arms[shift:] + arms[:shift]:
                        if (arm, task['task_id'], run) in finished:
                            continue
                        arm_dir = args.out / arm
                        for attempt in range(RETRIES + 1):
                            dr.wait_until_unlocked()
                            record = run_cell(model, task, arm_dir, run, interface, mode, lessons)
                            if 'error' not in record:
                                break
                            with (args.out / 'infra-errors.jsonl').open('a', encoding='utf-8') as stream:
                                stream.write(json.dumps(record | {'attempt': attempt}, ensure_ascii=False) + '\n')
                        record.setdefault('check', {'passed': False})
                        with (arm_dir / 'results.jsonl').open('a', encoding='utf-8') as stream:
                            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
                        print(json.dumps({k: record.get(k) for k in ('arm', 'task_id', 'run', 'seconds', 'error')}
                                         | {'passed': record['check'].get('passed')}, ensure_ascii=False), flush=True)
    print(args.out)


def dr_hash(path):
    from local_service import file_hash
    return file_hash(path)


if __name__ == '__main__':
    main()
