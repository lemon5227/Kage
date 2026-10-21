"""R2: guided fresh execution on practice tasks, then guidance-free SFT rows.

Scripted models and synthetic traces except for the end-to-end test, which runs the real chain
(including headless Chromium) with a scripted student. No network and no cloud teacher.
"""
import argparse
import json
from pathlib import Path
import re

import pytest

from core.evolution.agent_provider import KageChainProvider
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.leakage import guidance_free
from core.evolution.playbook import Playbook
from core.evolution.stream import chain_runner
from core.evolution.stream_tasks import make_task
from core.model_provider import ModelProvider, ModelResponse, OpenAICompatibleProvider
from scripts.experiments import rsr_collect

USAGE = {'input_tokens': 10, 'output_tokens': 5}
TIMESTAMP = re.compile(r'当前时间: [^\n]*')


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))


def _trace(path: Path, rows: list[dict]) -> None:
    _jsonl(path, rows)


@pytest.mark.parametrize('temperature,expected', [(None, 0), (0.6, 0.6)])
def test_recorded_local_provider_sends_the_requested_temperature(tmp_path, monkeypatch, temperature, expected):
    from scripts.experiments.task_suite import RecordedLocalProvider

    seen = []

    def fake_generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        seen.append(temperature)
        return ModelResponse(text='ok', usage=USAGE)

    monkeypatch.setattr(OpenAICompatibleProvider, 'generate', fake_generate)
    kwargs = {} if temperature is None else {'temperature': temperature}
    provider = RecordedLocalProvider(tmp_path / 'trace.jsonl', api_key='local',
                                     model_name='m', base_url='http://127.0.0.1:1/v1', **kwargs)
    provider.generate([{'role': 'user', 'content': 'hi'}])
    assert seen == [expected]


def test_collect_refuses_transfer_families_and_eval_seeds(tmp_path):
    parser = rsr_collect.build_parser()
    for family in ('web_form', 'text_normalize', 'config_migrate'):
        args = parser.parse_args(['collect', '--root', str(tmp_path), '--families', family,
                                  '--guidance', 'demo', '--memory', str(tmp_path / 'm.jsonl')])
        with pytest.raises(SystemExit):
            rsr_collect.validate_collect(parser, args)

    allowed = parser.parse_args(['collect', '--root', str(tmp_path), '--families', 'log_aggregation,web_invoice',
                                 '--seeds', '0', '--guidance', 'demo', '--memory', str(tmp_path / 'm.jsonl')])
    with pytest.raises(SystemExit):
        rsr_collect.validate_collect(parser, allowed)          # --seeds must stay positive

    args = parser.parse_args(['collect', '--root', str(tmp_path), '--families', 'log_aggregation,web_invoice',
                              '--guidance', 'demo', '--memory', str(tmp_path / 'm.jsonl')])
    rsr_collect.validate_collect(parser, args)
    with pytest.raises(AssertionError):
        rsr_collect.practice_task('log_aggregation', 9000)     # eval split

    assert rsr_collect.practice_seeds(2) == [13000, 13001]


