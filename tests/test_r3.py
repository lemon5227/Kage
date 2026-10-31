"""R3: LoRA data guards, train-log bookkeeping, and Kaggle r3/r3-smoke job construction.

No network, no GPU, no torch: lora_train imports torch only inside main().
"""
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from scripts.experiments import kaggle_e1, lora_train, r3_data


def _row(task_id: str, family: str, *, messages=None, target=None, negative: bool = False,
         attempt: int = 0) -> dict:
    return {
        'task_id': task_id, 'family': family, 'negative': negative, 'writes': False, 'tools': [],
        'messages': messages if messages is not None else [{'role': 'system', 'content': 'frozen soul'},
                                                          {'role': 'user', 'content': task_id}],
        'target': target if target is not None else {'role': 'assistant', 'content': 'done'},
        'source': 'rsr', 'attempt': attempt, 'guidance': [],
    }


def _jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
    return path


def _gzip(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wt') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    return path


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _out_rows(out: Path) -> list[dict]:
    return _read(out / 'train.jsonl') + _read(out / 'val.jsonl')


# ---------------------------------------------------------------- r3_data guards
@pytest.mark.parametrize('family', r3_data.TRANSFER_FAMILIES)
def test_refuses_transfer_families(tmp_path, family):
    sft = _jsonl(tmp_path / 'sft.jsonl', [_row(f'stream-v1-{family}-13000', family)])
    with pytest.raises(SystemExit) as exc:
        r3_data.main(['--sft', str(sft), '--out', str(tmp_path / 'out')])
    assert family in str(exc.value)
    assert not (tmp_path / 'out' / 'train.jsonl').exists()


@pytest.mark.parametrize('seed,split', [(9000, 'eval'), (5000, 'calibration'), (17000, 'validation')])
def test_refuses_non_practice_seeds(tmp_path, seed, split):
    sft = _jsonl(tmp_path / 'sft.jsonl', [_row(f'stream-v1-log_aggregation-{seed}', 'log_aggregation')])
    with pytest.raises(SystemExit) as exc:
        r3_data.main(['--sft', str(sft), '--out', str(tmp_path / 'out')])
    assert split in str(exc.value)


def test_refuses_a_malformed_task_id(tmp_path):
    sft = _jsonl(tmp_path / 'sft.jsonl', [_row('stream-v1-log_aggregation-last', 'log_aggregation')])
    with pytest.raises(SystemExit) as exc:
        r3_data.main(['--sft', str(sft), '--out', str(tmp_path / 'out')])
    assert 'numeric seed' in str(exc.value)


# ---------------------------------------------------------------- r3_data filtering
@pytest.mark.parametrize('marker', r3_data.GUIDANCE_MARKERS)
def test_drops_and_counts_guidance_remnants(tmp_path, marker):
    clean = _row('stream-v1-log_aggregation-13000', 'log_aggregation')
    dirty = _row('stream-v1-log_aggregation-13001', 'log_aggregation',
                 messages=[{'role': 'system', 'content': 'frozen soul' + marker + 'do X'}])
    sft = _jsonl(tmp_path / 'sft.jsonl', [clean, dirty])
    stats = r3_data.build([sft], tmp_path / 'out', val_frac=0.0)
    assert stats['dropped']['guidance_remnant'] == 1
    assert stats['rows_out'] == {'train': 1, 'val': 0}
    assert [row['task_id'] for row in _out_rows(tmp_path / 'out')] == [clean['task_id']]


def test_dedupes_identical_messages_and_target(tmp_path):
    row = _row('stream-v1-log_aggregation-13000', 'log_aggregation')
    same_content_new_task = _row('stream-v1-log_aggregation-13001', 'log_aggregation',
                                 messages=row['messages'], target=row['target'])
    sft = _jsonl(tmp_path / 'sft.jsonl', [row, dict(row), same_content_new_task])
    stats = r3_data.build([sft], tmp_path / 'out', val_frac=0.0)
    assert stats['dropped']['duplicate'] == 2
    assert stats['rows_out'] == {'train': 1, 'val': 0}


def test_per_family_cap_is_uniform_and_includes_negatives(tmp_path):
    rows = []
    for index in range(12):
        rows.append(_row(f'stream-v1-log_aggregation-{13000 + index}', 'log_aggregation',
                         target={'role': 'assistant', 'content': f'answer {index}'}))
    for index in range(2):
        rows.append(_row(f'stream-v1-subset_selection-{13000 + index}', 'subset_selection'))
    for index in range(5):
        rows.append(_row(f'stream-v1-read_preserve-{13000 + index}', 'read_preserve', negative=True))
    sft = _jsonl(tmp_path / 'sft.jsonl', rows)
    first = r3_data.build([sft], tmp_path / 'out1', cap=3, val_frac=0.0)
    second = r3_data.build([sft], tmp_path / 'out2', cap=3, val_frac=0.0)

    assert first['rows_out'] == {'train': 8, 'val': 0}
    assert first['rows']['train'] == {'log_aggregation': 3, 'read_preserve': 3, 'subset_selection': 2}
    assert first['dropped']['cap'] == 9 + 2
    assert (tmp_path / 'out1' / 'train.jsonl').read_text() == (tmp_path / 'out2' / 'train.jsonl').read_text()


def test_split_is_by_task_id_and_never_splits_a_task(tmp_path):
    rows = []
    for task in range(50):
        for attempt in range(2):
            rows.append(_row(f'stream-v1-log_aggregation-{13000 + task}', 'log_aggregation', attempt=attempt,
                             target={'role': 'assistant', 'content': f'task {task} attempt {attempt}'}))
    sft = _jsonl(tmp_path / 'sft.jsonl', rows)
    stats = r3_data.build([sft], tmp_path / 'out', val_frac=0.5)

    train = _read(tmp_path / 'out' / 'train.jsonl')
    val = _read(tmp_path / 'out' / 'val.jsonl')
    train_tasks = {row['task_id'] for row in train}
    val_tasks = {row['task_id'] for row in val}
    assert train_tasks and val_tasks
    assert not train_tasks & val_tasks
    assert len(train_tasks | val_tasks) == 50
    assert stats['tasks'] == {'train': len(train_tasks), 'val': len(val_tasks)}
    assert stats['rows_out'] == {'train': len(train), 'val': len(val)}


def test_writes_stats_with_family_counts_drops_and_sha256(tmp_path):
    rows = [
        _row('stream-v1-log_aggregation-13000', 'log_aggregation'),
        _row('stream-v1-log_aggregation-13001', 'log_aggregation'),
        _row('stream-v1-read_preserve-13000', 'read_preserve', negative=True),
    ]
    sft = _jsonl(tmp_path / 'sft.jsonl', rows)
    stats = r3_data.build([sft], tmp_path / 'out', val_frac=0.0)

    stored = json.loads((tmp_path / 'out' / 'data-stats.json').read_text())
    assert stored == stats
    assert stored['rows_in'] == 3
    assert stored['rows'] == {'train': {'log_aggregation': 2, 'read_preserve': 1}, 'val': {}}
    assert stored['dropped'] == {'guidance_remnant': 0, 'duplicate': 0, 'cap': 0}
    assert stored['inputs'][0]['sha256'] == hashlib.sha256(sft.read_bytes()).hexdigest()
    for name in ('train.jsonl', 'val.jsonl'):
        assert stored['sha256'][name] == hashlib.sha256((tmp_path / 'out' / name).read_bytes()).hexdigest()


def test_accepts_gzip_input(tmp_path):
    sft = _gzip(tmp_path / 'sft.jsonl.gz', [_row('stream-v1-web_invoice-13000', 'web_invoice')])
    stats = r3_data.build([sft], tmp_path / 'out', val_frac=0.0)
    assert stats['rows_out'] == {'train': 1, 'val': 0}
    assert stats['inputs'][0]['rows'] == 1


# ---------------------------------------------------------------- lora_train
def test_readback_inserts_an_exact_read_between_the_last_write_and_the_final_answer(tmp_path):
    write = {'role': 'assistant', 'content': '', 'tool_calls': [{'type': 'function', 'function': {
        'name': 'write_file', 'arguments': {'path': 'ops.py', 'content': 'def f():\n    return "é"\n'}}}]}
    result = {'role': 'tool', 'tool_call_id': 'call_x', 'content': '[Tool: write_file] {"success": true}'}
    base = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'u'}, write, result]
    final = {'role': 'assistant', 'content': 'done'}
    rows = [_row('stream-v1-interval_merge-13000', 'interval_merge', messages=base, target=final),
            _row('stream-v1-interval_merge-13000', 'interval_merge', messages=base[:2], target=write),
            _row('stream-v1-read_preserve-13001', 'read_preserve', messages=base, target=final, negative=True)]
    sft = _jsonl(tmp_path / 'sft.jsonl', rows)
    r3_data.main(['--sft', str(sft), '--out', str(tmp_path / 'out'), '--val-frac', '0', '--readback'])
    out = _out_rows(tmp_path / 'out')
    call = next(r for r in out if r.get('readback') == 'call')
    after = next(r for r in out if r.get('readback') == 'final')
    assert call['messages'] == base and call['target']['tool_calls'][0]['function'] == {
        'name': 'read_file', 'arguments': {'path': 'ops.py'}}
    assert after['target'] == final and after['messages'][-2] == call['target']
    assert after['messages'][-1]['content'] == '[Tool: read_file] {"success": true, "path": "ops.py", "content": "def f():\\n    return \\"é\\"\\n"}'
    assert sum(1 for r in out if 'readback' not in r) == 2       # the earlier step and the negative row are untouched
    assert json.loads((tmp_path / 'out' / 'data-stats.json').read_text())['readback'] == {'rows_added': 1}


