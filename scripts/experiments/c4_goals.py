"""C4 round 2: per-item goals for the browser pre-save checker, extracted by Clef from each task's instruction.

For every checkbox the page will show (the fixture's toggle labels), Clef answers a choice question
"after the task, should <label> be on / off / unchanged?" with the instruction as its state. Decision-bench
(10-21): Clef extracts per item at 1.00 but judges whole states at 0.64, so the model only extracts and a program
compares (core.computer_use.experiment.PreSaveChecker). The instructions of the frozen eval set are fixed, so the
extraction is done once here and cached in the repo (Kaggle has no Cloudflare credential); a live agent would make
the same call per new request. Calls are charged to the global teacher ledger at Clef's list price.

  python c4_goals.py [--manifest eval/stream_web_v1/eval.json] [--out eval/stream_web_v1/goals-clef.json]
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'decision_bench'))
from run_clef import USD_PER_M_INPUT, answer_of, call  # noqa: E402
from core.evolution.teacher_budget import charge_external, global_teacher_budget, remaining_usd  # noqa: E402


CRITERIA = {'on': 'the request asks to enable / turn on / check this item',
            'off': 'the request asks to disable / turn off / uncheck this item',
            'unchanged': 'the request does not ask to change this item'}


def toggles(fixture):
    if fixture.get('kind') == 'preferences':
        return [field['label'] for field in fixture['fields']]
    if fixture.get('kind') == 'catalog' and fixture.get('category_label'):
        return [fixture['category_label']]
    return []


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--manifest', type=Path, default=ROOT / 'eval' / 'stream_web_v1' / 'eval.json')
    p.add_argument('--out', type=Path, default=ROOT / 'eval' / 'stream_web_v1' / 'goals-clef.json')
    p.add_argument('--model', default='clef')
    args = p.parse_args(argv)
    budget = global_teacher_budget()
    start = remaining_usd(budget)
    goals, tokens = {}, 0
    for task in json.loads(args.manifest.read_text())['tasks']:
        labels = toggles(task['fixture'])
        if not labels:
            continue
        questions = {f'q{i}': {'type': 'choice', 'criteria': CRITERIA,
                               'question': f'After the requested task is done, what should the checkbox "{label}" be?'}
                     for i, label in enumerate(labels)}
        response = call(args.model, f'Request given to an assistant: {task["instruction"]}', questions)
        result = response.get('result', response)
        used = (result.get('usage') or {}).get('input_tokens') or (result.get('usage') or {}).get('prompt_tokens') or 0
        tokens += used
        charge_external(budget, used * USD_PER_M_INPUT[args.model] / 1e6, run_id='c4-goals', call_type='decision')
        goals[task['task_id']] = {label: answer_of(result['answers'][f'q{i}'], 'choice')[0] for i, label in enumerate(labels)}
        print(task['task_id'], goals[task['task_id']], flush=True)
    args.out.write_text(json.dumps({'model': args.model, 'source': str(args.manifest.relative_to(ROOT)),
                                    'goals': goals}, ensure_ascii=False, indent=1))
    print(json.dumps({'tasks': len(goals), 'input_tokens': tokens, 'spent_usd': round(start - remaining_usd(budget), 5)}))


if __name__ == '__main__':
    main()
