#!/usr/bin/env python3
"""
CLI entry point for Kage EvoLab.
Usage:
    python scripts/kage_evolve.py baseline --suite eval/evolution/smoke.json --provider fake
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate, RunSpec
from core.evolution.journal import Journal
from core.evolution.runner import EvolutionRunner, FakeEvolutionProvider


def run_baseline(
    suite_path: str | Path,
    provider_name: str = "fake",
    db_path: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> int:
    suite_file = Path(suite_path)
    if not suite_file.exists():
        print(f"Error: Suite file not found: {suite_file}", file=sys.stderr)
        return 1

    with open(suite_file, "r", encoding="utf-8") as f:
        suite = json.load(f)

    tasks = suite.get("tasks", [])
    suite_id = suite.get("suite_id", "unknown_suite")

    work_dir = Path(output_dir) if output_dir else PROJECT_ROOT / "runs" / "evolution" / "baseline"
    work_dir.mkdir(parents=True, exist_ok=True)

    journal_db = Path(db_path) if db_path else work_dir / "journal.db"
    journal = Journal(journal_db)

    budget = BudgetTracker(
        BudgetConfig(
            max_input_tokens_total=100_000,
            max_output_tokens_total=20_000,
            max_api_calls=100,
        )
    )

    provider = FakeEvolutionProvider(mode="baseline") if provider_name == "fake" else None
    runner = EvolutionRunner(
        journal=journal,
        budget=budget,
        base_dir=work_dir / "workspaces",
        provider=provider,
    )

    baseline_candidate = Candidate(
        candidate_id="candidate_baseline_v0",
        parent_ids=(),
        target="workflow",
        bundle_path=str(work_dir / "bundles" / "baseline"),
        digest="sha256:baseline00000000000000000000000000000000000000000000000000000000",
        hypothesis="Initial frozen baseline agent",
    )

    print("=" * 72)
    print(f"  Kage EvoLab - Baseline Evaluation Suite: {suite_id}")
    print(f"  Tasks: {len(tasks)} | Provider: {provider_name} | Journal: {journal_db.name}")
    print("=" * 72)

    results = []
    start_total = time.time()

    for task in tasks:
        task_id = task.get("task_id", "unknown_task")
        run_id = f"run_{task_id}_baseline"
        spec = RunSpec(
            run_id=run_id,
            candidate_id=baseline_candidate.candidate_id,
            task_id=task_id,
            seed=42,
            max_steps=5,
            timeout_s=60,
        )

        res = runner.run(
            candidate=baseline_candidate,
            task_def=task,
            spec=spec,
            retain_workspace=True,
        )
        results.append((task_id, res))

    total_time = round(time.time() - start_total, 2)

    # Formatted Report
    print(f"\n{'TASK ID':<28} {'STATUS':<12} {'SCORE':<8} {'INPUT':<8} {'OUTPUT':<8} {'STAGNANT'}")
    print("-" * 72)

    passed_count = 0
    total_input = 0
    total_output = 0

    for task_id, res in results:
        in_tok = res.usage.get("input_tokens", 0)
        out_tok = res.usage.get("output_tokens", 0)
        total_input += in_tok
        total_output += out_tok
        if res.status == "passed":
            passed_count += 1

        stag_str = "YES" if res.progress_stagnant else "NO"
        print(f"{task_id:<28} {res.status:<12} {res.score:<8.2f} {in_tok:<8} {out_tok:<8} {stag_str}")

    print("-" * 72)
    pass_rate = (passed_count / len(results) * 100.0) if results else 0.0
    print(
        f"Summary: {passed_count}/{len(results)} passed ({pass_rate:.1f}%) | "
        f"Tokens: in={total_input}, out={total_output} | Time: {total_time}s"
    )
    print(f"Estimated Cost: ${budget.total_cost_usd:.6f}")
    print("=" * 72 + "\n")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Kage EvoLab CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    baseline_parser = subparsers.add_parser("baseline", help="Run baseline candidate on a test suite")
    baseline_parser.add_argument("--suite", default="eval/evolution/smoke.json", help="Path to evaluation suite JSON")
    baseline_parser.add_argument("--provider", default="fake", choices=["fake", "live"], help="LLM provider mode")
    baseline_parser.add_argument("--db", default=None, help="Custom journal database path")
    baseline_parser.add_argument("--output", default=None, help="Custom output directory")

    args = parser.parse_args()

    if args.command == "baseline":
        code = run_baseline(
            suite_path=args.suite,
            provider_name=args.provider,
            db_path=args.db,
            output_dir=args.output,
        )
        sys.exit(code)


if __name__ == "__main__":
    main()