def test_build_strips_demo_history_and_lessons_and_counts_unremovable_guidance(tmp_path):
    family, seed = 'log_aggregation', 13000
    task = make_task(family, seed)
    demo_rows = [{'action': {'name': 'read_file', 'arguments': {'path': 'input.log'}},
                  'observation': {'success': True,
                                  'content': '2026-10-01 ERROR auth: failed to connect'}}]
    lesson = {'id': 'L1', 'scope': 'task', 'when': 'log lines vary in case',
              'do': 'upper-case the level before counting', 'avoid': '',
              'triggers': [task['instruction']]}
    _jsonl(tmp_path / 'guidance' / 'memory.jsonl',
           [{'instruction': task['instruction'], 'rows': demo_rows}])
    (tmp_path / 'guidance' / 'playbook.json').write_text(json.dumps({'entries': [lesson]}))

    demo_messages = KageChainProvider._history_messages(task, demo_rows)
    rendered = Playbook.render([lesson])
    system = {'role': 'system', 'content': 'frozen soul\n' + rendered}
    user = {'role': 'user', 'content': 'Work on ' + task['instruction']}
    target = {'role': 'assistant', 'content': '',
              'tool_calls': [{'name': 'write_file', 'arguments': {'path': 'counts.json', 'content': '{}'}}]}
    request = {'tools': [{'type': 'function', 'function': {'name': 'write_file'}}],
               'max_tokens': 1024, 'temperature': 0.6}

    _trace(tmp_path / 'traces' / 'clean.jsonl',
           [{'messages': [system, *demo_messages, user], 'request': request,
             'response': {**target, 'tool_calls': target['tool_calls']}}])
    # The demonstration line survives with different spacing, so exact block removal leaves it:
    # guidance_free must still catch it and drop the sample.
    altered = {'role': 'assistant', 'content': demo_messages[0]['content'].replace('] ', ']  ', 1)}
    _trace(tmp_path / 'traces' / 'contaminated.jsonl',
           [{'messages': [system, altered, demo_messages[1], user], 'request': request,
             'response': {'text': 'done', 'tool_calls': []}}])

    def attempt(index, score, path):
        return {'run_id': f'rsr-{task["task_id"]}-a{index}', 'task_id': task['task_id'],
                'family': family, 'seed': seed, 'attempt': index,
                'guidance': ['demo', 'lessons'], 'demo_index': 0, 'demo_instruction': task['instruction'],
                'lesson_ids': ['L1'], 'score': score, 'status': 'passed' if score >= 1 else 'failed',
                'writes': True, 'negative': False, 'trace': str(tmp_path / 'traces' / path)}
    _jsonl(tmp_path / 'attempts.jsonl',
           [attempt(0, 1.0, 'clean.jsonl'), attempt(1, 1.0, 'contaminated.jsonl'),
            attempt(2, 0.0, 'never-read.jsonl')])

    report = rsr_collect.build(argparse.Namespace(root=tmp_path, cap=400))
    samples = [json.loads(line) for line in (tmp_path / 'sft.jsonl').read_text().splitlines()]

    assert len(samples) == 1
    sample = samples[0]
    assert sample['source'] == 'rsr' and sample['attempt'] == 0
    assert sample['guidance'] == ['demo', 'lessons'] and sample['negative'] is False and sample['writes'] is True
    assert sample['messages'] == [{'role': 'system', 'content': 'frozen soul'}, user]
    assert guidance_free(sample['messages'], [rendered] + [m['content'] for m in demo_messages])
    assert sample['target'] == {'role': 'assistant', 'content': '', 'tool_calls': [
        {'type': 'function', 'function': {'name': 'write_file',
                                          'arguments': {'path': 'counts.json', 'content': '{}'}}}]}

    stats = json.loads((tmp_path / 'stats.json').read_text())
    state = stats['families'][family]
    assert state == {'tasks': 1, 'attempts': 3, 'successes': 2, 'yield': round(2 / 3, 4),
                     'samples_kept': 1,
                     'dropped': {'guidance_not_removed': 1, 'duplicate': 0, 'cap': 0, 'no_trace': 0}}


@pytest.mark.parametrize('family', ['log_aggregation'])
def test_build_skips_a_success_without_a_trace(tmp_path, family):
    task = make_task(family, 13000)
    _jsonl(tmp_path / 'attempts.jsonl', [
        {'run_id': 'x', 'task_id': task['task_id'], 'family': family, 'seed': 13000, 'attempt': 0,
         'guidance': ['demo'], 'demo_index': None, 'demo_instruction': '', 'lesson_ids': [],
         'score': 1.0, 'status': 'passed', 'writes': True, 'negative': False,
         'trace': str(tmp_path / 'traces' / 'missing.jsonl')}])
    report = rsr_collect.build(argparse.Namespace(root=tmp_path, cap=400))
    assert report['totals']['samples_kept'] == 0
    assert report['totals']['dropped']['no_trace'] == 1