def test_lora_parser_accepts_val_and_defaults_to_none():
    parser = lora_train.build_parser()
    args = parser.parse_args(['--data', 'train.jsonl', '--model', 'base', '--out', 'adapter',
                              '--val', 'val.jsonl'])
    assert args.val == Path('val.jsonl')
    assert parser.parse_args(['--data', 'train.jsonl', '--model', 'base', '--out', 'adapter']).val is None


def test_train_log_writer_records_train_and_val_rows(tmp_path):
    path = tmp_path / 'train-log.jsonl'
    path.write_text('stale\n')
    log = lora_train.TrainLog(path)
    log.append(lora_train.loss_record(1, 10, 1.23456789))
    log.append(lora_train.loss_record(1, 20, 0.5, 0.25))

    rows = _read(path)
    assert rows == [
        {'epoch': 1, 'step': 10, 'train_loss': 1.234568, 'val_loss': None},
        {'epoch': 1, 'step': 20, 'train_loss': 0.5, 'val_loss': 0.25},
    ]


# ---------------------------------------------------------------- kaggle_e1
@pytest.mark.parametrize('prefix', ['model.language_model.', 'model.'])
def test_lora_targets_match_decoder_layers_under_both_loaders_and_never_vision(prefix):
    # v23: transformers 5 loads Agents-A1-4B as a causal LM whose layers are `model.layers.N`;
    # the old `.*language_model.*` pattern matched nothing.
    import re
    safe, full = lora_train.TARGETS['safe'], lora_train.TARGETS['full']
    assert re.fullmatch(safe, prefix + 'layers.3.self_attn.o_proj')
    assert not re.fullmatch(safe, prefix + 'layers.0.linear_attn.out_proj')   # converter cannot reorder it
    assert re.fullmatch(safe, prefix + 'layers.7.mlp.down_proj')
    assert not re.fullmatch(safe, prefix + 'layers.3.self_attn.q_proj')
    assert not re.fullmatch(safe, prefix + 'layers.0.linear_attn.in_proj_qkv')
    assert re.fullmatch(full, prefix + 'layers.0.linear_attn.in_proj_qkv')
    for name in ('model.visual.blocks.0.attn.qkv', 'model.visual.blocks.0.mlp.linear_fc1', 'lm_head'):
        assert not re.fullmatch(safe, name) and not re.fullmatch(full, name)


