import importlib.util
from pathlib import Path

EXP = Path(__file__).resolve().parents[1] / 'scripts/experiments'


def load(name):
    spec = importlib.util.spec_from_file_location(f'{name}_under_test', EXP / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extracted_service_keeps_the_frozen_runtime():
    from scripts.experiments import native_model_pilot as native
    local = load('local_service')
    # Same frozen runtime as the native pilots, plus the host prompt cache disabled (memory only).
    assert local.server_argv(18082) == native.server_argv(18082) + ['--cache-ram', '0']
    assert (local.MODEL, local.SERVER) == (native.MODEL, native.SERVER)


def test_stream_scripts_no_longer_import_native_code():
    for name in ('stream_run.py', 'stream_calibrate.py'):
        text = (EXP / name).read_text()
        assert 'native_model_pilot' not in text and 'from local_service import LocalService' in text
