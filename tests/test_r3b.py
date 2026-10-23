"""R3b: replay conversion, reasoning filter and the Colab training mix (no network, no GPU)."""
import json

import pytest

from scripts.experiments import kaggle_e1, r3_data, replay_data


def _traj(completed='true', align=8, steps=None):
    steps = steps or [
        {'value': {'observation': 'Settings window open', 'thought': 'I should open Display',
                   'action': 'Click Display', 'last_step_correct': 'True', 'last_step_redundant': 'False'}},
        {'value': {'observation': 'Display pane', 'thought': 'redundant', 'action': 'Click Display again',
                   'last_step_correct': 'True', 'last_step_redundant': 'True'}},
        {'value': {'observation': 'Display pane', 'thought': 'Now pick Night Shift',
                   'action': 'Click Night Shift', 'last_step_correct': 'True', 'last_step_redundant': 'False'}},
    ]
    return {'task_completed': completed, 'alignment_score': align, 'natural_language_task': 'Turn on Night Shift',
            'traj': steps}


def test_agentnet_keeps_good_steps_of_completed_trajectories_as_reasoned_tool_calls():
    rows, stats = replay_data.agentnet_rows([_traj(), _traj(completed='false'), _traj(align=3)], n=10)
    assert stats['skipped_incomplete'] == 2 and len(rows) == 2           # redundant step rejected
    for row in rows:
        assert row['family'] == 'replay_agentnet' and row['target']['content'].strip()
        call = row['target']['tool_calls'][0]['function']
        assert call['name'] == 'computer_action' and call['arguments']['action'].startswith('Click')
    later = [r for r in rows if 'Night Shift' in r['target']['tool_calls'][0]['function']['arguments']['action']][0]
    assert 'Actions already taken:' in later['messages'][-1]['content']   # earlier actions are history


def test_toucan_takes_the_first_reasoned_turn_and_merges_its_tool_calls():
    rec = {'tools': json.dumps([{'type': 'function', 'function': {'name': 'a'}}]), 'messages': json.dumps([
        {'role': 'user', 'content': 'do x'},
        {'role': 'assistant', 'content': 'I will call a and b.'},
        {'role': 'tool_call', 'content': "{'name': 'a', 'arguments': '{\"k\": 1}'}"},
        {'role': 'tool_call', 'content': "{'name': 'b', 'arguments': '{}'}"},
        {'role': 'tool_response', 'content': 'ok'}])}
    silent = {'tools': '[]', 'messages': json.dumps([
        {'role': 'user', 'content': 'y'}, {'role': 'assistant', 'content': ''},
        {'role': 'tool_call', 'content': "{'name': 'a', 'arguments': '{}'}"}])}
    rows, stats = replay_data.toucan_rows([rec, silent], n=5)
    assert len(rows) == 1 and stats['no_reasoned_call'] == 1
    calls = rows[0]['target']['tool_calls']
    assert [c['function']['name'] for c in calls] == ['a', 'b'] and calls[0]['function']['arguments'] == {'k': 1}


def _r2_row(task_id, content, family='csv_transform'):
    return {'task_id': task_id, 'family': family, 'negative': False, 'tools': [],
            'messages': [{'role': 'user', 'content': task_id}],
            'target': {'role': 'assistant', 'content': content,
                       'tool_calls': [{'type': 'function', 'function': {'name': 'read_file', 'arguments': {}}}]}}


def test_require_reasoning_drops_silent_calls_and_replay_goes_to_train_only(tmp_path):
    sft = tmp_path / 'sft.jsonl'
    sft.write_text('\n'.join(json.dumps(_r2_row(f'stream-v1-csv_transform-{13000 + i}', '' if i % 2 else 'plan'))
                             for i in range(8)) + '\n')
    replay = tmp_path / 'replay.jsonl'
    replay.write_text(json.dumps({'family': 'replay_toucan', 'messages': [], 'target': {}}) + '\n')
    stats = r3_data.build([sft], tmp_path / 'out', require_reasoning=True, replay=[replay])
    assert stats['dropped']['no_reasoning'] == 4
    assert stats['rows']['train'].get('replay_toucan') == 1 and 'replay_toucan' not in stats['rows']['val']


