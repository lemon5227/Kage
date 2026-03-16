#!/usr/bin/env python3
"""Aggregate benchmark outputs into one readiness dashboard."""

from __future__ import annotations

import json
import time
from pathlib import Path


ROOT = Path("/Users/wenbo/Kage")
BM_DIR = ROOT / "docs" / "benchmarks"


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    e2e = _load(BM_DIR / "latest_kage_e2e_benchmark.json")
    route_ab = _load(BM_DIR / "latest_route_ab_benchmark.json")
    parallel = _load(BM_DIR / "latest_parallel_tools_benchmark.json")

    e2e_sum = e2e.get("summary") if isinstance(e2e, dict) else {}
    pass_rate = float((e2e_sum or {}).get("pass_rate") or 0.0)
    correctness_rate = float((e2e_sum or {}).get("correctness_rate") or 0.0)
    slo_rate = float((e2e_sum or {}).get("slo_rate") or 0.0)
    correction_rate = float((e2e_sum or {}).get("correction_success_rate") or 0.0)

    route_reco = str((route_ab or {}).get("recommendation") or "UNKNOWN")
    route_reason = str((route_ab or {}).get("reason") or "")

    speedup = float((parallel or {}).get("speedup") or 0.0)
    parallel_ok = speedup >= 1.2

    gates = {
        "e2e_quality_gate": pass_rate >= 0.95 and correctness_rate >= 0.95,
        "e2e_latency_gate": slo_rate >= 0.95,
        "correction_gate": correction_rate >= 0.95,
        "route_assist_gate": route_reco == "OFF",  # keep off unless AB says ON
        "parallel_speedup_gate": parallel_ok,
    }
    ready_for_test_assembly = all(bool(v) for v in gates.values())

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "inputs": {
            "e2e": str(BM_DIR / "latest_kage_e2e_benchmark.json"),
            "route_ab": str(BM_DIR / "latest_route_ab_benchmark.json"),
            "parallel": str(BM_DIR / "latest_parallel_tools_benchmark.json"),
        },
        "summary": {
            "pass_rate": pass_rate,
            "correctness_rate": correctness_rate,
            "slo_rate": slo_rate,
            "correction_success_rate": correction_rate,
            "route_assist_recommendation": route_reco,
            "route_assist_reason": route_reason,
            "parallel_speedup": round(speedup, 2),
        },
        "gates": gates,
        "ready_for_test_assembly": ready_for_test_assembly,
    }

    out = BM_DIR / "latest_benchmark_dashboard.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    print(f"saved={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
