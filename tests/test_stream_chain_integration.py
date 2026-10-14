"""Stream slice over the REAL chain/runner/mutator/skill runner with scripted models.

Engineering evidence only: proves trace parsing, skill extraction, library growth and reuse
plumbing that the Mac run uses. Not a learning result.
"""
import json
import re

from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.mutator import Mutator, bundle_digest
from core.evolution.sandbox import ProcessSkillRunner
from core.evolution.stream import StreamLearner, TeacherCache, chain_runner
from core.evolution.stream_tasks import log_aggregation, make_task
from core.model_provider import ModelProvider, ModelResponse

GENERAL = '''def build(fn, key, only):
    return f"""def {fn}(lines):
    out = {{}}
    for line in lines:
        if not isinstance(line, str):
            continue
        parts = line.split(' ', 3)
        if len(parts) < 4 or not parts[2].endswith(':') or len(parts[2]) < 2:
            continue
        level, service = parts[1].upper(), parts[2][:-1]
        if {only!r} and level not in {only!r}:
            continue
        name = level if {key!r} == 'level' else service
        out[name] = out.get(name, 0) + 1
    return out
"""
'''


def parse(instruction):
    fn = re.search(r'(\w+)\(lines\)', instruction).group(1)
    file = re.search(r'(\w+\.py)', instruction).group(1)
    m = re.search(r'service for levels ([A-Z, ]+) only', instruction)
    return fn, file, ('service', [x.strip() for x in m.group(1).split(',')]) if m else ('level', [])


def instruction_of(messages):
    return next(str(m['content']) for m in reversed(messages) if m.get('role') == 'user')


class Student(ModelProvider):
    """Uses a previewed skill if one exists; otherwise reads the file and gives up."""
    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        text = '\n'.join(str(m.get('content') or '') for m in messages)
        if '[Tool: skill_call]' in text or '[Tool: read_file]' in text:
            return ModelResponse(text='Finished.', usage={'input_tokens': 10, 'output_tokens': 5})
        preview = re.search(r'Local reusable skill preview \(descriptors only, not source code\): (\[.*?\])\n', text)
        fn, file, (key, only) = parse(instruction_of(messages))
        if preview and json.loads(preview.group(1)):
            skill = json.loads(preview.group(1))[0]
            return ModelResponse(text='', tool_calls=[{'name': 'skill_call', 'arguments': {
                'skill_id': skill['skill_id'], 'digest': skill['digest'],
                'arguments': {'file_path': file, 'function_name': fn, 'key': key, 'only_levels': only}}}],
                usage={'input_tokens': 10, 'output_tokens': 5})
        return ModelResponse(text='', tool_calls=[{'name': 'read_file', 'arguments': {'path': file}}],
                             usage={'input_tokens': 10, 'output_tokens': 5})


class Teacher(ModelProvider):
    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        text = '\n'.join(str(m.get('content') or '') for m in messages)
        if '[Tool: write_file]' in text:
            return ModelResponse(text='Saved.', usage={'input_tokens': 20, 'output_tokens': 5})
        fn, file, (key, only) = parse(instruction_of(messages))
        ns = {}
        exec(GENERAL, ns)
        return ModelResponse(text='', tool_calls=[{'name': 'write_file', 'arguments': {
            'path': file, 'content': ns['build'](fn, key, only)}}], usage={'input_tokens': 20, 'output_tokens': 50})


class Optimizer(ModelProvider):
    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        code = GENERAL + '''
def run(arguments, context):
    from pathlib import Path
    path = Path(context["workspace_dir"]) / arguments["file_path"]
    path.write_text(build(arguments["function_name"], arguments["key"], arguments.get("only_levels", [])))
    return {"success": True, "written": arguments["file_path"]}
'''
        return ModelResponse(text=json.dumps({
            'hypothesis': 'log counting procedure', 'skill_id': 'count_log_lines',
            'description': 'Count structured log lines per level or service. Only for tasks that ask to implement such a counter.',
            'parameters': {'type': 'object', 'properties': {'file_path': {'type': 'string'}, 'function_name': {'type': 'string'},
                           'key': {'enum': ['level', 'service']}, 'only_levels': {'type': 'array', 'items': {'type': 'string'}}},
                           'required': ['file_path', 'function_name', 'key']},
            'code': code}), usage={'input_tokens': 100, 'output_tokens': 300})


def test_real_chain_learns_skill_from_teacher_and_reuses_it(tmp_path):
    budget = lambda name: BudgetTracker(BudgetConfig(max_api_calls=10_000), tmp_path / name)
    journal = Journal(tmp_path / 'journal.sqlite')
    runner = ProcessSkillRunner(timeout_s=10)
    student = chain_runner(journal, budget('s.sqlite'), tmp_path / 'ws', lambda run_id: Student(), skill_runner=runner)
    teacher_run = chain_runner(Journal(tmp_path / 't.sqlite'), budget('t-b.sqlite'), tmp_path / 'tws',
                               lambda run_id: Teacher(), cloud=True)
    boot = tmp_path / 'boot'
    boot.mkdir()
    (boot / 'manifest.json').write_text('{"version":1,"skills":[]}')
    bootstrap = Candidate('no-skills', (), 'skill', str(boot), bundle_digest(boot))
    teacher = TeacherCache(tmp_path / 'cache', lambda task: teacher_run(bootstrap, task, 'teacher-' + task['task_id']))

    def propose(parent, task, demo):
        trace = [json.loads(l) for l in open(demo.trace_path)]
        return Mutator(Optimizer(), budget('o.sqlite'), journal, tmp_path / 'mut' / task['task_id']).propose(
            parent, {'task_id': task['task_id'], 'instruction': task['instruction'], 'failure_reason': 'x', 'trace': trace})

    learner = StreamLearner(tmp_path / 'A4', 'A4', bootstrap=bootstrap, run_student=student,
                            teacher=teacher, propose_skill=propose)
    tasks = [make_task('log_aggregation', 1000 + i) for i in range(3)]
    first = learner.step(tasks[0])
    assert first['student_score'] == 0.0 and first['teacher_score'] == 1.0
    assert first['learning']['accepted'] is True, first['learning']
    later = [learner.step(t) for t in tasks[1:]]
    assert all(r['solved_by_student'] and r['skill_calls'][0]['success'] for r in later)
    assert learner.competence.skills['count_log_lines'].status == 'active'
    cp = learner.evaluate([make_task('log_aggregation', 9000), make_task('log_aggregation', 9001)], 'cp-end')
    assert cp['passed'] == 2
