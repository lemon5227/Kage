import asyncio
import hashlib
import json
from pathlib import Path

from core.evolvable.recovery_help import recover
from core.model_provider import ModelResponse
from test_agentic_loop_multistep import call
from test_evolution_self_modify import configured_loop

SOURCE = Path(__file__).resolve().parents[1] / 'core/evolvable/recovery_help.py'


def test_four_rule_combinations():
    assert recover({'trigger': 'finish_attempt', 'goal': 'Implement f in a.py', 'written_files': ['a.py']}, [], [])['action'] == 'stop'
    assert recover({'trigger': 'finish_attempt', 'goal': 'Implement f in a.py', 'written_files': []}, [], [])['action'] == 'request_help'
    assert recover({'trigger': 'finish_attempt', 'goal': 'Read a.py and summarize it', 'written_files': []}, [], [])['action'] == 'stop'
    assert recover({'trigger': 'finish_after_tool_error', 'goal': 'Tell me about a.py', 'written_files': []}, [], [])['action'] == 'request_help'


def test_real_loop_and_sandboxed_bundle_request_help(tmp_path):
    from core.evolution.bundle import RecoveryPolicy
    from core.evolution.sandbox import ProcessSkillRunner
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    code = SOURCE.read_text()
    (bundle / 'recovery.py').write_text(code)
    (bundle / 'manifest.json').write_text(json.dumps({'version': 1, 'skills': [], 'modules': {'recovery': {
        'entrypoint': 'recovery.py:recover', 'digest': hashlib.sha256(code.encode()).hexdigest()}}}))
    policy = RecoveryPolicy.from_bundle(bundle, runner=ProcessSkillRunner())
    ws = tmp_path / 'ws'
    ws.mkdir()
    loop, _ = configured_loop(ws, [call('list_files'), ModelResponse(text='Not sure how')], policy)
    result = asyncio.run(loop.run('Implement count(lines) in stats.py and save it.'))
    assert result.stop_reason == 'help_requested'
    assert not (ws / 'stats.py').exists()


def test_stream_run_help_bundle_loads_as_recovery_policy(tmp_path):
    import importlib.util
    from core.evolution.bundle import RecoveryPolicy
    from core.evolution.sandbox import ProcessSkillRunner
    spec = importlib.util.spec_from_file_location(
        'stream_run_help_under_test', Path(__file__).resolve().parents[1] / 'scripts/experiments/stream_run.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    policy = RecoveryPolicy.from_bundle(module.help_bundle(tmp_path / 'b'), runner=ProcessSkillRunner())
    assert policy.identity()['module_sha256'] == hashlib.sha256(SOURCE.read_bytes()).hexdigest()
