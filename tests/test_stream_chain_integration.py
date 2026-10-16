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
from core.evolution.stream_tasks import make_task
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


class RecordingStudent(ModelProvider):
    def __init__(self, log):
        self.log = log

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        with open(self.log, 'a') as out:
            out.write(f'{max_tokens}\n')
        return ModelResponse(text='Finished.', usage={'input_tokens': 10, 'output_tokens': 5})


def test_chain_runner_lifts_companion_tool_reply_cap(tmp_path):
    # AgenticLoop's companion default (300 tokens per tool turn) truncated every real
    # student write_file in the first E-0 attempt; experiment runs use their own cap.
    from core.agentic_loop import AgenticLoop
    assert AgenticLoop.TOOL_MAX_TOKENS == 300
    boot = tmp_path / 'boot'
    boot.mkdir()
    (boot / 'manifest.json').write_text('{"version":1,"skills":[]}')
    bootstrap = Candidate('no-skills', (), 'skill', str(boot), bundle_digest(boot))
    log = tmp_path / 'max_tokens.txt'
    run = chain_runner(Journal(tmp_path / 'j.sqlite'), BudgetTracker(BudgetConfig(max_api_calls=100), tmp_path / 'b.sqlite'),
                       tmp_path / 'ws', lambda run_id: RecordingStudent(log), skill_runner=ProcessSkillRunner(timeout_s=10),
                       tool_max_tokens=1024)
    run(bootstrap, make_task('log_aggregation', 1000), 'cap')
    assert set(log.read_text().split()) == {'1024'}


def test_relevant_preview_shows_the_matching_skill_when_the_library_grows(tmp_path):
    import hashlib
    code = 'def run(arguments, context):\n    return {"success": True}\n'
    items = []
    lib = tmp_path / 'lib'
    lib.mkdir()
    for i, (sid, desc) in enumerate([('csv_a', 'Use this when cleaning CSV exports.'),
                                     ('csv_b', 'Use this when deduplicating CSV rows.'),
                                     ('csv_c', 'Use this when sorting CSV tables.'),
                                     ('log_line_counter', 'Use this when counting log lines per level or service.')]):
        d = {'skill_id': sid, 'description': desc, 'parameters': {'type': 'object', 'properties': {}},
             'entrypoint': f's{i}.py:run'}
        d['digest'] = hashlib.sha256(json.dumps(d, sort_keys=True, separators=(',', ':')).encode() + b'\n' + code.encode()).hexdigest()
        (lib / f's{i}.py').write_text(code)
        items.append(d)
    (lib / 'manifest.json').write_text(json.dumps({'version': 1, 'skills': items}))
    library = Candidate('lib', (), 'skill', str(lib), bundle_digest(lib))
    seen = {}
    for mode in ('preview', 'preview_relevant'):
        log = tmp_path / f'{mode}.txt'

        class Recorder(ModelProvider):
            def generate(self, messages, tools=None, max_tokens=200, temperature=0.7, _log=log):
                _log.write_text(messages[0]['content'])
                return ModelResponse(text='Done.', usage={'input_tokens': 1, 'output_tokens': 1})
        run = chain_runner(Journal(tmp_path / f'{mode}.sqlite'), BudgetTracker(BudgetConfig(max_api_calls=100), tmp_path / f'{mode}-b.sqlite'),
                           tmp_path / f'ws-{mode}', lambda run_id: Recorder(), skill_runner=ProcessSkillRunner(timeout_s=10),
                           skill_preview=mode)
        run(library, make_task('log_aggregation', 1000), f'run-{mode}')
        seen[mode] = 'log_line_counter' in log.read_text().split('skill preview')[1]
    assert seen == {'preview': False, 'preview_relevant': True}


