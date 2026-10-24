"""Kage app tools for macOS apps through the Accessibility API (G0 brought into daily use).

`desktop_task(app, instruction, document?)` runs the G0 desktop agent (core.computer_use.desktop_agent, interface
v4, lessons in plan mode) on the local model and returns what the app shows afterwards; the conversation model
then answers the user. `desktop_learn(correction)` hands the last run and the user's correction to the teacher,
which writes one general lesson for that app (stored in ~/.kage/desktop/lessons.json and used in plan mode from
the next task on). This is the "ask -> learn -> reuse" loop of the G0 demo, driven by the user instead of a
benchmark checker.

Scope: Calculator, one named TextEdit document window, and System Settings read-only (sidebar navigation only).
No keyboard events and no coordinates; Calculator's conversion mode and history sidebar are restored afterwards.
Teacher calls go through the global ledger and a per-day cap (same rule as the app's other teacher calls).
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time

from core.computer_use.desktop import DesktopAX, DesktopError
from core.computer_use.desktop_agent import TEACH_PROMPT, DesktopTools, run_agent

ROOT = Path('~/.kage/desktop').expanduser()
LESSONS = ROOT / 'lessons.json'
TEACHER_CONFIG = Path('~/.config/kage/teachers/deepseek.json').expanduser()
DAILY_TEACHER_USD = 0.05
APPS = {
    'calculator': {'bundle': 'com.apple.calculator', 'family': 'calculator', 'max_steps': 24},
    'textedit': {'bundle': 'com.apple.TextEdit', 'family': 'textedit', 'max_steps': 12},
    'settings': {'bundle': 'com.apple.systempreferences', 'family': 'settings_read', 'max_steps': 8,
                 'press_ids': 'com.apple.settings.'},
}
ALIASES = {'计算器': 'calculator', 'calculator': 'calculator', 'textedit': 'textedit', '文本编辑': 'textedit',
           'system settings': 'settings', 'settings': 'settings', '系统设置': 'settings', '设置': 'settings'}


def _wait(predicate, timeout=6.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if predicate():
                return True
        except DesktopError:
            pass
        time.sleep(.2)
    return False


def _ids(ax):
    return {item.get('id'): item for item in ax.snapshot()['items'] if item.get('ref')}


def load_lessons() -> dict:
    try:
        return json.loads(LESSONS.read_text())
    except (OSError, ValueError):
        return {}


class DesktopService:
    def __init__(self, model_provider, *, root: Path = ROOT):
        self.model = model_provider
        self.root = Path(root)
        self.last_run: Path | None = None

    # --- preparing and restoring the app (same steps as the G0 runs) -----------------------------------------
    def _prepare(self, app, document):
        spec = APPS[app]
        if app == 'calculator':
            ax = DesktopAX(spec['bundle'])
            subprocess.run(['open', '-g', '-a', 'Calculator'], check=True, timeout=10)
            _wait(lambda: ax.snapshot())
            restore = {}
            if 'UnitsSwapButton' in _ids(ax):
                restore['conversion'] = True
                ax.press_menu_unchecked('显示', '转换')
                _wait(lambda: 'UnitsSwapButton' not in _ids(ax))
            if ax.menu_item('显示', '隐藏历史记录') is not None:
                restore['history'] = True
                ax.press_menu_unchecked('显示', '隐藏历史记录')
            return ax, restore
        if app == 'textedit':
            path = Path(document).expanduser() if document and ('/' in document or document.startswith('~')) else None
            if path is not None:
                if not path.is_file() or not path.resolve().is_relative_to(Path.home()):
                    raise DesktopError('the TextEdit document must be an existing file in your home folder')
                subprocess.run(['open', '-g', '-a', 'TextEdit', str(path)], check=True, timeout=10)
            title = path.name if path is not None else (document or '')
            if not title:
                raise DesktopError('say which TextEdit document to edit (its name or path)')
            ax = DesktopAX(spec['bundle'], window_title=title, menus=[('文件', '保存')])
            if not _wait(lambda: ax.snapshot(), timeout=8):
                raise DesktopError(f'no open TextEdit window named "{title}"')
            return ax, {}
        ax = DesktopAX(spec['bundle'], max_items=200)
        subprocess.run(['open', '-g', 'x-apple.systempreferences:'], check=True, timeout=10)
        _wait(lambda: ax.snapshot(), timeout=8)
        return ax, {}

    @staticmethod
    def _restore(app, ax, restore):
        if app != 'calculator':
            return
        if restore.get('history') and ax.menu_item('显示', '显示历史记录') is not None:
            ax.press_menu_unchecked('显示', '显示历史记录')
        if restore.get('conversion') and 'UnitsSwapButton' not in _ids(ax):
            ax.press_menu_unchecked('显示', '转换')

    @staticmethod
    def _summary(app, ax, tools):
        observation = ax.snapshot()
        texts = [i['text'] for i in observation['items'] if i['kind'] in ('text', 'heading')]
        if app == 'calculator':
            shown = {t.split(':', 1)[0]: t.split(':', 1)[1].strip() for t in texts if ':' in t}
            return {'display': shown.get('编辑字段', ''), 'previous_expression': shown.get('上个表达式', '')}
        if app == 'textedit':
            area = next((i for i in observation['items'] if i.get('kind') == 'textarea'), {})
            return {'document_text': area.get('state', '')}
        return {'answer': (tools.final or {}).get('answer')}

    # --- the tools ------------------------------------------------------------------------------------------
    def run(self, app: str, instruction: str, document: str = '') -> dict:
        app = ALIASES.get(str(app).strip().lower(), str(app).strip().lower())
        if app not in APPS:
            return {'success': False, 'error': f'unsupported app {app!r}; use calculator, textedit or settings'}
        spec = APPS[app]
        run_dir = self.root / 'runs' / time.strftime('%Y%m%d-%H%M%S')
        run_dir.mkdir(parents=True, exist_ok=True)
        task = {'instruction': instruction, 'family': spec['family'], 'max_steps': spec['max_steps'],
                **({'press_ids': spec['press_ids']} if 'press_ids' in spec else {})}
        restore, ax = {}, None
        try:
            ax, restore = self._prepare(app, document)
            if app == 'calculator':
                ax.press(_ids(ax)['AllClear']['ref'])
            tools = DesktopTools(ax, task, interface='v4')
            with (run_dir / 'trace.jsonl').open('w', encoding='utf-8') as trace:
                agent = run_agent(self.model, tools, task, trace, max_tokens=600, lessons=load_lessons(), mode='plan')
            result = {'success': True, 'app': app, 'stop': agent['stop'], 'actions': agent['actions'],
                      **self._summary(app, ax, tools)}
        except Exception as exc:
            result = {'success': False, 'app': app, 'error': f'{type(exc).__name__}: {exc}'}
        finally:
            if ax is not None:
                try:
                    self._restore(app, ax, restore)
                except Exception:
                    pass
        (run_dir / 'task.json').write_text(json.dumps({'app': app, 'instruction': instruction, 'document': document,
                                                       'result': result}, ensure_ascii=False, indent=1))
        self.last_run = run_dir
        return result

    def learn(self, correction: str) -> dict:
        """The teacher turns the last run plus the user's correction into one general lesson for that app."""
        if self.last_run is None:
            return {'success': False, 'error': 'no desktop task has run in this session yet'}
        from core.evolution.teacher_budget import global_teacher_budget, remaining_usd
        from core.model_provider import OpenAICompatibleProvider
        task = json.loads((self.last_run / 'task.json').read_text())
        spent_today = self._spent_today()
        if spent_today >= DAILY_TEACHER_USD:
            return {'success': False, 'error': 'the daily teacher budget for desktop lessons is used up'}
        steps = [json.loads(line) for line in (self.last_run / 'trace.jsonl').read_text().splitlines()]
        actions = [f"{s['tool']}({json.dumps(s['arguments'], ensure_ascii=False)}) -> {s['result'].split(chr(10), 1)[0]}"
                   for s in steps if 'tool' in s]
        window = next((s['result'].split('\n', 1)[1] for s in steps if 'tool' in s and '\n' in s['result']), '')
        message = (f"Task: {task['instruction']}\n\nThe application window (controls the assistant can use):\n"
                   f"{window[:2500]}\n\nActions:\n" + '\n'.join(actions) +
                   f"\n\nResult the app showed: {json.dumps(task['result'], ensure_ascii=False)}"
                   f"\nThe user says this is wrong: {correction}")
        cloud = json.loads(TEACHER_CONFIG.read_text())['model']['cloud_api']
        teacher = OpenAICompatibleProvider(api_key=cloud['api_key'], model_name=cloud['model_name'],
                                           base_url=cloud['base_url'], timeout_sec=120, thinking=True)
        budget = global_teacher_budget()
        start = remaining_usd(budget)
        reservation = budget.reserve(4000, 2000, call_type='desktop_lesson', run_id=f'desktop-{self.last_run.name}')
        response = None
        try:
            response = teacher.generate(messages=[{'role': 'system', 'content': TEACH_PROMPT},
                                                  {'role': 'user', 'content': message}], max_tokens=2000, temperature=0.0)
        finally:
            budget.settle(reservation, getattr(response, 'usage', None))
        lesson = ' '.join((response.text or '').split()) if response and not response.error else ''
        if not lesson:
            return {'success': False, 'error': 'the teacher did not return a lesson'}
        family = APPS[task['app']]['family']
        lessons = load_lessons()
        lessons.setdefault(family, []).append(lesson)
        LESSONS.parent.mkdir(parents=True, exist_ok=True)
        LESSONS.write_text(json.dumps(lessons, ensure_ascii=False, indent=1))
        cost = round(start - remaining_usd(budget), 5)
        with (self.root / 'teacher-spend.jsonl').open('a') as stream:
            stream.write(json.dumps({'day': time.strftime('%Y-%m-%d'), 'usd': cost}) + '\n')
        return {'success': True, 'app': task['app'], 'lesson': lesson, 'cost_usd': cost}

    def recent(self, minutes: float = 15) -> bool:
        """A desktop task ran in this session within the last `minutes` (a correction can refer to it)."""
        return self.last_run is not None and time.time() - self.last_run.stat().st_mtime < minutes * 60

    def _spent_today(self) -> float:
        try:
            rows = [json.loads(line) for line in (self.root / 'teacher-spend.jsonl').read_text().splitlines()]
        except OSError:
            return 0.0
        return sum(r['usd'] for r in rows if r['day'] == time.strftime('%Y-%m-%d'))


