#!/usr/bin/env python3
"""Lightweight route benchmark for Kage eval cases.

This runner intentionally avoids starting the full runtime. It imports the
realtime lane classifier and verifies that route/reason decisions match
`eval/eval_cases.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "eval" / "eval_cases.json"
DEFAULT_OUT = ROOT / "docs" / "benchmarks" / "latest_kage_eval_runner.json"


def _load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"expected list in {path}")
    return [case for case in data if isinstance(case, dict)]


def _predicted_route(decision) -> str:
    reason = str(getattr(decision, "reason", "") or "")
    lane = str(getattr(decision, "lane", "") or "")
    return reason or lane


def main() -> int:
    parser = argparse.ArgumentParser(description="Run static Kage route eval cases.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    from core.realtime_lane import classify_realtime_task

    cases = _load_cases(args.cases)
    results: list[dict] = []

    for case in cases:
        text = str(case.get("input") or "")
        expected = str(case.get("expected_route") or "")
        start = time.perf_counter()
        decision = classify_realtime_task(text)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        predicted = _predicted_route(decision)
        passed = predicted == expected
        results.append(
            {
                "id": case.get("id"),
                "category": case.get("category"),
                "input": text,
                "expected_route": expected,
                "predicted_route": predicted,
                "lane": getattr(decision, "lane", ""),
                "can_background": getattr(decision, "can_background", False),
                "latency_ms": round(elapsed_ms, 3),
                "pass": passed,
            }
        )

    total = len(results)
    passed = sum(1 for item in results if item["pass"])
    failed = total - passed
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "route_accuracy": round(passed / total, 4) if total else 0.0,
            "avg_latency_ms": round(
                sum(float(item["latency_ms"]) for item in results) / total, 3
            )
            if total
            else 0.0,
        },
        "results": results,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report["summary"], ensure_ascii=False))
        for item in results:
            if not item["pass"]:
                print(
                    f"FAIL {item['id']}: expected={item['expected_route']} predicted={item['predicted_route']}"
                )
        print(f"saved={args.out}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
