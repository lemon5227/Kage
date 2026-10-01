"""Recovery changes must execute through the real loop and original tool executor."""
import asyncio

from core.agentic_loop import AgenticLoop
from core.model_provider import ModelResponse
from test_agentic_loop_multistep import make_loop, call


class Policy:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []
    def recover(self, error, history, checkpoints):
        self.calls.append((error, history, checkpoints))
        return self.decision


def configured_loop(path, responses, policy):
    original, model, _ = make_loop(path, responses)
    loop = AgenticLoop(model, original.tools, original.prompt, original.session, recovery_policy=policy)
    return loop, model


def test_recovery_executes_real_write_then_read_in_same_step_budget(tmp_path):
    (tmp_path / 'input.txt').write_text('7')
    policy = Policy({'action': 'switch_tool', 'tool_call': {'name': 'write_file', 'arguments': {'path': 'out.txt', 'content': '14'}}})
    loop, model = configured_loop(tmp_path, [call('read_file', path='input.txt'), ModelResponse(text='Need to compute'), call('read_file', path='out.txt'), ModelResponse(text='Done')], policy)
    result = asyncio.run(loop.run('Read input.txt and write double into out.txt file.'))
    assert (tmp_path / 'out.txt').read_text() == '14'
    assert [r['name'] for r in result.tool_calls_executed] == ['read_file', 'write_file', 'read_file']
    assert result.tool_calls_executed[1]['actor'] == 'recovery_policy'
    assert len(policy.calls) == 1 and len(model.messages) == 4 and result.steps == 4
    assert policy.calls[0][1][0]['arguments'] == {'path': 'input.txt'}


def test_stop_unknown_and_exception_do_not_fabricate_completion(tmp_path):
    for decision in [{'action': 'stop'}, {'action': 'imaginary'}, {'action': 'switch_tool', 'tool_call': {'name': 'write_file', 'arguments': 'bad'}}]:
        policy = Policy(decision)
        loop, _ = configured_loop(tmp_path, [call('list_files'), ModelResponse(text='Done')], policy)
        result = asyncio.run(loop.run('Inspect files and write out.txt.'))
        assert len(result.tool_calls_executed) == 1
        assert not (tmp_path / 'out.txt').exists()
    class Broken(Policy):
        def recover(self, *args):
            raise ValueError('broken policy')
    loop, _ = configured_loop(tmp_path, [call('list_files'), ModelResponse(text='Done')], Broken(None))
    result = asyncio.run(loop.run('Inspect files and write out.txt.'))
    assert len(result.tool_calls_executed) == 1
    assert loop.recovery_events[-1]['error'] == 'ValueError: broken policy'


def test_recovery_is_disabled_by_default_and_never_runs_without_evidence(tmp_path):
    loop, _ , _ = make_loop(tmp_path, [call('list_files'), ModelResponse(text='Done')])
    result = asyncio.run(loop.run('Inspect files and write out.txt.'))
    assert len(result.tool_calls_executed) == 1 and loop.recovery_events == []
    policy = Policy({'action': 'stop'})
    loop, _ = configured_loop(tmp_path, [ModelResponse(text='Hello')], policy)
    asyncio.run(loop.run('Hello'))
    assert policy.calls == []
