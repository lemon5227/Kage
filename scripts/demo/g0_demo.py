"""D8 live demo: the student fails a Calculator task, the teacher writes one lesson, the student solves a task
it has never seen by first planning how the lesson applies. Real macOS Calculator through the Accessibility API,
the frozen student on one local llama-server (stopped at the end), one real teacher call through the ledger.

  python scripts/demo/g0_demo.py [--attempts 3]

Output: ~/.kage/g0/demo-<time>/ (results, traces, the lesson). Nothing outside Calculator is touched; the
user's Calculator mode is restored after every task.
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts' / 'experiments'))
import desktop_run as d  # noqa: E402

PORT = 8091
d.TEACH_THINKING = True     # the teacher reasons first: without it, 2 of 3 demo lessons assumed parenthesis keys


def say(text):
    print(f'\n=== {text}', flush=True)


def attempt(model, task, run_dir, lessons=None):
    environment = d.Calculator(task, run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        tools = d.Tools(environment.setup(), task)
        with (run_dir / 'trace.jsonl').open('w', encoding='utf-8') as trace:
            agent = d.run_agent(model, tools, task, trace, max_tokens=600, lessons=lessons)
        check = environment.check(tools.final)
    finally:
        environment.cleanup()
    steps = [json.loads(line) for line in (run_dir / 'trace.jsonl').read_text().splitlines()]
    plan = next((s['text'] for s in steps if 'text' in s and s['text']), '')
    keys = [s['arguments'].get('ref') for s in steps if s.get('tool') == 'press']
    return {'task_id': task['task_id'], 'run': 1, 'family': 'calculator', 'agent': agent, 'check': check,
            'plan': plan, 'keys': keys}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--attempts', type=int, default=3, help='tries to show the initial failure (the student is stochastic)')
    args = p.parse_args()
    tasks = {t['task_id']: t for t in json.loads(d.MANIFEST.read_text())['tasks']}
    out = d.WORK / f"demo-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True)
    from local_service import LocalService
    from core.model_provider import OpenAICompatibleProvider
    model = OpenAICompatibleProvider(api_key='local', model_name='agents-a1-4b',
                                     base_url=f'http://127.0.0.1:{PORT}/v1', timeout_sec=180)
    with LocalService(PORT, out):
        say('第 1 步：学生（本机 4B 模型）第一次做 (15 + 27) × 3，没有任何指导')
        failed = None
        for index in range(1, args.attempts + 1):
            record = attempt(model, tasks['calc_chain'], out / f'calc_chain-r{index}')
            print(f"  按键：{' '.join(record['keys'])}")
            print(f"  计算器显示 {record['check']['display']}（上个表达式 {record['check']['previous_expression']}）"
                  f" → {'做对' if record['check']['passed'] else '做错'}")
            if not record['check']['passed']:
                failed = record
                break
            print('  这次碰巧做对了（学生每次不一样），再来一次。')
        if failed is None:
            say('学生连续做对，用基线里老师已写好的规则继续演示')
            lessons = json.loads((ROOT / 'evidence' / 'reports' / 'g0' / 'a0-baseline-v1' / 'lessons.json').read_text())
        else:
            say('第 2 步：老师（DeepSeek，经 $4 账本）看失败记录，写一条通用规则（不含本题数字）')
            # teach() reads <task>-r<run>/trace.jsonl; the failing attempt is the last one written.
            last = sorted(out.glob('calc_chain-r*'))[-1]
            failed['run'] = int(last.name.rsplit('-r', 1)[1])
            (out / 'results.jsonl').write_text(json.dumps(failed, ensure_ascii=False) + '\n')
            d.teach(out, tasks)
            lessons = json.loads((out / 'lessons.json').read_text())
        print('  规则：' + ' / '.join(lessons.get('calculator', [])))
        say('第 3 步：一道学生没见过的新题 (9 + 6) × 4，带着规则，先写计划再动手')
        d.LESSON_MODE = 'plan'
        record = attempt(model, tasks['calc_chain2'], out / 'calc_chain2-r1', lessons=lessons)
        print('  学生的计划：' + ' '.join(record['plan'].split())[:400])
        print(f"  按键：{' '.join(record['keys'])}")
        print(f"  计算器显示 {record['check']['display']}（上个表达式 {record['check']['previous_expression']}）"
              f" → {'做对' if record['check']['passed'] else '做错'}")
        (out / 'demo.json').write_text(json.dumps({'initial_failure': failed, 'lessons': lessons, 'new_task': record},
                                                  ensure_ascii=False, indent=1))
    say(f'演示结束，模型服务已关闭。记录：{out}')


if __name__ == '__main__':
    main()
