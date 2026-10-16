"""Relevance gating and automatic task grouping (P3, docs/plans/self-evolving-proactive-agent-2026-10-14.md §2.1).

E-1c showed that every learning arm got worse on families it never learned (cp0 16/24 →
6–14/24) without calling a single skill: three irrelevant skills or a weakly matched
demonstration in the prompt were enough to distract the 4B student. The gate below
injects knowledge only when the task looks like one the knowledge was verified on, and
otherwise leaves the student exactly as the raw student (A0).

The same similarity also replaces the benchmark's family label: the agent groups tasks
into clusters by nearest earlier instruction, so competence, help decisions and practice
targets use only what the agent can see.

Similarity is TF-IDF cosine over visible instructions, with document frequencies from the
instructions this agent has observed so far (``InstructionSpace``). Offline replay of the
frozen stream-v1 manifests (2026-10-16): word-set Jaccard could not separate families
pairwise (same-family phrasings as low as 0.18, cross-family up to 0.29); dynamic TF-IDF at
RELEVANCE_MIN = 0.3 gives one pure cluster per capability family on both seeds, and an eval
task scores ≥0.38 against a single verified same-family instruction versus ≤0.25 against
any other capability family. That is a property of these templated instructions; free-form
user tasks would need an embedding model here.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

RELEVANCE_MIN = 0.3
CLUSTER_MEMBERS = 20          # instructions kept per cluster (most recent)
SOURCES_PER_SKILL = 20

_WORD = re.compile(r'[a-z0-9_]+')


_CJK = re.compile(r'[\u3400-\u9fff]+')


def tokens(text: str) -> list[str]:
    # Same normalisation as skill search: fold a plural "s", drop very short words.
    out = []
    for w in _WORD.findall(str(text).casefold()):
        if len(w) >= 3:
            out.append(w[:-1] if len(w) > 3 and w.endswith('s') else w)
    # Chinese has no spaces: character bigrams (real user requests, A3b). The English benchmark
    # instructions contain no CJK, so stream-v1 similarities are unchanged.
    for run in _CJK.findall(str(text)):
        out += [run[i:i + 2] for i in range(len(run) - 1)] or [run]
    return out


class InstructionSpace:
    """TF-IDF over the instructions this agent has observed (persisted document frequencies)."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else None
        data = json.loads(self.path.read_text()) if self.path and self.path.exists() else {}
        self.n, self.df = int(data.get('n', 0)), Counter(data.get('df', {}))
        self.seen = set(data.get('seen', []))

    def observe(self, instruction: str) -> None:
        key = hashlib.sha256(instruction.encode()).hexdigest()[:16]
        if key in self.seen:
            return
        self.seen.add(key)
        self.n += 1
        self.df.update(set(tokens(instruction)))
        if self.path:
            _write_json(self.path, {'n': self.n, 'df': dict(self.df), 'seen': sorted(self.seen)})

    def vector(self, text: str) -> dict[str, float]:
        counts = Counter(tokens(text))
        vec = {w: (1 + math.log(c)) * (math.log((1 + self.n) / (1 + self.df.get(w, 0))) + 1)
               for w, c in counts.items()}
        norm = math.sqrt(sum(x * x for x in vec.values())) or 1.0
        return {w: x / norm for w, x in vec.items()}

    def similarity(self, a: str, b: str) -> float:
        va, vb = self.vector(a), self.vector(b)
        return sum(x * vb.get(w, 0.0) for w, x in va.items())


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    with os.fdopen(fd, 'w') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


class TaskClusters:
    """Agent-side task grouping: a new instruction joins the cluster of its nearest earlier one."""

    def __init__(self, path: Path, space: InstructionSpace, threshold: float = RELEVANCE_MIN):
        self.path, self.space, self.threshold = Path(path), space, threshold
        self.clusters: list[dict] = json.loads(self.path.read_text())['clusters'] if self.path.exists() else []

    def nearest(self, instruction: str) -> tuple[str | None, float]:
        best = (None, 0.0)
        for cluster in self.clusters:
            for member in cluster['instructions']:
                score = self.space.similarity(instruction, member)
                if score > best[1]:
                    best = (cluster['id'], score)
        return best if best[1] >= self.threshold else (None, best[1])

    def assign(self, instruction: str, *, generator: str | None = None) -> str:
        """Cluster id for this instruction, creating a cluster when nothing is similar enough.

        ``generator`` is the environment's task generator for the instruction; it is kept only so
        practice can ask the environment for fresh variants of a cluster, never used for decisions.
        """
        self.space.observe(instruction)
        cid, _ = self.nearest(instruction)
        if cid is None:
            cid = f'c{len(self.clusters)}'
            self.clusters.append({'id': cid, 'instructions': [], 'generators': []})
        cluster = next(c for c in self.clusters if c['id'] == cid)
        if instruction not in cluster['instructions']:
            cluster['instructions'] = (cluster['instructions'] + [instruction])[-CLUSTER_MEMBERS:]
        if generator and generator not in cluster['generators']:
            cluster['generators'].append(generator)
        _write_json(self.path, {'clusters': self.clusters})
        return cid

    def generator_of(self, cid: str) -> str | None:
        cluster = next((c for c in self.clusters if c['id'] == cid), None)
        return cluster['generators'][0] if cluster and cluster['generators'] else None


