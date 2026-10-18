"""R1: deterministic leak screening of learned lessons and guidance-free training samples."""
import pytest

from core.evolution.leakage import guidance_free, instance_values, leaks, screen_lessons
from core.evolution.stream_tasks import make_task
from core.model_provider import ModelProvider, ModelResponse

USAGE = {'input_tokens': 10, 'output_tokens': 5}
CLEAN = {'scope': 'task', 'when': 'a table hides rows',
         'do': 'click Show more rows before computing the total', 'avoid': ''}


@pytest.mark.parametrize('family', ['web_invoice', 'web_catalog', 'web_form', 'web_prefs'])
@pytest.mark.parametrize('seed', [1000, 1003, 1007])
def test_browser_instance_values_and_generic_labels(family, seed):
    task = make_task(family, seed)
    values = instance_values(task)
    fixture = task['fixture']
    record = task['scoring_criteria']['expected']['record']
    if family == 'web_invoice':
        assert str(record['total']) in values
        assert fixture['fields'][0]['label'] not in values
    elif family == 'web_catalog':
        chosen = next(item for item in fixture['items'] if item['id'] == record['property_id'])
        assert chosen['name'] in values and record['city'] in values
        assert fixture['category_label'] not in values and fixture['apply_label'] not in values
    elif family == 'web_form':
        assert set(record.values()) <= values
        notes = [line.split(': ', 1)[1] for line in fixture['note'][1:] if ': ' in line]
        assert notes and set(notes) <= values
        assert fixture['submit'] not in values
    else:
        assert 'True' not in values and 'False' not in values
        assert fixture['submit'] not in values


@pytest.mark.parametrize('family', ['web_invoice', 'web_catalog', 'web_form', 'web_prefs'])
@pytest.mark.parametrize('seed', [1000, 1003, 1007])
def test_browser_keeps_generic_lesson(family, seed):
    kept, rejected = screen_lessons([dict(CLEAN)], make_task(family, seed))
    assert kept == [dict(CLEAN)] and rejected == []


@pytest.mark.parametrize('seed', [1000, 1003, 1007])
def test_invoice_lesson_naming_the_real_total_is_rejected(seed):
    task = make_task('web_invoice', seed)
    total = task['scoring_criteria']['expected']['record']['total']
    kept, rejected = screen_lessons(
        [dict(CLEAN), {'scope': 'task', 'when': '', 'do': f'enter {total} in Total', 'avoid': ''}], task)
    assert kept == [dict(CLEAN)]
    assert len(rejected) == 1 and str(total) in rejected[0]['leaked']


@pytest.mark.parametrize('seed', [1000, 1003, 1007])
def test_catalog_lesson_naming_the_chosen_hotel_is_rejected(seed):
    task = make_task('web_catalog', seed)
    record = task['scoring_criteria']['expected']['record']
    chosen = next(item for item in task['fixture']['items'] if item['id'] == record['property_id'])
    kept, rejected = screen_lessons(
        [dict(CLEAN), {'scope': 'task', 'when': '', 'do': f'choose {chosen["name"]}', 'avoid': ''}], task)
    assert kept == [dict(CLEAN)]
    assert len(rejected) == 1 and chosen['name'] in rejected[0]['leaked']


def test_file_function_file_and_cases_are_instance_values_and_screen_lessons():
    task = make_task('log_aggregation', 1000)
    criteria = task['scoring_criteria']
    values = instance_values(task)
    assert {criteria['function'], criteria['file']} <= values

    clean = {'scope': 'task', 'when': 'log lines vary in case',
             'do': 'skip malformed lines and upper-case the level', 'avoid': ''}
    leaking = {'scope': 'task', 'when': '', 'do': f'implement {criteria["function"]} in {criteria["file"]}',
               'avoid': ''}
    kept, rejected = screen_lessons([clean, leaking], task)
    assert kept == [clean]
    assert len(rejected) == 1 and criteria['function'] in rejected[0]['leaked']


def test_file_cases_recurse_and_skip_generic_words_and_small_values():
    task = {'instruction': 'Do it.', 'scoring_criteria': {
        'type': 'python_function', 'file': 'a.py', 'function': 'fn',
        'cases': [{'args': [[{'id': 'alpha', 'n': 12, 'flag': True, 'note': '2026-10-01 INFO'}]],
                   'expected': {'beta': 3}}]}}
    values = instance_values(task)
    assert {'fn', 'a.py', '12', '2026-10-01 INFO'} <= values
    assert 'alpha' not in values and 'beta' not in values
    assert '3' not in values and 'True' not in values


@pytest.mark.parametrize('seed', range(1000, 1010))
def test_file_screen_keeps_a_generic_lesson_and_rejects_one_naming_the_function(seed):
    task = make_task('log_aggregation', seed)
    function = task['scoring_criteria']['function']
    clean = {'scope': 'task', 'when': 'log levels vary in case',
             'do': 'upper-case the level name, e.g. ERROR, and skip malformed lines', 'avoid': ''}
    leaking = {'scope': 'task', 'when': '', 'do': f'write {function} to handle the log lines', 'avoid': ''}
    kept, rejected = screen_lessons([clean, leaking], task)
    assert kept == [clean]
    assert len(rejected) == 1 and function in rejected[0]['leaked']


def test_numeric_leaks_respect_number_boundaries_and_thousands_separators():
    task = {'instruction': 'Enter 12 for the count and 1143 for the total.',
            'fixture': {'kind': 'invoice', 'fields': [], 'rows': [], 'note': []},
            'scoring_criteria': {'type': 'json_exact_match', 'expected': {'record': {'total': 1143}}}}
    assert leaks('the year 2012', task) == []           # 12 is not a token inside 2012
    assert leaks('enter 12 now', task) == ['12']
    assert leaks('the total is 1,143', task) == ['1143']


def test_guidance_free_rejects_a_sample_that_still_contains_the_lesson():
    guidance = ['lessons from earlier tasks:\n- click Show more rows before computing the total']
    contaminated = [{'role': 'system',
                     'content': 'Lessons from earlier tasks:\n- click   Show more\nrows before computing the total'},
                    {'role': 'user', 'content': 'Compute the invoice total.'}]
    assert guidance_free(contaminated, guidance) is False

    clean = [{'role': 'system', 'content': 'You are a browser agent.'},
             {'role': 'user', 'content': 'Compute the invoice total.'}]
    assert guidance_free(clean, guidance) is True


def test_learner_stores_only_clean_lessons_and_records_rejections(tmp_path):
    pytest.importorskip('playwright.async_api')
    from core.evolution.playbook import Playbook
    from test_stream_lessons import LESSON, hidden_row_invoices, make_world

    class Idle(ModelProvider):
        def __init__(self, task_of):
            self.task_of = task_of

        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            return ModelResponse(text='I looked at the page.', usage=USAGE)

    def extractor(task, demo, student):
        total = task['scoring_criteria']['expected']['record']['total']
        return [dict(LESSON),
                {'when': 'the invoice total is needed', 'do': f'enter {total} as the total', 'avoid': ''}]

    tasks = hidden_row_invoices()
    learner, _ = make_world(tmp_path, Idle, extractor, tasks)
    row = learner.step(tasks[0])
    total = str(tasks[0]['scoring_criteria']['expected']['record']['total'])
    assert row['learning']['lessons'] == {'n': 1, 'rejected': 1, 'rejected_values': [total],
                                           'outcomes': ['added']}, row['learning']
    assert row['learning']['accepted'] is True
    saved = Playbook(tmp_path / 'L' / 'playbook.json').entries
    assert [entry['do'] for entry in saved] == [LESSON['do']]
