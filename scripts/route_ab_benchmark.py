#!/usr/bin/env python3
"""A/B benchmark for route model assist.

Runs E2E benchmark twice:
- A: rule-only routing (KAGE_ROUTE_MODEL_ASSIST=0)
- B: rule + model-assist routing (KAGE_ROUTE_MODEL_ASSIST=1)

If B does not meet gates, recommendation is to keep feature OFF.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path


ROOT = Path("/Users/wenbo/Kage")
BENCH_JSON = ROOT / "docs/benchmarks/latest_kage_e2e_benchmark.json"
OUT_JSON = ROOT / "docs/benchmarks/latest_route_ab_benchmark.json"


def _run_one(assist: bool) -> dict:
    env = os.environ.copy()
    env["KAGE_TEXT_ONLY"] = "1"
    env["KAGE_BENCH_TEXT_ONLY"] = "1"
    env["KAGE_ROUTE_MODEL_ASSIST"] = "1" if assist else "0"

    server = subprocess.Popen(
        ["uvicorn", "core.server:app", "--host", "127.0.0.1", "--port", "12346"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ready = False
        for _ in range(60):
            p = subprocess.run(
                ["curl", "-sf", "http://127.0.0.1:12346/api/health"],
                cwd=str(ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if p.returncode == 0:
                ready = True
                break
            time.sleep(1)
        if not ready:
            return {"error": "server_not_ready"}

        run = subprocess.run(
            [
                "python",
                "scripts/kage_e2e_benchmark.py",
                "--uri",
                "ws://127.0.0.1:12346/ws",
                "--include-system",
            ],
            cwd=str(ROOT),
            env=env,
        )
        if run.returncode not in (0, 1):
            return {"error": f"benchmark_failed:{run.returncode}"}
        if not BENCH_JSON.exists():
            return {"error": "missing_benchmark_json"}
        return json.loads(BENCH_JSON.read_text(encoding="utf-8"))
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()


def main() -> int:
    a = _run_one(False)
    b = _run_one(True)

    a_sum = (a or {}).get("summary") if isinstance(a, dict) else None
    b_sum = (b or {}).get("summary") if isinstance(b, dict) else None

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "A_rule_only": a_sum if isinstance(a_sum, dict) else {"error": "invalid"},
        "B_model_assist": b_sum if isinstance(b_sum, dict) else {"error": "invalid"},
        "recommendation": "OFF",
        "reason": "invalid_result",
    }

    if isinstance(a_sum, dict) and isinstance(b_sum, dict):
        a_pass = float(a_sum.get("pass_rate") or 0.0)
        b_pass = float(b_sum.get("pass_rate") or 0.0)
        a_avg = float(a_sum.get("avg_ms") or 0.0)
        b_avg = float(b_sum.get("avg_ms") or 0.0)

        # Gate: no quality drop; latency regression <= 10%
        quality_ok = b_pass >= a_pass
        latency_ok = b_avg <= (a_avg * 1.10 if a_avg > 0 else b_avg)
        if quality_ok and latency_ok:
            report["recommendation"] = "ON"
            report["reason"] = "meets_quality_and_latency_gates"
        else:
            report["recommendation"] = "OFF"
            report["reason"] = "fails_quality_or_latency_gates"

    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    print(f"saved={OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
