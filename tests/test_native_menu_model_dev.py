"""Offline contracts for selecting and freezing the single TextEdit dev attempt."""
import hashlib
import json
import sys

import pytest

from scripts.experiments import native_menu_model_dev as dev


class StopBeforeModel(Exception):
    pass


@pytest.mark.parametrize('selection, task_id, filename, expected', [
    ([], 'native_menu_repair_dev1', 'kage-menu-repair-dev1.txt',
     'Kage native menu dev.\nStatus: verified through TextEdit.\n'),
    (['--task', 'dev1'], 'native_menu_repair_dev1', 'kage-menu-repair-dev1.txt',
     'Kage native menu dev.\nStatus: verified through TextEdit.\n'),
    (['--task', 'dev2'], 'native_menu_unicode_dev2', 'kage-menu-unicode-dev2.txt',
     '项目进度\n状态：已保存\n复核：AX + 磁盘\n'),
    (['--task', 'dev3'], 'native_text_recovery_dev3', 'kage-text-recovery-dev3.txt',
     '项目复核\n结论：已核对\n操作：保存并读回\n'),
])
def test_selected_task_reaches_existing_chain_and_freeze(monkeypatch, tmp_path, selection, task_id, filename, expected):
    output = tmp_path / 'attempt'
    monkeypatch.setattr(sys, 'argv', ['dev', '--output', str(output), *selection])
    monkeypatch.setattr(dev.subprocess, 'check_output',
                        lambda command, **kwargs: '' if 'status' in command else 'committed-revision')

    class Service:
        def __init__(self, port, output):
            self.runtime = {'model_sha256': 'offline-test'}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(dev, 'LocalService', Service)
    monkeypatch.setattr(dev, 'local_broker', lambda port: type('Broker', (), {'background_provider': None})())
    monkeypatch.setattr(dev, 'DeterministicLocalModel', lambda provider: provider)
    selected = [];prompts=[]
    def stop(provider, task, **kwargs):
        selected.append(task)
        prompts.append(kwargs.get('native_soul',dev.NATIVE_SOUL))
        raise StopBeforeModel
    monkeypatch.setattr(dev, 'NativeChainProvider', stop)
    with pytest.raises(StopBeforeModel):
        dev.main()
    task = selected[0]
    assert task['task_id'] == task_id
    assert task['document_name'] == task['output_file'] == filename
    assert task['expected'].encode('utf-8') == expected.encode('utf-8')
    assert json.loads(task['instruction'].split('Exact JSON text:\n')[1]) == expected
    assert list(task['initial_files']) == [filename]
    frozen = json.loads((output / 'freeze.json').read_text())
    assert frozen['task'] == task
    assert frozen['selected_task'] == (selection[1] if selection else 'dev1')
    assert frozen['prompt']==prompts[0]
    if selection==['--task','dev3']:
        assert 'then open the document menu and press its Save command' not in prompts[0]
        assert 'verify the returned text value' in prompts[0]
    else:
        assert prompts[0]==dev.NATIVE_SOUL
    assert frozen['task_sha256'] == hashlib.sha256(json.dumps(task, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    assert frozen['protocol_sha256'] == hashlib.sha256(json.dumps(frozen['protocol'], sort_keys=True).encode()).hexdigest()
    test_name = 'tests/test_native_menu_model_dev.py'
    assert frozen['source_hashes'][test_name] == hashlib.sha256((dev.ROOT / test_name).read_bytes()).hexdigest()


def test_invalid_task_rejected_before_service_or_output(monkeypatch, tmp_path):
    output = tmp_path / 'invalid'
    monkeypatch.setattr(sys, 'argv', ['dev', '--output', str(output), '--task', 'unknown'])
    def forbidden(*args, **kwargs):
        pytest.fail('invalid selection reached service or git preflight')
    monkeypatch.setattr(dev, 'LocalService', forbidden)
    monkeypatch.setattr(dev.subprocess, 'check_output', forbidden)
    with pytest.raises(SystemExit) as error:
        dev.main()
    assert error.value.code == 2
    assert not output.exists()
