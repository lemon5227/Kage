"""A3b: experience from earlier real tasks, offered only when the new task is close enough.

Sources (from the usage-time trajectory store): task turns the user marked 👍, and teacher redos
that passed the automatic check or got a 👍. A new real task retrieves the most similar one by
TF-IDF over the user's request (document frequencies from the stored requests); below
``MIN_SIMILARITY`` nothing is injected and the turn runs exactly as before. Real requests are free
text, so the bar is higher than on the templated benchmark (0.3): a wrong hint costs more than a
missing one (E-1c interference).
"""
from __future__ import annotations

import json
from pathlib import Path

from core.evolution.relevance import InstructionSpace
from core.trajectories import evidence

MIN_SIMILARITY = 0.45
MAX_CHARS = 1500


def usable(record: dict) -> bool:
    if record.get('kind') != 'task':
        return False
    ev = evidence(record)
    return ev == 'user' or (ev == 'auto' and record.get('source') == 'teacher')


def render(record: dict) -> str:
    """The successful procedure as a short hint: the tool calls in order and the final answer."""
    lines = []
    for step in record.get('steps', []):
        for call in (step.get('response') or {}).get('tool_calls') or []:
            fn = call.get('function') or call
            args = fn.get('arguments')
            if not isinstance(args, str):
                args = json.dumps(args or {}, ensure_ascii=False)
            lines.append(f"- {fn.get('name')}({args[:300]})")
    final = str(record.get('final_text') or '').strip()
    text = (f"以前做过一个类似的任务：“{str(record.get('user_input') or '')[:200]}”。当时成功的做法：\n"
            + '\n'.join(lines) + (f"\n结果：{final[:200]}" if final else '')
            + "\n参数（文件名、路径、内容等）要按这次的要求来，不要照抄。")
    return text[:MAX_CHARS]


class RealExperience:
    def __init__(self, root: str | Path, min_similarity: float = MIN_SIMILARITY):
        self.root, self.min_similarity = Path(root), min_similarity

    def _records(self) -> list[dict]:
        out = []
        for path in sorted(self.root.glob('*.json')) if self.root.exists() else []:
            try:
                r = json.loads(path.read_text())
            except ValueError:
                continue
            if usable(r):
                out.append(r)
        return out

    def retrieve(self, user_input: str) -> tuple[dict | None, float]:
        records = self._records()
        if not records:
            return None, 0.0
        space = InstructionSpace()
        for r in records:
            space.observe(str(r.get('user_input') or ''))
        space.observe(user_input)
        best, score = None, 0.0
        for r in records:
            s = space.similarity(user_input, str(r.get('user_input') or ''))
            if s > score:
                best, score = r, s
        return (best, round(score, 4)) if score >= self.min_similarity else (None, round(score, 4))