def test_r3_general_jobs_carry_the_adapter_only_for_l3_and_summary_marks_missing(tmp_path):
    adapter = tmp_path / 'adapter.gguf'
    jobs = kaggle_e1.r3_general_jobs(adapter)
    assert [name for name, _, _ in jobs] == ['general-L3', 'general-A0']
    assert jobs[0][2] == {'KAGE_LORA': str(adapter)} and jobs[1][2] == {}
    assert jobs[0][1][0] == 'scripts/experiments/general_check.py'
    summary = kaggle_e1.r3_general_summary([('general-A0', ['--root', str(tmp_path / 'nope')], {})])
    assert summary == {'A0': {'status': 'missing'}}


def test_general_check_scoring_is_case_and_markdown_insensitive():
    from scripts.experiments import general_check
    import json
    assert general_check.passes('The answer is **391**.', ['391'])
    assert general_check.passes('`Tokyo`', ['tokyo'])
    assert not general_check.passes('392', ['391'])
    questions = json.loads(general_check.QUESTIONS.read_text())
    assert len(questions) == 30 and len({q['id'] for q in questions}) == 30


def test_r3_train_only_packages_the_adapter_and_eval_finds_it(tmp_path, monkeypatch):
    import tarfile
    monkeypatch.setattr(kaggle_e1, 'OUT', tmp_path / 'colab' / 'e1')
    monkeypatch.setattr(kaggle_e1, 'WORK', tmp_path / 'colab')
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'data-stats.json').write_text('{}')
    seen = {}

    def fake_adapter(linfo, data_dir, out, extra):
        seen['extra'] = extra
        out.mkdir(parents=True, exist_ok=True)
        (out / 'adapter.gguf').write_bytes(b'gguf')
        (out / 'train-log.jsonl').write_text('{}')
        return out / 'adapter.gguf'

    monkeypatch.setattr(kaggle_e1, 'prepare_r3_data', lambda: data)
    monkeypatch.setattr(kaggle_e1, 'lora_setup', lambda: {})
    monkeypatch.setattr(kaggle_e1, 'r3_adapter', fake_adapter)
    kaggle_e1.r3_train_only()
    assert seen['extra'][:len(kaggle_e1.R3_TRAIN_ARGS)] == kaggle_e1.R3_TRAIN_ARGS and '--val' in seen['extra']
    tarball = tmp_path / 'colab' / 'r3-adapter.tar.gz'
    with tarfile.open(tarball) as tar:
        assert {'r3-adapter/adapter.gguf', 'r3-adapter/data-stats.json'} <= set(tar.getnames())
    # Kaggle side: the uploaded tarball is found under the input dir and unpacked
    inp = tmp_path / 'input' / 'r3-adapter-v1'
    inp.mkdir(parents=True)
    tarball.rename(inp / 'r3-adapter.tar.gz')
    monkeypatch.setattr(kaggle_e1, 'INPUT', tmp_path / 'input')
    monkeypatch.setattr(kaggle_e1, 'OUT', tmp_path / 'kaggle' / 'e1')
    gguf = kaggle_e1.r3_input_adapter()
    assert gguf.read_bytes() == b'gguf'


