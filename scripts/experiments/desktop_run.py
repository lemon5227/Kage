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

MANIFEST = ROOT / 'eval' / 'desktop_v1' / 'tasks.json'
WORK = Path.home() / '.kage' / 'g0'
SYSTEM = (
    'You operate one macOS application through its accessibility controls. The observation lists the window '
    'contents in reading order: "[e7] button "7" id=Seven (press)" is a control you can act on by its ref, '
    '"= value" is its current state, and lines starting with "-" are plain text on screen. '
    'Tools: press(ref) clicks a control; fill(ref, text) replaces the whole text of a text field or text area; '
    'activate() brings the app to the front (its menus only work while it is in front); menu(menu, item) runs '
    'one of the allowed menu commands; answer(text) gives your final answer to a question; done() ends the task. '
    'Every action returns a fresh observation and refs can change, so always use refs from the latest '
    'observation. Act one step at a time. The result is checked by reading the app or the file afterwards: '
    'saying the task is done does not make it done.'
)
TOOLS = {
    'press': ('Click (AXPress) a control from the latest observation.', {'ref': {'type': 'string'}}, ['ref']),
    'fill': ('Replace the whole text of a text field or text area with the given text.',
             {'ref': {'type': 'string'}, 'text': {'type': 'string'}}, ['ref', 'text']),
    'activate': ('Bring the application to the front.', {}, []),
    'menu': ('Run an allowed menu command, e.g. menu="文件", item="保存".',
             {'menu': {'type': 'string'}, 'item': {'type': 'string'}}, ['menu', 'item']),
    'observe': ('Observe the window again.', {}, []),
    'answer': ('Give the final answer to the question and end the task.', {'text': {'type': 'string'}}, ['text']),
    'done': ('End the task when it is complete.', {}, []),
}
FAMILY_TOOLS = {'calculator': ['press', 'observe', 'done'],
                'textedit': ['fill', 'activate', 'menu', 'observe', 'done'],
                'settings_read': ['observe', 'answer']}
ON = {'on', 'yes', 'true', 'enabled', '开', '开启', '打开', '是', '已开启'}
OFF = {'off', 'no', 'false', 'disabled', '关', '关闭', '否', '未开启'}


def tool_schemas(names):
    return [{'type': 'function', 'function': {'name': n, 'description': TOOLS[n][0],
             'parameters': {'type': 'object', 'properties': TOOLS[n][1], 'required': TOOLS[n][2]}}} for n in names]


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

    def setup(self):
        subprocess.run(['open', '-g', '-a', 'Calculator'], check=True, timeout=10)
        wait_for(lambda: self.ax.snapshot())
        if 'UnitsSwapButton' in ids(self.ax.snapshot()):            # the user's conversion mode: off for the task
            self.restore_conversion = True
            self.ax.press_menu_unchecked('显示', '转换')
            if not wait_for(lambda: 'UnitsSwapButton' not in ids(self.ax.snapshot())):
                raise RuntimeError('could not leave Calculator conversion mode')
        self.ax.press(ids(self.ax.snapshot())['AllClear']['ref'])
        return self.ax

    def check(self, final):
        observation = self.ax.snapshot()
        shown = {t.split(':', 1)[0]: t.split(':', 1)[1].strip() for t in texts(observation) if ':' in t}
        display, previous = shown.get('编辑字段', ''), shown.get('上个表达式', '')
        computed = bool(re.search(r'[+\-−×÷*/]', previous))       # typing the answer digits is not computing it
        ok = digits(display) == self.task['expected'] and computed
        return {'passed': ok, 'display': display, 'previous_expression': previous, 'computed': computed}

    def cleanup(self):
        if self.restore_conversion:
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
class Tools:
    """The model-facing tools of one task; every call returns a status line plus the fresh observation."""

    def __init__(self, ax, task):
        self.ax, self.task, self.final, self.actions = ax, task, None, 0
        self.allowed = FAMILY_TOOLS[task['family']] + (['press'] if task.get('press_ids') else [])

    def observation(self):
        observation = self.ax.snapshot()
        if self.task['family'] == 'settings_read':      # read-only: show no operations except allowed navigation
            for item in observation['items']:
                navigable = self.task.get('press_ids') and str(item.get('id', '')).startswith(self.task['press_ids'])
                item['ops'] = ['press'] if navigable else []
        return render(observation)

    def call(self, name, arguments):
        if name not in self.allowed:
            return f'error: tool {name} is not available in this task'
        try:
            if name == 'press':
                ref = str(arguments.get('ref', ''))
                ref = self.ax.resolve(ref) or ref
                if self.task['family'] == 'settings_read':
                    item = next((i for i in self.ax._items if i.get('ref') == ref), {})
                    if not str(item.get('id', '')).startswith(self.task.get('press_ids') or '\0'):
                        return 'error: only page navigation buttons in the sidebar may be pressed in this task'
                self.ax.press(ref)
            elif name == 'fill':
                self.ax.fill(str(arguments.get('ref', '')), arguments.get('text', ''))
            elif name == 'activate':
                self.ax.activate()
            elif name == 'menu':
                self.ax.menu(str(arguments.get('menu', '')), str(arguments.get('item', '')))
            elif name == 'answer':
                self.final = {'answer': arguments.get('text')}
                return 'answer recorded'
            elif name == 'done':
                self.final = {'done': True}
                return 'task ended'
            if name != 'observe':
                self.actions += 1
            return 'ok\n' + self.observation()
        except DesktopError as exc:
            return f'error: {exc}\n' + self.observation()
        except Exception as exc:
            return f'error: {type(exc).__name__}: {exc}\n' + self.observation()


