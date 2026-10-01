"""Index complete experiment results without copying hidden scoring criteria."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.evolution.archive import ExperienceArchive
from core.evolution.contracts import RunResult
from core.evolution.journal import Journal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--suite", type=Path, default=ROOT / "eval/computer-use/files-v1.json")
    parser.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args()
    tasks = {t["task_id"]: t for t in json.loads(args.suite.read_text())["tasks"]}
    archive = ExperienceArchive(Journal(args.journal))
    for row in json.loads(args.results.read_text()):
        result = RunResult(**{k: row[k] for k in RunResult.__dataclass_fields__ if k in row})
        archive.record(tasks[row["task"]], result)
    print(json.dumps({"episodes": len(archive.list_episodes()),
                      "dev_retrievable": sum(len(archive.retrieve(family, limit=1000))
                          for family in {task["family"] for task in tasks.values()})}))


if __name__ == "__main__":
    main()
