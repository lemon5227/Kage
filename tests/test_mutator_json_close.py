import json

from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.mutator import Mutator, bundle_digest, parse_proposal
from core.model_provider import ModelProvider, ModelResponse

GOOD = {'hypothesis': 'h', 'skill_id': 'noop', 'description': 'Use this when testing.',
        'parameters': {'type': 'object', 'properties': {}},
        'code': 'def run(arguments, context):\n    return {"success": True}\n'}


def test_parse_accepts_reply_missing_only_final_brace():
    raw = json.dumps(GOOD)
    assert parse_proposal(raw) == (GOOD, False)
    assert parse_proposal(raw[:-1]) == (GOOD, True)          # E-0: 23/25 malformed replies were exactly this
    for bad in (raw[:-5], 'not json', raw[:-1] + ']'):
        try:
            parse_proposal(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_missing_brace_costs_no_repair_call(tmp_path):
    calls = []

    class Optimizer(ModelProvider):
        def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
            calls.append(1)
            return ModelResponse(text=json.dumps(GOOD)[:-1], usage={'input_tokens': 10, 'output_tokens': 10})

    boot = tmp_path / 'boot'
    boot.mkdir()
    (boot / 'manifest.json').write_text('{"version":1,"skills":[]}')
    parent = Candidate('p', (), 'skill', str(boot), bundle_digest(boot))
    child = Mutator(Optimizer(), BudgetTracker(BudgetConfig(max_api_calls=10), tmp_path / 'b.sqlite'),
                    Journal(tmp_path / 'j.sqlite'), tmp_path / 'm').propose(
        parent, {'task_id': 't', 'instruction': 'x', 'failure_reason': 'y', 'trace': []})
    assert len(calls) == 1 and child.digest
    attempt = json.loads(next((tmp_path / 'm' / 'attempts').glob('*.json')).read_text())
    assert attempt['json_closed'] is True
