"""C4.3: one verified dev teacher episode -> E1 candidate -> paired local evaluation."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.evolution.agent_provider import KageChainProvider
from core.evolution.archive import ExperienceArchive
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.mutator import Mutator, bundle_digest
from core.evolution.promotion import Promoter
from core.evolution.sandbox import DockerSkillRunner
from core.evolution.skills import SkillCatalog
from task_suite import RecordedLocalProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode-journal", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--teacher-config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18082)
    parser.add_argument("--skill-context", choices=["search", "preview"], default="search")
    parser.add_argument("--candidate-record", type=Path, help="Reevaluate a previously generated immutable candidate without another optimizer call")
    args = parser.parse_args()
    task = json.loads(args.suite.read_text())["tasks"][0]
    if task.get("split") != "dev":
        parser.error("skill learning requires a dev task")
    episodes = ExperienceArchive(Journal(args.episode_journal)).retrieve(task["family"])
    episode = next((e for e in episodes if e["task_id"] == task["task_id"] and
                   any(c.get("takeover", {}).get("teacher_check", {}).get("check_passed")
                       for c in e["run"]["metadata"].get("chain", []))), None)
    if episode is None:
        parser.error("no intact verified dev teacher episode available")
    cloud = json.loads(args.teacher_config.read_text())["model"]["cloud_api"]
    if cloud.get("model_name") != "deepseek-flash" or cloud.get("base_url", "").rstrip("/") != "https://api.deepseek.com":
        parser.error("verified official Flash configuration required")
    skill_runner = DockerSkillRunner(timeout_s=10)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    journal = Journal(args.output_dir / "journal.sqlite")
    optimizer_budget = BudgetTracker(BudgetConfig(max_api_calls=3, max_input_tokens_total=36000,
        max_output_tokens_total=9000, max_cost_usd=0.03, input_cost_per_million=.3,
        output_cost_per_million=1.2), args.output_dir / "optimizer-budget.sqlite")
    local_budget = BudgetTracker(BudgetConfig(max_api_calls=36, input_cost_per_million=0,
        output_cost_per_million=0), args.output_dir / "student-budget.sqlite")
    parent_dir = args.output_dir / "parent"; parent_dir.mkdir()
    (parent_dir / "manifest.json").write_text('{"version":1,"skills":[]}')
    parent = Candidate("no-skills", (), "skill", str(parent_dir.resolve()), bundle_digest(parent_dir))
    trace = [json.loads(line) for line in Path(episode["run"]["trace_path"]).read_text().splitlines()]
    optimizer = RecordedLocalProvider(args.output_dir / "optimizer-model.jsonl", api_key=cloud["api_key"],
        model_name=cloud["model_name"], base_url=cloud["base_url"], thinking=False, output_limit=3000)
    feedback = {"task_id": task["task_id"], "instruction": task["instruction"],
        "failure_reason": "The student failed; the teacher's actual correction passed external checks. Extract a reusable repair skill. Parameterize the target Python file path. Do not encode any example job IDs, weights, or answers.", "trace": trace}
    if args.candidate_record:
        data = json.loads(args.candidate_record.read_text())["candidate"]
        data["parent_ids"] = tuple(data["parent_ids"])
        child = Candidate(**data)
        if bundle_digest(Path(child.bundle_path)) != child.digest:
            raise ValueError("candidate artifact changed")
    else:
        child = Mutator(optimizer, optimizer_budget, journal, args.output_dir / "mutation").propose(parent, feedback)
    def provider_factory(candidate):
        path = args.output_dir / f"student-{candidate.digest[:16]}.jsonl"
        model = RecordedLocalProvider(path, api_key="local", model_name="agents-a1-4b",
            base_url=f"http://127.0.0.1:{args.port}/v1", timeout_sec=120)
        return KageChainProvider(model, model_label="agents-a1-4b", max_model_calls=6,
            skill_catalog=SkillCatalog.from_bundle(Path(candidate.bundle_path), runner=skill_runner),
            skill_context_mode=args.skill_context)
    promoter = Promoter(journal, local_budget, provider_factory, args.output_dir / "evaluation",
                        timeout_s=150, step_isolation="fork")
    comparison = promoter.compare(parent, child, [task])
    # Reuse input is never sent to the optimizer or used to decide promotion.
    reuse = {**task, "task_id": task["task_id"] + "-unseen", "split": "reuse", "initial_files": {
        "selection.py": "def choose(jobs, capacity):\n    return []\n"}, "scoring_criteria": {
        "type": "python_function", "file": "selection.py", "function": "choose", "cases": [
            {"args": [[{"id":"x","weight":2,"value":4},{"id":"y","weight":3,"value":7},{"id":"z","weight":5,"value":10}],5],"expected":["x","y"]},
            {"args": [[{"id":"y","weight":1,"value":2},{"id":"x","weight":1,"value":2}],1],"expected":["x"]},
            {"args": [[],0],"expected":[]}]}}
    result = promoter.evaluate(child, reuse)
    rows = [json.loads(line) for line in Path(result.trace_path).read_text().splitlines()]
    actual_skill_calls = sum(row.get("action", {}).get("name") == "skill_call" for row in rows)
    report = {"episode_id": episode["episode_id"], "parent": asdict(parent), "child": asdict(child),
              "comparison": comparison, "reuse": asdict(result), "reuse_skill_calls": actual_skill_calls,
              "candidate_record": str(args.candidate_record) if args.candidate_record else None,
              "optimizer_usage": optimizer_budget.usage_by_type, "optimizer_estimated_cost_usd": optimizer_budget.total_cost_usd,
              "docker_image_id": skill_runner.image_id, "cloud_off_in_student_evaluation": True, "skill_context_mode": args.skill_context,
              "capability_verified": comparison["promoted"] and result.status == "passed" and actual_skill_calls > 0}
    (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"promoted": comparison["promoted"], "parent_score": comparison["parent_score"],
         "child_score": comparison["child_score"], "reuse_status": result.status, "reuse_skill_calls": actual_skill_calls,
         "capability_verified": report["capability_verified"]}), flush=True)


if __name__ == "__main__":
    main()