def test_replay_rows_must_be_marked(tmp_path):
    sft = tmp_path / 'sft.jsonl'
    sft.write_text(json.dumps(_r2_row('stream-v1-csv_transform-13000', 'plan')) + '\n')
    bad = tmp_path / 'bad.jsonl'
    bad.write_text(json.dumps({'family': 'csv_transform'}) + '\n')
    with pytest.raises(SystemExit):
        r3_data.build([sft], tmp_path / 'out', replay=[bad])


def test_r3b_train_packages_final_and_epoch_adapters(tmp_path, monkeypatch):
    import tarfile
    monkeypatch.setattr(kaggle_e1, 'OUT', tmp_path / 'e1')
    monkeypatch.setattr(kaggle_e1, 'WORK', tmp_path)
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'data-stats.json').write_text('{}')
    replay = tmp_path / 'replay' / 'replay.jsonl'
    replay.parent.mkdir()
    replay.write_text('')
    (replay.parent / 'replay-stats.json').write_text('{}')
    seen = {}

    def fake_adapter(linfo, data_dir, out, extra):
        seen['extra'] = extra
        (out / 'adapter-epoch1').mkdir(parents=True)
        (out / 'adapter.gguf').write_bytes(b'g')
        return out / 'adapter.gguf'

    def fake_sh(cmd, **kw):
        seen.setdefault('sh', []).append(cmd)
        if '--outfile' in cmd:
            open(cmd[cmd.index('--outfile') + 1], 'wb').write(b'e1')

    monkeypatch.setattr(kaggle_e1, 'lora_setup', lambda: {'converter': 'conv.py', 'hf_model': 'hf'})
    monkeypatch.setattr(kaggle_e1, 'prepare_replay', lambda: replay)
    monkeypatch.setattr(kaggle_e1, 'prepare_r3_data', lambda extra, name, sft=None: (seen.update(data_extra=extra), data)[1])
    monkeypatch.setattr(kaggle_e1, 'r3_adapter', fake_adapter)
    monkeypatch.setattr(kaggle_e1, 'sh', fake_sh)
    kaggle_e1.r3b_train_only()
    assert '--require-reasoning' in seen['data_extra'] and str(kaggle_e1.R2_CONTROL) in seen['data_extra']
    assert '--save-epochs' in seen['extra']
    with tarfile.open(tmp_path / 'r3b-adapter.tar.gz') as tar:
        names = set(tar.getnames())
    assert {'r3b-adapter/adapter.gguf', 'r3b-adapter/adapter-epoch1.gguf', 'r3b-adapter/replay-stats.json'} <= names


def test_lora_train_accepts_save_epochs():
    from scripts.experiments import lora_train
    args = lora_train.build_parser().parse_args(['--data', 'd', '--model', 'm', '--out', 'o', '--save-epochs'])
    assert args.save_epochs


def test_less_diverse_top_respects_the_cluster_cap_and_score_order():
    from scripts.experiments import less_select
    scores = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4]
    clusters = [0, 0, 0, 1, 1, 2]
    # n=3 over 3 clusters -> cap ceil(2*3/3) = 2 per cluster
    assert less_select.diverse_top(scores, clusters, 3, 3) == [0, 1, 3]


