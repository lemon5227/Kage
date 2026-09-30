"""Only paired external dev improvement can change the active candidate."""
import json
from pathlib import Path

import pytest

from core.evolution.budget import BudgetTracker
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.skills import SkillCatalog

from test_evolution_mutation import _Generator, _parent, _mutator, PROPOSAL


class _SkillProvider:
    """Fixture adapter executes candidate Python; scorer remains outside the adapter."""
    def __init__(self, candidate):
        self.catalog = SkillCatalog.from_bundle(Path(candidate.bundle_path))

    def generate_step(self, task, step, history, workspace):
        rows = json.loads((workspace / "input.json").read_text())
        if self.catalog.digests:
            result = self.catalog.call("normalize", self.catalog.digests["normalize"],
                                       {"records": rows}, workspace)
            if not result.get("success"):
                raise RuntimeError(result)
            rows = result["rows"]
        (workspace / "output.json").write_text(json.dumps(rows))
        return {"action": {"name": "finish"}, "usage": {"input_tokens": 1, "output_tokens": 1}}


def _task(task_id, name):
    return {"task_id": task_id, "split": "dev", "instruction": "Trim names from input.json into output.json",
            "initial_files": {"input.json": json.dumps([{"name": name}])},
            "scoring_criteria": {"type": "json_exact_match", "file": "output.json",
                                 "expected": [{"name": name.strip()}]}}


def _promoter(tmp_path):
    import importlib.util
    assert importlib.util.find_spec("core.evolution.promotion"), "E1 paired promotion missing"
    from core.evolution.promotion import Promoter
    return Promoter(Journal(tmp_path / "journal.sqlite"), BudgetTracker(), _SkillProvider,
                    tmp_path / "experiment/method/seed-42")


def test_failure_to_generated_skill_to_promotion_and_restart_reuse(tmp_path):
    parent = _parent(tmp_path / "parent")
    child = _mutator(tmp_path, _Generator([PROPOSAL])).propose(parent, {"failure_reason": "whitespace"})
    promoter = _promoter(tmp_path)
    comparison = promoter.compare(parent, child, [_task("repair", " Ada "), _task("unseen", " Lin ")])
    assert comparison["promoted"] and comparison["parent_score"] == 0 and comparison["child_score"] == 1
    active = _promoter(tmp_path).load_active()
    assert active.digest == child.digest
    catalog = SkillCatalog.from_bundle(Path(active.bundle_path))
    reused = catalog.call("normalize", catalog.digests["normalize"], {"records": [{"name": " Ken "}]}, tmp_path / "reuse")
    assert reused["rows"] == [{"name": "Ken"}]


def test_dev_regression_and_test_split_never_activate(tmp_path):
    parent = _parent(tmp_path / "parent")
    # Overfit code succeeds on repair but corrupts already-valid inputs.
    overfit = {**PROPOSAL, "code": 'def run(arguments, context):\n    return {"success": True, "rows": [{"name": "Ada"}]}\n'}
    child = _mutator(tmp_path, _Generator([overfit])).propose(parent, {})
    promoter = _promoter(tmp_path)
    result = promoter.compare(parent, child, [_task("repair", " Ada "), _task("preserve", "Grace")])
    assert not result["promoted"] and not (promoter.root / "active.json").exists()
    with pytest.raises(ValueError, match="dev"):
        promoter.compare(parent, child, [{**_task("holdout", " Secret "), "split": "test"}])
