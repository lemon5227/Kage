import asyncio
import datetime
import json

from core.evolution.competence import CompetenceModel
from core.evolution.notices import (DAILY_OPTIONAL_CAP, NoticeSource, NoticeStore, adoption_confirm,
                                    help_request, learning_report, record_reply)

NOW = datetime.datetime(2026, 10, 14, 21, 0)


def test_help_request_numbers_come_from_competence():
    comp = CompetenceModel()
    for ok in (True, False, False):
        comp.record_task('log_aggregation', ok)
    n = help_request(comp, 'log_aggregation', now=NOW)
    assert n['kind'] == 'help_request' and n['needs_reply'] is True
    assert n['evidence'] == {'family': 'log_aggregation', 'successes': 1, 'attempts': 3,
                             'p_success': round(comp.family('log_aggregation').p_success, 4)}
    assert '3 次' in n['body'] and '1 次' in n['body'] and len(n['title']) <= 40 and len(n['body']) <= 300
    assert help_request(CompetenceModel(), 'never_seen', now=NOW) is None


def test_learning_report_and_adoption_confirm():
    round_row = {'label': 'r1', 'tasks': 6, 'passed': 4,
                 'families': {'log_aggregation': {'tasks': 6, 'passed': 4, 'p_before': 0.4, 'p_after': 0.55}}}
    r = learning_report(round_row, accepted_skills=['count_log_lines'], now=NOW)
    assert r['needs_reply'] is False and '练了 6 题、对 4 题' in r['body'] and 'count_log_lines' in r['body']
    assert r['evidence']['passed'] == 4
    assert learning_report({'tasks': 0}, now=NOW) is None
    a = adoption_confirm('count_log_lines', 'Count log lines.', writes_files=True,
                         validation={'passed': 3, 'total': 3}, now=NOW)
    assert a['needs_reply'] is True and '3/3' in a['body']
    assert adoption_confirm('x', 'read only', writes_files=False, validation={}, now=NOW) is None


def test_daily_cap_applies_only_to_optional_notices(tmp_path):
    store = NoticeStore(tmp_path / 'notices.jsonl')
    row = {'tasks': 1, 'passed': 1, 'families': {}}
    added = [store.add(learning_report(row, now=NOW)) for _ in range(DAILY_OPTIONAL_CAP + 2)]
    assert added.count(True) == DAILY_OPTIONAL_CAP
    comp = CompetenceModel()
    comp.record_task('f', False)
    assert store.add(help_request(comp, 'f', now=NOW)) is True          # needs a reply: not capped
    assert store.add(learning_report(row, now=NOW + datetime.timedelta(days=1))) is True
    assert store.add(None) is False


def test_source_delivers_each_notice_once_with_reply_action(tmp_path):
    store = NoticeStore(tmp_path / 'notices.jsonl')
    comp = CompetenceModel()
    comp.record_task('f', False)
    store.add(help_request(comp, 'f', now=NOW))
    store.add(learning_report({'tasks': 2, 'passed': 1, 'families': {}}, now=NOW))
    source = NoticeSource(store)
    first = asyncio.run(source.collect(NOW))
    assert [n['type'] for n in first] == ['help_request', 'learning_report']
    assert first[0]['source'] == 'evolution:help_request' and first[0]['action']['type'] == 'notice_reply'
    assert 'action' not in first[1]
    assert asyncio.run(source.collect(NOW)) == []
    reply = record_reply(tmp_path / 'notice_replies.jsonl', first[0]['action'], now=NOW)
    assert reply['kind'] == 'help_request'
    assert json.loads((tmp_path / 'notice_replies.jsonl').read_text())['notice_id'] == first[0]['action']['notice_id']
