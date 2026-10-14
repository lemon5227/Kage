import hashlib
import json
import shutil

from core.evolution.competence import CompetenceModel
from core.evolution.contracts import Candidate, RunResult
from core.evolution.mutator import bundle_digest
from core.evolution.practice import maintain_library
from core.evolution.skills import SkillCatalog

CODE = 'def run(arguments, context):\n    return {"success": True}\n'


def make_bundle(path, skills):
    path.mkdir(parents=True)
    items = []
    for i, (skill_id, description) in enumerate(skills):
        descriptor = {'skill_id': skill_id, 'description': description,
                      'parameters': {'type': 'object', 'properties': {}}, 'entrypoint': f's{i}.py:run'}
        canonical = json.dumps(descriptor, sort_keys=True, separators=(',', ':'), allow_nan=False)
        descriptor['digest'] = hashlib.sha256(canonical.encode() + b'\n' + CODE.encode()).hexdigest()
        (path / f's{i}.py').write_text(CODE)
        items.append(descriptor)
    (path / 'manifest.json').write_text(json.dumps({'version': 1, 'skills': items}))
    return Candidate('lib-' + path.name, (), 'skill', str(path), bundle_digest(path))


def setup(tmp_path, *, repaired_passes):
    lib = make_bundle(tmp_path / 'v1', [('count_log', 'Use this when counting log lines per level.'),
                                        ('old_slug', 'Use this when making slugs.')])
    root = tmp_path / 'practice'
    root.mkdir()
    queue = [{'task_id': f'stream-v1-log_aggregation-{s}', 'family': 'log_aggregation', 'seed': s,
              'skill_ids_called': ['count_log'], 'failure': {'trace_path': None}} for s in (13000, 13001)]
    (root / 'repair_queue.jsonl').write_text(''.join(json.dumps(q) + '\n' for q in queue))
    (root / 'skill_successes.jsonl').write_text(json.dumps(
        {'skill_id': 'count_log', 'family': 'log_aggregation', 'seed': 13002}) + '\n')
    comp = CompetenceModel()
    for _ in range(3):
        comp.record_skill('old_slug', False)          # low success -> retirement candidate
    comp.record_skill('count_log', True)

    def propose(parent, feedback):
        assert 'external check failed' in feedback['failure_reason'] and 'scoring_criteria' not in json.dumps(feedback)
        child = tmp_path / 'v2'
        shutil.copytree(parent.bundle_path, child)
        return Candidate('lib-v2', (parent.candidate_id,), 'skill', str(child), bundle_digest(child))

    checked = []

    def run_student(candidate, task, run_id):
        checked.append((candidate.candidate_id, task['task_id']))
        score = 1.0 if (candidate.candidate_id == 'lib-v2' and repaired_passes) else 0.0
        return RunResult(run_id, 'passed' if score else 'failed', score, '', {}, '')
    return lib, root, comp, propose, run_student, checked


def test_repair_accepted_only_after_failures_and_prior_successes_pass(tmp_path):
    lib, root, comp, propose, run_student, checked = setup(tmp_path, repaired_passes=True)
    new_lib, summary = maintain_library(root, lib, comp, propose=propose, run_student=run_student)
    assert summary['repair'] == {'skill_id': 'count_log', 'accepted': True, 'checked': 3}
    assert {t for _, t in checked} == {'stream-v1-log_aggregation-13000', 'stream-v1-log_aggregation-13001',
                                       'stream-v1-log_aggregation-13002'}
    # repaired queue entries are not repaired again
    _, again = maintain_library(root, new_lib, comp, propose=propose, run_student=run_student)
    assert again['repair'] is None


def test_failed_repair_keeps_old_version_and_retirement_removes_skill(tmp_path):
    lib, root, comp, propose, run_student, _ = setup(tmp_path, repaired_passes=False)
    new_lib, summary = maintain_library(root, lib, comp, propose=propose, run_student=run_student)
    assert summary['repair']['accepted'] is False
    assert summary['retired'] == ['old_slug'] and comp.skills['old_slug'].status == 'retired'
    catalog = SkillCatalog.from_bundle(new_lib.bundle_path)
    assert 'old_slug' not in catalog.digests and 'count_log' in catalog.digests
    assert new_lib.parent_ids == (lib.candidate_id,) and new_lib.digest == bundle_digest(new_lib.bundle_path)
    retired = json.loads((root / 'retired.json').read_text())
    assert retired[0]['skill_id'] == 'old_slug' and 'def run' in retired[0]['source']
    changes = [json.loads(l)['change'] for l in (root / 'library_changes.jsonl').read_text().splitlines()]
    assert changes == ['repair_rejected', 'retire']


def test_merge_candidates_are_only_recorded(tmp_path):
    lib = make_bundle(tmp_path / 'v1', [('count_a', 'Use this when counting log lines per level or service.'),
                                        ('count_b', 'Use this when counting log lines per service or level.')])
    comp = CompetenceModel()
    for sid in ('count_a', 'count_b'):
        comp.record_skill(sid, True)
    root = tmp_path / 'p'
    root.mkdir()
    new_lib, summary = maintain_library(root, lib, comp, propose=None, run_student=None)
    assert new_lib is lib and summary['merge_candidates'] == [['count_a', 'count_b']]
