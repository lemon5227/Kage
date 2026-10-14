"""A3: verified teacher demonstrations as retrieved trajectory memory (no family lookup)."""
import json

from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate, RunResult
from core.evolution.journal import Journal
from core.evolution.mutator import bundle_digest
from core.evolution.sandbox import ProcessSkillRunner
from core.evolution.stream import ARMS, MemoryStore, StreamLearner, TeacherCache, chain_runner
from core.evolution.stream_tasks import make_task
from core.model_provider import ModelProvider, ModelResponse
from test_stream_chain_integration import Teacher


def demo_trace(tmp_path, name, rows):
    path = tmp_path / f'{name}.jsonl'
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    return RunResult(name, 'passed', 1.0, str(path), {}, str(tmp_path))


WRITE = {'action': {'name': 'write_file', 'arguments': {'path': 'report.py', 'content': 'def f():\n    return 1\n'}},
         'observation': {'success': True, 'content': 'ok', 'scoring_criteria': 'SECRET'}}
READ = {'action': {'name': 'read_file', 'arguments': {'path': 'x'}}, 'observation': {'success': True, 'content': 'y' * 5000}}


def test_store_keeps_only_writing_demos_and_visible_fields(tmp_path):
    store = MemoryStore(tmp_path / 'memory.jsonl')
    assert store.add({'instruction': 'Read notes and summarize'}, demo_trace(tmp_path, 'r', [READ])) is False
    assert store.add({'instruction': 'Implement f in report.py', 'family': 'x'}, demo_trace(tmp_path, 'w', [READ, WRITE]))
    saved = json.loads((tmp_path / 'memory.jsonl').read_text())
    assert 'family' not in json.dumps(saved) and 'SECRET' not in json.dumps(saved)
    assert all(len(r['observation']['content']) <= 1500 for r in saved['rows'])


def test_retrieval_by_instruction_overlap_not_family(tmp_path):
    store = MemoryStore(tmp_path / 'memory.jsonl')
    store.add({'instruction': 'Implement summarize(lines) counting log lines per level in report.py'},
              demo_trace(tmp_path, 'w', [WRITE]))
    assert store.retrieve('Implement tally(lines) counting log lines per level in ops.py')
    assert store.retrieve('Merge overlapping booking intervals sorted by start') == []
    rows = store.retrieve('Implement summarize(lines) counting log lines per level in report.py')
    assert sum(len(json.dumps(r)) for r in rows) <= 4000


class CopyingStudent(ModelProvider):
    """Writes a solution only when a demonstrated write_file is in its history; otherwise gives up."""
    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        text = '\n'.join(str(m.get('content') or '') for m in messages)
        if '[Tool: write_file]' in text:
            return ModelResponse(text='Done.', usage={'input_tokens': 5, 'output_tokens': 1})
        if '[tool call] write_file' not in text:
            return ModelResponse(text='I cannot do this.', usage={'input_tokens': 5, 'output_tokens': 1})
        return Teacher().generate(messages)


def test_a3_learns_from_demo_and_solves_next_same_family_task(tmp_path):
    assert ARMS['A3'] == {'learn': 'memory', 'help': 'after_failure'}
    boot = tmp_path / 'boot'
    boot.mkdir()
    (boot / 'manifest.json').write_text('{"version":1,"skills":[]}')
    bootstrap = Candidate('no-skills', (), 'skill', str(boot), bundle_digest(boot))
    budget = lambda n: BudgetTracker(BudgetConfig(max_api_calls=1000), tmp_path / n)
    memory = MemoryStore(tmp_path / 'A3' / 'memory.jsonl')
    student = chain_runner(Journal(tmp_path / 's.sqlite'), budget('s.sqlite'), tmp_path / 'ws',
                           lambda run_id: CopyingStudent(), skill_runner=ProcessSkillRunner(timeout_s=10),
                           mode='memory', memory=memory)
    teacher_run = chain_runner(Journal(tmp_path / 't.sqlite'), budget('t.sqlite'), tmp_path / 'tws',
                               lambda run_id: Teacher(), cloud=True)
    teacher = TeacherCache(tmp_path / 'cache', lambda task: teacher_run(bootstrap, task, 'teacher-' + task['task_id']))
    learner = StreamLearner(tmp_path / 'A3', 'A3', bootstrap=bootstrap, run_student=student, teacher=teacher,
                            propose_skill=None, memory=memory)
    first = learner.step(make_task('log_aggregation', 1000))
    assert first['student_score'] == 0.0 and first['learning']['accepted'] is True
    second = learner.step(make_task('log_aggregation', 1001))
    assert second['solved_by_student'] is True
