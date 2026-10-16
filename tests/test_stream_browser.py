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
        steps = [('fill', f['label'], want[f['name']]) for f in fx['fields'] if 'initial' not in f]
    elif fx['kind'] == 'invoice':
        steps = [('fill', fx['fields'][0]['label'], str(want['total']))]
    elif fx['kind'] == 'preferences':
        steps = [('click', f['label'], None) for f in fx['fields'] if want[f['name']] != f['initial']]
    else:
        item = next(i for i in fx['items'] if i['id'] == want['property_id'])
        return [('fill', fx['query_label'], want['city']), ('click', fx['category_label'], None),
                ('click', fx['apply_label'], None), ('click', f"Choose {item['name']}", None)]
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
        assert len(plan(a)) <= 4, (family, seed)          # 5 loop steps, one page action each
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
