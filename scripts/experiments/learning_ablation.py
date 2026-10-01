"""C4.4 fixed candidate/holdout: raw, cloud rescue, trajectory, skills and local retry."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.agentic_loop import AgenticLoop
from core.evolution.agent_provider import KageChainProvider
from core.evolution.archive import ExperienceArchive
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate, RunSpec
from core.evolution.journal import Journal
from core.evolution.mutator import bundle_digest
from core.evolution.retries import LocalRetryProvider
from core.evolution.runner import EvolutionRunner
from core.evolution.sandbox import DockerSkillRunner
from core.evolution.skills import SkillCatalog
from core.evolution.takeover import TeacherTakeoverProvider
from task_suite import RecordedLocalProvider

ARMS = ["raw", "cloud", "trajectory", "skills", "retries"]


class DemonstrationChain(KageChainProvider):
    def __init__(self, *args, demonstration, **kwargs):
        super().__init__(*args, **kwargs)
        self.demonstration = demonstration

    def cache_identity(self):
        return {**super().cache_identity(), "demonstration_sha256": hashlib.sha256(
            json.dumps(self.demonstration, sort_keys=True).encode()).hexdigest()}

    def generate_step(self, task_def, step, history, workspace_dir):
        # Only recorded dev teacher actions and their actual feedback; never
        # inject the new task's checks or expected outputs.
        return super().generate_step(task_def, step, self.demonstration + history, workspace_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=ROOT / "eval/computer-use/learning-transfer-v1.json")
    parser.add_argument("--candidate-record", type=Path, required=True)
    parser.add_argument("--episode-journal", type=Path, required=True)
    parser.add_argument("--teacher-config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18082)
    args = parser.parse_args()
    suite = json.loads(args.suite.read_text())
    if len(suite["tasks"]) != 1 or suite["tasks"][0].get("split") != "holdout":
        parser.error("this pilot requires exactly one frozen holdout task")
    task = suite["tasks"][0]
    data = json.loads(args.candidate_record.read_text())["candidate"]
    data["parent_ids"] = tuple(data["parent_ids"])
    candidate = Candidate(**data)
    if bundle_digest(Path(candidate.bundle_path)) != candidate.digest:
        parser.error("candidate bundle changed")
    episodes = ExperienceArchive(Journal(args.episode_journal)).retrieve(task["family"])
    episode = next((e for e in episodes if any(c.get("takeover", {}).get("teacher_check", {}).get("check_passed")
                    for c in e["run"]["metadata"].get("chain", []))), None)
    if episode is None:
        parser.error("verified dev teacher demonstration missing")
    trace = list(map(json.loads, Path(episode["run"]["trace_path"]).read_text().splitlines()))
    demo = [row for row in trace if row.get("observation", {}).get("actor") == "teacher"]
    cloud = json.loads(args.teacher_config.read_text())["model"]["cloud_api"]
    if cloud.get("model_name") != "deepseek-flash" or cloud.get("base_url", "").rstrip("/") != "https://api.deepseek.com":
        parser.error("verified official Flash configuration required")
    docker_runner = DockerSkillRunner(timeout_s=10)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    config = {"suite_sha256": hashlib.sha256(args.suite.read_bytes()).hexdigest(), "candidate_digest": candidate.digest,
              "episode_id": episode["episode_id"], "arms": ARMS, "repeats": 3, "local_max_calls": 6,
              "local_max_steps": 5, "local_output_tokens": 300, "teacher_max_calls": 6,
              "teacher_output_tokens": 1024, "teacher_input_bytes": 12000,
              "cloud_cost_ceiling_usd": 0.0869184, "cloud_budget_usd": .10, "docker_image_id": docker_runner.image_id}
    (args.output_dir / "config.json").write_text(json.dumps(config, indent=2))
    journal = Journal(args.output_dir / "journal.sqlite")
    archive = ExperienceArchive(journal)
    budget = BudgetTracker(BudgetConfig(max_api_calls=108, max_cost_usd=.20,
              max_input_tokens_total=1_000_000, max_output_tokens_total=200000,
              input_cost_per_million=.3, output_cost_per_million=1.2), args.output_dir / "budget.sqlite")
    # Includes local tokens at cloud rates conservatively; the actual paid
    # ceiling is enforced separately by the three fixed cloud attempts.
    rows = []
    for repeat in range(3):
        for arm in ARMS:
            run_id = f"{arm}-{repeat}"
            def local_chain(call_cap=6, step_cap=5, catalog=None, chain_cls=KageChainProvider):
                model = RecordedLocalProvider(args.output_dir / f"{run_id}-local.jsonl", api_key="local",
                    model_name="agents-a1-4b", base_url=f"http://127.0.0.1:{args.port}/v1", timeout_sec=120)
                loop_cls = type("BudgetedLoop", (AgenticLoop,), {"MAX_STEPS": step_cap})
                options = {"demonstration": demo} if chain_cls is DemonstrationChain else {}
                return chain_cls(model, model_label="agents-a1-4b", max_model_calls=call_cap,
                    agentic_loop_cls=loop_cls, skill_catalog=catalog,
                    skill_context_mode="preview" if catalog is not None else "search", **options)
            if arm == "skills":
                provider = local_chain(catalog=SkillCatalog.from_bundle(Path(candidate.bundle_path), runner=docker_runner))
            elif arm == "trajectory":
                provider = local_chain(chain_cls=DemonstrationChain)
            elif arm == "retries":
                provider = LocalRetryProvider(local_chain, task)
            elif arm == "cloud":
                model = RecordedLocalProvider(args.output_dir / f"{run_id}-cloud.jsonl", api_key=cloud["api_key"],
                    model_name=cloud["model_name"], base_url=cloud["base_url"], timeout_sec=60,
                    thinking=False, output_limit=1024)
                teacher = KageChainProvider(model, model_label="deepseek-flash", provider_mode="cloud", max_model_calls=6)
                teacher.RESERVATION_OUTPUT_CAP = 6144
                provider = TeacherTakeoverProvider(local_chain(), teacher, task)
            else:
                provider = local_chain()
            runner = EvolutionRunner(journal, budget, args.output_dir / "workspaces", provider)
            start = time.monotonic()
            result = runner.run(candidate, task, RunSpec(run_id, candidate.candidate_id,
                        task["task_id"], max_steps=1, timeout_s=150))
            trace_rows = list(map(json.loads, Path(result.trace_path).read_text().splitlines()))
            row = {"arm": arm, "repeat": repeat, "seconds": round(time.monotonic()-start,3),
                   "skill_calls": sum(r.get("action", {}).get("name") == "skill_call" for r in trace_rows), **asdict(result)}
            rows.append(row)
            archive.record(task, result)  # holdout is always excluded from learning
            (args.output_dir / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
            print(json.dumps({k:row[k] for k in ["arm","repeat","status","score","seconds","skill_calls"]}), flush=True)
    summary = {arm: {"passed": sum(r["status"] == "passed" for r in rows if r["arm"] == arm),
                        "total": sum(r["arm"] == arm for r in rows)} for arm in ARMS}
    (args.output_dir / "summary.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
