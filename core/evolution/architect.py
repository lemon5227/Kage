"""Cloud architect (W4-3, Meta-Harness style): propose one L2 policy change from a version archive.

The architect reads a *version archive* through three read-only tools and returns one
candidate module for exactly one evolvable target:

  prompt_template  def text() -> str                         (extra student system-prompt section)
  skill_selection  def select(instruction, skills) -> list   (skill_ids to preview, from given descriptors)
  help_policy      def recover(error, history, checkpoints)  (in-task help, W3-2 shape)
  recovery         def recover(error, history, checkpoints)  (G1 recovery shape)

Scorer, budgets, rollback and the execution kernel are frozen and not part of the archive.
Protocol is plain JSON in text (works with any chat model): each reply is either
{"tool": "ls"|"cat"|"grep", "args": {...}} or {"final": {"target", "hypothesis", "code"}}.
At most MAX_TURNS model calls; every call reserves its worst-case cost in the global teacher
ledger first and stops once the candidate would exceed CANDIDATE_CAP_USD.

Promotion: the candidate and its parent run the same validation tasks under the same budget;
it is promoted only if no task regresses and at least one improves. Results go to the W4-4
version tree (lineage.jsonl).
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Callable

from core.evolution.lineage import Lineage, Version
from core.evolution.mutator import parse_proposal

TARGETS = {'prompt_template': 'text', 'skill_selection': 'select', 'help_policy': 'recover', 'recovery': 'recover'}
MAX_TURNS = 8
CANDIDATE_CAP_USD = 0.015
INPUT_BYTES_PER_CALL = 24000
OUTPUT_TOKENS_PER_CALL = 1500
TOOL_OUTPUT_CHARS = 4000
HIDDEN_KEYS = {'scoring_criteria', 'expected', 'cases', 'sha256'}

SYSTEM = (
    "You are Kage's architect. Kage is a small local agent; its scorer, budgets and execution "
    "kernel are fixed. You may change exactly ONE of these policy modules: "
    + ", ".join(f"{t} (python: def {f}(...))" for t, f in TARGETS.items()) + ". "
    "Inspect the version archive (sources, validation scores, raw traces) with read-only tools, "
    "find a concrete failure pattern, and propose one change. Reply with ONE JSON object per turn: "
    '{"tool": "ls"|"cat"|"grep", "args": {"path": ..., "start": int, "end": int, "pattern": ...}} '
    'or {"final": {"target": ..., "hypothesis": ..., "code": ...}}. Standard library only; no file '
    "or network access in code. Your hypothesis is unverified until validation."
)


def scrub(value):
    """Remove hidden scoring material before anything enters the archive."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in HIDDEN_KEYS}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


