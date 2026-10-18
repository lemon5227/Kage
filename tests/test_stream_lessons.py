"""C3: teacher-written task-scoped lessons (rule only vs demo + rule) on the real browser chain.

Scripted models only: no network, no cloud teacher. The learner tests import the oracle and
observation helpers from ``test_stream_browser`` and run the same local fixtures.
"""
import json
import sqlite3

import pytest

pytest.importorskip('playwright.async_api')

from core.computer_use.experiment import BrowserChainProvider
from core.evolution.budget import BudgetConfig, BudgetExhaustedError, BudgetTracker
from core.evolution.contracts import Candidate, RunResult
from core.evolution.journal import Journal
from core.evolution.lessons import MAX_INPUT_BYTES, extract_lessons
from core.evolution.mutator import bundle_digest
from core.evolution.playbook import Playbook
from core.evolution.relevance import RELEVANCE_MIN, InstructionSpace, SkillSources
from core.evolution.stream import StreamLearner, TeacherCache, chain_runner
from core.evolution.stream_tasks import make_task
from core.model_provider import ModelProvider, ModelResponse
from test_stream_browser import USAGE, Oracle, _latest

LESSON = {'when': 'an invoice table has hidden rows', 'do': 'click "Show more rows" before computing', 'avoid': ''}
FENCED = '''Here is what the failure teaches:

```json
{"lessons": [
  {"when": "a table hides rows", "do": "reveal all rows before computing", "avoid": "summing visible rows only"},
  {"when": "a form has a Next button", "do": "fill the first page, click Next, then continue", "avoid": "saving early"},
  {"when": "a checkbox is already in the target state", "do": "leave it unchanged", "avoid": "clicking it"}
]}
```
'''


class Scripted(ModelProvider):
    def __init__(self, reply):
        self.reply, self.messages, self.request = reply, None, {}

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        self.messages = messages
        self.request = {'max_tokens': max_tokens, 'temperature': temperature}
        return ModelResponse(text=self.reply, usage=USAGE)


def browser_result(tmp_path, name, steps, *, score=1.0, status='passed'):
    rows = []
    for operation, target, value in steps:
        acted = {'operation': operation, 'label': target}
        if value is not None:
            acted['value'] = value
        rows.append({'action': {'name': 'browser_act', 'arguments': {}},
                     'observation': {'success': True, 'content': json.dumps({'acted': acted})}})
    path = tmp_path / f'{name}.jsonl'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    return RunResult(name, status, score, str(path))


def invoice_task(tmp_path):
    return {'task_id': 'web-invoice-test', 'family': 'web_invoice',
            'instruction': 'Compute the invoice total over all rows and save it.',
            'scoring_criteria': {'expected': {'record': {'total': 'SCORING-SECRET-7'}, 'posts': 1}}}


def test_extract_lessons_parses_fences_forces_task_scope_and_caps_at_two(tmp_path):
    model = Scripted(FENCED)
    budget = BudgetTracker(BudgetConfig(max_api_calls=10), tmp_path / 'budget.sqlite')
    demo = browser_result(tmp_path, 'demo', [('click', 'Show more rows', None),
                                             ('fill', 'Total', '1143'), ('click', 'Save', None)])
    student = browser_result(tmp_path, 'student', [('fill', 'Total', '1'), ('click', 'Save', None)],
                             score=0.0, status='failed')
    task = invoice_task(tmp_path)
    lessons = extract_lessons(model, budget, task=task, demo=demo, student=student, run_id='lesson-1')

    assert len(lessons) == 2 and all(lesson['scope'] == 'task' for lesson in lessons)
    assert lessons[0]['do'] == 'reveal all rows before computing'
    prompt = '\n'.join(message['content'] for message in model.messages)
    assert task['instruction'] in prompt
    assert 'click "Show more rows"' in prompt and 'fill "Total" = "1143"' in prompt
    assert 'fill "Total" = "1"' in prompt
    assert 'SCORING-SECRET-7' not in prompt
    assert model.request == {'max_tokens': 600, 'temperature': 0.0}
    with sqlite3.connect(tmp_path / 'budget.sqlite') as conn:
        rows = conn.execute('SELECT call_type, state, calls_used, input_used, output_used '
                            'FROM evolution_budget').fetchall()
    assert rows == [('lesson', 'settled', 1, 10, 5)]


