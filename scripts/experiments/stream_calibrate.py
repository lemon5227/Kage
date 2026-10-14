"""Difficulty calibration for Kage-Stream families: raw student (A0), no cloud calls.

  python scripts/experiments/stream_calibrate.py --root artifacts/stream-calibration [--per-family 10] \
      [--families a,b,...] [--no-manage-server]

Seeds 5000+i come from the calibration split only, so calibrated instances never enter
the frozen stream or eval manifests. Resumable: (family, seed) already in results.jsonl
is skipped. Capability families should land in [0.10, 0.50] before W1-9 freezes stream-v1.
"""
import argparse
import json
from pathlib import Path
import sys
import time
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.evolution.stream_tasks import FAMILIES, NEGATIVE_FAMILIES, make_task, split_of

BAND = (0.10, 0.50)
CALIBRATION_BASE = 5000


def calibration_tasks(families: list[str], per_family: int) -> list[dict]:
    tasks = []
    for family in families:
        for i in range(per_family):
            seed = CALIBRATION_BASE + i
            if split_of(seed) != 'calibration':
                raise ValueError(f'seed {seed} is outside the calibration split')
            tasks.append(make_task(family, seed) | {'seed': seed})
    return tasks


def calibrate(root: Path, tasks: list[dict], run_one: Callable[[dict], tuple[float, str]]) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    results = root / 'results.jsonl'
    done = set()
    if results.exists():
        done = {(r['family'], r['seed']) for r in map(json.loads, results.read_text().splitlines()) if r}
    for task in tasks:
        if (task['family'], task['seed']) in done:
            continue
        start = time.monotonic()
        score, status = run_one(task)
        row = {'family': task['family'], 'seed': task['seed'], 'score': score, 'status': status,
               'seconds': round(time.monotonic() - start, 1)}
        with results.open('a') as out:
            out.write(json.dumps(row) + '\n')
        print(json.dumps(row), flush=True)
    rows = [json.loads(line) for line in results.read_text().splitlines() if line.strip()]
    return summarize(rows, root)


def summarize(rows: list[dict], root: Path | None = None) -> dict:
    summary = {}
    for family in sorted({r['family'] for r in rows}):
        fam = [r for r in rows if r['family'] == family]
        passed = sum(r['score'] >= 1.0 for r in fam)
        rate = passed / len(fam)
        entry = {'passed': passed, 'total': len(fam), 'rate': round(rate, 4),
                 'negative': family in NEGATIVE_FAMILIES}
        if not entry['negative']:
            entry['in_band'] = BAND[0] <= rate <= BAND[1]
        summary[family] = entry
    if root is not None:
        (root / 'summary.json').write_text(json.dumps(summary, indent=2))
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--per-family', type=int, default=10)
    p.add_argument('--families', default=','.join(FAMILIES))
    p.add_argument('--port', type=int, default=18082)
    p.add_argument('--no-manage-server', action='store_true')
    args = p.parse_args()
    families = [f for f in args.families.split(',') if f]
    unknown = set(families) - set(FAMILIES)
    if unknown:
        p.error(f'unknown families: {sorted(unknown)}')
    tasks = calibration_tasks(families, args.per_family)
    args.root.mkdir(parents=True, exist_ok=True)

    import contextlib
    if args.no_manage_server:
        service = contextlib.nullcontext()
    else:
        from local_service import LocalService
        service = LocalService(args.port, args.root)
    with service:
        run_one = live_runner(args.root, args.port)
        print(json.dumps(calibrate(args.root, tasks, run_one), indent=2))


def live_runner(root: Path, port: int) -> Callable[[dict], tuple[float, str]]:
    """Same student wiring as stream_run.py A0: empty skill library, local model only."""
    from core.evolution.budget import BudgetConfig, BudgetTracker
    from core.evolution.contracts import Candidate
    from core.evolution.journal import Journal
    from core.evolution.mutator import bundle_digest
    from core.evolution.sandbox import DockerSkillRunner
    from core.evolution.stream import chain_runner
    from stream_run import STUDENT_OUTPUT_TOKENS
    from task_suite import RecordedLocalProvider
    journal = Journal(root / 'journal.sqlite')
    budget = BudgetTracker(BudgetConfig(max_api_calls=100_000, max_input_tokens_total=10**9,
        max_output_tokens_total=10**8, input_cost_per_million=0, output_cost_per_million=0), root / 'local-budget.sqlite')
    boot = root / 'bootstrap'
    boot.mkdir(exist_ok=True)
    (boot / 'manifest.json').write_text('{"version":1,"skills":[]}')
    bootstrap = Candidate('no-skills', (), 'skill', str(boot.resolve()), bundle_digest(boot))
    (root / 'model-traces').mkdir(exist_ok=True)

    def student_model(run_id):
        return RecordedLocalProvider(root / 'model-traces' / f'{run_id}.jsonl', api_key='local',
            model_name='agents-a1-4b', base_url=f'http://127.0.0.1:{port}/v1', timeout_sec=120)
    run = chain_runner(journal, budget, root / 'workspaces', student_model, skill_runner=DockerSkillRunner(timeout_s=10),
                       tool_max_tokens=STUDENT_OUTPUT_TOKENS)

    def run_one(task):
        result = run(bootstrap, {k: v for k, v in task.items() if k != 'seed'}, f"cal-{task['task_id']}")
        return result.score, result.status
    return run_one


if __name__ == '__main__':
    main()
