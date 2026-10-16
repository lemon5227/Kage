"""A4: idle-time practice on variants of the user's real file tasks.

One round (when practice is switched on, the user has been idle long enough and the local model
is up):
  1. seeds — real task turns that wrote files, the ones that failed first (👎 / failed checks);
  2. the teacher writes a practice variant per seed: same kind of job, different specifics, a set
     of starting files and a ``check(ws)`` function (Self-Challenging style; via the ledger and the
     real-use daily cap);
  3. the student does it with the app's own agent loop, in a fresh temporary directory, with file
     tools only — so the trajectory has the real-use format and can become training data;
  4. the checker decides; the trajectory is stored as ``source='practice'`` (sharing its seed's
     train/held-out split); a learning report notice summarises the round.
Nothing touches the user's files: tasks live in a temp directory named in the instruction.
"""
from __future__ import annotations

import ast
import datetime
import json
from pathlib import Path
import re
import tempfile
import uuid

from core.evolution.mutator import parse_proposal
from core.trajectories import TrajectoryRecorder

PRACTICE_TOOLS = ('fs_write', 'fs_preview', 'fs_search', 'fs_move', 'fs_rename', 'fs_apply')
ALLOWED_IMPORTS = {'json', 're', 'csv', 'os', 'pathlib', 'datetime', 'math', 'collections', 'string'}
BANNED_CALLS = {'eval', 'exec', 'compile', '__import__', 'system', 'popen', 'remove', 'rmtree',
                'unlink', 'rmdir', 'rename', 'chmod', 'kill'}

MAKER_PROMPT = """你在给一个本地小模型出练习题。下面是用户真实交给它的一件文件类任务：
「{task}」
请出一道同一类型、但具体内容不同的新题（文件名、数据、要求的细节都要换），只用读写文件就能完成。
所有文件都放在目录 {{WS}} 下（题目里用 {{WS}} 指代这个目录）。只回复一个 JSON 对象：
{{"instruction": "给模型的中文任务描述，提到 {{WS}}", "files": {{"相对路径": "初始内容"}},
  "check": "def check(ws):\\n    ...  # ws 是目录路径字符串；只读文件判断结果是否正确，返回 True/False"}}
check 只能用 json/re/csv/os.path/pathlib 读文件，不能修改、删除文件，不能联网或执行命令。"""


class PracticeError(ValueError):
    pass


def validate_check(code: str) -> str:
    tree = ast.parse(code)
    if not any(isinstance(n, ast.FunctionDef) and n.name == 'check' for n in tree.body):
        raise PracticeError('check(ws) is missing')
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name.split('.')[0] for a in node.names] if isinstance(node, ast.Import) \
                else [str(node.module or '').split('.')[0]]
            if any(n not in ALLOWED_IMPORTS for n in names):
                raise PracticeError(f'import not allowed in check: {names}')
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ''
            if name in BANNED_CALLS:
                raise PracticeError(f'call not allowed in check: {name}')
            if name == 'open' and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) \
                    and any(m in str(node.args[1].value) for m in 'wax+'):
                raise PracticeError('check may only read files')
    return code


def make_task(teacher, seed: dict) -> dict:
    reply = teacher.generate(messages=[{'role': 'user', 'content': MAKER_PROMPT.format(task=str(seed['user_input'])[:500])}],
                             max_tokens=1024)
    raw = str(getattr(reply, 'text', '') or '').strip()
    raw = re.sub(r'^```(?:json)?|```$', '', raw).strip()
    try:
        task, _ = parse_proposal(raw)
    except ValueError as exc:
        raise PracticeError(f'teacher reply is not JSON: {exc}') from exc
    if not isinstance(task, dict) or not isinstance(task.get('instruction'), str) or '{WS}' not in task['instruction']:
        raise PracticeError('instruction must mention {WS}')
    files = task.get('files') or {}
    if not isinstance(files, dict) or any(not isinstance(k, str) or '..' in k or k.startswith('/') for k in files):
        raise PracticeError('files must be relative paths')
    return {'instruction': task['instruction'], 'files': {k: str(v) for k, v in files.items()},
            'check': validate_check(str(task.get('check') or ''))}


def run_check(code: str, ws: Path, runner=None) -> bool:
    """Run the teacher's check(ws) in a subprocess; any error counts as a failed check."""
    from core.evolution.sandbox import ProcessSkillRunner
    runner = runner or ProcessSkillRunner(timeout_s=10)
    adapter = '\n\ndef run(arguments, context):\n    return {"success": True, "passed": bool(check(context["workspace_dir"]))}\n'
    result = runner.run((code + adapter).encode(), 'run', {}, ws)
    return bool(isinstance(result, dict) and result.get('success') and result.get('passed'))


def seeds(store: TrajectoryRecorder, k: int) -> list[dict]:
    """Real file-writing task turns, failed ones first, newest first within each group."""
    failed, ok = [], []
    for path in store.root.glob('*.json') if store.root.exists() else []:
        try:
            r = json.loads(path.read_text())
        except ValueError:
            continue
        check = r.get('auto_check') or {}
        if r.get('source') == 'real' and r.get('kind') == 'task' and check.get('wrote_files'):
            (failed if r.get('feedback') == 'down' or not check.get('all_tools_ok') else ok).append(r)
    newest = lambda rows: sorted(rows, key=lambda r: str(r.get('created') or ''), reverse=True)
    return (newest(failed) + newest(ok))[:k]