def test_extract_lessons_garbage_is_empty_and_long_steps_stay_under_the_byte_cap(tmp_path):
    task = invoice_task(tmp_path)
    garbage = Scripted('I could not produce JSON.')
    assert extract_lessons(garbage, BudgetTracker(BudgetConfig(max_api_calls=10), tmp_path / 'g.sqlite'),
                           task=task, demo=browser_result(tmp_path, 'd1', [('click', 'Save', None)]),
                           student=None, run_id='lesson-garbage') == []

    steps = [('fill', 'Field ' + 'x' * 80, str(i) + 'y' * 80) for i in range(400)]
    long_demo = browser_result(tmp_path, 'd2', steps)
    long_student = browser_result(tmp_path, 's2', steps, score=0.0, status='failed')
    model = Scripted(FENCED)
    lessons = extract_lessons(model, BudgetTracker(BudgetConfig(max_api_calls=10), tmp_path / 'l.sqlite'),
                              task=task, demo=long_demo, student=long_student, run_id='lesson-long')
    assert len(lessons) == 2
    request = json.dumps(model.messages, ensure_ascii=False).encode('utf-8')
    assert len(request) <= MAX_INPUT_BYTES and task['instruction'] in model.messages[-1]['content']


def test_extract_lessons_propagates_budget_exhaustion(tmp_path):
    budget = BudgetTracker(BudgetConfig(max_api_calls=0), tmp_path / 'empty.sqlite')
    with pytest.raises(BudgetExhaustedError):
        extract_lessons(Scripted(FENCED), budget, task=invoice_task(tmp_path),
                        demo=browser_result(tmp_path, 'd', [('click', 'Save', None)]),
                        student=None, run_id='lesson-broke')


def test_playbook_select_uses_similarity_only_when_asked(tmp_path):
    pb = Playbook(tmp_path / 'playbook.json')
    pb.add([{'scope': 'task', 'when': 'a table has hidden rows', 'do': 'click "Show more rows"', 'avoid': ''}],
           source_task='t1', trigger='Compute the invoice total over all rows')
    similar = lambda a, b: 1.0 if 'invoice' in a.casefold() and 'invoice' in b.casefold() else 0.0

    shown = pb.select('Compute the invoice total for all rows', similarity=similar, min_score=0.5)
    assert len(shown) == 1 and 'Show more rows' in Playbook.render(shown)
    assert pb.select('Change the notification settings checkboxes', similarity=similar, min_score=0.5) == []

    # Without similarity the old word-overlap retrieval is unchanged.
    assert len(pb.select('Compute the invoice total for all rows')) == 1
    assert pb.select('Merge booking intervals') == []


def test_browser_provider_soul_is_unchanged_without_guidance_and_carries_guidance(tmp_path):
    task = make_task('web_invoice', 1000)
    bare = BrowserChainProvider(Scripted(''), task)
    empty = BrowserChainProvider(Scripted(''), task, extra_guidance='')
    assert empty._experiment_soul() == bare._experiment_soul()
    guided = BrowserChainProvider(Scripted(''), task, extra_guidance='Lessons from earlier tasks:\n- reveal rows first')
    assert guided._experiment_soul() == bare._experiment_soul() + '\nLessons from earlier tasks:\n- reveal rows first'


def hidden_row_invoices():
    return [task for task in (make_task('web_invoice', seed) for seed in range(1000, 1100))
            if len(task['fixture']['rows']) > task['fixture']['visible_rows']][:2]


def make_world(tmp_path, student_cls, extractor, tasks):
    by_instruction = {task['instruction']: task for task in tasks}

    def task_of(messages):
        text = '\n'.join(str(message.get('content') or '') for message in messages)
        return next(task for instruction, task in by_instruction.items() if instruction in text), text

    class Teacher(ModelProvider):
        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            task, text = task_of(messages)
            oracle = Oracle(task)
            oracle.done = text.count('"acted"')
            return oracle.generate(messages, tools, max_tokens, temperature)

    big = BudgetConfig(max_api_calls=10_000, max_input_tokens_total=10**8, max_output_tokens_total=10**7)
    sources = SkillSources(tmp_path / 'L' / 'skill_sources.json', InstructionSpace(tmp_path / 'L' / 'space.json'))
    playbook = Playbook(tmp_path / 'L' / 'playbook.json')
    student = chain_runner(Journal(tmp_path / 's.sqlite'), BudgetTracker(big, tmp_path / 'sb.sqlite'), tmp_path / 'ws',
                           lambda run_id: student_cls(task_of), playbook=playbook,
                           playbook_similarity=sources.space.similarity, playbook_min=RELEVANCE_MIN, gate=sources)
    teacher_run = chain_runner(Journal(tmp_path / 't.sqlite'), BudgetTracker(big, tmp_path / 'tb.sqlite'), tmp_path / 'tws',
                               lambda run_id: Teacher(), cloud=True)
    boot = tmp_path / 'boot'
    boot.mkdir()
    (boot / 'manifest.json').write_text('{"version":1,"skills":[]}')
    bootstrap = Candidate('no-skills', (), 'skill', str(boot), bundle_digest(boot))
    teacher = TeacherCache(tmp_path / 'cache', lambda task: teacher_run(bootstrap, task, 'teacher-' + task['task_id']))
    learner = StreamLearner(tmp_path / 'L', 'AGL', bootstrap=bootstrap, run_student=student, teacher=teacher,
                            propose_skill=None, playbook=playbook, extract_lessons=extractor, skill_sources=sources)
    return learner, task_of


