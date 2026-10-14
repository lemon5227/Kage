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


def test_mutator_requests_lessons_only_when_enabled_and_saves_them(tmp_path):
    import json
    from core.evolution.budget import BudgetConfig, BudgetTracker
    from core.evolution.contracts import Candidate
    from core.evolution.journal import Journal
    from core.evolution.mutator import Mutator, bundle_digest
    from core.model_provider import ModelProvider, ModelResponse

    seen = []

    class Optimizer(ModelProvider):
        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            seen.append(messages[0]['content'])
            return ModelResponse(text=json.dumps({
                'hypothesis': 'h', 'skill_id': 'noop', 'description': 'Use this when testing.',
                'parameters': {'type': 'object', 'properties': {}},
                'code': 'def run(arguments, context):\n    return {"success": True}\n',
                'lessons': [{'scope': 'general', 'when': '', 'do': 'read the file first', 'avoid': ''}]}),
                usage={'input_tokens': 10, 'output_tokens': 10})

    boot = tmp_path / 'boot'
    boot.mkdir()
    (boot / 'manifest.json').write_text('{"version":1,"skills":[]}')
    parent = Candidate('p', (), 'skill', str(boot), bundle_digest(boot))
    feedback = {'task_id': 't', 'instruction': 'x', 'failure_reason': 'y', 'trace': []}
    for enabled in (False, True):
        root = tmp_path / f'm-{enabled}'
        Mutator(Optimizer(), BudgetTracker(BudgetConfig(max_api_calls=10), tmp_path / f'b{enabled}.sqlite'),
                Journal(tmp_path / 'j.sqlite'), root, request_lessons=enabled).propose(parent, feedback)
        assert (root / 'lessons.json').exists() is enabled
    assert 'lessons' not in seen[0] and 'lessons' in seen[1]
    saved = json.loads((tmp_path / 'm-True' / 'lessons.json').read_text())
    assert parse_lessons(saved)[0]['do'] == 'read the file first'


def test_chain_runner_injects_selected_lessons_into_system_prompt(tmp_path):
    from core.evolution.budget import BudgetConfig, BudgetTracker
    from core.evolution.contracts import Candidate
    from core.evolution.journal import Journal
    from core.evolution.mutator import bundle_digest
    from core.evolution.sandbox import ProcessSkillRunner
    from core.evolution.stream import chain_runner
    from core.evolution.stream_tasks import make_task
    from core.model_provider import ModelProvider, ModelResponse

    log = tmp_path / 'system.txt'

    class Recorder(ModelProvider):
        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            log.write_text(messages[0]['content'])
            return ModelResponse(text='Done.', usage={'input_tokens': 1, 'output_tokens': 1})

    pb = Playbook(tmp_path / 'playbook.json')
    pb.add([{'scope': 'general', 'when': '', 'do': 'read the target file before writing', 'avoid': ''}], source_task='g')
    boot = tmp_path / 'boot'
    boot.mkdir()
    (boot / 'manifest.json').write_text('{"version":1,"skills":[]}')
    bootstrap = Candidate('no-skills', (), 'skill', str(boot), bundle_digest(boot))
    for book, expected in ((None, False), (pb, True)):
        run = chain_runner(Journal(tmp_path / 'j.sqlite'), BudgetTracker(BudgetConfig(max_api_calls=100), tmp_path / 'b.sqlite'),
                           tmp_path / 'ws', lambda run_id: Recorder(), skill_runner=ProcessSkillRunner(timeout_s=10),
                           playbook=book)
        run(bootstrap, make_task('log_aggregation', 1000 + int(expected)), f'run-{expected}')
        assert ('read the target file before writing' in log.read_text()) is expected
    assert Playbook(tmp_path / 'playbook.json').entries[0]['injected'] == 1
