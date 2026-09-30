"""Bounded E1 skill search using the real Kage chain and paired external scores."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import subprocess

from core.evolution.agent_provider import KageChainProvider, build_live_provider
from core.evolution.artifacts import atomic_json
from core.evolution.budget import BudgetConfig, BudgetTracker, BudgetExhaustedError
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.mutator import Mutator, MutationFailed, bundle_digest
from core.evolution.promotion import Promoter
from core.evolution.sandbox import DockerSkillRunner, ProcessSkillRunner
from core.evolution.skills import SkillCatalog


def report_outcome(report):
    runs = list(report.get("baseline", [])) + list(report.get("reuse", []))
    for comparison in report.get("comparisons", []):
        for pair in comparison["pairs"]:
            runs.extend((pair["parent"], pair["child"]))
    if any(run["status"] in {"crashed", "timeout"} for run in runs):
        return "infrastructure_failure"
    if report.get("stop_reason") == "budget_stop" or any(run["status"] == "budget_exhausted" for run in runs):
        return "budget_stop"
    return "complete"


def _candidate(data):
    return Candidate(**{**data, "parent_ids": tuple(data["parent_ids"])})


def _public_configuration(value):
    if isinstance(value, dict):
        return {key: _public_configuration(item) for key, item in value.items()
                if key.lower() not in {"api_key", "token", "password", "secret", "headers"}}
    if isinstance(value, list):
        return [_public_configuration(item) for item in value]
    return value


def run_search(config_path, provider_mode=None):
    config = json.loads(Path(config_path).read_text())
    mode = provider_mode or config.get("provider", "live")
    if mode not in {"live", "fixture"}:
        raise ValueError("search provider must be live or fixture")
    dev = [task for task in config["tasks"] if task.get("split") == "dev"]
    reuse = [task for task in config["tasks"] if task.get("split") == "reuse"]
    if not dev or len(dev) + len(reuse) != len(config["tasks"]):
        raise ValueError("pilot requires explicit dev tasks and optional reuse tasks")
    ids = [task["task_id"] for task in config["tasks"]]
    if len(set(ids)) != len(ids):
        raise ValueError("task IDs must be unique across splits")
    experiment = str(config.get("experiment_id", "pilot"))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", experiment):
        raise ValueError("invalid experiment_id")
    seed = int(config.get("seed", 42))
    root = Path(config.get("output_dir", "runs/evolution/search")) / mode / experiment / f"seed-{seed}"
    protocol = {"config": config, "provider_mode": mode}
    settings = {}
    if mode == "live":
        settings = json.loads(Path(config.get("settings", "config/settings.json")).read_text())
        effective = _public_configuration(settings)
        protocol["model_configuration_digest"] = hashlib.sha256(
            json.dumps(effective, sort_keys=True).encode()).hexdigest()
    protocol_path = root / "protocol.json"
    if protocol_path.exists() and json.loads(protocol_path.read_text()) != protocol:
        raise ValueError("experiment directory already contains a different protocol")
    if (root / "report.json").exists():
        report = json.loads((root / "report.json").read_text())
        if report.get("execution_mode") == "docker":
            probe = subprocess.run(["docker", "image", "inspect", config.get("image", "kage-evolution:local")],
                                   capture_output=True, timeout=10)
            if probe.returncode or json.loads(probe.stdout)[0]["Id"] != report.get("image_id"):
                raise ValueError("container image unavailable or changed since this report")
        active_path = root / "active.json"
        if active_path.exists():
            active = _candidate(json.loads(active_path.read_text())["candidate"])
            if bundle_digest(Path(active.bundle_path)) != active.digest:
                raise ValueError("cached active bundle digest mismatch")
        return report
    if mode == "fixture":
        from core.evolution.fixtures import FixtureAgent, FixtureOptimizer
        optimizer = FixtureOptimizer()
        model_factory = FixtureAgent
        model_label = "synthetic-fixture"
    else:
        options = config.get("model_options", {})
        def model_factory():
            return build_live_provider(settings, role="background", **options)[0]
        optimizer = model_factory()  # unavailable credentials fail before artifacts or model calls
        model_label = str(getattr(optimizer, "model_name", type(optimizer).__name__))
    mode_execution = config.get("execution_mode", "docker")
    if mode_execution == "docker":
        skill_runner = DockerSkillRunner(timeout_s=config.get("skill_timeout_s", 10),
                                         image=config.get("image", "kage-evolution:local"))
    elif mode_execution == "process" and mode == "fixture":
        skill_runner = ProcessSkillRunner(timeout_s=config.get("skill_timeout_s", 5))
    else:
        raise ValueError("live generated code requires docker; process is only for trusted fixtures")
    atomic_json(protocol_path, protocol)
    journal = Journal(root / "journal.sqlite")
    budget_config = BudgetConfig(**config["budget"])
    if budget_config.max_cost_usd is None or budget_config.max_cost_usd <= 0:
        raise ValueError("search requires a positive explicit cost ceiling")
    budget = BudgetTracker(budget_config, root / "budget.sqlite")
    baseline_path = root / "baseline"
    baseline_path.mkdir(exist_ok=True)
    if not (baseline_path / "manifest.json").exists():
        atomic_json(baseline_path / "manifest.json", {"version": 1, "skills": []})
    baseline = Candidate("baseline", (), "skill", str(baseline_path.resolve()), bundle_digest(baseline_path))
    def provider_factory(candidate):
        return KageChainProvider(model_factory(), provider_mode=mode, model_label=model_label,
            skill_catalog=SkillCatalog.from_bundle(Path(candidate.bundle_path), runner=skill_runner))
    promoter = Promoter(journal, budget, provider_factory, root, seed=seed,
                        timeout_s=config.get("task_timeout_s", 120), step_isolation="inline")
    state_path = root / "search_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "parent": asdict(baseline), "next_index": 0, "comparisons": [], "generation_failures": []}
    parent = _candidate(state["parent"])
    baseline_results = [asdict(promoter.evaluate(baseline, task)) for task in dev]
    stop_reason = "candidate_limit"
    for index in range(state["next_index"], int(config.get("max_candidates", 2))):
        results = [promoter.evaluate(parent, task) for task in dev]
        if any(result.status not in {"passed", "failed"} for result in results):
            stop_reason = "infrastructure_or_budget_failure"
            break
        failing = next(((task, result) for task, result in zip(dev, results) if result.status != "passed"), None)
        if not failing:
            stop_reason = "dev_passed"
            break
        task, failure = failing
        trace = [json.loads(line) for line in Path(failure.trace_path).read_text().splitlines()]
        feedback = {"task_id": task["task_id"], "instruction": task["instruction"],
                    "failure_reason": "external dev evaluator rejected the output",
                    "trace": [item for item in trace if item.get("event_type") in {"action", "observation"}]}
        mutator = Mutator(optimizer, budget, journal, root / "mutations" / f"slot-{index}")
        try:
            child = mutator.propose(parent, feedback)
            comparison = promoter.compare(parent, child, dev)
            state["comparisons"].append(comparison)
            if comparison["promoted"]:
                parent = child
        except MutationFailed as exc:
            state["generation_failures"].append({"index": index, "error": str(exc)})
        except BudgetExhaustedError:
            stop_reason = "budget_stop"
            break
        state.update({"parent": asdict(parent), "next_index": index + 1})
        atomic_json(state_path, state)
    reused = [asdict(promoter.evaluate(parent, task)) for task in reuse]
    report = {"provider_mode": mode, "model": model_label, "execution_mode": mode_execution,
              "image_id": getattr(skill_runner, "image_id", None), "stop_reason": stop_reason,
              "baseline": baseline_results, "active_candidate": asdict(parent),
              "comparisons": state["comparisons"], "generation_failures": state["generation_failures"],
              "reuse": reused, "usage_by_type": budget.usage_by_type,
              "total_api_calls": budget.total_api_calls, "estimated_cost_usd": budget.total_cost_usd,
              "cost_basis": "configured planning rates; fixture usage is synthetic",
              "report_path": str(root / "report.json")}
    atomic_json(root / "report.json", report)
    return report
