"""Export a Kage skill bundle as Agent Skills folders (SKILL.md + scripts/skill.py).

  python scripts/export_skills.py --bundle <skill library dir> --out <dir> [--stream-root <stream arm dir>]

SKILL.md keeps a short YAML header (name, description) for progressive loading; the
body lists parameters, when to use / not use, and provenance. With --stream-root the
provenance names the teacher-demonstrated task each skill was learned from and its
re-check result. The script copies the verified source byte-for-byte (the bundle digest
is checked first) and adds a small CLI wrapper around run(arguments, context).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.evolution.skills import SkillCatalog

CLI = '''

if __name__ == "__main__":
    # python skill.py '<json arguments>' <workspace dir>
    import json as _json
    import sys as _sys
    _args = _json.loads(_sys.argv[1])
    _workspace = _sys.argv[2] if len(_sys.argv) > 2 else "."
    print(_json.dumps({entry}(_args, {{"workspace_dir": _workspace}}), ensure_ascii=False))
'''


def provenance(stream_root: Path | None) -> dict[str, dict]:
    """skill_id -> first accepted learning event that introduced it."""
    if stream_root is None or not (stream_root / 'stream.jsonl').exists():
        return {}
    seen: dict[str, dict] = {}
    for line in (stream_root / 'stream.jsonl').read_text().splitlines():
        row = json.loads(line)
        learning = row.get('learning') or {}
        if not learning.get('accepted'):
            continue
        proposal = stream_root / 'mutations' / row['task_id'] / 'proposal.json'
        if not proposal.exists():
            continue
        bundle = Path(json.loads(proposal.read_text())['candidate']['bundle_path'])
        for item in json.loads((bundle / 'manifest.json').read_text())['skills']:
            seen.setdefault(item['skill_id'], {'task_id': row['task_id'], 'family': row.get('family'),
                                               'check_score': learning.get('check_score'),
                                               'stream_index': row.get('index')})
    return seen


def _yaml_str(text: str) -> str:
    return json.dumps(' '.join(str(text).split()), ensure_ascii=False)   # JSON strings are valid YAML


def skill_md(item: dict, source: dict | None) -> str:
    params = item['parameters']
    required = set(params.get('required', []))
    rows = [f"| `{name}` | {spec.get('type', spec.get('enum', ''))} | {'yes' if name in required else 'no'} |"
            for name, spec in params.get('properties', {}).items()]
    origin = (f"Learned from teacher demonstration `{source['task_id']}` (family `{source['family']}`, "
              f"stream task {source['stream_index']}); student re-check score {source['check_score']}."
              if source else 'Provenance not recorded for this export.')
    lines = ['---', f"name: {item['skill_id']}", f"description: {_yaml_str(item['description'])}", '---', '',
             f"# {item['skill_id']}", '', item['description'], '',
             '## Parameters', '', '| name | type | required |', '|---|---|---|', *rows, '',
             '## When to use', '', 'Only when the task matches the description above, as decided by the description itself.',
             'Read the target file first and confirm it asks for this procedure.', '',
             '## When not to use', '',
             '- The request only asks to read, review, explain or summarize a file.',
             '- The file already implements the requested behavior.',
             '- The task belongs to a different family than the description states.', '',
             '## Run', '', '```', "python scripts/skill.py '<json arguments>' <workspace dir>", '```', '',
             '## Provenance', '', origin, f"Bundle digest of this skill: `{item['digest']}`.", '']
    return '\n'.join(lines)


def export(bundle: Path, out: Path, stream_root: Path | None = None) -> list[Path]:
    bundle = bundle.resolve()
    SkillCatalog.from_bundle(bundle)          # verifies every digest before anything is copied
    manifest = json.loads((bundle / 'manifest.json').read_text())
    sources = provenance(stream_root)
    written = []
    for item in manifest['skills']:
        filename, function = item['entrypoint'].split(':')
        target = out / item['skill_id']
        (target / 'scripts').mkdir(parents=True, exist_ok=True)
        code = (bundle / filename).read_text()
        (target / 'scripts' / 'skill.py').write_text(code + CLI.format(entry=function))
        (target / 'SKILL.md').write_text(skill_md(item, sources.get(item['skill_id'])))
        written.append(target)
    return written


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--stream-root', type=Path)
    args = p.parse_args(argv)
    for path in export(args.bundle, args.out, args.stream_root):
        print(path)


if __name__ == '__main__':
    main()