def test_r3_eval_without_an_adapter_input_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(kaggle_e1, 'INPUT', tmp_path)
    monkeypatch.setattr(kaggle_e1, 'OUT', tmp_path / 'e1')
    with pytest.raises(SystemExit):
        kaggle_e1.r3_input_adapter()


def test_r3_scale_jobs_set_the_scale_only_on_scaled_arms_and_keep_anchors(tmp_path):
    adapter = tmp_path / 'adapter.gguf'
    jobs = kaggle_e1.r3_scale_jobs(adapter)
    names = [name for name, _, _ in jobs]
    assert len(jobs) == 2 * (3 * 3 + 2) and len({argv[-1] for _, argv, _ in jobs}) == len(jobs)
    env = {name: e for name, _, e in jobs}
    assert env['file-L3x0.5-r2'] == {'KAGE_LORA': str(adapter), 'KAGE_LORA_SCALE': '0.5'}
    assert env['file-L3x1.0-r1'] == {'KAGE_LORA': str(adapter)}
    assert env['file-A0-r1'] == {} and env['web-A0-r1']['KAGE_CTX'] == kaggle_e1.BROWSER_CTX
    assert 'KAGE_LORA' not in env['web-A0-r1']
    assert all(name.split('-', 2)[0] in ('file', 'web') for name in names)


