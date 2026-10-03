"""Paired external dev evaluation and atomic activation, scoped to one experiment."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from core.evolution.artifacts import atomic_json

from core.evolution.contracts import Candidate, EvolutionEvent, RunSpec
from core.evolution.mutator import bundle_digest
from core.evolution.runner import EvolutionRunner


class Promoter:
    def __init__(self, journal, budget, provider_factory, root: Path, seed: int = 42,
                 timeout_s: int = 120, step_isolation: str = "inline",kernel_max_steps: int = 5):
        self.journal, self.budget = journal, budget
        self.provider_factory = provider_factory
        self.root = Path(root)
        self.seed, self.timeout_s, self.step_isolation = seed, timeout_s, step_isolation
        if kernel_max_steps < 1: raise ValueError('kernel_max_steps must be positive')
        self.kernel_max_steps=kernel_max_steps
        self.root.mkdir(parents=True, exist_ok=True)

    def load_active(self) -> Candidate | None:
        path = self.root / "active.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())["candidate"]
        data["parent_ids"] = tuple(data["parent_ids"])
        candidate = Candidate(**data)
        if bundle_digest(Path(candidate.bundle_path)) != candidate.digest:
            raise ValueError("active bundle digest mismatch")
        return candidate

    def evaluate(self, candidate: Candidate, task: dict, repeat_id: int | None = None):
        if bundle_digest(Path(candidate.bundle_path)) != candidate.digest:
            raise ValueError("candidate bundle digest mismatch")
        task_digest = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()[:16]
        split = task.get("split", "dev")
        if repeat_id is not None and (not isinstance(repeat_id,int) or isinstance(repeat_id,bool) or repeat_id<0):
            raise ValueError('repeat_id must be a nonnegative integer')
        if split not in {"dev", "reuse", "test"}:
            raise ValueError("unknown evaluation split")
        provider = self.provider_factory(candidate)
        runner = EvolutionRunner(self.journal, self.budget, self.root / "runs", provider,
                                 step_isolation=self.step_isolation)
        run_id = f"{split}-{candidate.digest[:24]}-{task_digest}-s{self.seed}"
        if repeat_id is not None:
            run_id += f'-r{repeat_id}'
        return runner.run(candidate, task, RunSpec(run_id, candidate.candidate_id,
                          task["task_id"], self.seed, self.kernel_max_steps, self.timeout_s))

    def compare(self, parent: Candidate, child: Candidate, tasks: list[dict], repeats: int = 1) -> dict:
        if not isinstance(repeats,int) or isinstance(repeats,bool) or repeats<1:
            raise ValueError('repeats must be a positive integer')
        if not tasks or any(task.get("split") != "dev" for task in tasks):
            raise ValueError("promotion requires explicit dev tasks only")
        if len({task["task_id"] for task in tasks}) != len(tasks):
            raise ValueError("duplicate dev task IDs")
        if parent.candidate_id not in child.parent_ids:
            raise ValueError("child must descend from the compared parent")
        active = self.load_active()
        if active and active.digest not in {parent.digest, child.digest}:
            raise ValueError("stale parent: active candidate changed")
        pairs = []
        for candidate in (parent, child):
            if bundle_digest(Path(candidate.bundle_path)) != candidate.digest:
                raise ValueError("candidate bundle digest mismatch")
        for task in tasks:
            for repeat_id in range(repeats):
                results = []
                for candidate in (parent, child):
                    result = self.evaluate(candidate, task, repeat_id=repeat_id if repeats>1 else None)
                    results.append(asdict(result))
                pair={"task_id": task["task_id"], "parent": results[0], "child": results[1]}
                if repeats>1: pair['repeat_id']=repeat_id
                pairs.append(pair)
        parent_score = sum(pair["parent"]["score"] for pair in pairs) / len(pairs)
        child_score = sum(pair["child"]["score"] for pair in pairs) / len(pairs)
        valid = all(item["status"] in {"passed", "failed"} for pair in pairs
                    for item in (pair["parent"], pair["child"]))
        no_regression = all(pair["child"]["score"] >= pair["parent"]["score"] for pair in pairs)
        promoted = valid and no_regression and child_score > parent_score
        comparison = {"promoted": promoted, "parent_score": parent_score, "child_score": child_score,
                      "reason": "paired_improvement" if promoted else "no_improvement_or_regression_or_infrastructure_failure",
                      "parent": asdict(parent), "child": asdict(child), "pairs": pairs, "seed": self.seed}
        if repeats>1: comparison['repeats']=repeats
        comparison_id = hashlib.sha256(json.dumps(comparison, sort_keys=True).encode()).hexdigest()
        atomic_json(self.root / "comparisons" / f"{comparison_id}.json", comparison)
        if promoted:
            atomic_json(self.root / "active.json", {"candidate": asdict(child), "comparison_id": comparison_id})
        self.journal.record_event(EvolutionEvent("promotion-" + comparison_id, child.candidate_id,
            "dev", 0, "promotion", {"promoted": promoted, "parent_score": parent_score,
                                     "child_score": child_score, "comparison_id": comparison_id}))
        return comparison
