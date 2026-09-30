#!/usr/bin/env python3
"""
CLI entry point for Kage EvoLab.

Usage:
    # Deterministic fixture provider (bypasses the Kage chain; plumbing only)
    python scripts/kage_evolve.py baseline --suite eval/evolution/smoke.json --provider fake

    # Real frozen Kage chain (AgenticLoop + PromptBuilder + ToolExecutor + ModelBroker)
    python scripts/kage_evolve.py baseline --suite eval/evolution/smoke.json --provider live

Exit codes:
    0  experiment completed (read report["outcome"] for pass/fail; a frozen
       baseline is *expected* to fail some tasks, which is data, not a CLI error)
    1  suite/config error (missing suite, bad JSON, unknown provider)
    2  live provider unavailable (no credential / hybrid escalation refused)
    3  infrastructure failure observed during the run (transport/model error)
    4  tasks failed and --fail-on-task-failure was requested
"""

from __future__ import annotations

import argparse
import hashlib
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

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_PROVIDER_UNAVAILABLE = 2
EXIT_INFRA_FAILURE = 3
EXIT_TASK_FAILED = 4


def _load_suite(suite_path: str | Path) -> dict:
    suite_file = Path(suite_path)
    if not suite_file.exists():
        raise FileNotFoundError(f"Suite file not found: {suite_file}")
    with open(suite_file, "r", encoding="utf-8") as f:
        suite = json.load(f)
    if not isinstance(suite, dict) or not isinstance(suite.get("tasks"), list):
        raise ValueError(f"Suite is malformed (expected an object with a tasks list): {suite_file}")
    return suite


def _build_provider(provider_name: str, *, config_path: str | None, role: str,
                    base_url: str | None, model_name: str | None,
                    api_key_env: str, allow_hybrid: bool):
    """Return (provider, provider_info). Never silently substitutes a fake provider."""
    if provider_name == "fake":
        return FakeEvolutionProvider(mode="baseline"), {
            "provider_mode": "fake",
            "provider_class": "FakeEvolutionProvider",
            "model": "deterministic-fixture",
            "chain": "bypassed (fixture writes workspace directly)",
            "credential_source": "none",
        }

    from core.evolution.agent_provider import (
        KageChainProvider,
        ProviderUnavailableError,
        build_live_provider,
    )

    config = {}
    if config_path:
        cfg_file = Path(config_path)
        if not cfg_file.exists():
            raise ProviderUnavailableError(f"config file not found: {cfg_file}")
        config = json.loads(cfg_file.read_text(encoding="utf-8"))

    provider, info = build_live_provider(
        config,
        role=role,
        base_url=base_url,
        model_name=model_name,
        api_key_env=api_key_env,
        allow_hybrid=allow_hybrid,
    )
    chain = KageChainProvider(
        provider,
        provider_mode="live",
        model_label=info.get("model", ""),
        provider_label=info.get("provider_type", type(provider).__name__),
    )
    info = dict(info)
    info.update({
        "provider_mode": "live",
        "provider_class": info.get("provider_type", type(provider).__name__),
        "chain": "AgenticLoop + PromptBuilder + ToolExecutor (frozen)",
    })
    return chain, info


