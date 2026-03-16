#!/usr/bin/env python3
"""Search primitive benchmark.

Measures latency and basic correctness across search sources.

Usage:
  python scripts/search_quality_benchmark.py
  python scripts/search_quality_benchmark.py --mock
"""

from __future__ import annotations

import argparse
import json
import time
import sys
from pathlib import Path


ROOT_DIR = str(Path(__file__).resolve().parents[1])
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


CASES = [
    {
        "name": "youtube-latest",
        "query": "曹操 最新 视频",
        "source": "youtube",
        "sort": "latest",
        "expects_any_domain": ["youtube.com", "youtu.be"],
    },
    {
        "name": "bilibili-latest",
        "query": "曹操 最新 视频",
        "source": "bilibili",
        "sort": "latest",
        "expects_any_domain": ["bilibili.com"],
    },
    {
        "name": "web-weather",
        "query": "明天 尼斯 天气",
        "source": "web",
        "sort": "relevance",
        "expects_any_domain": [],
    },
]


def _run_once(tools_impl, case: dict) -> dict:
    t0 = time.perf_counter()
    raw = tools_impl.search(
        query=case["query"],
        source=case["source"],
        sort=case.get("sort", "relevance"),
        max_results=5,
        filters={},
    )
    dt_ms = (time.perf_counter() - t0) * 1000

    try:
        payload = json.loads(raw)
    except Exception:
        payload = {"success": False, "error": "InvalidJSON"}

    items = payload.get("items") if isinstance(payload, dict) else None
    items = items if isinstance(items, list) else []
    top = items[0] if items else {}
    domain = str((top or {}).get("domain") or "")

    ok = bool(payload.get("success"))
    domain_ok = True
    expected_domains = case.get("expects_any_domain") or []
    if expected_domains and domain:
        domain_ok = any(d in domain for d in expected_domains)
    elif expected_domains and not domain:
        domain_ok = False

    return {
        "name": case["name"],
        "source": case["source"],
        "query": case["query"],
        "latency_ms": round(dt_ms, 1),
        "success": ok,
        "items_count": len(items),
        "top_domain": domain,
        "domain_ok": domain_ok,
        "error": payload.get("error") if isinstance(payload, dict) else None,
    }


def _mock_tavily_search(query: str, max_results: int = 5) -> str:
    q = str(query or "").lower()
    if "site:youtube.com" in q:
        return json.dumps(
            {
                "results": [
                    {"title": "曹操新视频", "url": "https://www.youtube.com/watch?v=abc", "content": "video"},
                    {"title": "杂项", "url": "https://example.com/x", "content": "x"},
                ]
            },
            ensure_ascii=False,
        )
    if "site:bilibili.com" in q:
        return json.dumps(
            {
                "results": [
                    {"title": "曹操新视频", "url": "https://www.bilibili.com/video/BV1xx", "content": "video"},
                    {"title": "杂项", "url": "https://example.com/x", "content": "x"},
                ]
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "results": [
                {"title": "Nice weather", "url": "https://wttr.in/Nice?format=j1", "content": "weather"}
            ]
        },
        ensure_ascii=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="Run benchmark with mocked search backend")
    args = parser.parse_args()

    from core import tools_impl

    if args.mock:
        from unittest.mock import patch

        p = patch.object(tools_impl, "tavily_search", side_effect=_mock_tavily_search)
        p.start()
    else:
        p = None

    try:
        rows = [_run_once(tools_impl, c) for c in CASES]
    finally:
        if p is not None:
            p.stop()

    ok_count = sum(1 for r in rows if r["success"] and r["domain_ok"])
    pass_rate = ok_count / max(1, len(rows))
    avg_ms = sum(r["latency_ms"] for r in rows) / max(1, len(rows))

    print("search benchmark results:")
    for r in rows:
        print(
            f"- {r['name']}: {r['latency_ms']}ms success={r['success']} "
            f"items={r['items_count']} domain_ok={r['domain_ok']} top={r['top_domain']} err={r['error']}"
        )
    print(f"summary: pass_rate={pass_rate:.2%} avg_ms={avg_ms:.1f}")

    out_dir = Path("/Users/wenbo/Kage/docs/benchmarks")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest_search_benchmark.json"
    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "mock" if args.mock else "real",
        "summary": {"pass_rate": pass_rate, "avg_ms": avg_ms},
        "results": rows,
    }
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")

    # Non-zero exit if quality gate fails.
    return 0 if pass_rate >= 0.67 else 1


if __name__ == "__main__":
    raise SystemExit(main())