def test_gated_real_chain_learns_and_keeps_unrelated_prompts_identical_to_a0(tmp_path):
    from core.evolution.relevance import RELEVANCE_MIN, InstructionSpace, SkillSources
    from core.evolution.stream import MemoryStore
    budget = lambda name: BudgetTracker(BudgetConfig(max_api_calls=10_000), tmp_path / name)
    journal = Journal(tmp_path / 'journal.sqlite')
    runner = ProcessSkillRunner(timeout_s=10)
    sources = SkillSources(tmp_path / 'A4mG' / 'skill_sources.json', InstructionSpace(tmp_path / 'A4mG' / 'space.json'))
    memory = MemoryStore(tmp_path / 'A4mG' / 'memory.jsonl', min_jaccard=RELEVANCE_MIN, similarity=sources.space.similarity)
    student = chain_runner(journal, budget('s.sqlite'), tmp_path / 'ws', lambda run_id: Student(), skill_runner=runner,
                           memory=memory, mode='memory', gate=sources, skill_preview='preview_relevant')
    teacher_run = chain_runner(Journal(tmp_path / 't.sqlite'), budget('t-b.sqlite'), tmp_path / 'tws',
                               lambda run_id: Teacher(), cloud=True)
    boot = tmp_path / 'boot'
    boot.mkdir()
    (boot / 'manifest.json').write_text('{"version":1,"skills":[]}')
    bootstrap = Candidate('no-skills', (), 'skill', str(boot), bundle_digest(boot))
    teacher = TeacherCache(tmp_path / 'cache', lambda task: teacher_run(bootstrap, task, 'teacher-' + task['task_id']))

    def propose(parent, task, demo, hint=None):
        trace = [json.loads(l) for l in open(demo.trace_path)]
        return Mutator(Optimizer(), budget('o.sqlite'), journal, tmp_path / 'mut' / task['task_id']).propose(
            parent, {'task_id': task['task_id'], 'instruction': task['instruction'], 'failure_reason': 'x', 'trace': trace})

    learner = StreamLearner(tmp_path / 'A4mG', 'A4mG', bootstrap=bootstrap, run_student=student, teacher=teacher,
                            propose_skill=propose, memory=memory, skill_sources=sources)
    first = learner.step(make_task('log_aggregation', 1000))
    assert first['learning']['accepted'] is True and first['cluster'] == 'c0'
    assert learner.step(make_task('log_aggregation', 1001))['solved_by_student']
    # Unrelated task: the gated student's prompt is byte-identical to the raw student's.
    class Recorder(ModelProvider):            # runs in the chain's worker: record through files
        def __init__(self, path):
            self.path = path

        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            if not self.path.exists():
                self.path.write_text(json.dumps(messages, sort_keys=True))   # whole request, memory included
            return ModelResponse(text='Done.', usage={'input_tokens': 1, 'output_tokens': 1})
    other = make_task('text_normalize', 9000)
    gated = chain_runner(journal, budget('g.sqlite'), tmp_path / 'wsg', lambda run_id: Recorder(tmp_path / 'gated.txt'),
                         skill_runner=runner, memory=memory, mode='memory', gate=sources, skill_preview='preview_relevant')
    plain = chain_runner(Journal(tmp_path / 'a0.sqlite'), budget('a0.sqlite'), tmp_path / 'ws0',
                         lambda run_id: Recorder(tmp_path / 'a0.txt'), skill_runner=runner)
    gated(learner.library, other, 'gated-other')
    plain(bootstrap, other, 'a0-other')
    assert (tmp_path / 'gated.txt').read_text() == (tmp_path / 'a0.txt').read_text()
    assert 'count_log_lines' not in (tmp_path / 'gated.txt').read_text()
    # A related task still sees the learned skill.
    (tmp_path / 'gated.txt').unlink()
    gated(learner.library, make_task('log_aggregation', 9001), 'gated-related')
    assert 'count_log_lines' in (tmp_path / 'gated.txt').read_text()


