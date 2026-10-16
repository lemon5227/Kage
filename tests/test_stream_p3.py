"""P3 (E-2): relevance gate, agent-side clusters, gated proactive help, background evolution, L2 selection."""
import json
from pathlib import Path

from core.evolution.contracts import Candidate, RunResult
from core.evolution.relevance import FIXED_SELECT, InstructionSpace, SkillSources, TaskClusters, run_select
from core.evolution.skills import SkillCatalog
from core.evolution.stream import MemoryStore, StreamLearner, TeacherCache
from core.evolution.stream_tasks import FAMILIES, NEGATIVE_FAMILIES, make_task

CAPABILITY = sorted(f for f in FAMILIES if f not in NEGATIVE_FAMILIES)
from core.evolution.relevance import RELEVANCE_MIN


def result(tmp, run_id, score, rows):
    path = Path(tmp) / f'{run_id}.jsonl'
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    return RunResult(run_id, 'passed' if score >= 1 else 'failed', score, str(path),
                     metadata={'chain': [{'stop_reason': 'model_returned'}]})


WRITE = {'action': {'name': 'write_file', 'arguments': {}}, 'observation': {'success': True}}
READ = {'action': {'name': 'read_file', 'arguments': {}}, 'observation': {'success': True}}


def bundle(root: Path, families: list[str]) -> Candidate:
    """A real manifest whose skill ids are family names (fake code; the fake student never runs it)."""
    d = root / ('lib-' + '-'.join(families) if families else 'lib-empty')
    d.mkdir(parents=True, exist_ok=True)
    (d / 'manifest.json').write_text(json.dumps({'version': 1, 'skills': [
        {'skill_id': f, 'digest': f'{f}-d', 'description': f, 'parameters': {'type': 'object'},
         'entrypoint': 'x.py:run'} for f in families]}))
    return Candidate('lib-' + '-'.join(families), (), 'skill', str(d), (('%064d' % len(families))), ' '.join(families))


class World:
    """Student solves a task iff the gate shows it its own family's skill; teacher always writes."""
    def __init__(self, tmp, sources):
        self.tmp, self.sources, self.teacher_calls, self.shown = tmp, sources, 0, []

    def student(self, cand, task, run_id):
        from core.evolution.relevance import skill_ids
        shown = self.sources.relevant(task['instruction'], skill_ids(cand.bundle_path))
        self.shown.append((task['family'], shown))
        if task.get('negative'):
            return result(self.tmp, run_id, 0.0 if shown else 1.0, [READ])
        if task['family'] in shown:
            return result(self.tmp, run_id, 1.0, [{'action': {'name': 'skill_call', 'arguments': {'skill_id': task['family']}},
                                                   'observation': {'success': True}}])
        return result(self.tmp, run_id, 0.0, [READ])

    def solve(self, task):
        self.teacher_calls += 1
        return result(self.tmp, 'teacher-' + task['task_id'], 1.0, [WRITE])

    def propose(self, parent, task, demo, hint=None):
        have = parent.hypothesis.split() if parent.hypothesis else []
        return bundle(self.tmp, sorted(set(have) | {task['family']}))


def sources_for(root):
    return SkillSources(root / 'skill_sources.json', InstructionSpace(root / 'space.json'))


def learner(tmp_path, arm, world, sources, **kw):
    return StreamLearner(tmp_path / arm, arm, bootstrap=bundle(tmp_path, []), run_student=world.student,
                         teacher=TeacherCache(tmp_path / f'cache-{arm}', world.solve), propose_skill=world.propose,
                         memory=MemoryStore(tmp_path / arm / 'memory.jsonl', min_jaccard=RELEVANCE_MIN,
                                            similarity=sources.space.similarity),
                         skill_sources=sources, **kw)


def test_same_family_instructions_are_similar_and_others_are_not():
    space = InstructionSpace()
    for f in FAMILIES:
        for i in range(10):
            space.observe(make_task(f, 1000 + i)['instruction'])
    for f in CAPABILITY:
        a = make_task(f, 1000)['instruction']
        same = min(space.similarity(a, make_task(f, 1000 + i)['instruction']) for i in range(1, 10))
        other = max(space.similarity(a, make_task(g, 1000 + i)['instruction']) for g in CAPABILITY if g != f for i in range(10))
        assert other < RELEVANCE_MIN, (f, other)
        assert same > other, (f, same, other)


