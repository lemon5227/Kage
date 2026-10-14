import json

import pytest

from core.evolution.architect import (Architect, ArchiveTools, promote, validate_candidate, write_archive,
                                      write_module)
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.lineage import Lineage, Version
from core.evolution.stream_tasks import split_of
from core.model_provider import ModelProvider, ModelResponse

HELP_CODE = ("def recover(error, history, checkpoints):\n"
             "    if not error.get('written_files'):\n"
             "        return {'action': 'request_help', 'reason': 'nothing written'}\n"
             "    return {'action': 'stop'}\n")


def archive(tmp_path):
    return write_archive(tmp_path / 'archive', [{
        'id': 'v0', 'target': 'help_policy', 'source': 'def recover(e, h, c):\n    return {"action": "stop"}\n',
        'validation': {'passed': 1, 'total': 3, 'scoring_criteria': {'cases': ['SECRET']}},
        'traces': [[{'action': {'name': 'list_files'}, 'observation': {'success': True},
                     'scoring_criteria': {'expected': 'SECRET'}}]]}])


class Scripted(ModelProvider):
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        self.seen.append(messages[-1]['content'])
        return ModelResponse(text=self.replies.pop(0), usage={'input_tokens': 2000, 'output_tokens': 300})


def ledger(tmp_path):
    return BudgetTracker(BudgetConfig(max_api_calls=100, max_cost_usd=1.0, input_cost_per_million=0.3,
                                      output_cost_per_million=1.2), tmp_path / 'ledger.sqlite')


def test_tools_stay_inside_archive_and_hide_scoring(tmp_path):
    root = archive(tmp_path)
    tools = ArchiveTools(root)
    assert 'error: PermissionError' in tools.call('cat', {'path': '../../etc/passwd'})
    assert 'error' in tools.call('rm', {'path': 'v0'})
    everything = tools.call('grep', {'pattern': '.', 'path': '.'}) + tools.call('cat', {'path': 'v0/validation.json'})
    assert 'SECRET' not in everything and 'scoring_criteria' not in everything


def test_scripted_architect_reads_then_proposes_and_reserves_first(tmp_path):
    model = Scripted([json.dumps({'tool': 'cat', 'args': {'path': 'v0/help_policy.py'}}),
                      json.dumps({'final': {'target': 'help_policy', 'hypothesis': 'ask when nothing written',
                                            'code': HELP_CODE}})[:-1]])       # missing final brace is tolerated
    budget = ledger(tmp_path)
    out = Architect(model, budget).propose(archive(tmp_path), 'Improve help requests.', run_id='arch-1')
    assert out['status'] == 'proposed' and out['target'] == 'help_policy' and out['turns'] == 2
    assert 'def recover' in model.seen[1]                      # the model saw the cat output
    budget._load_totals()
    assert budget.total_api_calls == 2 and 0 < out['cost_usd'] <= 0.015


def test_illegal_target_is_rejected_then_budget_stop(tmp_path):
    with pytest.raises(ValueError):
        validate_candidate({'target': 'scorer', 'hypothesis': 'h', 'code': 'def f(): pass'})
    with pytest.raises(ValueError):
        validate_candidate({'target': 'help_policy', 'hypothesis': 'h',
                            'code': 'import os\ndef recover(e, h, c):\n    return {}\n'})
    bad = json.dumps({'final': {'target': 'scorer', 'hypothesis': 'h', 'code': 'x'}})
    model = Scripted([bad] * 20)
    out = Architect(model, ledger(tmp_path), cap_usd=0.006).propose(archive(tmp_path), 'b', run_id='a')
    assert out['status'] == 'budget_stop' and out['cost_usd'] <= 0.006


def test_promotion_and_rejection_paths(tmp_path):
    lin = Lineage(tmp_path / 'lineage.jsonl')
    parent = lin.record(Version(id='v0', parent=None, target='help_policy', digest='0' * 64,
                                validation={'passed': 1, 'total': 3}))
    cand = validate_candidate({'target': 'help_policy', 'hypothesis': 'ask more', 'code': HELP_CODE})
    module, digest = write_module(tmp_path / 'modules', cand)
    better = promote(lin, parent, cand, module, digest, lambda d: {'a': 1.0, 'b': 1.0 if d else 0.0, 'c': 0.0},
                     parent_dir=None)
    assert better['promoted'] and better['improved'] == ['b'] and lin.nodes[better['version']].status == 'active'
    cand2 = validate_candidate({'target': 'help_policy', 'hypothesis': 'always ask',
                                'code': HELP_CODE.replace("'nothing written'", "'always'")})
    module2, digest2 = write_module(tmp_path / 'modules', cand2)
    worse = promote(lin, parent, cand2, module2, digest2,
                    lambda d: {'a': 0.0 if d else 1.0, 'b': 1.0 if d else 0.0}, parent_dir=None)
    assert not worse['promoted'] and worse['regressed'] == ['a']
    assert split_of(17000) == 'validation'
