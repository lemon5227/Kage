"""Supplementary raw-student control: max 1024/call, original 1800 total output."""
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
from core.model_provider import ModelCallLimitExceeded
from scripts.experiments.task_suite import RecordedLocalProvider


class FlexibleLocalProvider(RecordedLocalProvider):
    def __init__(self, *args, total_output_tokens=1800, **kwargs):
        super().__init__(*args, **kwargs)
        self.remaining_output = total_output_tokens

    def generate(self, messages, **kwargs):
        if self.remaining_output <= 0:
            raise ModelCallLimitExceeded("total output token allowance exhausted")
        kwargs["max_tokens"] = min(1024, self.remaining_output)
        response = super().generate(messages, **kwargs)
        # Unknown spend cannot justify another request under a fixed allowance.
        self.remaining_output = self.remaining_output - response.usage["output_tokens"] if "output_tokens" in response.usage else 0
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=ROOT / "eval/computer-use/learning-transfer-v1.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18082)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    suite_bytes = args.suite.read_bytes()
    suite = json.loads(suite_bytes)
    task = suite["tasks"][0]
    (args.output_dir / "config.json").write_text(json.dumps({"suite_sha256": hashlib.sha256(suite_bytes).hexdigest(),
        "max_model_calls":6,"max_loop_steps":5,"per_call_output_tokens":1024,"total_output_tokens":1800,"repeats":3,"cloud":False},indent=2))
    journal = Journal(args.output_dir / "journal.sqlite")
    budget = BudgetTracker(BudgetConfig(max_api_calls=18,input_cost_per_million=0,output_cost_per_million=0),args.output_dir/"budget.sqlite")
    candidate = Candidate("raw-flexible",(),"workflow",str(ROOT),"raw-flexible-output-v1")
    rows=[]
    for repeat in range(3):
        model=FlexibleLocalProvider(args.output_dir/f"model-{repeat}.jsonl",api_key="local",model_name="agents-a1-4b",base_url=f"http://127.0.0.1:{args.port}/v1",timeout_sec=120)
        chain=KageChainProvider(model,model_label="agents-a1-4b",max_model_calls=6)
        runner=EvolutionRunner(journal,budget,args.output_dir/"workspaces",chain)
        start=time.monotonic()
        result=runner.run(candidate,task,RunSpec(f"flexible-{repeat}",candidate.candidate_id,task["task_id"],max_steps=1,timeout_s=150))
        row={"repeat":repeat,"seconds":round(time.monotonic()-start,3),**asdict(result)}
        rows.append(row)
        (args.output_dir/"results.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2))
        print(json.dumps({k:row[k] for k in ["repeat","status","score","seconds","usage"]}),flush=True)


if __name__ == "__main__":
    main()