def test_lora_argv_uses_the_scaled_form_only_when_a_scale_is_set(monkeypatch):
    from scripts.experiments import local_service
    monkeypatch.setattr(local_service, 'LORA', '/x/a.gguf')
    monkeypatch.setattr(local_service, 'LORA_SCALE', None)
    assert local_service.lora_argv() == ['--lora', '/x/a.gguf']
    monkeypatch.setattr(local_service, 'LORA_SCALE', '0.5')
    assert local_service.lora_argv() == ['--lora-scaled', '/x/a.gguf:0.5']
    monkeypatch.setattr(local_service, 'LORA', None)
    assert local_service.lora_argv() == []


def test_r3_phases_are_available():
    parser = kaggle_e1.build_parser()
    assert parser.parse_args(['--phase', 'r3-smoke']).phase == 'r3-smoke'
    assert parser.parse_args(['--phase', 'r3']).phase == 'r3'


def test_r3_eval_jobs_build_12_runs_with_distinct_ports_and_adapter_only_for_l3(tmp_path):
    adapter = tmp_path / 'adapter.gguf'
    jobs = kaggle_e1.r3_eval_jobs(adapter)

    assert [job[0] for job in jobs] == [f'{kind}-{arm}-r{index}' for kind in ('file', 'web')
                                        for arm in ('L3', 'A0') for index in (1, 2, 3)]
    ports = [int(job[1][job[1].index('--port') + 1]) for job in jobs]
    assert len(set(ports)) == len(jobs) == 12

    for name, argv, env in jobs:
        kind, arm, _ = name.split('-', 2)
        manifest = kaggle_e1.ROOT / 'eval' / ('stream_v1' if kind == 'file' else 'stream_web_v1')
        assert Path(argv[argv.index('--root') + 1]) == kaggle_e1.OUT / 'r3' / kind / f'{arm}-{name.rsplit("-", 1)[1]}'
        assert Path(argv[argv.index('--stream-manifest') + 1]) == manifest / 'stream-seed1.json'
        assert Path(argv[argv.index('--eval-manifest') + 1]) == manifest / 'eval.json'
        assert argv[argv.index('--arm') + 1] == 'A0'
        assert argv[argv.index('--eval-only') + 1] == 'cp0'
        if arm == 'L3':
            assert env['KAGE_LORA'] == str(adapter)
        else:
            assert 'KAGE_LORA' not in env
        assert ('KAGE_CTX' in env) == (kind == 'web')


def test_r3_summary_counts_passes_and_negative_misuse(tmp_path, monkeypatch):
    monkeypatch.setattr(kaggle_e1, 'OUT', tmp_path)
    root = tmp_path / 'r3' / 'file' / 'L3-r1'
    root.mkdir(parents=True)
    _jsonl(root / 'checkpoints.jsonl', [
        {'task_id': 'a', 'family': 'log_aggregation', 'negative': False, 'score': 1.0, 'misuse': False},
        {'task_id': 'b', 'family': 'log_aggregation', 'negative': False, 'score': 0.0, 'misuse': False},
        {'task_id': 'c', 'family': 'read_preserve', 'negative': True, 'score': 1.0, 'misuse': True},
    ])
    jobs = [('file-L3-r1', ['--root', str(root)], {'KAGE_LORA': 'x'})]

    summary = kaggle_e1.r3_summary(jobs)['file']['L3-r1']
    assert summary['families'] == {'log_aggregation': {'passed': 1, 'total': 2},
                                   'read_preserve': {'passed': 1, 'total': 1}}
    assert summary['negative_misuse'] == {'read_preserve': 1}
    assert (summary['passed'], summary['total'], summary['status']) == (2, 3, 'ok')
    assert kaggle_e1.r3_summary([('file-A0-r1', ['--root', str(tmp_path / 'nope')], {})])['file']['A0-r1']['status'] == 'missing'


