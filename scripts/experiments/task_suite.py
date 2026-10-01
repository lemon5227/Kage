"""Run the frozen C2 file suite through the real chain and external evaluator."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.evolution.agent_provider import KageChainProvider
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate, RunSpec
from core.evolution.journal import Journal
from core.evolution.runner import EvolutionRunner
from core.evolution.takeover import TeacherTakeoverProvider
from core.evolution.archive import ExperienceArchive
from core.model_provider import OpenAICompatibleProvider


class RecordedLocalProvider(OpenAICompatibleProvider):
    def __init__(self, trace_path, output_limit=None, **kwargs):
        super().__init__(**kwargs)
        self.trace_path = trace_path
        self.output_limit = output_limit

    def generate(self, messages, **kwargs):
        kwargs["temperature"] = 0
        if self.thinking is False:
            if len(json.dumps({"messages": messages, "model": self.model_name, **kwargs}, ensure_ascii=False).encode()) > 12000:
                raise RuntimeError("teacher input byte cap reached")
            kwargs["max_tokens"] = self.output_limit or min(300, kwargs.get("max_tokens", 300))
        response = super().generate(messages=messages, **kwargs)
        with self.trace_path.open("a") as out:
            out.write(json.dumps({"messages": messages, "request": kwargs,
                                  "response": asdict(response)}, ensure_ascii=False) + "\n")
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=ROOT / "eval/computer-use/files-v1.json")
    parser.add_argument("--port", type=int, default=18082)
    parser.add_argument("--model", default="agents-a1-4b")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--split", choices=["dev", "holdout", "all"], default="all")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--task", help="Run only this task ID")
    parser.add_argument("--teacher-config", type=Path, help="Private DeepSeek settings; never copied into artifacts")
    parser.add_argument("--max-cost-usd", type=float, default=0.03)
    parser.add_argument("--teacher-output-tokens", type=int, choices=[300, 1024], default=300)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    cloud = None
    if args.teacher_config:
        cloud = json.loads(args.teacher_config.read_text())["model"]["cloud_api"]
        if cloud.get("model_name") != "deepseek-flash" or cloud.get("base_url", "").rstrip("/") != "https://api.deepseek.com":
            parser.error("pilot requires the verified deepseek-flash official endpoint")
        if not cloud.get("api_key"):
            parser.error("teacher credential missing")
        if args.runs != 1 or not args.task:
            parser.error("teacher pilot is limited to one selected task/run")
        teacher_ceiling = 6 * (12000 * 0.3 + args.teacher_output_tokens * 1.2) / 1_000_000
        if args.max_cost_usd < teacher_ceiling:
            parser.error(f"budget must cover the conservative teacher ceiling of ${teacher_ceiling}")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    suite_bytes = args.suite.read_bytes()
    suite = json.loads(suite_bytes)
    protocol = suite["protocol"]
    tasks = [t for t in suite["tasks"] if (args.split == "all" or t["split"] == args.split) and (not args.task or t["task_id"] == args.task)]
    config = {"model": args.model, "port": args.port, "runs": args.runs, "split": args.split,
              "task": args.task, "teacher": ({"model": cloud["model_name"], "thinking": False, "max_calls": 6, "max_request_input_bytes": 12000, "max_output_tokens": args.teacher_output_tokens, "cost_ceiling_usd": teacher_ceiling} if cloud else None),
              "suite_sha256": hashlib.sha256(suite_bytes).hexdigest(), "protocol": protocol}
    (args.output_dir / "config.json").write_text(json.dumps(config, indent=2))
    journal = Journal(args.output_dir / "journal.sqlite")
    archive = ExperienceArchive(journal)
    cap = len(tasks) * args.runs * protocol["max_model_calls"] * (2 if cloud else 1)
    budget = BudgetTracker(BudgetConfig(max_api_calls=cap, max_input_tokens_total=cap*8000,
                          max_output_tokens_total=cap*2000, max_cost_usd=args.max_cost_usd if cloud else None,
                          input_cost_per_million=0.3 if cloud else 0,
                          output_cost_per_million=1.2 if cloud else 0), args.output_dir / "budget.sqlite")
    candidate = Candidate("local_baseline", (), "workflow", str(ROOT), "frozen-c2-v1")
    rows = []
    for repeat in range(args.runs):
        for task in tasks:
            run_id = f'{task["task_id"]}-{repeat}'
            model = RecordedLocalProvider(args.output_dir / f"{run_id}-model.jsonl", api_key="local",
                    model_name=args.model, base_url=f"http://127.0.0.1:{args.port}/v1", timeout_sec=120)
            chain = KageChainProvider(model, model_label=args.model,
                                    max_model_calls=protocol["max_model_calls"])
            if cloud:
                teacher_model = RecordedLocalProvider(args.output_dir / f"{run_id}-teacher.jsonl",
                    api_key=cloud["api_key"], model_name=cloud["model_name"],
                    base_url=cloud["base_url"], timeout_sec=60, thinking=False, output_limit=args.teacher_output_tokens)
                teacher = KageChainProvider(teacher_model, model_label=cloud["model_name"],
                    provider_mode="cloud", max_model_calls=6)
                teacher.RESERVATION_OUTPUT_CAP = args.teacher_output_tokens * 6
                chain = TeacherTakeoverProvider(chain, teacher, task)
            runner = EvolutionRunner(journal, budget, args.output_dir / "workspaces", chain)
            start = time.monotonic()
            result = runner.run(candidate, task, RunSpec(run_id, candidate.candidate_id, task["task_id"],
                        max_steps=1, timeout_s=protocol["timeout_s"]), retain_workspace=True)
            archive.record(task, result)
            row = {"task": task["task_id"], "family": task["family"], "split": task["split"],
                   "repeat": repeat, "seconds": round(time.monotonic()-start, 3), **asdict(result)}
            rows.append(row)
            (args.output_dir / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
            print(json.dumps({k: row[k] for k in ["task", "repeat", "status", "score", "seconds"]} | {
                  "completion": result.metadata["completion"]}), flush=True)
    print(json.dumps({"passed": sum(r["status"] == "passed" for r in rows), "total": len(rows)}), flush=True)


if __name__ == "__main__":
    main()