class ArchiveTools:
    """Read-only ls/cat/grep confined to one archive root."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _path(self, path: str) -> Path:
        target = (self.root / str(path or '.').lstrip('/')).resolve()
        if not target.is_relative_to(self.root):
            raise PermissionError('path outside the version archive')
        return target

    def ls(self, path='.', **_):
        target = self._path(path)
        return '\n'.join(sorted(p.name + ('/' if p.is_dir() else '') for p in target.iterdir()))

    def cat(self, path, start=1, end=200, **_):
        lines = self._path(path).read_text(errors='replace').splitlines()
        start, end = max(1, int(start)), min(len(lines), int(end))
        return '\n'.join(f'{i}: {lines[i - 1]}' for i in range(start, end + 1))

    def grep(self, pattern, path='.', **_):
        regex, out = re.compile(str(pattern)), []
        base = self._path(path)
        files = [base] if base.is_file() else sorted(p for p in base.rglob('*') if p.is_file())
        for file in files:
            for i, line in enumerate(file.read_text(errors='replace').splitlines(), 1):
                if regex.search(line):
                    out.append(f'{file.relative_to(self.root)}:{i}: {line[:300]}')
                    if len(out) >= 50:
                        return '\n'.join(out)
        return '\n'.join(out)

    def call(self, name: str, args: dict) -> str:
        if name not in {'ls', 'cat', 'grep'}:
            return f'error: unknown tool {name!r}'
        try:
            return str(getattr(self, name)(**(args or {})))[:TOOL_OUTPUT_CHARS]
        except Exception as exc:                 # tool errors are shown to the model, never raised
            return f'error: {type(exc).__name__}: {exc}'


def write_archive(root: Path, versions: list[dict]) -> Path:
    """versions: [{id, target, source, validation, traces: [list of trace rows]}] -> scrubbed files."""
    root = Path(root)
    for v in versions:
        d = root / v['id']
        (d / 'traces').mkdir(parents=True, exist_ok=True)
        (d / f"{v['target']}.py").write_text(v['source'])
        (d / 'validation.json').write_text(json.dumps(scrub(v.get('validation', {})), indent=1))
        for i, trace in enumerate(v.get('traces', [])):
            (d / 'traces' / f'{i:03d}.jsonl').write_text(''.join(json.dumps(scrub(r)) + '\n' for r in trace))
    return root


def validate_candidate(final: dict) -> dict:
    if not isinstance(final, dict):
        raise ValueError('final must be an object')
    target, code = final.get('target'), final.get('code')
    if target not in TARGETS:
        raise ValueError(f'target must be one of {sorted(TARGETS)}')
    if not isinstance(code, str) or not str(final.get('hypothesis') or '').strip():
        raise ValueError('code and a non-empty hypothesis are required')
    tree = ast.parse(code)
    if not any(isinstance(n, ast.FunctionDef) and n.name == TARGETS[target] for n in tree.body):
        raise ValueError(f'{target} code must define {TARGETS[target]}()')
    banned = {'open', 'exec', 'eval', '__import__', 'compile'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in banned:
            raise ValueError(f'{node.id} is not allowed in policy code')
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name.split('.')[0] for a in node.names] if isinstance(node, ast.Import) else [str(node.module).split('.')[0]]
            if any(n in {'os', 'subprocess', 'socket', 'shutil', 'pathlib', 'urllib', 'requests', 'sys'} for n in names):
                raise ValueError('file, process and network modules are not allowed')
    return {'target': target, 'hypothesis': final['hypothesis'].strip(), 'code': code}


class Architect:
    def __init__(self, model, budget, *, cap_usd: float = CANDIDATE_CAP_USD,
                 input_price: float = 0.30, output_price: float = 1.20):
        self.model, self.budget = model, budget
        self.cap_usd, self.input_price, self.output_price = cap_usd, input_price, output_price

    def _worst_case(self) -> float:
        # ~4 bytes per token for the input cap, full output cap.
        return (INPUT_BYTES_PER_CALL / 4) * self.input_price / 1e6 + OUTPUT_TOKENS_PER_CALL * self.output_price / 1e6

    def propose(self, archive: Path, brief: str, *, run_id: str) -> dict:
        tools = ArchiveTools(archive)
        messages = [{'role': 'system', 'content': SYSTEM},
                    {'role': 'user', 'content': brief + '\nArchive root listing:\n' + tools.ls('.')}]
        spent, log = 0.0, []
        for turn in range(MAX_TURNS):
            if spent + self._worst_case() > self.cap_usd:
                return {'status': 'budget_stop', 'turns': turn, 'cost_usd': round(spent, 6), 'log': log}
            if len(json.dumps(messages).encode()) > INPUT_BYTES_PER_CALL:
                return {'status': 'input_cap', 'turns': turn, 'cost_usd': round(spent, 6), 'log': log}
            reservation = self.budget.reserve(INPUT_BYTES_PER_CALL // 4, OUTPUT_TOKENS_PER_CALL,
                                              call_type='architect', run_id=run_id)
            response = None
            try:
                response = self.model.generate(messages=messages, max_tokens=OUTPUT_TOKENS_PER_CALL, temperature=0)
            finally:
                usage = dict(getattr(response, 'usage', None) or {})
                self.budget.settle(reservation, usage or None)
                if 'input_tokens' in usage and 'output_tokens' in usage:
                    spent += usage['input_tokens'] * self.input_price / 1e6 + usage['output_tokens'] * self.output_price / 1e6
                else:
                    spent += self._worst_case()          # unknown usage counts as the full reservation
            raw = str(getattr(response, 'text', '') or '')
            messages.append({'role': 'assistant', 'content': raw})
            try:
                reply, _ = parse_proposal(raw.strip().removeprefix('```json').removesuffix('```').strip())
            except ValueError:
                messages.append({'role': 'user', 'content': 'Reply with exactly one JSON object.'})
                log.append({'turn': turn, 'error': 'not json'})
                continue
            if 'final' in reply:
                try:
                    candidate = validate_candidate(reply['final'])
                except (ValueError, SyntaxError) as exc:
                    messages.append({'role': 'user', 'content': f'Invalid final answer: {exc}. Fix it.'})
                    log.append({'turn': turn, 'error': str(exc)})
                    continue
                return {'status': 'proposed', 'turns': turn + 1, 'cost_usd': round(spent, 6), 'log': log, **candidate}
            result = tools.call(str(reply.get('tool')), reply.get('args') or {})
            log.append({'turn': turn, 'tool': reply.get('tool'), 'args': reply.get('args')})
            messages.append({'role': 'user', 'content': f'[{reply.get("tool")}]\n{result}'})
        return {'status': 'turn_limit', 'turns': MAX_TURNS, 'cost_usd': round(spent, 6), 'log': log}


def write_module(root: Path, candidate: dict) -> tuple[Path, str]:
    """Store a candidate as an immutable module directory named by its digest."""
    code = candidate['code']
    digest = hashlib.sha256(f"{candidate['target']}\n{code}".encode()).hexdigest()
    d = Path(root) / digest
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{candidate['target']}.py").write_text(code)
    (d / 'manifest.json').write_text(json.dumps({'version': 1, 'target': candidate['target'],
        'entrypoint': f"{candidate['target']}.py:{TARGETS[candidate['target']]}", 'digest': digest,
        'hypothesis': candidate['hypothesis']}, ensure_ascii=False))
    return d, digest


def promote(lineage: Lineage, parent: Version, candidate: dict, module_dir: Path, digest: str,
            evaluate: Callable[[Path | None], dict[str, float]], *, parent_dir: Path | None) -> dict:
    """Same validation tasks and budget for parent and child; no regression and >=1 improvement."""
    before, after = evaluate(parent_dir), evaluate(module_dir)
    if set(before) != set(after):
        raise ValueError('parent and candidate must run the same validation tasks')
    regressed = sorted(t for t in before if after[t] < before[t])
    improved = sorted(t for t in before if after[t] > before[t])
    promoted = not regressed and bool(improved)
    node = lineage.record(Version(id=digest[:16], parent=parent.id, target=candidate['target'], digest=digest,
                                  hypothesis=candidate['hypothesis'][:300], created=time.time(),
                                  validation={'passed': sum(v >= 1.0 for v in after.values()), 'total': len(after)},
                                  status='active' if promoted else 'rejected'))
    return {'promoted': promoted, 'regressed': regressed, 'improved': improved, 'version': node.id,
            'parent_passed': sum(v >= 1.0 for v in before.values()), 'child_passed': node.validation['passed']}