def test_clusters_recover_families_without_labels(tmp_path):
    clusters = TaskClusters(tmp_path / 'clusters.json', InstructionSpace())
    ids = {f: {clusters.assign(make_task(f, 1000 + i)['instruction'], generator=f) for i in range(8)}
           for f in CAPABILITY}
    owners = {}
    for f, cids in ids.items():                      # a phrasing may open its own cluster, but
        for cid in cids:                             # no cluster ever mixes two families
            assert owners.setdefault(cid, f) == f
    assert all(len(v) <= 2 for v in ids.values())
    assert TaskClusters(tmp_path / 'clusters.json', InstructionSpace()).generator_of(next(iter(ids['csv_transform']))) == 'csv_transform'


def test_gate_shows_nothing_for_unrelated_tasks(tmp_path):
    sources = sources_for(tmp_path)
    for f in FAMILIES:
        sources.space.observe(make_task(f, 1000)['instruction'])
    sources.add(['log_skill'], [make_task('log_aggregation', 1000)['instruction']])
    assert sources.relevant(make_task('log_aggregation', 1003)['instruction'], ['log_skill']) == ['log_skill']
    assert sources.relevant(make_task('text_normalize', 1000)['instruction'], ['log_skill']) == []
    assert sources.relevant('anything', ['never_verified']) == []


def test_empty_gate_means_empty_catalog(tmp_path):
    lib = bundle(tmp_path, ['a'])
    catalog = SkillCatalog({'a': ({'description': 'a', 'parameters': {}}, 'd', b'', 'run')}, runner=None)
    assert catalog.restrict([]).digests == {} and catalog.restrict(['a']).digests == {'a': 'd'}


def test_gated_arm_learns_and_keeps_unseen_family_clean(tmp_path):
    sources = sources_for(tmp_path / 'A4mG')
    world = World(tmp_path, sources)
    lr = learner(tmp_path, 'A4mG', world, sources)
    rows = [lr.step(make_task('log_aggregation', 1000 + i)) for i in range(3)]
    assert rows[0]['learning']['accepted'] and rows[1]['solved_by_student'] and rows[2]['solved_by_student']
    assert rows[0]['cluster'] == rows[2]['cluster'] == 'c0'
    ev = lr.evaluate([make_task('log_aggregation', 9000), make_task('text_normalize', 9000),
                      make_task('read_preserve', 9001)], 'cp3')
    # The fake student cannot do text_normalize; what matters is that nothing was shown for it.
    assert ev['passed'] == 2 and ev['misuse'] == 0
    assert ('text_normalize', []) in world.shown and ('read_preserve', []) in world.shown


def test_proactive_gated_tries_first_once_something_relevant_is_learned(tmp_path):
    sources = sources_for(tmp_path / 'A5')
    world = World(tmp_path, sources)
    lr = learner(tmp_path, 'A5', world, sources)
    for i in range(2):                                           # two failures -> low competence
        lr.competence.record_task('c0', False)
    lr.clusters.assign(make_task('log_aggregation', 1000)['instruction'], generator='log_aggregation')
    first = lr.step(make_task('log_aggregation', 1000))
    assert first['cluster'] == 'c0' and first['help_decision']['knows'] is False
    assert 'student_score' not in first and first['learning']['accepted']      # asked first, learned
    second = lr.step(make_task('log_aggregation', 1001))
    assert second['help_decision']['knows'] and second['solved_by_student']    # tries first now