def test_a6_evolution_round_over_real_chain(tmp_path):
    from core.evolution.architect import Architect
    from core.evolution.l2_selection import selection_step
    from core.evolution.practice import evolve_round
    from core.evolution.relevance import RELEVANCE_MIN, InstructionSpace, SkillSources
    from core.evolution.stream import MemoryStore
    budget = lambda name: BudgetTracker(BudgetConfig(max_api_calls=10_000), tmp_path / name)
    journal = Journal(tmp_path / 'journal.sqlite')
    runner = ProcessSkillRunner(timeout_s=10)
    root = tmp_path / 'A6'
    sources = SkillSources(root / 'skill_sources.json', InstructionSpace(root / 'space.json'), runner=runner)
    memory = MemoryStore(root / 'memory.jsonl', min_jaccard=RELEVANCE_MIN, similarity=sources.space.similarity)
    student = chain_runner(journal, budget('s.sqlite'), tmp_path / 'ws', lambda run_id: Student(), skill_runner=runner,
                           memory=memory, mode='memory', gate=sources, skill_preview='preview_relevant')
    teacher_run = chain_runner(Journal(tmp_path / 't.sqlite'), budget('t-b.sqlite'), tmp_path / 'tws',
                               lambda run_id: Teacher(), cloud=True)
    boot = tmp_path / 'boot'
    boot.mkdir()
    (boot / 'manifest.json').write_text('{"version":1,"skills":[]}')
    bootstrap = Candidate('no-skills', (), 'skill', str(boot), bundle_digest(boot))
    teacher = TeacherCache(tmp_path / 'cache', lambda task: teacher_run(bootstrap, task, 'teacher-' + task['task_id']))

    def propose(parent, task, demo, hint=None):
        trace = [json.loads(l) for l in open(demo.trace_path)]
        return Mutator(Optimizer(), budget('o.sqlite'), journal, tmp_path / 'mut' / task['task_id']).propose(
            parent, {'task_id': task['task_id'], 'instruction': task['instruction'], 'failure_reason': 'x', 'trace': trace})

    class ArchitectModel(ModelProvider):
        def __init__(self):
            self.turn = 0

        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            self.turn += 1
            reply = ({'tool': 'grep', 'args': {'pattern': 'similarity', 'path': '.'}} if self.turn == 1 else
                     {'final': {'target': 'skill_selection', 'hypothesis': 'never show skills',
                                'code': 'def select(instruction, skills):\n    return []\n'}})
            return ModelResponse(text=json.dumps(reply), usage={'input_tokens': 500, 'output_tokens': 50})

    def architect_step(lrn, *, label):
        return selection_step(lrn, label=label, round_index=0, architect=Architect(ArchitectModel(), budget('a.sqlite')))

    def evolver(lrn, *, label, round_index, architect):
        return evolve_round(lrn, label=label, round_index=round_index, architect=architect, practice_tasks=2,
                            propose_repair=None, architect_step=architect_step)
    learner = StreamLearner(root, 'A6', bootstrap=bootstrap, run_student=student, teacher=teacher,
                            propose_skill=propose, memory=memory, skill_sources=sources, evolver=evolver)
    learner.cfg = {**learner.cfg, 'evolve': {'every': 2, 'practice': 2, 'architect_every': 2}}
    # Document frequencies of a stream already under way (with N≈4 instructions TF-IDF is immature;
    # on the real stream order no same-family task falls below the gate, 2026-10-16 replay).
    from core.evolution.stream_tasks import FAMILIES
    for family in FAMILIES:
        for seed in range(1100, 1104):
            sources.space.observe(make_task(family, seed)['instruction'])
    for i in range(2):
        learner.step(make_task('log_aggregation', 1000 + i))
    summary = learner.maybe_evolve()
    assert summary['practice']['tasks'] == 2 and summary['practice']['passed'] == 2
    arch = summary['architect']
    assert arch['status'] == 'proposed' and arch['validation_tasks'] == 1 and arch['parent_passed'] == 1
    assert arch['promoted'] is False and arch['regressed']          # hiding the skill breaks the log task
    assert sources.policy is None                                   # parent rule stays active
    assert json.loads((root / 'evolution.jsonl').read_text())['label'] == 'e2'
    assert learner.maybe_evolve() is None
