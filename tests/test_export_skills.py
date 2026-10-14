import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

CODE = '''def run(arguments, context):
    from pathlib import Path
    path = Path(context["workspace_dir"]) / arguments["file_path"]
    path.write_text("def f():\\n    return 1\\n")
    return {"success": True, "written": arguments["file_path"]}
'''


def load():
    path = Path(__file__).resolve().parents[1] / 'scripts/export_skills.py'
    spec = importlib.util.spec_from_file_location('export_skills_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_bundle(root: Path) -> Path:
    root.mkdir()
    descriptor = {'skill_id': 'write_stub', 'description': 'Write a stub: function. Only for "implement f" tasks.',
                  'parameters': {'type': 'object', 'properties': {'file_path': {'type': 'string'}},
                                 'required': ['file_path']},
                  'entrypoint': 'skill-a.py:run'}
    canonical = json.dumps(descriptor, sort_keys=True, separators=(',', ':'), allow_nan=False)
    descriptor['digest'] = hashlib.sha256(canonical.encode() + b'\n' + CODE.encode()).hexdigest()
    (root / 'skill-a.py').write_text(CODE)
    (root / 'manifest.json').write_text(json.dumps({'version': 1, 'skills': [descriptor]}))
    return root


def test_export_writes_skill_md_and_runnable_script(tmp_path):
    E = load()
    bundle = make_bundle(tmp_path / 'bundle')
    out = tmp_path / 'out'
    E.main(['--bundle', str(bundle), '--out', str(out)])
    md = (out / 'write_stub' / 'SKILL.md').read_text()
    assert md.startswith('---\n') and len(md.splitlines()) <= 60
    header = md.split('---\n')[1]
    yaml = pytest.importorskip('yaml')
    meta = yaml.safe_load(header)
    assert meta['name'] == 'write_stub' and meta['description'].startswith('Write a stub:')
    assert '## When not to use' in md and '`file_path`' in md
    work = tmp_path / 'work'
    work.mkdir()
    proc = subprocess.run([sys.executable, str(out / 'write_stub' / 'scripts' / 'skill.py'),
                           json.dumps({'file_path': 'x.py'}), str(work)], capture_output=True, text=True, check=True)
    assert json.loads(proc.stdout)['success'] is True
    assert (work / 'x.py').read_text().startswith('def f()')


def test_export_refuses_tampered_bundle(tmp_path):
    E = load()
    bundle = make_bundle(tmp_path / 'bundle')
    (bundle / 'skill-a.py').write_text(CODE + '\n# changed\n')
    with pytest.raises(ValueError):
        E.export(bundle, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_provenance_from_stream_root(tmp_path):
    E = load()
    bundle = make_bundle(tmp_path / 'bundle')
    arm = tmp_path / 'A4'
    (arm / 'mutations' / 't1').mkdir(parents=True)
    (arm / 'mutations' / 't1' / 'proposal.json').write_text(json.dumps({'candidate': {'bundle_path': str(bundle)}}))
    (arm / 'stream.jsonl').write_text(json.dumps({'task_id': 't1', 'family': 'log_aggregation', 'index': 3,
                                                  'learning': {'accepted': True, 'check_score': 1.0}}) + '\n')
    E.export(bundle, tmp_path / 'out', arm)
    md = (tmp_path / 'out' / 'write_stub' / 'SKILL.md').read_text()
    assert '`t1`' in md and 'stream task 3' in md