LESSON_MODE = 'system'


def system_prompt(task, lessons):
    learned = (lessons or {}).get(task['family'], [])
    if not learned or LESSON_MODE != 'system':
        return SYSTEM
    return SYSTEM + '\n\nLessons learned from earlier tasks in this app (follow them):\n' + '\n'.join(f'- {x}' for x in learned)


def user_lessons(task, lessons):
    """lesson-mode `plan`: lessons next to the task, and the student must say how each applies before acting
    (in G0 the 4B student ignored the same lessons placed in the system prompt: 3/15 with and without)."""
    if LESSON_MODE == 'plan-only':                     # control: the same planning request, no lessons
        return ('\n\nBefore your first action, write a short plan for this task (for example the exact text or the '
                'exact button order you will use). Then follow the plan.')
    learned = (lessons or {}).get(task['family'], [])
    if not learned or LESSON_MODE != 'plan':
        return ''
    return ('\n\nLessons from your earlier attempts at this kind of task:\n' + '\n'.join(f'- {x}' for x in learned)
            + '\nBefore your first action, write a short plan that says how each lesson applies to this task '
              '(for example the exact text or the exact button order you will use). Then follow the plan.')


def run_agent(model, tools, task, trace, max_tokens=400, lessons=None):
    messages = [{'role': 'system', 'content': system_prompt(task, lessons)},
                {'role': 'user', 'content': task['instruction'] + user_lessons(task, lessons)
                 + '\n\nCurrent observation:\n' + tools.observation()}]
    schemas = tool_schemas(tools.allowed)
    stop, calls, nudged = 'max_steps', 0, False
    for step in range(task['max_steps']):
        response = model.generate(messages=messages, tools=schemas, max_tokens=max_tokens, temperature=0.7)
        trace.write(json.dumps({'step': step, 'request_messages': len(messages), 'text': response.text,
                                'tool_calls': response.tool_calls, 'error': response.error,
                                'usage': response.usage}, ensure_ascii=False) + '\n')
        if response.error and not response.tool_calls:
            stop = 'model_error'
            break
        if not response.tool_calls:
            if nudged:
                stop = 'no_tool_call'
                break
            # Interface v2: one reminder (the student once wrote "Answer: 中" as plain text instead of calling answer).
            nudged = True
            finish = 'answer(text)' if 'answer' in tools.allowed else 'done()'
            messages += [{'role': 'assistant', 'content': response.text or ''},
                         {'role': 'user', 'content': f'Reply only through the tools. If you are finished, call {finish}.'}]
            continue
        call = response.tool_calls[0]                              # one action per turn
        calls += 1
        call_id = f'call_{calls}'
        messages.append({'role': 'assistant', 'content': response.text or '',
                         'tool_calls': [{'id': call_id, 'type': 'function',
                                         'function': {'name': call['name'],
                                                      'arguments': json.dumps(call['arguments'], ensure_ascii=False)}}]})
        result = tools.call(call['name'], call['arguments'])
        trace.write(json.dumps({'step': step, 'tool': call['name'], 'arguments': call['arguments'],
                                'result': result}, ensure_ascii=False) + '\n')
        # Context packing (C4): only the latest observation stays in full; earlier tool results keep their status line.
        for message in messages:
            if message['role'] == 'tool' and '\n' in message['content']:
                message['content'] = message['content'].split('\n', 1)[0] + ' (observation superseded)'
        messages.append({'role': 'tool', 'tool_call_id': call_id, 'content': result})
        if tools.final is not None:
            stop = call['name']
            break
    return {'stop': stop, 'tool_calls': calls, 'actions': tools.actions, 'steps': step + 1}


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
TEACH_PROMPT = (
    'A small assistant model operates a macOS application through accessibility tools (press a control, fill a text '
    'field, run a menu command). It failed the task below. You see the task, the actions it took with their results, '
    'and what a trusted checker found. Write ONE general lesson for this application: one or two imperative '
    'sentences that would prevent the same mistake on other tasks of the same kind. Do not mention this task\'s '
    'specific numbers, words or file names, and do not give the answer. Reply with the lesson only.')