# ---------------------------------------------------------------- end to end, real chain
pytest.importorskip('playwright.async_api')
from test_stream_browser import _latest, plan  # noqa: E402


class Tracing(ModelProvider):
    """Scripted student plus the same trace row RecordedLocalProvider writes."""

    def __init__(self, path: Path, inner: ModelProvider):
        self.path, self.inner = path, inner

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        response = self.inner.generate(messages=messages, tools=tools, max_tokens=max_tokens)
        with self.path.open('a') as out:
            out.write(json.dumps({'messages': messages,
                                  'request': {'tools': tools, 'max_tokens': max_tokens},
                                  'response': {'text': response.text,
                                               'tool_calls': response.tool_calls}}, ensure_ascii=False) + '\n')
        return response


class DemoStudent(ModelProvider):
    """Solves invoice tasks with the hidden total only when a demonstration is in context."""

    def __init__(self, task):
        self.task, self.first = task, None

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        if self.first is None:
            self.first = messages
        text = '\n'.join(str(m.get('content') or '') for m in messages)
        mark = text.rfind(self.task['instruction'])
        learned = '"target": "Show more rows"' in text[:mark]
        current = text[mark:]
        fixture = self.task['fixture']
        steps = []
        if learned and len(fixture['rows']) > fixture['visible_rows']:
            steps.append(('click', 'Show more rows', None))
        total = self.task['scoring_criteria']['expected']['record']['total']
        steps.append(('fill', fixture['fields'][0]['label'], str(total) if learned else '1'))
        steps.append(('click', fixture['submit'], None))
        done = current.count('"acted"')
        if done >= len(steps):
            return ModelResponse(text='Saved.', usage=USAGE)
        operation, label, value = steps[done]
        obs, refs, _ = _latest([{'content': current}])
        args = {'observation_id': obs, 'operation': operation, 'target_ref': refs[label]}
        if value is not None:
            args['value'] = value
        return ModelResponse(text='', tool_calls=[{'name': 'browser_act', 'arguments': args}], usage=USAGE)


def _demo_rows(task):
    """Label-level memory rows, exactly the shape ``stream._browser_rows`` stores."""
    rows = []
    for operation, label, value in plan(task):
        arguments = {'operation': operation, 'target': label}
        if value is not None:
            arguments['value'] = value
        rows.append({'action': {'name': 'browser_act', 'arguments': arguments},
                     'observation': {'success': True,
                                     'content': 'done (earlier page: pick the target_ref with this label '
                                                'from the current observation)'}})
    return rows


VOLATILE = {'observation_id', 'surface_id', 'revision', 'document_id', 'url'}