def test_proactive_gated_stops_asking_where_help_teaches_nothing(tmp_path):
    sources = sources_for(tmp_path / 'A5')
    world = World(tmp_path, sources)
    lr = learner(tmp_path, 'A5', world, sources)
    world.solve = lambda task: result(tmp_path, 't-' + task['task_id'], 1.0, [READ])   # read-only demos
    lr.teacher = TeacherCache(tmp_path / 'cache-ro', world.solve)
    lr.run_student = lambda c, t, r: result(tmp_path, r, 0.0, [READ])                 # student breaks negatives
    rows = [lr.step(make_task('csv_transform', 1000 + i)) for i in range(4)]
    assert len({r['cluster'] for r in rows}) == 1
    assert [r['helped'] for r in rows] == [True, True, False, False]
    assert rows[2]['help_declined']


def test_maybe_evolve_runs_due_rounds_once(tmp_path):
    sources = sources_for(tmp_path / 'A6')
    world = World(tmp_path, sources)
    calls = []

    def evolver(lr, *, label, round_index, architect):
        calls.append((label, architect))
        return {'ok': True}
    lr = learner(tmp_path, 'A6', world, sources, evolver=evolver)
    for i in range(20):
        lr.step(make_task('log_aggregation', 1000 + i))
        lr.maybe_evolve()
    assert calls == [('e10', False), ('e20', True)]
    again = learner(tmp_path, 'A6', world, sources, evolver=evolver)
    assert again.maybe_evolve() is None and len(calls) == 2


def test_evolve_round_practises_by_cluster(tmp_path):
    from core.evolution.practice import evolve_round
    sources = sources_for(tmp_path / 'A6')
    world = World(tmp_path, sources)
    lr = learner(tmp_path, 'A6-fixed', world, sources, evolver=lambda *a, **k: {})
    for i in range(3):
        lr.step(make_task('csv_transform', 1000 + i))
    summary = evolve_round(lr, label='e3', round_index=1, architect=False, practice_tasks=4, propose_repair=None)
    practice = summary['practice']
    assert practice['tasks'] == 4 and list(practice['families']) == ['c0']
    assert practice['families']['c0']['generator'] == 'csv_transform' and practice['passed'] == 4


def test_policy_module_runs_isolated_and_falls_back(tmp_path):
    rows = [{'skill_id': 'a', 'similarity': 0.9, 'verified_on': []}, {'skill_id': 'b', 'similarity': 0.1, 'verified_on': []}]
    assert run_select(FIXED_SELECT.encode(), 'x', rows, ['a', 'b']) == ['a']
    assert run_select(b'def select(i, s):\n    return []\n', 'x', rows, ['a']) == []
    assert run_select(b'def select(i, s):\n    raise ValueError()\n', 'x', rows, ['a']) is None
    sources = sources_for(tmp_path)
    sources.add(['a'], ['sort the csv rows by date'])
    sources.set_policy('def select(i, s):\n    return 1/0\n')
    assert sources.relevant('sort the csv rows by date', ['a']) == ['a'] and sources.policy_errors == 1
    sources.set_policy('def select(i, s):\n    return []\n')
    assert sources.relevant('sort the csv rows by date', ['a']) == []


def test_l2_selection_step_promotes_only_on_improvement(tmp_path):
    from core.evolution.l2_selection import selection_step
    sources = sources_for(tmp_path / 'A6')
    world = World(tmp_path, sources)
    lr = learner(tmp_path, 'A6', world, sources, evolver=lambda *a, **k: {})
    lr.step(make_task('log_aggregation', 1000))                      # learns the log skill
    lr.run_student = world.student
    # Proposal shows every skill: the log task still passes, nothing improves -> rejected.
    show_all = {'status': 'proposed', 'target': 'skill_selection', 'hypothesis': 'show all',
                'code': 'def select(instruction, skills):\n    return [s["skill_id"] for s in skills]\n', 'cost_usd': 0.0}

    class Arch:
        def propose(self, archive, brief, run_id):
            assert (Path(archive) / next(p.name for p in Path(archive).iterdir()) / 'tasks').exists()
            return dict(show_all)
    out = selection_step(lr, label='e20', round_index=0, architect=Arch())
    assert out['status'] == 'proposed' and out['promoted'] is False and sources.policy is None
    lines = (lr.root / 'l2' / 'lineage.jsonl').read_text().splitlines()
    assert [json.loads(l)['status'] for l in lines] == ['active', 'rejected']
