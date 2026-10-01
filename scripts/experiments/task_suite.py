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
from core.model_provider import OpenAICompatibleProvider


class RecordedLocalProvider(OpenAICompatibleProvider):
    def __init__(self, trace_path, **kwargs):
        super().__init__(**kwargs)
        self.trace_path = trace_path

    def generate(self, messages, **kwargs):
        kwargs["temperature"] = 0
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
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    suite_bytes = args.suite.read_bytes()
    suite = json.loads(suite_bytes)
    protocol = suite["protocol"]
    tasks = [t for t in suite["tasks"] if args.split == "all" or t["split"] == args.split]
    config = {"model": args.model, "port": args.port, "runs": args.runs, "split": args.split,
              "suite_sha256": hashlib.sha256(suite_bytes).hexdigest(), "protocol": protocol}
    (args.output_dir / "config.json").write_text(json.dumps(config, indent=2))
    journal = Journal(args.output_dir / "journal.sqlite")
    cap = len(tasks) * args.runs * protocol["max_model_calls"]
    budget = BudgetTracker(BudgetConfig(max_api_calls=cap, max_input_tokens_total=cap*8000,
                          max_output_tokens_total=cap*2000, input_cost_per_million=0,
                          output_cost_per_million=0), args.output_dir / "budget.sqlite")
    candidate = Candidate("local_baseline", (), "workflow", str(ROOT), "frozen-c2-v1")
    rows = []
    for repeat in range(args.runs):
        for task in tasks:
            run_id = f'{task["task_id"]}-{repeat}'
            model = RecordedLocalProvider(args.output_dir / f"{run_id}-model.jsonl", api_key="local",
                    model_name=args.model, base_url=f"http://127.0.0.1:{args.port}/v1", timeout_sec=120)
            chain = KageChainProvider(model, model_label=args.model,
                                    max_model_calls=protocol["max_model_calls"])
            runner = EvolutionRunner(journal, budget, args.output_dir / "workspaces", chain)
            start = time.monotonic()
            result = runner.run(candidate, task, RunSpec(run_id, candidate.candidate_id, task["task_id"],
                        max_steps=1, timeout_s=protocol["timeout_s"]), retain_workspace=True)
            row = {"task": task["task_id"], "family": task["family"], "split": task["split"],
                   "repeat": repeat, "seconds": round(time.monotonic()-start, 3), **asdict(result)}
            rows.append(row)
            (args.output_dir / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
            print(json.dumps({k: row[k] for k in ["task", "repeat", "status", "score", "seconds"]} | {
                  "completion": result.metadata["completion"]}), flush=True)
    print(json.dumps({"passed": sum(r["status"] == "passed" for r in rows), "total": len(rows)}), flush=True)


if __name__ == "__main__":
    main()