async def practice_round(*, store: TrajectoryRecorder, teacher, make_runner, variants: int = 2, k_seeds: int = 2,
                         workdir: Path | None = None, check_runner=None) -> dict:
    """``make_runner(recorder)`` returns an agent loop whose model calls go to ``recorder``."""
    summary = {'created': datetime.datetime.now().isoformat(timespec='seconds'), 'tasks': 0, 'passed': 0,
               'errors': [], 'items': []}
    base = Path(workdir or tempfile.mkdtemp(prefix='kage-practice-'))
    for seed in seeds(store, k_seeds):
        for _ in range(variants):
            try:
                task = make_task(teacher, seed)
            except Exception as exc:                 # a bad or unaffordable variant is skipped, not fatal
                summary['errors'].append(f'{type(exc).__name__}: {str(exc)[:120]}')
                if type(exc).__name__ == 'DailyCapReached':
                    return summary
                continue
            ws = base / uuid.uuid4().hex[:8]
            ws.mkdir(parents=True)
            for rel, content in task['files'].items():
                (ws / rel).parent.mkdir(parents=True, exist_ok=True)
                (ws / rel).write_text(content)
            instruction = task['instruction'].replace('{WS}', str(ws))
            recorder = TrajectoryRecorder(store.root, enabled=True)
            practice_id = f"practice-{uuid.uuid4().hex[:10]}"
            recorder.begin(practice_id, instruction, source='practice', parent=seed['id'])
            result, error = None, None
            try:
                result = await make_runner(recorder).run(user_input=instruction, current_emotion='neutral')
            except Exception as exc:
                error = type(exc).__name__
            finally:
                record = recorder.finish(str(getattr(result, 'final_text', '') or ''),
                                         list(getattr(result, 'tool_calls_executed', None) or []))
            passed = error is None and run_check(task['check'], ws, check_runner)
            if record is not None:
                record['auto_check'] = {**record.get('auto_check', {}), 'checker_passed': passed}
                record['practice'] = {'seed': seed['id'], 'files': task['files'], 'check': task['check']}
                recorder._write(record)
            summary['tasks'] += 1
            summary['passed'] += int(passed)
            summary['items'].append({'id': practice_id, 'seed': seed['id'], 'passed': passed, 'error': error})
    return summary


def report_notice(summary: dict) -> dict | None:
    from core.evolution.notices import _notice
    if not summary.get('tasks'):
        return None
    body = (f"空闲时照着你最近交给我的文件类任务出了 {summary['tasks']} 道练习题，自己做对了 {summary['passed']} 道。"
            "做对的过程已记下来，以后用来学习。")
    return _notice('learning_report', '我刚练习完一轮', body,
                   {'tasks': summary['tasks'], 'passed': summary['passed'], 'items': summary['items']}, False)


# ---------------------------------------------------------------------- idle trigger (heartbeat source)
PRACTICE_DEFAULTS = {'practice': False, 'practice_idle_minutes': 30, 'practice_rounds_per_day': 3,
                     'practice_variants': 2, 'practice_seeds': 2}


class PracticeScheduler:
    """Heartbeat source: start at most one practice round at a time when every condition holds.

    ``evolution.practice`` must be switched on (default off). The round runs in the background;
    its learning report is written to the notice store and delivered by NoticeSource.
    """

    def __init__(self, config: dict | None, *, last_user_time, model_ready, start_round, notices,
                 state_path: str | Path = '~/.kage/practice_state.json'):
        self.cfg = {**PRACTICE_DEFAULTS, **(config or {})}
        self.last_user_time, self.model_ready, self.start_round = last_user_time, model_ready, start_round
        self.notices = notices
        self.state_path = Path(str(state_path)).expanduser()
        self.task = None

    def _rounds_today(self) -> int:
        if not self.state_path.exists():
            return 0
        return int(json.loads(self.state_path.read_text()).get(datetime.date.today().isoformat(), 0))

    def should_run(self, now_ts: float) -> tuple[bool, str]:
        if not self.cfg['practice']:
            return False, 'practice is off'
        if self.task is not None and not self.task.done():
            return False, 'a round is running'
        last = self.last_user_time()
        if last is not None and now_ts - last < 60 * float(self.cfg['practice_idle_minutes']):
            return False, 'user active'
        if self._rounds_today() >= int(self.cfg['practice_rounds_per_day']):
            return False, 'daily rounds used'
        if not self.model_ready():
            return False, 'local model not running'
        return True, 'ok'

    async def _round(self) -> dict:
        import asyncio  # noqa: F401  (kept local: the module is imported in sync contexts too)
        summary = await self.start_round(variants=int(self.cfg['practice_variants']),
                                         k_seeds=int(self.cfg['practice_seeds']))
        today = datetime.date.today().isoformat()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({today: self._rounds_today() + 1}))
        notice = report_notice(summary)
        if notice is not None:
            self.notices.add(notice)
        return summary

    async def collect(self, now) -> list[dict]:
        import asyncio
        ok, _ = self.should_run(now.timestamp())
        if ok:
            self.task = asyncio.create_task(self._round())
        return []