CORRECTION_WORDS = ('不对', '错了', '不是这样', '应该是', 'wrong', 'should be')


def is_correction(text: str) -> bool:
    """The user says the last result was wrong. The 4B conversation model apologised instead of calling
    desktop_learn in the first app test, so the server triggers learning itself (like the 👎 -> teacher flow)."""
    text = str(text or '').lower()
    return any(word in text for word in CORRECTION_WORDS)


def register_desktop_tools(registry, service: DesktopService) -> None:
    from core.tool_registry import ToolDefinition
    registry.register(ToolDefinition(
        name='desktop_task',
        description=('Operate inside a macOS app through its accessibility controls, ONLY when the user asks you to '
                     'use that app or the information exists only in its window: textedit (edit an open document; '
                     'give its name or path as document), settings (read a System Settings value, read-only), or '
                     'calculator (only if the user explicitly wants the Calculator app). Never use it for plain '
                     'arithmetic or anything you can answer or do directly. Returns what the app shows afterwards.'),
        parameters={'type': 'object', 'properties': {
            'app': {'type': 'string', 'enum': ['calculator', 'textedit', 'settings']},
            'instruction': {'type': 'string'},
            'document': {'type': 'string', 'description': 'TextEdit only: document name or path', 'default': ''}},
            'required': ['app', 'instruction']},
        handler=lambda app, instruction, document='': json.dumps(service.run(app, instruction, document),
                                                                 ensure_ascii=False),
        safety_level='SAFE'))
    registry.register(ToolDefinition(
        name='desktop_learn',
        description=('When the user says the last desktop_task result was wrong, pass their correction; a teacher '
                     'writes one general lesson for that app, used on later tasks.'),
        parameters={'type': 'object', 'properties': {'correction': {'type': 'string'}}, 'required': ['correction']},
        handler=lambda correction: json.dumps(service.learn(correction), ensure_ascii=False),
        safety_level='SAFE'))

