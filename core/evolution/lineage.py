"""Version tree for evolvable agent parts, with parent selection by descendant performance.

One ``lineage.jsonl`` row per version: {id, parent, target, digest, hypothesis, created,
validation: {passed, total}, status: active|rejected|retired}. Rows are append-only; a
later row with the same id updates that node (e.g. active -> retired).

Parent selection follows the Huxley-Gödel Machine idea (arXiv 2510.21614): judge a node by
how well its whole clade does, not only by its own score. Subtree score = mean over the
node and all its descendants of the Laplace-smoothed validation rate (k+1)/(n+2). Rejected
children count toward their parent's clade (a branch that keeps producing failures is a
poor place to grow); only non-rejected nodes can be chosen. Ties go to the newer node.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import time

STATUSES = {'active', 'rejected', 'retired'}


@dataclass
class Version:
    id: str
    parent: str | None
    target: str
    digest: str
    hypothesis: str = ''
    created: float = field(default_factory=time.time)
    validation: dict | None = None        # {'passed': k, 'total': n}
    status: str = 'active'

    def smoothed(self) -> float:
        v = self.validation or {}
        k, n = int(v.get('passed', 0)), int(v.get('total', 0))
        return (k + 1) / (n + 2)


class Lineage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.nodes: dict[str, Version] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    self._apply(Version(**json.loads(line)))

    def _apply(self, version: Version) -> None:
        if version.status not in STATUSES:
            raise ValueError(f'unknown status {version.status!r}')
        if version.parent is not None and version.parent not in self.nodes and version.parent != version.id:
            raise ValueError(f'unknown parent {version.parent!r}')
        old = self.nodes.get(version.id)
        if old is not None and (old.parent, old.digest) != (version.parent, version.digest):
            raise ValueError(f'version {version.id!r} cannot change parent or digest')
        self.nodes[version.id] = version

    def record(self, version: Version) -> Version:
        self._apply(version)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a') as out:
            out.write(json.dumps(asdict(version), ensure_ascii=False, sort_keys=True) + '\n')
        return version

    def set_status(self, version_id: str, status: str) -> Version:
        node = self.nodes[version_id]
        return self.record(Version(**{**asdict(node), 'status': status}))

    def children(self, version_id: str) -> list[Version]:
        return [n for n in self.nodes.values() if n.parent == version_id]

    def subtree(self, version_id: str) -> list[Version]:
        out, stack = [], [version_id]
        while stack:
            node = self.nodes[stack.pop()]
            out.append(node)
            stack.extend(c.id for c in self.children(node.id))
        return out

    def subtree_score(self, version_id: str) -> float:
        members = self.subtree(version_id)
        return sum(m.smoothed() for m in members) / len(members)

    def select_parent(self, target: str | None = None) -> Version:
        candidates = [n for n in self.nodes.values()
                      if n.status != 'rejected' and (target is None or n.target == target)]
        if not candidates:
            raise ValueError('no selectable version')
        return max(candidates, key=lambda n: (self.subtree_score(n.id), n.created))

    def roots(self) -> list[Version]:
        return [n for n in self.nodes.values() if n.parent is None]