def test_r3c_wires_warmup_selection_and_training(tmp_path, monkeypatch):
    import gzip
    monkeypatch.setattr(kaggle_e1, 'OUT', tmp_path / 'e1')
    (tmp_path / 'e1').mkdir()
    pool = tmp_path / 'pool' / 'replay.jsonl'
    pool.parent.mkdir()
    pool.write_text(''.join(json.dumps({'family': 'replay_toucan', 'i': i}) + '\n' for i in range(100)))
    control = tmp_path / 'control.jsonl.gz'
    with gzip.open(control, 'wt') as f:
        f.write(json.dumps(_r2_row('stream-v1-csv_transform-13000', 'plan')) + '\n')
        f.write(json.dumps(_r2_row('stream-v1-csv_transform-13001', '')) + '\n')
    monkeypatch.setattr(kaggle_e1, 'R2_CONTROL', control)
    calls = []

    def fake_sh(cmd, **kw):
        calls.append(cmd)
        if 'less_select.py' in cmd[1]:
            out = Path(cmd[cmd.index('--out') + 1])
            out.mkdir(parents=True)
            (out / 'replay.jsonl').write_text('')
            (out / 'replay-stats.json').write_text('{"selected": 0}')

    from pathlib import Path
    monkeypatch.setattr(kaggle_e1, 'sh', fake_sh)
    monkeypatch.setattr(kaggle_e1, 'lora_setup', lambda: {'hf_model': 'hf', 'converter': 'c'})
    monkeypatch.setattr(kaggle_e1, 'prepare_replay', lambda n, name: pool)
    monkeypatch.setattr(kaggle_e1, 'prepare_r3_data', lambda extra, name, sft=None: tmp_path / name)
    trained = {}
    monkeypatch.setattr(kaggle_e1, 'train_mix', lambda linfo, replay, tag, smoke: trained.update(replay=replay, tag=tag))
    kaggle_e1.r3c_train_only()
    warm = [c for c in calls if 'lora_train.py' in c[1]][0]
    assert '--save-optimizer' in warm and len((tmp_path / 'e1' / 'r3c-warmup.jsonl').read_text().splitlines()) == 20
    less = [c for c in calls if 'less_select.py' in c[1]][0]
    assert any(a.startswith('own=') for a in less) and any(a.startswith('task=') for a in less)
    assert len((tmp_path / 'e1' / 'r3c-own.jsonl').read_text().splitlines()) == 1   # reasonless control row dropped
    assert trained['tag'] == 'r3c' and trained['replay'].name == 'replay.jsonl'


def test_r3d_uses_rationalized_data_and_prefers_the_less_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(kaggle_e1, 'OUT', tmp_path / 'e1')
    less = tmp_path / 'e1' / 'replay-less' / 'replay.jsonl'
    less.parent.mkdir(parents=True)
    less.write_text('')
    seen = {}
    monkeypatch.setattr(kaggle_e1, 'lora_setup', lambda: {})
    monkeypatch.setattr(kaggle_e1, 'prepare_replay', lambda *a, **k: (_ for _ in ()).throw(AssertionError('random')))
    monkeypatch.setattr(kaggle_e1, 'train_mix', lambda linfo, replay, tag, smoke, sft=None, control=None:
                        seen.update(replay=replay, tag=tag, sft=sft, control=control))
    kaggle_e1.r3d_train_only()
    assert seen['replay'] == less and seen['tag'] == 'r3d'
    assert seen['sft'].name == 'sft-v21-rationalized.jsonl.gz' and 'control' in seen['control'].name


def test_rationale_filter_rejects_hint_talk_and_empty_text():
    from scripts.experiments import rationalize
    assert rationalize.acceptable('No matching skill was found, so I will write the implementation directly.')
    assert not rationalize.acceptable('Following the lesson from earlier tasks, I will click Save.')
    assert not rationalize.acceptable('')
    row = {'messages': [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'Fix x.py'}],
           'target': {'role': 'assistant', 'content': '', 'tool_calls': [
               {'type': 'function', 'function': {'name': 'read_file', 'arguments': {'path': 'x.py'}}}]}}
    assert rationalize.reasonless(row)
    msgs = rationalize.prompt_messages(row)
    assert 'Fix x.py' in msgs[1]['content'] and 'read_file' in msgs[1]['content']
