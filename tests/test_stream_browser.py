"""C: browser families in the stream benchmark, over the REAL chain, runner and headless Chromium.

Scripted models only (engineering evidence): an oracle that reads the live observation and acts
by label proves each generated task is solvable within the caps and that the independent check
decides; a do-nothing model and a saving-on-a-question model prove the check fails closed.
"""
import json
import re

import pytest

pytest.importorskip('playwright.async_api')

from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.browser_tasks import BROWSER_FAMILIES
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.stream import MemoryStore, StreamLearner, TeacherCache, chain_runner
from core.evolution.stream_tasks import make_task
from core.model_provider import ModelProvider, ModelResponse

USAGE = {'input_tokens': 10, 'output_tokens': 5}


def _latest(messages):
    text = '\n'.join(str(m.get('content') or '') for m in messages)
    obs = re.findall(r'"observation_id":"([0-9a-f]+)"', text)[-1]
    tail = text[text.rfind(f'"observation_id":"{obs}"'):]
    refs = {}
    for ref, label in re.findall(r'\{"target_ref":"(e\d+)","label":"((?:[^"\\]|\\.)*)"', tail):
        refs.setdefault(json.loads(f'"{label}"'), ref)
    return obs, refs, tail


def plan(task):
    """The label-level actions that solve a task (test-side oracle; uses the hidden record)."""
    fx, want = task['fixture'], task['scoring_criteria']['expected']['record']
    if want is None:
        return []
    if fx['kind'] == 'profile':
        first = [('fill', f['label'], want[f['name']]) for f in fx['fields'] if 'initial' not in f and f.get('step') != 2]
        later = [('fill', f['label'], want[f['name']]) for f in fx['fields'] if 'initial' not in f and f.get('step') == 2]
        steps = first + ([('click', 'Next', None)] if later else []) + later
    elif fx['kind'] == 'invoice':
        hidden = len(fx['rows']) - fx.get('visible_rows', len(fx['rows']))
        steps = [('click', 'Show more rows', None)] * -(-hidden // 3) + [('fill', fx['fields'][0]['label'], str(want['total']))]
    elif fx['kind'] == 'preferences':
        steps = [('click', f['label'], None) for f in fx['fields'] if want[f['name']] != f['initial']]
    else:
        item = next(i for i in fx['items'] if i['id'] == want['property_id'])
        matches = [i for i in fx['items'] if i['city'] == want['city'] and i['category'] == want['category']]
        details = [('click', f"Details {i['name']}", None) for i in matches] if fx.get('ratings_hidden') else []
        return [('fill', fx['query_label'], want['city']), ('click', fx['category_label'], None),
                ('click', fx['apply_label'], None), *details, ('click', f"Choose {item['name']}", None)]
    return steps + [('click', fx['submit'], None)]


class Oracle(ModelProvider):
    def __init__(self, task, save_anyway=False):
        self.steps, self.done = plan(task), 0
        if save_anyway:                                  # a negative task, wrongly saved
            self.steps = [('click', task['fixture']['submit'], None)]

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        if self.done >= len(self.steps):
            return ModelResponse(text='Done; the page shows the saved values.', usage=USAGE)
        op, label, value = self.steps[self.done]
        self.done += 1
        obs, refs, _ = _latest(messages)
        args = {'observation_id': obs, 'operation': op, 'target_ref': refs[label]}
        if value is not None:
            args['value'] = value
        return ModelResponse(text='', tool_calls=[{'name': 'browser_act', 'arguments': args}], usage=USAGE)


class Idle(ModelProvider):
    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        return ModelResponse(text='I looked at the page.', usage=USAGE)


def runner_for(tmp_path, factory, **kw):
    journal = Journal(tmp_path / 'journal.sqlite')
    budget = BudgetTracker(BudgetConfig(max_api_calls=500, max_input_tokens_total=10**7, max_output_tokens_total=10**6),
                           tmp_path / 'budget.sqlite')
    return chain_runner(journal, budget, tmp_path / 'ws', factory, **kw)


CAND = Candidate('bootstrap', (), 'workflow', '.', 'x')


@pytest.mark.parametrize('family', sorted(BROWSER_FAMILIES))
def test_generated_tasks_are_deterministic_and_within_the_action_cap(family):
    for seed in range(1000, 1040):
        a, b = make_task(family, seed), make_task(family, seed)
        assert a == b and a['split'] == 'stream' and a['scoring_criteria']['type'] == 'json_exact_match'
        assert len(plan(a)) <= 7, (family, seed)          # 8 loop steps, one page action each + answer
    assert len({make_task(family, s)['instruction'] for s in range(1000, 1040)}) > 20


@pytest.mark.parametrize('family', ['web_form', 'web_invoice', 'web_prefs', 'web_catalog'])
def test_oracle_passes_and_idle_fails_on_a_real_page(tmp_path, family):
    task = make_task(family, 1003)
    oracle = runner_for(tmp_path / 'o', lambda run_id: Oracle(task))(CAND, task, 'oracle')
    idle = runner_for(tmp_path / 'i', lambda run_id: Idle())(CAND, task, 'idle')
    assert oracle.score == 1.0, oracle.metadata
    assert idle.score == 0.0


def test_negative_passes_only_without_a_save(tmp_path):
    task = next(make_task('web_lookup', s) for s in range(1000, 1100)
                if make_task('web_lookup', s)['fixture']['kind'] == 'invoice')
    assert task['negative']
    assert runner_for(tmp_path / 'a', lambda run_id: Idle())(CAND, task, 'answer').score == 1.0
    assert runner_for(tmp_path / 'b', lambda run_id: Oracle(task, save_anyway=True))(CAND, task, 'save').score == 0.0


def test_memory_turns_a_browser_demo_into_label_steps_and_replays_it(tmp_path):
    task = make_task('web_form', 1003)
    demo = runner_for(tmp_path / 't', lambda run_id: Oracle(task))(CAND, task, 'teacher')
    memory = MemoryStore(tmp_path / 'memory.jsonl')
    assert memory.add(task, demo)
    rows = memory.entries()[0]['rows']
    assert [r['action']['arguments']['operation'] for r in rows] == [op for op, _, _ in plan(task)]
    assert all('target' in r['action']['arguments'] and 'target_ref' not in r['action']['arguments'] for r in rows)

    seen = tmp_path / 'seen.jsonl'

    class Recorder(Oracle):
        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            with seen.open('a') as f:
                f.write(json.dumps(messages, default=str) + '\n')
            return super().generate(messages, tools, max_tokens, temperature)
    new = make_task('web_form', 1004)
    out = runner_for(tmp_path / 'm', lambda run_id: Recorder(new), mode='memory', memory=MemoryStore(
        tmp_path / 'memory.jsonl', min_jaccard=0.0))(CAND, new, 'student')
    assert out.score == 1.0
    first = json.loads(seen.read_text().splitlines()[0])
    assert any('[tool call] browser_act' in str(m.get('content')) for m in first)
    # A passing negative changed nothing: nothing to remember.
    neg = make_task('web_lookup', 1000)
    assert not memory.add(neg, runner_for(tmp_path / 'n', lambda run_id: Idle())(CAND, neg, 'neg'))


def test_retry_attempts_each_start_from_a_clean_backend(tmp_path):
    task = make_task('web_invoice', 1003)
    fills = tmp_path / 'fills.txt'            # the chain runs in a forked worker: count through a file

    class WrongThenRight(ModelProvider):
        """Each attempt starts with no actions in its history: fill, save, stop. First fill is wrong."""
        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            text = '\n'.join(str(m.get('content') or '') for m in messages)
            acted = text.count('"acted"')
            if acted >= 2:
                return ModelResponse(text='done', usage=USAGE)
            obs, refs, _ = _latest(messages)
            if acted == 0:
                with fills.open('a') as f:
                    f.write('x')
                value = '1' if fills.read_text() == 'x' else str(task['scoring_criteria']['expected']['record']['total'])
                args = {'operation': 'fill', 'target_ref': refs[task['fixture']['fields'][0]['label']], 'value': value}
            else:
                args = {'operation': 'click', 'target_ref': refs[task['fixture']['submit']]}
            return ModelResponse(text='', tool_calls=[{'name': 'browser_act', 'arguments': {'observation_id': obs, **args}}],
                                 usage=USAGE)
    out = runner_for(tmp_path, lambda run_id: WrongThenRight(), mode='retry')(CAND, task, 'retry')
    # Attempt 1 saved a wrong total; attempt 2 saved the right one on a fresh backend, so the check
    # sees exactly one POST of the right record.
    assert fills.read_text() == 'xx' and out.score == 1.0, out.metadata


def test_gated_learner_learns_a_browser_procedure_from_the_teacher(tmp_path):
    """A4mG on web_invoice: the student sums only the visible rows unless a remembered demonstration
    shows the "Show more rows" step; the teacher (oracle, cloud browser chain) demonstrates it once."""
    from core.evolution.mutator import bundle_digest
    from core.evolution.relevance import RELEVANCE_MIN, InstructionSpace, SkillSources
    tasks = [t for t in (make_task('web_invoice', s) for s in range(1000, 1100))
             if len(t['fixture']['rows']) > t['fixture']['visible_rows']][:2]
    by_instruction = {t['instruction']: t for t in tasks}

    def task_of(messages):
        text = '\n'.join(str(m.get('content') or '') for m in messages)
        return next(t for i, t in by_instruction.items() if i in text), text

    class Student(ModelProvider):
        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            task, text = task_of(messages)
            current = text[text.rfind(task['instruction']):]          # this task, after any remembered demo
            learned = '"target": "Show more rows"' in text[:text.rfind(task['instruction'])]
            fx, done = task['fixture'], current.count('"acted"')
            steps = ([('click', 'Show more rows', None)] if learned else []) + [
                ('fill', fx['fields'][0]['label'], str(task['scoring_criteria']['expected']['record']['total'])
                 if learned else '1'), ('click', fx['submit'], None)]
            if done >= len(steps):
                return ModelResponse(text='Saved.', usage=USAGE)
            op, label, value = steps[done]
            obs, refs, _ = _latest([{'content': current}])
            args = {'observation_id': obs, 'operation': op, 'target_ref': refs[label], **({'value': value} if value else {})}
            return ModelResponse(text='', tool_calls=[{'name': 'browser_act', 'arguments': args}], usage=USAGE)

    class Teacher(ModelProvider):
        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            task, text = task_of(messages)
            oracle = Oracle(task)
            oracle.done = text.count('"acted"')
            return oracle.generate(messages, tools, max_tokens, temperature)

    big = BudgetConfig(max_api_calls=10_000, max_input_tokens_total=10**8, max_output_tokens_total=10**7)
    sources = SkillSources(tmp_path / 'L' / 'skill_sources.json', InstructionSpace(tmp_path / 'L' / 'space.json'))
    memory = MemoryStore(tmp_path / 'L' / 'memory.jsonl', min_jaccard=RELEVANCE_MIN, similarity=sources.space.similarity)
    student = chain_runner(Journal(tmp_path / 's.sqlite'), BudgetTracker(big, tmp_path / 'sb.sqlite'), tmp_path / 'ws',
                           lambda run_id: Student(), memory=memory, mode='memory', gate=sources)
    teacher_run = chain_runner(Journal(tmp_path / 't.sqlite'), BudgetTracker(big, tmp_path / 'tb.sqlite'), tmp_path / 'tws',
                               lambda run_id: Teacher(), cloud=True)
    boot = tmp_path / 'boot'
    boot.mkdir()
    (boot / 'manifest.json').write_text('{"version":1,"skills":[]}')
    bootstrap = Candidate('no-skills', (), 'skill', str(boot), bundle_digest(boot))
    teacher = TeacherCache(tmp_path / 'cache', lambda task: teacher_run(bootstrap, task, 'teacher-' + task['task_id']))
    learner = StreamLearner(tmp_path / 'L', 'A4mG', bootstrap=bootstrap, run_student=student, teacher=teacher,
                            propose_skill=lambda *a, **k: (_ for _ in ()).throw(AssertionError('no file skills')),
                            memory=memory, skill_sources=sources)
    first = learner.step(tasks[0])
    assert first['student_score'] == 0.0 and first['teacher_score'] == 1.0, first
    assert first['learning'].get('memory_stored') is True, first['learning']
    second = learner.step(tasks[1])
    assert second['solved_by_student'] and not second['helped'], second


def test_hidden_content_is_absent_until_revealed(tmp_path):
    """v16: a page rule (label{display:block}) overrode [hidden], so step-2 form fields were visible."""
    import asyncio
    from playwright.async_api import async_playwright
    from core.computer_use.browser import BrowserAdapter
    from core.computer_use.task_environment import browser_task_server
    form = next(t for t in (make_task('web_form', s) for s in range(1000, 1050))
                if any(f.get('step') == 2 for f in t['fixture']['fields']))
    later = {f['label'] for f in form['fixture']['fields'] if f.get('step') == 2}

    async def labels_before_and_after():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            with browser_task_server(form['fixture'], tmp_path) as (url, _):
                page = await (await browser.new_context()).new_page()
                await page.goto(url)
                adapter = BrowserAdapter(page)
                before = {t['label'] for t in (await adapter.observe())['targets']}
                nxt = next(t['target_ref'] for t in adapter.current['targets'] if t['label'] == 'Next')
                after = await adapter.act(adapter.current['observation_id'], 'click', nxt)
            await browser.close()
            return before, {t['label'] for t in after['observation']['targets']}
    before, after = asyncio.run(labels_before_and_after())
    assert not later & before and later <= after
