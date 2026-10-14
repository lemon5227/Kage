"""A1: budget-matched local retries over the real chain (scripted model)."""

from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.mutator import bundle_digest
from core.evolution.sandbox import ProcessSkillRunner
from core.evolution.stream import ARMS, StreamLearner, chain_runner
from core.evolution.stream_tasks import make_task
from core.model_provider import ModelProvider, ModelResponse
from test_stream_chain_integration import GENERAL, instruction_of, parse


class SecondAttemptStudent(ModelProvider):
    """Gives up on its first attempt; writes a correct file on the next fresh attempt."""
    def __init__(self, log):
        self.log = log

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        with open(self.log, 'a') as out:
            out.write('call\n')
        text = '\n'.join(str(m.get('content') or '') for m in messages)
        if '[Tool: write_file]' in text:
            return ModelResponse(text='Saved.', usage={'input_tokens': 10, 'output_tokens': 5})
        attempts = open(self.log).read().count('attempt\n')
        if 'Finished without' not in text and attempts == 0:
            with open(self.log, 'a') as out:
                out.write('attempt\n')
            return ModelResponse(text='Finished without changes.', usage={'input_tokens': 10, 'output_tokens': 5})
        fn, file, (key, only) = parse(instruction_of(messages))
        ns = {}
        exec(GENERAL, ns)
        return ModelResponse(text='', tool_calls=[{'name': 'write_file', 'arguments': {
            'path': file, 'content': ns['build'](fn, key, only)}}], usage={'input_tokens': 10, 'output_tokens': 50})


def test_a1_retries_within_the_same_total_budget(tmp_path):
    assert ARMS['A1'] == {'learn': False, 'help': 'never'}
    boot = tmp_path / 'boot'
    boot.mkdir()
    (boot / 'manifest.json').write_text('{"version":1,"skills":[]}')
    bootstrap = Candidate('no-skills', (), 'skill', str(boot), bundle_digest(boot))
    log = tmp_path / 'calls.txt'
    run = chain_runner(Journal(tmp_path / 'j.sqlite'), BudgetTracker(BudgetConfig(max_api_calls=1000), tmp_path / 'b.sqlite'),
                       tmp_path / 'ws', lambda run_id: SecondAttemptStudent(log), skill_runner=ProcessSkillRunner(timeout_s=10),
                       mode='retry')
    learner = StreamLearner(tmp_path / 'A1', 'A1', bootstrap=bootstrap, run_student=run, teacher=None, propose_skill=None)
    row = learner.step(make_task('log_aggregation', 1000))
    assert row['solved_by_student'] is True and row['student_score'] == 1.0
    assert open(log).read().count('call\n') <= 6
