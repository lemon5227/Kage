"""G0: run the desktop-v1 tasks (eval/desktop_v1) on this Mac through the Accessibility API.

  python desktop_run.py --arm oracle                      # scripted solutions: checks setup/checkers/tools, no model
  python desktop_run.py --arm a0 --runs 3 [--tasks calc_add,te_fix] [--split train]   # the frozen student (local llama-server)
  python desktop_run.py --arm teach --from <a0 results dir>            # teacher writes one lesson per failed task -> lessons.json
  python desktop_run.py --arm a0 --split test --lessons <lessons.json>  # the student with the lessons, on unseen variants

Each run: trusted setup (open the app/page, reset Calculator, write the dedicated file) -> the agent acts only
through the task's tools -> a trusted checker reads the app or the file itself -> cleanup restores what setup
changed (Calculator's conversion mode, the test document window). Results: <out>/results.jsonl, one directory
per run with the full model/tool trace. Local model runs are limited to G0 by the user (one server, stopped
when the run ends; see memory no-local-model-runs).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.computer_use.desktop import DesktopAX, DesktopError, render   # noqa: E402
from core.computer_use.desktop_agent import (FAMILY_TOOLS, SYSTEM, TEACH_PROMPT, TOOLS, DesktopTools,  # noqa: E402,F401
                                            tool_schemas,
                                            run_agent as agent_loop)

MANIFEST = ROOT / 'eval' / 'desktop_v1' / 'tasks.json'
WORK = Path.home() / '.kage' / 'g0'
ON = {'on', 'yes', 'true', 'enabled', '开', '开启', '打开', '是', '已开启'}
OFF = {'off', 'no', 'false', 'disabled', '关', '关闭', '否', '未开启'}


def wait_until_unlocked(poll_s: float = 30) -> None:
    """Accessibility actions fail while the screen is locked; every run then errors in setup (10-26: a
    replication left unattended at 3 am voided 58 of 60 runs). Wait instead of recording invalid runs."""
    import Quartz
    announced = False
    while (Quartz.CGSessionCopyCurrentDictionary() or {}).get('CGSSessionScreenIsLocked'):
        if not announced:
            print(f'{time.strftime("%H:%M:%S")} screen locked: waiting', flush=True)
            announced = True
        time.sleep(poll_s)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def norm(text):
    return re.sub(r'[\s"“”\'。.,，]', '', str(text or '')).lower()


def digits(text):
    return re.sub(r'[^\d.\-]', '', str(text or '').replace(' ', '').replace(',', ''))


def wait_for(predicate, timeout=6.0, step=.2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if predicate():
                return True
        except DesktopError:
            pass
        time.sleep(step)
    return False


def ids(observation):
    return {item.get('id'): item for item in observation['items'] if item.get('ref')}


def texts(observation):
    return [item['text'] for item in observation['items'] if item['kind'] in ('text', 'heading')]


# --- environments: trusted setup / checker / cleanup ------------------------------------------------------
class Calculator:
    def __init__(self, task, run_dir):
        self.task, self.ax, self.restore_conversion = task, DesktopAX('com.apple.calculator'), False
        self.restore_history = False

    def setup(self):
        subprocess.run(['open', '-g', '-a', 'Calculator'], check=True, timeout=10)
        wait_for(lambda: self.ax.snapshot())
        if 'UnitsSwapButton' in ids(self.ax.snapshot()):            # the user's conversion mode: off for the task
            self.restore_conversion = True
            self.ax.press_menu_unchecked('显示', '转换')
            if not wait_for(lambda: 'UnitsSwapButton' not in ids(self.ax.snapshot())):
                raise RuntimeError('could not leave Calculator conversion mode')
        # The history sidebar lists earlier expressions and results (answers) and pushes the keypad out of the
        # observation; a student opened it once in the D8 demo. Close it for the task, reopen it in cleanup.
        if self.ax.menu_item('显示', '隐藏历史记录') is not None:
            self.restore_history = True
            self.ax.press_menu_unchecked('显示', '隐藏历史记录')
            wait_for(lambda: self.ax.menu_item('显示', '显示历史记录') is not None)
        # "AC" (AllClear) only exists while the display is clear; after a half-finished expression the key is
        # "C" (Clear). Agents-A1 always left the display clear; Nemotron did not (11/30 setups failed, 10-26).
        for _ in range(3):
            found = ids(self.ax.snapshot())
            if 'AllClear' in found:
                self.ax.press(found['AllClear']['ref'])
                break
            self.ax.press(found['Clear']['ref'])
        return self.ax

    def check(self, final):
        observation = self.ax.snapshot()
        shown = {t.split(':', 1)[0]: t.split(':', 1)[1].strip() for t in texts(observation) if ':' in t}
        display, previous = shown.get('编辑字段', ''), shown.get('上个表达式', '')
        computed = bool(re.search(r'[+\-−×÷*/]', previous))       # typing the answer digits is not computing it
        ok = digits(display) == self.task['expected'] and computed
        return {'passed': ok, 'display': display, 'previous_expression': previous, 'computed': computed}

    def cleanup(self):
        if self.restore_history and self.ax.menu_item('显示', '显示历史记录') is not None:
            self.ax.press_menu_unchecked('显示', '显示历史记录')
        if self.restore_conversion:
            if not wait_for(lambda: self.ax.snapshot(), timeout=1):     # Calculator was quit during the task
                subprocess.run(['open', '-g', '-a', 'Calculator'], check=True, timeout=10)
                wait_for(lambda: self.ax.snapshot())
            if 'UnitsSwapButton' in ids(self.ax.snapshot()):           # quit and relaunched in the user's mode
                return {'conversion_restored': True, 'relaunched': True}
            self.ax.press_menu_unchecked('显示', '转换')
            wait_for(lambda: 'UnitsSwapButton' in ids(self.ax.snapshot()))
        return {'conversion_restored': self.restore_conversion}


class TextEdit:
    def __init__(self, task, run_dir):
        self.task = task
        self.path = Path(run_dir) / task['document']
        self.ax = DesktopAX('com.apple.TextEdit', window_title=task['document'],
                            menus=[tuple(m) for m in task.get('menus', [])])

    def setup(self):
        self.path.write_text(self.task['initial'], encoding='utf-8')
        subprocess.run(['open', '-g', '-a', 'TextEdit', str(self.path)], check=True, timeout=10)
        if not wait_for(lambda: self.ax.snapshot(), timeout=8):
            raise RuntimeError('the dedicated document window did not appear')
        return self.ax

    def check(self, final):
        content = self.path.read_text(encoding='utf-8')
        return {'passed': content == self.task['expected'], 'disk': content}

    def cleanup(self):
        return {'window': self.ax.close_window()}


class SettingsRead:
    def __init__(self, task, run_dir):
        self.task = task
        self.ax = DesktopAX('com.apple.systempreferences', max_items=200)

    def open_pane(self, pane):
        subprocess.run(['open', '-g', f'x-apple.systempreferences:{pane}'], check=True, timeout=10)
        time.sleep(2.5)

    def setup(self):
        self.open_pane(self.task['pane'])
        if not wait_for(lambda: len(self.ax.snapshot()['items']) > 20, timeout=8):
            raise RuntimeError('System Settings did not show the page')
        return self.ax

    def truth(self):
        check = self.task['check']
        if check.get('pane') and check['pane'] != self.task['pane']:
            self.open_pane(check['pane'])
        items = self.ax.snapshot()['items']
        if 'id' in check:
            item = next(i for i in items if i.get('id') == check['id'])
            return item['state']
        start = next(n for n, i in enumerate(items) if i.get('text') == check['radio_group_after'])
        radios = [i for i in items[start + 1:start + 8] if i.get('kind') == 'radio']
        return next(i['label'] for i in radios if i.get('state') == 'on')

    def check(self, final):
        truth, answer = self.truth(), (final or {}).get('answer')
        if truth in ('on', 'off'):
            words = set(re.findall(r'[a-z]+|[一-鿿]+', str(answer or '').lower()))
            ok = bool(words & (ON if truth == 'on' else OFF)) and not words & (OFF if truth == 'on' else ON)
        else:
            ok = answer is not None and norm(answer) == norm(truth)
        return {'passed': ok, 'answer': answer, 'truth': truth}

    def cleanup(self):
        return {}


ENVIRONMENTS = {'calculator': Calculator, 'textedit': TextEdit, 'settings_read': SettingsRead}


# --- the agent side ------------------------------------------------------------------------------------
class Tools(DesktopTools):
    def __init__(self, ax, task):
        super().__init__(ax, task, interface=INTERFACE)


LESSON_MODE = 'system'
INTERFACE = 'v2'


def run_agent(model, tools, task, trace, max_tokens=400, lessons=None):
    return agent_loop(model, tools, task, trace, max_tokens=max_tokens, lessons=lessons, mode=LESSON_MODE)


def oracle(tools, task):
    """Scripted solutions through the same tools: validates setup, tools and checkers without a model."""
    family = task['family']
    if family == 'calculator':
        keys = {'+': 'Add', '×': 'Multiply', '÷': 'Divide', '-': 'Subtract'}
        names = ['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine']
        expression = re.search(r'compute (.+?)\.', task['instruction']).group(1)
        sequence = []
        for token in re.findall(r'\d+|[+×÷\-]|\)', expression):
            if token == ')':
                sequence.append('Equals')
            elif token.isdigit():
                sequence += [names[int(c)] for c in token]
            else:
                sequence.append(keys[token])
        sequence.append('Equals')
        for key in sequence:
            tools.call('press', {'ref': ids(tools.ax.snapshot())[key]['ref']})
        tools.call('done', {})
    elif family == 'textedit':
        area = next(i for i in tools.ax.snapshot()['items'] if i.get('kind') == 'textarea')
        tools.call('fill', {'ref': area['ref'], 'text': task['expected']})
        tools.call('activate', {})
        print(tools.call('menu', {'menu': '文件', 'item': '保存'}).split('\n')[0])
        tools.call('done', {})
    else:
        if task.get('press_ids'):
            target = ids(tools.ax.snapshot())['com.apple.settings.appearance']
            tools.call('press', {'ref': target['ref']})
            time.sleep(1.5)
        environment = SettingsRead(task, None)
        environment.task = {**task, 'pane': task['check'].get('pane', task['pane'])}
        tools.call('answer', {'text': environment.truth()})
    return {'stop': 'oracle', 'actions': tools.actions}


TEACHER_CONFIG = Path('~/.config/kage/teachers/deepseek.json').expanduser()
TEACH_THINKING = False      # True: the teacher reasons before writing the lesson (D8 demo: fewer lessons about absent controls)
def teach(source, tasks):
    """One lesson per failed train task (its first failing run), written by the teacher through the global ledger."""
    from core.evolution.teacher_budget import global_teacher_budget, remaining_usd
    from core.model_provider import OpenAICompatibleProvider
    cloud = json.loads(TEACHER_CONFIG.read_text())['model']['cloud_api']
    model = OpenAICompatibleProvider(api_key=cloud['api_key'], model_name=cloud['model_name'],
                                     base_url=cloud['base_url'], timeout_sec=120, thinking=TEACH_THINKING)
    budget = global_teacher_budget()
    start = remaining_usd(budget)
    records = [json.loads(line) for line in (source / 'results.jsonl').read_text().splitlines()]
    lessons, log, seen = {}, [], set()
    for record in records:
        task = tasks[record['task_id']]
        if record['check'].get('passed') or record['task_id'] in seen or task['family'] == 'settings_read':
            continue                       # settings failures were interface problems (fixed in v2), not knowledge
        if record.get('error'):
            continue                       # a setup error is not a student failure: nothing to teach from
        seen.add(record['task_id'])
        actions = []
        for line in (source / f"{record['task_id']}-r{record['run']}" / 'trace.jsonl').read_text().splitlines():
            step = json.loads(line)
            if 'tool' in step:
                status = step['result'].split('\n', 1)[0]
                actions.append(f"{step['tool']}({json.dumps(step['arguments'], ensure_ascii=False)}) -> {status}")
        found = {k: v for k, v in record['check'].items() if k != 'passed'}
        # The teacher sees the controls the app offers (the first full observation), so a lesson never relies on
        # a control that does not exist (a demo lesson once suggested parentheses; basic Calculator has none).
        trace_lines = (source / f"{record['task_id']}-r{record['run']}" / 'trace.jsonl').read_text().splitlines()
        first_observation = next((json.loads(l)['result'].split('\n', 1)[1] for l in trace_lines
                                  if 'tool' in json.loads(l) and '\n' in json.loads(l)['result']), '')
        expected = task['expected']
        message = (f"Task: {task['instruction']}\n\nThe application window (controls the assistant can use):\n"
                   f"{first_observation[:2500]}\n\nActions:\n" + '\n'.join(actions) +
                   f"\n\nChecker: expected {json.dumps(expected, ensure_ascii=False)}, found {json.dumps(found, ensure_ascii=False)}")
        reservation = budget.reserve(4000, 2000 if TEACH_THINKING else 200, call_type='g0_lesson', run_id=f"g0-{record['task_id']}")
        response = None
        try:
            response = model.generate(messages=[{'role': 'system', 'content': TEACH_PROMPT},
                                                {'role': 'user', 'content': message}], max_tokens=2000 if TEACH_THINKING else 200, temperature=0.0)
        finally:
            budget.settle(reservation, getattr(response, 'usage', None))
        lesson = (response.text or '').strip() if response and not response.error else ''
        log.append({'task_id': record['task_id'], 'family': task['family'], 'prompt': message, 'lesson': lesson})
        if lesson:
            lessons.setdefault(task['family'], []).append(lesson)
    write_json(source / 'lessons.json', lessons)
    write_json(source / 'teach-log.json', {'entries': log, 'spent_usd': round(start - remaining_usd(budget), 4),
                                           'ledger_remaining_usd': round(remaining_usd(budget), 4)})
    print(json.dumps(lessons, ensure_ascii=False, indent=1))
    print(source / 'lessons.json')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--arm', choices=['oracle', 'a0', 'teach'], default='oracle')
    p.add_argument('--split', choices=['train', 'test', 'all'], default='train')
    p.add_argument('--lessons', type=Path, default=None)
    p.add_argument('--interface', choices=['v2', 'v3', 'v4'], default='v2',
                   help='TextEdit tools: v3 adds replace_text/append_text; v4 = replace_text + line-based append/set (no fill)')
    p.add_argument('--lesson-mode', choices=['system', 'plan', 'plan-only'], default='system')
    p.add_argument('--from', dest='source', type=Path, default=None, help='teach: the a0 results directory')
    p.add_argument('--runs', type=int, default=1)
    p.add_argument('--tasks', default='')
    p.add_argument('--port', type=int, default=8091)
    p.add_argument('--out', type=Path, default=None)
    args = p.parse_args(argv)
    manifest = json.loads(MANIFEST.read_text())
    tasks = [t for t in manifest['tasks'] if (not args.tasks or t['task_id'] in args.tasks.split(','))
             and (args.tasks or args.split == 'all' or t.get('split', 'train') == args.split)]
    if args.arm == 'teach':
        return teach(args.source, {t['task_id']: t for t in manifest['tasks']})
    lessons = json.loads(args.lessons.read_text()) if args.lessons else None
    global LESSON_MODE, INTERFACE
    LESSON_MODE, INTERFACE = args.lesson_mode, args.interface
    out = args.out or WORK / f"{args.arm}-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / 'config.json', {'arm': args.arm, 'runs': args.runs, 'tasks': [t['task_id'] for t in tasks],
                                     'manifest': manifest['version'], 'lessons': lessons, 'lesson_mode': args.lesson_mode,
                                     'interface': args.interface})
    import contextlib
    service, model = contextlib.nullcontext(), None
    if args.arm == 'a0':
        from local_service import LocalService
        from core.model_provider import OpenAICompatibleProvider
        service = LocalService(args.port, out)
        model = OpenAICompatibleProvider(api_key='local', model_name='agents-a1-4b',
                                         base_url=f'http://127.0.0.1:{args.port}/v1', timeout_sec=180)
    with service:
        for run in range(1, args.runs + 1):
            for task in tasks:
                wait_until_unlocked()
                run_dir = out / f"{task['task_id']}-r{run}"
                run_dir.mkdir(exist_ok=True)
                environment = ENVIRONMENTS[task['family']](task, run_dir)
                start, record = time.monotonic(), {'task_id': task['task_id'], 'family': task['family'],
                                                   'run': run, 'arm': args.arm}
                try:
                    ax = environment.setup()
                    tools = Tools(ax, task)
                    with (run_dir / 'trace.jsonl').open('w', encoding='utf-8') as trace:
                        record['agent'] = oracle(tools, task) if args.arm == 'oracle' else run_agent(model, tools, task, trace, lessons=lessons)
                    record['check'] = environment.check(tools.final)
                except Exception as exc:
                    record['error'] = f'{type(exc).__name__}: {exc}'
                    record.setdefault('check', {'passed': False})
                try:
                    record['cleanup'] = environment.cleanup()
                except Exception as exc:
                    record['cleanup'] = {'error': f'{type(exc).__name__}: {exc}'}
                record['seconds'] = round(time.monotonic() - start, 1)
                with (out / 'results.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + '\n')
                print(json.dumps({k: record.get(k) for k in ('task_id', 'run', 'seconds', 'error')}
                                 | {'passed': record['check'].get('passed')}, ensure_ascii=False), flush=True)
    print(out)


if __name__ == '__main__':
    main()
