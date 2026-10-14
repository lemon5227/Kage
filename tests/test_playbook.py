from core.evolution.playbook import GENERAL_CAP, Playbook, parse_lessons


def test_parse_tolerates_missing_and_truncates():
    assert parse_lessons({'skill_id': 'x'}) == []
    assert parse_lessons({'lessons': 'nope'}) == []
    many = [{'scope': 'task', 'when': 'w', 'do': 'd' * 500, 'avoid': ''} for _ in range(5)]
    out = parse_lessons({'lessons': many + [{'scope': 'bogus', 'do': 'x'}]})
    assert len(out) == 3 and all(len(l['do']) == 200 for l in out)
    assert parse_lessons({'lessons': [{'scope': 'general', 'when': 'only when'}]}) == []   # no do/avoid


def test_merge_similar_add_different_and_general_cap(tmp_path):
    pb = Playbook(tmp_path / 'playbook.json')
    first = {'scope': 'task', 'when': 'aggregating log lines', 'do': 'skip malformed log lines before counting',
             'avoid': 'crashing on short lines'}
    similar = {'scope': 'task', 'when': 'aggregating log lines', 'do': 'skip malformed log lines before counting levels',
               'avoid': 'crashing on short lines'}
    other = {'scope': 'task', 'when': 'merging intervals', 'do': 'sort intervals by start first', 'avoid': ''}
    assert pb.add([first], source_task='t1', trigger='log lines level count') == ['added']
    assert pb.add([similar, other], source_task='t2', trigger='intervals merge') == ['merged', 'added']
    assert len(pb.entries) == 2 and pb.entries[0]['count'] == 2 and pb.entries[0]['do'].endswith('levels')
    generals = [{'scope': 'general', 'when': '', 'do': f'unique rule number{i} alpha{i} beta{i}', 'avoid': ''}
                for i in range(GENERAL_CAP + 2)]
    outcomes = pb.add(generals, source_task='t3')
    assert outcomes.count('added') == GENERAL_CAP and outcomes.count('dropped') == 2
    pb.save()
    assert len(Playbook(tmp_path / 'playbook.json').entries) == 2 + GENERAL_CAP


def test_injection_general_always_task_only_when_relevant(tmp_path):
    pb = Playbook(tmp_path / 'playbook.json')
    pb.add([{'scope': 'general', 'when': '', 'do': 'read the target file before writing', 'avoid': ''}], source_task='g')
    pb.add([{'scope': 'task', 'when': 'aggregating log lines', 'do': 'upper-case levels', 'avoid': ''}],
           source_task='t', trigger='log lines level service count')
    unrelated = Playbook.render(pb.select('Merge the overlapping intervals in ranges.py'))
    related = Playbook.render(pb.select('Count log lines per level in report.py'))
    assert 'read the target file' in unrelated and 'upper-case levels' not in unrelated
    assert 'read the target file' in related and 'upper-case levels' in related
    used = pb.select('Count log lines per level')
    pb.record_use(used, success=True)
    assert all(e['injected'] == 1 and e['injected_success'] == 1 for e in pb.entries)