def teach(source, tasks):
    """One lesson per failed train task (its first failing run), written by the teacher through the global ledger."""
    from core.evolution.teacher_budget import global_teacher_budget, remaining_usd
    from core.model_provider import OpenAICompatibleProvider
    cloud = json.loads(TEACHER_CONFIG.read_text())['model']['cloud_api']
    model = OpenAICompatibleProvider(api_key=cloud['api_key'], model_name=cloud['model_name'],
                                     base_url=cloud['base_url'], timeout_sec=60, thinking=False)
    budget = global_teacher_budget()
    start = remaining_usd(budget)
    records = [json.loads(line) for line in (source / 'results.jsonl').read_text().splitlines()]
    lessons, log, seen = {}, [], set()
    for record in records:
        task = tasks[record['task_id']]
        if record['check'].get('passed') or record['task_id'] in seen or task['family'] == 'settings_read':
            continue                       # settings failures were interface problems (fixed in v2), not knowledge
        seen.add(record['task_id'])
        actions = []
        for line in (source / f"{record['task_id']}-r{record['run']}" / 'trace.jsonl').read_text().splitlines():
            step = json.loads(line)
            if 'tool' in step:
                status = step['result'].split('\n', 1)[0]
                actions.append(f"{step['tool']}({json.dumps(step['arguments'], ensure_ascii=False)}) -> {status}")
        found = {k: v for k, v in record['check'].items() if k != 'passed'}
        expected = task['expected']
        message = (f"Task: {task['instruction']}\n\nActions:\n" + '\n'.join(actions) +
                   f"\n\nChecker: expected {json.dumps(expected, ensure_ascii=False)}, found {json.dumps(found, ensure_ascii=False)}")
        reservation = budget.reserve(3000, 200, call_type='g0_lesson', run_id=f"g0-{record['task_id']}")
        response = None
        try:
            response = model.generate(messages=[{'role': 'system', 'content': TEACH_PROMPT},
                                                {'role': 'user', 'content': message}], max_tokens=200, temperature=0.0)
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
    global LESSON_MODE
    LESSON_MODE = args.lesson_mode
    out = args.out or WORK / f"{args.arm}-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / 'config.json', {'arm': args.arm, 'runs': args.runs, 'tasks': [t['task_id'] for t in tasks],
                                     'manifest': manifest['version'], 'lessons': lessons, 'lesson_mode': args.lesson_mode,
                                     'interface': 'v2'})
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
