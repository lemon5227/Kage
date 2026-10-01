"""Small live-model compatibility probe; not a general capability benchmark."""
import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.evolution.agent_provider import KageChainProvider
from core.model_provider import OpenAICompatibleProvider

TASKS = [
    ("sales", {"sales.csv": "region,amount\nEast,12\nWest,7\nEast,-2\nWest,3\n"},
     "Read sales.csv. Sum signed amounts per region and write totals.json as an object mapping each region to its numeric total.", "totals.json"),
    ("code", {"helper.py": "def clamp(value, low, high):\n    return low\n"},
     "Read helper.py and fix clamp(value, low, high): return low below low, high above high, otherwise value. Raise ValueError if low > high. Write the fixed helper.py.", "helper.py"),
    ("report", {"before.txt": "Revenue: 80\nOrders: 10\n", "after.txt": "Revenue: 100\nOrders: 8\n"},
     "Read before.txt and after.txt. Write report.md with headings Revenue and Orders, their before and after values, and percentage changes (revenue +25%, orders -20%).", "report.md"),
]

def check(task_id, path):
    if task_id == "sales":
        return json.loads(path.read_text()) == {"East": 10, "West": 10}
    if task_id == "code":
        checks = '''import runpy,sys
f=runpy.run_path(sys.argv[1])["clamp"]
for args,want in [((-5,0,10),0),((15,0,10),10),((4,0,10),4),((0,0,10),0),((10,0,10),10),((1.5,0,2),1.5)]:
 assert f(*args)==want, (args,want)
try: f(2,5,1)
except ValueError: pass
else: raise AssertionError("missing ValueError")
'''
        p = subprocess.run([sys.executable, "-I", "-c", checks, str(path)], capture_output=True, text=True, timeout=5)
        return p.returncode == 0
    text = path.read_text().lower()
    # A narrow content checker, not a judge of prose quality.
    return all(s in text for s in ("revenue", "orders", "80", "100", "10", "8", "25%", "-20%"))

class FixedProvider(OpenAICompatibleProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.requests = []
        self.responses = []
    def generate(self, messages, **kwargs):
        self.requests.append(messages)
        kwargs['temperature'] = 0
        response = super().generate(messages, **kwargs)
        self.responses.append({"text": response.text, "tool_calls": response.tool_calls})
        return response

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("engine")
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--model", default="local-model")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "config.json").write_text(json.dumps({**vars(args), "temperature": 0, "max_chain_calls": 6, "max_loop_steps": 5, "max_output_tokens_per_call": 300}, indent=2))
    results = []
    for repeat in range(args.runs):
        for task_id, files, instruction, output in TASKS:
            workspace = output_dir / "tasks" / f"{task_id}-{repeat}"
            workspace.mkdir(parents=True, exist_ok=True)
            for name, content in files.items():
                (workspace / name).write_text(content)
            provider = FixedProvider(api_key="local", model_name=args.model,
                base_url=f"http://127.0.0.1:{args.port}/v1", timeout_sec=90)
            chain = KageChainProvider(provider, model_label="Qwen3-4B", max_model_calls=6)
            started = time.monotonic()
            error = None
            record = {}
            try:
                record = chain.generate_step({"task_id": task_id, "instruction": instruction}, 1, [], workspace)
                passed = check(task_id, workspace / output)
            except Exception as exc:
                passed = False
                error = f"{type(exc).__name__}: {exc}"
            row = {"engine": args.engine, "task": task_id, "repeat": repeat,
                   "passed": passed, "seconds": round(time.monotonic()-started,3),
                   "error": error, "record": record, "requests": provider.requests, "responses": provider.responses}
            results.append(row)
            (output_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
            print(json.dumps({k:v for k,v in row.items() if k not in {"record", "requests", "responses"}}), flush=True)
    print("Summary", sum(r["passed"] for r in results), "/", len(results), "median seconds", statistics.median(r["seconds"] for r in results))

if __name__ == "__main__":
    main()