def test_agl_learns_a_lesson_from_the_teacher_and_solves_the_next_task(tmp_path):
    tasks = hidden_row_invoices()

    class Student(ModelProvider):
        def __init__(self, task_of):
            self.task_of = task_of

        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            task, text = self.task_of(messages)
            system = str(messages[0].get('content') or '')
            learned = 'Lessons from earlier tasks' in system and 'Show more rows' in system
            current = text[text.rfind(task['instruction']):]
            fixture = task['fixture']
            total = str(task['scoring_criteria']['expected']['record']['total']) if learned else '1'
            steps = ([('click', 'Show more rows', None)] if learned else []) + [
                ('fill', fixture['fields'][0]['label'], total), ('click', fixture['submit'], None)]
            done = current.count('"acted"')
            if done >= len(steps):
                return ModelResponse(text='Saved.', usage=USAGE)
            operation, label, value = steps[done]
            obs, refs, _ = _latest([{'content': current}])
            arguments = {'observation_id': obs, 'operation': operation, 'target_ref': refs[label]}
            if value is not None:
                arguments['value'] = value
            return ModelResponse(text='', tool_calls=[{'name': 'browser_act', 'arguments': arguments}], usage=USAGE)

    learner, _ = make_world(tmp_path, Student, lambda task, demo, student: [dict(LESSON)], tasks)
    first = learner.step(tasks[0])
    assert first['student_score'] == 0.0 and first['teacher_score'] == 1.0, first
    assert first['learning']['kind'] == 'lessons' and first['learning']['accepted'] is True, first['learning']
    assert first['learning']['lessons'] == {'n': 1, 'rejected': 0, 'rejected_values': [],
                                             'outcomes': ['added']}, first['learning']
    assert not (tmp_path / 'L' / 'memory.jsonl').exists()
    saved = Playbook(tmp_path / 'L' / 'playbook.json').entries
    assert len(saved) == 1 and saved[0]['scope'] == 'task' and saved[0]['do'] == LESSON['do']
    assert saved[0]['triggers'] == [tasks[0]['instruction']]

    second = learner.step(tasks[1])
    assert second['solved_by_student'] is True and second['helped'] is False, second


def test_lessons_are_not_shown_for_another_browser_family(tmp_path):
    invoice = hidden_row_invoices()[0]
    prefs = make_task('web_prefs', 1000)
    prompts = tmp_path / 'prompts.jsonl'

    class Recorder(ModelProvider):
        def __init__(self, task_of):
            self.task_of = task_of

        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            with prompts.open('a') as out:
                out.write(json.dumps({'system': str(messages[0].get('content') or ''),
                                      'user': str(messages[-1].get('content') or '')}) + '\n')
            return ModelResponse(text='I looked at the page.', usage=USAGE)

    learner, _ = make_world(tmp_path, Recorder, lambda task, demo, student: [dict(LESSON)], [invoice, prefs])
    assert learner.step(invoice)['learning']['lessons']['n'] == 1
    assert Playbook(tmp_path / 'L' / 'playbook.json').entries
    learner.step(prefs)

    rows = [json.loads(line) for line in prompts.read_text().splitlines()]
    prefs_rows = [row for row in rows if prefs['instruction'] in row['user']]
    assert prefs_rows and all('Lessons from earlier tasks' not in row['system'] for row in prefs_rows)


def test_exhausted_ledger_during_lessons_stops_learning_like_a_refused_demo(tmp_path):
    """Review fix: BudgetExhaustedError from the extractor must become TeacherBudgetExhausted."""
    from core.evolution.stream import TeacherBudgetExhausted

    def broke(task, demo, student):
        raise BudgetExhaustedError('ledger empty')

    class Idle(ModelProvider):
        def __init__(self, task_of):
            pass

        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            return ModelResponse(text='I looked at the page.', usage=USAGE)

    task = hidden_row_invoices()[0]
    learner, _ = make_world(tmp_path, Idle, broke, [task])
    with pytest.raises(TeacherBudgetExhausted):
        learner.step(task)
