"""P0 hook interface: policies see why they were called and may ask for help."""
import asyncio

from core.agentic_loop import recovery_context
from core.model_provider import ModelResponse
from test_agentic_loop_multistep import call
from test_evolution_self_modify import Policy, configured_loop


def test_context_marks_ordinary_finish_and_written_files():
    rows = [{'name': 'read_file', 'arguments': {'path': 'a.py'}, 'success': True},
            {'name': 'write_file', 'arguments': {'path': 'b.py'}, 'success': True},
            {'name': 'skill_call', 'arguments': {'skill_id': 's', 'arguments': {'file_path': 'c.py'}}, 'success': True},
            {'name': 'write_file', 'arguments': {'path': 'd.py'}, 'success': False}]
    ctx = recovery_context('goal', 'done', rows[:3])
    assert ctx['reason'] == 'no_tool_calls'          # frozen historical policies unchanged
    assert ctx['trigger'] == 'finish_attempt'
    assert ctx['written_files'] == ['b.py', 'c.py'] and ctx['last_tool_success'] is True
    failed = recovery_context('goal', 'oops', rows)
    assert failed['trigger'] == 'finish_after_tool_error' and failed['tool_errors'] == 1
    assert failed['written_files'] == ['b.py', 'c.py']


def test_read_only_finish_reports_no_writes_and_final_text(tmp_path):
    (tmp_path / 'p.py').write_text('x = 1\n')
    policy = Policy({'action': 'stop'})
    loop, _ = configured_loop(tmp_path, [call('read_file', path='p.py'), ModelResponse(text='I read it.')], policy)
    asyncio.run(loop.run('Read p.py and leave it unchanged.'))
    error = policy.calls[0][0]
    assert error['trigger'] == 'finish_attempt' and error['written_files'] == []
    assert error['final_text'] == 'I read it.' and error['goal'].startswith('Read p.py')


def test_request_help_stops_loop_without_side_effects(tmp_path):
    policy = Policy({'action': 'request_help', 'reason': 'no matching skill'})
    loop, _ = configured_loop(tmp_path, [call('list_files'), ModelResponse(text='Not sure')], policy)
    result = asyncio.run(loop.run('Inspect files and write out.txt.'))
    assert result.stop_reason == 'help_requested'
    assert len(result.tool_calls_executed) == 1 and not (tmp_path / 'out.txt').exists()
    assert loop.recovery_events[-1]['help_reason'] == 'no matching skill'