def run_baseline(
    suite_path: str | Path,
    provider_name: str = "fake",
    db_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    *,
    config_path: str | None = "config/settings.json",
    role: str = "background",
    base_url: str | None = None,
    model_name: str | None = None,
    api_key_env: str = "OPENAI_API_KEY",
    allow_hybrid: bool = False,
    max_steps: int | None = None,
    timeout_s: int = 180,
    report_path: str | Path | None = None,
    step_isolation: str = "fork",
    fail_on_task_failure: bool = False,
    retry_crashed: bool = False,
    quiet: bool = False,
) -> int:
    try:
        suite = _load_suite(suite_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if provider_name not in ("fake", "live"):
        print(f"Error: unknown provider '{provider_name}' (expected fake|live)", file=sys.stderr)
        return EXIT_CONFIG

    try:
        provider, provider_info = _build_provider(
            provider_name,
            config_path=config_path,
            role=role,
            base_url=base_url,
            model_name=model_name,
            api_key_env=api_key_env,
            allow_hybrid=allow_hybrid,
        )
    except Exception as exc:  # noqa: BLE001 - provider availability is an explicit exit path
        from core.evolution.agent_provider import ProviderUnavailableError

        if isinstance(exc, ProviderUnavailableError):
            print(f"Error: {exc}", file=sys.stderr)
            print("Refusing to fall back to the fake provider: a live run must be a live run.",
                  file=sys.stderr)
            return EXIT_PROVIDER_UNAVAILABLE
        raise

    tasks = suite.get("tasks", [])
    suite_id = suite.get("suite_id", "unknown_suite")

    if output_dir:
        work_dir = Path(output_dir)
    else:
        work_dir = PROJECT_ROOT / "runs" / "evolution" / provider_name
    work_dir.mkdir(parents=True, exist_ok=True)

    journal_db = Path(db_path) if db_path else work_dir / "journal.db"
    journal = Journal(journal_db)
    budget = BudgetTracker(
        BudgetConfig(
            max_input_tokens_total=200_000,
            max_output_tokens_total=50_000,
            max_api_calls=200,
        ),
        db_path=journal_db,
    )

    runner = EvolutionRunner(
        journal=journal,
        budget=budget,
        base_dir=work_dir / "workspaces",
        provider=provider,
        step_isolation=step_isolation,
    )

    # Run ids are deterministic per (task, candidate, provider), so an earlier
    # infrastructure failure would otherwise be served forever from the journal.
    # Retrying is explicit (--retry-crashed) and also releases the conservative
    # budget charge that was booked for the failed attempt.
    crashed_statuses = {"crashed", "timeout", "budget_exhausted"}
    retried: list[str] = []
    if retry_crashed:
        for task in tasks:
            task_id = task.get("task_id", "unknown_task")
            task_hash = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()[:12]
            candidate_run_id = f"run_{task_id}_baseline_{task_hash}"
            cached = journal.get_run(candidate_run_id)
            if cached is not None and cached.status in crashed_statuses:
                budget.forget_run(candidate_run_id)
                journal.delete_run(candidate_run_id)
                retried.append(candidate_run_id)
        if retried and not quiet:
            print(f"Retrying {len(retried)} previously failed run(s): {', '.join(retried)}")

    baseline_candidate = Candidate(
        candidate_id="candidate_baseline_v0",
        parent_ids=(),
        target="workflow",
        bundle_path=str(work_dir / "bundles" / "baseline"),
        digest="sha256:baseline00000000000000000000000000000000000000000000000000000000",
        hypothesis="Initial frozen baseline agent",
    )

    # A live chain invocation already runs the agent's internal steps, so one
    # kernel step per task is the default; the fixture provider keeps 5.
    if max_steps is None:
        max_steps = 5 if provider_name == "fake" else 1

    if not quiet:
        print("=" * 78)
        print(f"  Kage EvoLab - Baseline Suite: {suite_id}")
        print(f"  Provider mode : {provider_info.get('provider_mode', provider_name).upper()}")
        print(f"  Model         : {provider_info.get('model', 'n/a')}")
        print(f"  Chain         : {provider_info.get('chain', 'n/a')}")
        print(f"  Tasks         : {len(tasks)} | kernel steps/task: {max_steps} | journal: {journal_db.name}")
        print("=" * 78)

    results: list[dict] = []
    start_total = time.time()

    for task in tasks:
        task_id = task.get("task_id", "unknown_task")
        task_hash = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()[:12]
        run_id = f"run_{task_id}_baseline_{task_hash}"
        spec = RunSpec(
            run_id=run_id,
            candidate_id=baseline_candidate.candidate_id,
            task_id=task_id,
            seed=42,
            max_steps=max_steps,
            timeout_s=timeout_s,
        )

        try:
            res = runner.run(
                candidate=baseline_candidate,
                task_def=task,
                spec=spec,
                retain_workspace=True,
            )
        except Exception as exc:  # noqa: BLE001 - kernel-level failure must be visible
            results.append({
                "task_id": task_id,
                "run_id": run_id,
                "status": "crashed",
                "score": 0.0,
                "usage": {},
                "error": f"{type(exc).__name__}: {exc}",
                "tool_calls": [],
            })
            continue

        metadata = res.metadata or {}
        chain_records = metadata.get("chain") or []
        results.append({
            "task_id": task_id,
            "run_id": run_id,
            "status": res.status,
            "score": res.score,
            "usage": res.usage,
            "kernel_steps": metadata.get("kernel_steps"),
            "chain_model_calls": metadata.get("chain_model_calls", 0),
            "chain_tool_calls": metadata.get("chain_tool_calls", 0),
            "tool_call_names": [
                str((e.payload.get("action") or {}).get("name"))
                for e in journal.get_events(run_id)
                if e.event_type == "action" and e.payload.get("source") == "kage_chain"
            ],
            "chain_steps": [c.get("chain_steps") for c in chain_records],
            "final_text": (chain_records[0].get("final_text") if chain_records else ""),
            "progress_stagnant": res.progress_stagnant,
        })

    elapsed = round(time.time() - start_total, 2)

    passed = sum(1 for r in results if r["status"] == "passed")
    crashed = [r for r in results if r["status"] == "crashed"]
    total_input = sum(int((r.get("usage") or {}).get("input_tokens", 0)) for r in results)
    total_output = sum(int((r.get("usage") or {}).get("output_tokens", 0)) for r in results)

    if crashed:
        outcome = "infrastructure_failure"
    elif passed == len(results) and results:
        outcome = "pass"
    else:
        outcome = "fail"

    report = {
        "suite_id": suite_id,
        "provider_mode": provider_info.get("provider_mode", provider_name),
        "provider": provider_info,
        "environment": (provider.metadata().get("environment")
                        if hasattr(provider, "metadata") else {}),
        "generated_at": time.time(),
        "journal_db": str(journal_db),
        "tasks": results,
        "totals": {
            "tasks": len(results),
            "passed": passed,
            "input_tokens": total_input,
            "output_tokens": total_output,
            # model_calls counts real provider calls (a live chain step may make
            # several); budget_settlements counts kernel reservations.
            "model_calls": sum(int(r.get("chain_model_calls") or 0) for r in results),
            "budget_settlements": budget.total_api_calls,
            "estimated_cost_usd": round(budget.total_cost_usd, 6),
            "elapsed_s": elapsed,
        },
        "outcome": outcome,
        "notes": (
            "provider_mode=fake bypasses the Kage chain (fixture writes files directly). "
            "provider_mode=live runs the frozen AgenticLoop/PromptBuilder/ToolExecutor chain "
            "with a real provider; usage is provider-reported."
        ),
    }

    report_file = Path(report_path) if report_path else work_dir / "report.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not quiet:
        print(f"\n{'TASK ID':<28} {'STATUS':<12} {'SCORE':<7} {'IN':<7} {'OUT':<7} {'CALLS':<6} {'TOOLS'}")
        print("-" * 78)
        for r in results:
            usage = r.get("usage") or {}
            print(f"{r['task_id']:<28} {r['status']:<12} {float(r.get('score') or 0):<7.2f} "
                  f"{int(usage.get('input_tokens', 0)):<7} {int(usage.get('output_tokens', 0)):<7} "
                  f"{int(r.get('chain_model_calls') or 0):<6} {','.join(r.get('tool_call_names') or [])}")
        print("-" * 78)
        cost_note = ("provider-reported tokens" if provider_name == "live"
                     else "illustrative; no API charge")
        print(f"Outcome: {outcome} | {passed}/{len(results)} passed | "
              f"tokens in={total_input} out={total_output} | time={elapsed}s")
        print(f"Estimated cost: ${budget.total_cost_usd:.6f} ({cost_note})")
        print(f"Report: {report_file}")
        print("=" * 78 + "\n")

    if crashed:
        return EXIT_INFRA_FAILURE
    if fail_on_task_failure and passed != len(results):
        return EXIT_TASK_FAILED
    return EXIT_OK


def main() -> None:
    parser = argparse.ArgumentParser(description="Kage EvoLab CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    baseline_parser = subparsers.add_parser("baseline", help="Run baseline candidate on a test suite")
    baseline_parser.add_argument("--suite", default="eval/evolution/smoke.json", help="Path to evaluation suite JSON")
    baseline_parser.add_argument("--provider", default="fake", choices=["fake", "live"], help="LLM provider mode")
    baseline_parser.add_argument("--config", default="config/settings.json", help="Settings JSON used to build the live provider")
    baseline_parser.add_argument("--profile", default="background",
                                 choices=["background", "routing", "realtime"], help="ModelBroker role for live runs")
    baseline_parser.add_argument("--base-url", default=None, help="Override the provider base URL (live)")
    baseline_parser.add_argument("--model", default=None, help="Override the model name (live)")
    baseline_parser.add_argument("--api-key-env", default="OPENAI_API_KEY",
                                 help="Environment variable holding the API key (live)")
    baseline_parser.add_argument("--allow-hybrid-escalation", action="store_true",
                                 help="Permit HYBRID role mode (records that local→cloud escalation is possible)")
    baseline_parser.add_argument("--max-steps", type=int, default=None, help="Kernel steps per task")
    baseline_parser.add_argument("--timeout", type=int, default=180, help="Per-task wall-clock timeout (seconds)")
    baseline_parser.add_argument("--db", default=None, help="Custom journal database path")
    baseline_parser.add_argument("--output", default=None, help="Custom output directory")
    baseline_parser.add_argument("--report", default=None, help="Custom report.json path")
    baseline_parser.add_argument("--retry-crashed", action="store_true",
                                 help="Drop journal+budget records of previously crashed/"
                                      "timeout/budget-exhausted runs so they are re-executed")
    baseline_parser.add_argument("--fail-on-task-failure", action="store_true",
                                 help="Return exit code 4 when tasks fail evaluation "
                                      "(default: exit 0 once the experiment completes)")
    baseline_parser.add_argument("--step-isolation", default="fork", choices=["fork", "inline"],
                                 help="fork = one process group per step (default); "
                                      "inline = run in-process (needed where fork() is unsafe)")

    args = parser.parse_args()

    if args.command == "baseline":
        code = run_baseline(
            suite_path=args.suite,
            provider_name=args.provider,
            db_path=args.db,
            output_dir=args.output,
            config_path=args.config,
            role=args.profile,
            base_url=args.base_url,
            model_name=args.model,
            api_key_env=args.api_key_env,
            allow_hybrid=args.allow_hybrid_escalation,
            max_steps=args.max_steps,
            timeout_s=args.timeout,
            report_path=args.report,
            step_isolation=args.step_isolation,
            fail_on_task_failure=args.fail_on_task_failure,
            retry_crashed=args.retry_crashed,
        )
        sys.exit(code)


if __name__ == "__main__":
    main()