def _scrub(value):
    if isinstance(value, dict):
        return {key: ('<volatile>' if key in VOLATILE else _scrub(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        return re.sub(r'127\.0\.0\.1:\d+', '127.0.0.1:<port>', value)
    return value


def _normalized(messages):
    marker = '\nInitial browser observation supplied by runtime:\n'
    out = []
    for message in messages:
        message = dict(message)
        content = TIMESTAMP.sub('当前时间: <now>', str(message.get('content') or ''))
        head, sep, tail = content.partition(marker)
        if sep:
            content = head + sep + json.dumps(_scrub(json.loads(tail)), sort_keys=True)
        message['content'] = content
        out.append(message)
    return out


def test_collect_and_build_end_to_end_on_a_real_browser_task(tmp_path):
    pytest.importorskip('playwright.async_api')
    target = next(task for task in (make_task('web_invoice', seed) for seed in range(13000, 13100))
                  if 0 < len(task['fixture']['rows']) - task['fixture']['visible_rows'] <= 3)
    assert target['split'] == 'practice'
    demo = make_task('web_invoice', 1000)
    memory_file = tmp_path / 'demo-memory.jsonl'
    _jsonl(memory_file, [{'instruction': demo['instruction'], 'rows': _demo_rows(demo)}])

    seeds = int(target['task_id'].rsplit('-', 1)[1]) - 13000 + 1
    root = tmp_path / 'rsr'
    root.mkdir()

    def factory(run_id):
        task_id = run_id.rsplit('-a', 1)[0].removeprefix('rsr-')
        task = make_task('web_invoice', int(task_id.rsplit('-', 1)[1]))
        return Tracing(root / 'traces' / f'{run_id}.jsonl', DemoStudent(task))

    args = argparse.Namespace(root=root, families='web_invoice', seeds=seeds, k=2, temperature=0.6,
                              guidance='demo', memory=[str(memory_file)], playbook=[], negatives=0,
                              run_suffix='', port=18082)
    rsr_collect.collect_tasks(args, factory)

    attempts = [json.loads(line) for line in (root / 'attempts.jsonl').read_text().splitlines()]
    target_attempts = [row for row in attempts if row['task_id'] == target['task_id']]
    assert len(target_attempts) == 2
    assert all(row['score'] == 1.0 and row['status'] == 'passed' for row in target_attempts), target_attempts
    assert all(row['guidance'] == ['demo'] and row['demo_index'] == 0 for row in target_attempts)
    assert all(Path(row['trace']).exists() for row in target_attempts)

    report = rsr_collect.build(argparse.Namespace(root=root, cap=400))
    samples = [json.loads(line) for line in (root / 'sft.jsonl').read_text().splitlines()]
    assert report['families']['web_invoice']['tasks'] == seeds
    assert report['families']['web_invoice']['attempts'] == len(attempts)
    assert report['families']['web_invoice']['successes'] == sum(row['score'] >= 1.0 for row in attempts)

    target_samples = [row for row in samples if row['task_id'] == target['task_id']]
    assert target_samples, report
    sample = min(target_samples, key=lambda row: row['attempt'])
    assert sample['attempt'] == 0 and sample['guidance'] == ['demo']

    # Reference A0 request: same task, same chain settings, no gathered guidance. The chain runs
    # in a forked worker, so the first request is captured through a file, not an object.
    first_path = tmp_path / 'a0-first.json'

    class FirstCall(DemoStudent):
        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            if not first_path.exists():
                first_path.write_text(json.dumps(messages, ensure_ascii=False, default=str))
            return super().generate(messages, tools, max_tokens, temperature)

    plain = chain_runner(Journal(tmp_path / 'a0.sqlite'),
                         BudgetTracker(BudgetConfig(max_api_calls=50), tmp_path / 'a0-budget.sqlite'),
                         tmp_path / 'a0-ws', lambda run_id: FirstCall(target),
                         tool_max_tokens=1024, max_steps=5, max_tool_actions=12)
    plain(Candidate('bootstrap', (), 'workflow', '.', 'x'), target, 'a0-reference')
    assert _normalized(sample['messages']) == _normalized(json.loads(first_path.read_text()))

    target_trace = [json.loads(line) for line in
                    Path(target_attempts[0]['trace']).read_text().splitlines()]
    first_action = target_trace[0]['response']['tool_calls'][0]['arguments']
    assert first_action['operation'] == 'click' and first_action['target_ref']
    assert sample['target']['tool_calls'][0]['function']['name'] == 'browser_act'


def test_none_guidance_is_the_unguided_control():
    """v20 follow-up: the control runs the same practice tasks without guidance (no --memory needed)."""
    import argparse
    import rsr_collect
    assert rsr_collect.guidance_kinds('none') == []
    parser = rsr_collect.build_parser()
    args = parser.parse_args(['collect', '--root', '/tmp/x', '--families', 'web_invoice', '--guidance', 'none'])
    rsr_collect.validate_collect(parser, args)          # no memory/playbook required