def test_train_and_convert_default_data_path_is_unchanged(tmp_path, monkeypatch):
    calls = []

    def fake_sh(cmd, **kwargs):
        calls.append(cmd)
        if 'convert_lora_to_gguf.py' in cmd[1]:
            Path(cmd[cmd.index('--outfile') + 1]).write_bytes(b'gguf')

    monkeypatch.setattr(kaggle_e1, 'sh', fake_sh)
    monkeypatch.setattr(kaggle_e1, 'log', lambda *args, **kwargs: None)
    linfo = {'hf_model': '/base', 'converter': '/convert_lora_to_gguf.py'}

    gguf = kaggle_e1.train_and_convert(linfo, tmp_path, [])
    assert calls[0][calls[0].index('--data') + 1] == str(kaggle_e1.SFT_DATA)
    assert gguf == tmp_path / 'adapter.gguf'

    custom = tmp_path / 'train.jsonl'
    kaggle_e1.train_and_convert(linfo, tmp_path, ['--smoke'], data=custom)
    assert calls[2][calls[2].index('--data') + 1] == str(custom)


def test_r2_data_points_at_the_committed_v21_samples():
    assert kaggle_e1.R2_DATA == kaggle_e1.ROOT / 'evidence' / 'reports' / 'r2' / 'sft-v21.jsonl.gz'


def test_job_env_applies_per_job_overrides_only(monkeypatch):
    monkeypatch.delenv('KAGE_LORA', raising=False)
    monkeypatch.delenv('KAGE_CTX', raising=False)
    info = {'model': 'm.gguf', 'server': 'llama-server'}
    plain = kaggle_e1.job_env(info, 0)
    lora = kaggle_e1.job_env(info, 1, {'KAGE_LORA': 'adapter.gguf', 'KAGE_CTX': '16384'})
    assert 'KAGE_LORA' not in plain and 'KAGE_CTX' not in plain
    assert lora['KAGE_LORA'] == 'adapter.gguf' and lora['KAGE_CTX'] == '16384'
    assert lora['CUDA_VISIBLE_DEVICES'] == '1'


def test_split_is_stratified_so_every_family_with_two_tasks_is_in_both_splits(tmp_path):
    """v21 dry run: a plain hash split put a whole negative family into val (none in train)."""
    rows = []
    for family, n_tasks in (('log_aggregation', 20), ('inspect_question', 2), ('web_prefs', 8), ('read_preserve', 1)):
        for task in range(n_tasks):
            rows.append(_row(f'stream-v1-{family}-{13000 + task}', family,
                             target={'role': 'assistant', 'content': f'{family} {task}'}))
    stats = r3_data.build([_jsonl(tmp_path / 'sft.jsonl', rows)], tmp_path / 'out', val_frac=0.1)
    assert stats['tasks']['val'] == 2 + 1 + 1         # round(0.1 * 20) = 2; at least 1 for 2 and 8 tasks
    for family in ('log_aggregation', 'inspect_question', 'web_prefs'):
        assert stats['rows']['train'].get(family) and stats['rows']['val'].get(family), family
    assert 'read_preserve' not in stats['rows']['val']  # a single task stays in train


def test_r3t_variant_tags_name_the_adapter_and_its_data_change():
    assert kaggle_e1.r3t_variant('2') == ('r3t2', 2, [])
    assert kaggle_e1.r3t_variant('g0') == ('r3g0', 0, ['--readback'])
    for bad in ('x1', 'g', 'smoke'):
        with pytest.raises(SystemExit):
            kaggle_e1.r3t_variant(bad)