# The human-written rule as an L2 policy module: the parent of every architect proposal (A6) and
# the fixed policy of A6-fixed. `skills` rows: {skill_id, similarity, verified_on: [instructions]}.
FIXED_SELECT = f'''def select(instruction, skills):
    """Show a skill only if this task is close to an instruction it was verified on."""
    ranked = sorted(skills, key=lambda s: (-s["similarity"], s["skill_id"]))
    return [s["skill_id"] for s in ranked if s["similarity"] >= {RELEVANCE_MIN}][:3]
'''
SELECT_ADAPTER = b'''\n\ndef run(arguments, context):
    ids = select(arguments["instruction"], arguments["skills"])
    return {"success": True, "skill_ids": [str(i) for i in list(ids or [])]}
'''
MAX_SHOWN = 3


class SkillSources:
    """Which instructions each skill was verified on; the gate admits a skill only near them.

    By default the gate is the fixed similarity rule. An evolved selection policy (W4-3,
    target ``skill_selection``) can replace it: ``set_policy`` stores the module next to the
    sources file, and every decision then runs it in a subprocess (no files, no network);
    a policy error falls back to the fixed rule and is counted.
    """

    def __init__(self, path: Path, space: InstructionSpace, threshold: float = RELEVANCE_MIN, runner=None):
        self.path, self.space, self.threshold = Path(path), space, threshold
        self.sources: dict[str, list[str]] = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.policy_path = self.path.with_name('gate-policy.py')
        self.runner, self.policy_errors = runner, 0

    @property
    def policy(self) -> bytes | None:
        return self.policy_path.read_bytes() if self.policy_path.exists() else None

    def set_policy(self, source: str | None) -> None:
        if source is None:
            self.policy_path.unlink(missing_ok=True)
        else:
            self.policy_path.write_text(source)

    def policy_digest(self) -> str | None:
        policy = self.policy
        return hashlib.sha256(policy).hexdigest() if policy is not None else None

    def rows(self, instruction: str, present) -> list[dict]:
        return [{'skill_id': sid, 'similarity': score, 'verified_on': self.sources.get(sid, [])[-5:]}
                for sid, score in self.scores(instruction, present)]

    def add(self, skill_ids, instructions) -> None:
        for skill_id in skill_ids:
            have = self.sources.setdefault(skill_id, [])
            for text in instructions:
                if text not in have:
                    have.append(text)
            self.sources[skill_id] = have[-SOURCES_PER_SKILL:]
        _write_json(self.path, self.sources)

    def scores(self, instruction: str, present) -> list[tuple[str, float]]:
        out = []
        for skill_id in present:
            best = max((self.space.similarity(instruction, s) for s in self.sources.get(skill_id, [])), default=0.0)
            out.append((skill_id, round(best, 4)))
        return sorted(out, key=lambda row: (-row[1], row[0]))

    def relevant(self, instruction: str, present) -> list[str]:
        """Skill ids worth showing for this instruction, most relevant first (empty: show none)."""
        present = list(present)
        fixed = [sid for sid, score in self.scores(instruction, present) if score >= self.threshold][:MAX_SHOWN]
        policy = self.policy
        if policy is None or not present:
            return fixed
        chosen = run_select(policy, instruction, self.rows(instruction, present), present, self.runner)
        if chosen is None:
            self.policy_errors += 1
            return fixed
        return chosen


def run_select(source: bytes, instruction: str, rows: list[dict], present, runner=None) -> list[str] | None:
    """Run an L2 select() module in a subprocess; None on any error (caller falls back)."""
    from core.evolution.sandbox import ProcessSkillRunner
    runner = runner or ProcessSkillRunner(timeout_s=5)
    with tempfile.TemporaryDirectory(prefix='kage-select-') as scratch:
        result = runner.run(source + SELECT_ADAPTER, 'run', {'instruction': instruction, 'skills': rows}, Path(scratch))
    ids = result.get('skill_ids') if isinstance(result, dict) and result.get('success') else None
    if not isinstance(ids, list):
        return None
    keep = set(present)
    # An empty list is a valid decision ("show nothing"); unknown ids are dropped.
    return [i for i in ids if i in keep][:MAX_SHOWN]


def skill_ids(bundle_path) -> list[str]:
    try:
        manifest = json.loads((Path(bundle_path) / 'manifest.json').read_text())
    except (OSError, ValueError):
        return []
    return [item['skill_id'] for item in manifest.get('skills', [])]
