#!/usr/bin/env python3
"""End-to-end benchmark through running Kage websocket.

Measures real latency from sending `text_input` to receiving `speech` output.

Prerequisites:
- Kage server is already running on ws://127.0.0.1:12345/ws
- Runtime model path is configured and reachable

Usage:
  python scripts/kage_e2e_benchmark.py
  python scripts/kage_e2e_benchmark.py --uri ws://127.0.0.1:12345/ws --timeout 45
  python scripts/kage_e2e_benchmark.py --include-system
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path


ROOT_DIR = str(Path(__file__).resolve().parents[1])
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


DEFAULT_CASES = [
    {
        "name": "weather",
        "text": "帮我查一下明天尼斯天气。",
        "expect_any": ["天气", "度", "体感", "湿度", "尼斯"],
    },
    {
        "name": "video",
        "text": "帮我查一下曹操说最新视频。",
        "expect_any": ["youtube", "youtu.be", "链接", "曹操说", "频道：曹操说"],
    },
    {
        "name": "video_correction",
        "turns": [
            {
                "text": "帮我查一下曹操最新视频。",
                "expect_any": ["youtube", "youtu.be", "链接", "视频"],
                "slo_ms": 2500,
            },
            {
                "text": "不是这个，是曹操说最新视频。",
                "expect_any": ["曹操说", "频道：曹操说", "youtube", "链接"],
                "slo_ms": 2500,
            },
        ],
    },
    {
        "name": "weather_correction",
        "turns": [
            {
                "text": "帮我查一下上海天气。",
                "expect_any": ["上海", "天气", "度"],
                "slo_ms": 4000,
            },
            {
                "text": "不是这个，是帮我查一下尼斯天气。",
                "expect_any": ["尼斯", "天气", "度"],
                "slo_ms": 4000,
            },
        ],
    },
    {
        "name": "command_correction",
        "turns": [
            {
                "text": "帮我把音量调高一点。",
                "expect_any": ["音量", "调高", "已调"],
                "slo_ms": 800,
            },
            {
                "text": "不是这个，是把亮度调高。",
                "expect_any": ["亮度", "调高", "已调"],
                "slo_ms": 800,
            },
        ],
    },
]

SYSTEM_CASE = {
    "name": "system",
    "text": "帮我调高亮度。",
    "expect_any": ["亮度", "调高", "已调"],
}

DEFAULT_SLO_MS = {
    "command": 800,
    "system": 800,
    "video": 2500,
    "weather": 4000,
}


async def _drain_initial_events(ws, drain_sec: float = 2.0) -> None:
    """Drain initial greeting/state events so benchmark starts clean."""
    start = time.monotonic()
    while (time.monotonic() - start) < drain_sec:
        remain = drain_sec - (time.monotonic() - start)
        if remain <= 0:
            break
        try:
            _ = await asyncio.wait_for(ws.recv(), timeout=min(0.25, remain))
        except asyncio.TimeoutError:
            continue


def _is_speech_event(msg_obj: dict) -> bool:
    return isinstance(msg_obj, dict) and str(msg_obj.get("type") or "") == "speech"


async def _run_case(ws, text: str, timeout: float) -> dict:
    t0 = time.monotonic()
    await ws.send(json.dumps({"type": "text_input", "text": text}, ensure_ascii=False))

    speech_text = ""
    events = 0

    while True:
        elapsed = time.monotonic() - t0
        remain = timeout - elapsed
        if remain <= 0:
            return {
                "ok": False,
                "latency_ms": round(elapsed * 1000, 1),
                "speech": "",
                "error": "timeout",
                "events": events,
            }

        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remain)
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "speech": "",
                "error": "timeout",
                "events": events,
            }

        events += 1
        try:
            obj = json.loads(raw)
        except Exception:
            continue

        if _is_speech_event(obj):
            speech_text = str(obj.get("text") or "")
            return {
                "ok": bool(speech_text.strip()),
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "speech": speech_text,
                "error": None if speech_text.strip() else "empty_speech",
                "events": events,
            }


def _match_expectation(speech: str, expect_any: list[str] | None) -> bool:
    if not expect_any:
        return True
    low = str(speech or "").lower()
    for tok in expect_any:
        t = str(tok or "").strip().lower()
        if t and t in low:
            return True
    return False


async def main_async(uri: str, timeout: float, include_system: bool) -> int:
    try:
        import websockets  # type: ignore
    except Exception as exc:
        print(f"error: missing dependency `websockets`: {exc}")
        return 2

    cases = list(DEFAULT_CASES)
    if include_system:
        cases.append(SYSTEM_CASE)

    results = []

    try:
        for c in cases:
            name = str(c["name"])
            turns_raw = c.get("turns") if isinstance(c, dict) else None
            turn_specs = turns_raw if isinstance(turns_raw, list) and turns_raw else [c]
            turn_rows = []

            async with websockets.connect(  # type: ignore[arg-type]
                uri,
                max_size=2**22,
                ping_interval=20,
                ping_timeout=180,
            ) as ws:
                await _drain_initial_events(ws)

                for t in turn_specs:
                    if not isinstance(t, dict):
                        continue
                    t_text = str(t.get("text") or "")
                    t_row = await _run_case(ws, t_text, timeout=timeout)
                    t_row["text"] = t_text
                    t_exp = t.get("expect_any") if isinstance(t, dict) else None
                    t_exp_list = [str(x) for x in t_exp] if isinstance(t_exp, list) else []
                    t_row["expect_any"] = t_exp_list
                    t_row["correct"] = _match_expectation(str(t_row.get("speech") or ""), t_exp_list)
                    t_slo = int(t.get("slo_ms") or DEFAULT_SLO_MS.get(name, 5000))
                    t_row["slo_ms"] = t_slo
                    t_row["latency_ok"] = float(t_row.get("latency_ms") or 0.0) <= float(t_slo)
                    t_row["ok"] = bool(t_row.get("ok")) and bool(t_row.get("correct")) and bool(t_row.get("latency_ok"))
                    if not t_row.get("correct") and not t_row.get("error"):
                        t_row["error"] = "expectation_mismatch"
                    if t_row.get("correct") and not t_row.get("latency_ok") and not t_row.get("error"):
                        t_row["error"] = "latency_exceeded"
                    turn_rows.append(t_row)
                    await asyncio.sleep(0.15)

            row = dict(turn_rows[-1]) if turn_rows else {"ok": False, "latency_ms": 0.0, "speech": "", "error": "empty_case", "events": 0}
            row["name"] = name
            row["turns"] = turn_rows
            row["turn_count"] = len(turn_rows)
            row["correction_case"] = len(turn_rows) >= 2
            row["correction_success"] = bool(turn_rows and turn_rows[-1].get("ok")) if row["correction_case"] else None
            row["correct"] = all(bool(t.get("correct")) for t in turn_rows) if turn_rows else False
            row["latency_ok"] = all(bool(t.get("latency_ok")) for t in turn_rows) if turn_rows else False
            row["ok"] = all(bool(t.get("ok")) for t in turn_rows) if turn_rows else False
            row["latency_ms_total"] = round(sum(float(t.get("latency_ms") or 0.0) for t in turn_rows), 1)
            row["slo_ms_total"] = int(sum(int(t.get("slo_ms") or 0) for t in turn_rows))
            row["text"] = str((turn_rows[0].get("text") if turn_rows else "") or "")
            results.append(row)
            print(
                f"- {name}: ok={row['ok']} turns={row['turn_count']} latency_total={row['latency_ms_total']}ms "
                f"slo_total={row['slo_ms_total']}ms latency_ok={row['latency_ok']} err={row.get('error')} speech={str(row.get('speech') or '')[:80]}"
            )
            await asyncio.sleep(0.2)
    except Exception as exc:
        print(f"error: websocket benchmark failed: {exc}")
        return 2

    lat_ok = [r["latency_ms_total"] for r in results if r.get("ok")]
    pass_rate = (sum(1 for r in results if r.get("ok")) / max(1, len(results)))
    correctness_rate = (sum(1 for r in results if r.get("correct")) / max(1, len(results)))
    slo_rate = (sum(1 for r in results if r.get("latency_ok")) / max(1, len(results)))
    correction_rows = [r for r in results if r.get("correction_case")]
    correction_success_rate = (
        sum(1 for r in correction_rows if r.get("correction_success")) / max(1, len(correction_rows))
        if correction_rows
        else 1.0
    )
    avg_ms = statistics.mean(lat_ok) if lat_ok else 0.0
    p95_ms = sorted(lat_ok)[max(0, int(len(lat_ok) * 0.95) - 1)] if lat_ok else 0.0

    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "uri": uri,
        "timeout_sec": timeout,
        "include_system": include_system,
        "summary": {
            "pass_rate": pass_rate,
            "correctness_rate": correctness_rate,
            "slo_rate": slo_rate,
            "correction_success_rate": correction_success_rate,
            "avg_ms": round(avg_ms, 1),
            "p95_ms": round(p95_ms, 1),
            "count": len(results),
        },
        "results": results,
    }

    out_dir = Path("/Users/wenbo/Kage/docs/benchmarks")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest_kage_e2e_benchmark.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"summary: pass_rate={pass_rate:.2%} correctness={correctness_rate:.2%} slo={slo_rate:.2%} "
        f"correction={correction_success_rate:.2%} "
        f"avg_ms={avg_ms:.1f} p95_ms={p95_ms:.1f} saved={out_path}"
    )
    return 0 if pass_rate >= 0.67 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uri", default="ws://127.0.0.1:12345/ws", help="Kage websocket URI")
    ap.add_argument("--timeout", type=float, default=45.0, help="Timeout per case (sec)")
    ap.add_argument("--include-system", action="store_true", help="Include system-control case")
    args = ap.parse_args()
    return asyncio.run(main_async(args.uri, args.timeout, args.include_system))


if __name__ == "__main__":
    raise SystemExit(main())
