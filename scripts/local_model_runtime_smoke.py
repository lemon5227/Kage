#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from core.local_model_runtime import LocalModelRuntime
from core.model_provider import OpenAICompatibleProvider
from core.response_sanitizer import strip_reasoning_artifacts


DEFAULT_PROMPT = "Reply with exactly: smoke ok"


@dataclass
class SmokeSample:
    text: str
    elapsed_ms: float


def _request(url: str, *, timeout_sec: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Kage smoke test"})
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        return resp.read()


def wait_until_ready(base_url: str, *, timeout_sec: float, poll_interval: float) -> tuple[bool, float, str]:
    started_at = time.monotonic()
    deadline = started_at + timeout_sec
    models_url = f"{base_url.rstrip('/')}/models"
    last_error = ""
    while time.monotonic() < deadline:
        try:
            _request(models_url, timeout_sec=min(3.0, timeout_sec))
            return (True, time.monotonic() - started_at, "")
        except urllib.error.URLError as exc:
            last_error = str(exc)
        except Exception as exc:
            last_error = str(exc)
        time.sleep(poll_interval)
    return (False, time.monotonic() - started_at, last_error)


def run_generation(base_url: str, *, timeout_sec: int, prompt: str) -> SmokeSample:
    provider = OpenAICompatibleProvider(
        api_key="local",
        model_name="local-model",
        base_url=base_url,
        timeout_sec=timeout_sec,
    )
    started_at = time.monotonic()
    response = provider.generate(
        [{"role": "user", "content": prompt}],
        max_tokens=48,
        temperature=0.0,
    )
    elapsed_ms = (time.monotonic() - started_at) * 1000.0
    return SmokeSample(text=response.text.strip(), elapsed_ms=elapsed_ms)


def summarize_samples(samples: list[SmokeSample]) -> dict[str, float]:
    elapsed_values = [sample.elapsed_ms for sample in samples]
    first = elapsed_values[0]
    avg = statistics.fmean(elapsed_values)
    min_value = min(elapsed_values)
    max_value = max(elapsed_values)
    p95_index = max(0, min(len(elapsed_values) - 1, round((len(elapsed_values) - 1) * 0.95)))
    p95_value = sorted(elapsed_values)[p95_index]
    return {
        "first_ms": first,
        "avg_ms": avg,
        "min_ms": min_value,
        "max_ms": max_value,
        "p95_ms": p95_value,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manual smoke test for the local llama.cpp-compatible runtime."
    )
    parser.add_argument("--model-path", help="Absolute path to a local GGUF model file.")
    parser.add_argument("--binary-path", help="Optional absolute path to llama-server.")
    parser.add_argument("--host", default="127.0.0.1", help="Runtime host.")
    parser.add_argument("--port", type=int, default=8080, help="Runtime port.")
    parser.add_argument("--ctx", type=int, default=4096, help="Context window for smoke boot.")
    parser.add_argument("--ngl", type=int, default=99, help="GPU layers for llama-server.")
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=120.0,
        help="Seconds to wait for /v1/models to become reachable.",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=120,
        help="Seconds to wait for the smoke generation request.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between readiness probes.",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Prompt used for the smoke generation request.",
    )
    parser.add_argument(
        "--reuse-running",
        action="store_true",
        help="Reuse an already-running local runtime on the given host/port instead of starting one.",
    )
    parser.add_argument(
        "--keep-running",
        action="store_true",
        help="Do not stop the runtime if this script started it.",
    )
    parser.add_argument(
        "--warmup-runs",
        type=int,
        default=0,
        help="Warm-up generations to discard before collecting metrics.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Measured generation runs after warm-up.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the final smoke metrics as a JSON object.",
    )
    parser.add_argument(
        "--reasoning",
        default="off",
        choices=("off", "on", "auto"),
        help="Reasoning mode passed to llama-server.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = f"http://{args.host}:{args.port}/v1"
    overall_started_at = time.monotonic()
    runtime = LocalModelRuntime(
        user_dir=os.path.expanduser("~/.kage"),
        managed_model_getter=lambda _model_id: None,
    )

    started_here = False
    start_payload = {
        "model_path": args.model_path,
        "binary_path": args.binary_path,
        "host": args.host,
        "port": args.port,
        "ctx": args.ctx,
        "ngl": args.ngl,
        "reasoning": args.reasoning,
        "force_restart": False,
    }

    try:
        if args.reuse_running:
            print(f"[smoke] Reusing runtime at {base_url}")
        else:
            if not args.model_path:
                print("[smoke] --model-path is required unless --reuse-running is used", file=sys.stderr)
                return 2
            print(f"[smoke] Starting local runtime for model: {args.model_path}")
            result = runtime.start(start_payload)
            if not result.ok:
                print(f"[smoke] Runtime start failed: {result.payload.get('error')}", file=sys.stderr)
                return 1
            started_here = True
            print(
                "[smoke] Runtime started",
                f"pid={result.payload.get('pid')}",
                f"log={result.payload.get('log_path')}",
            )

        ready, ready_at, error = wait_until_ready(
            base_url,
            timeout_sec=args.ready_timeout,
            poll_interval=args.poll_interval,
        )
        if not ready:
            print(f"[smoke] Runtime never became ready: {error}", file=sys.stderr)
            return 1

        print(f"[smoke] Runtime ready after {ready_at:.2f} seconds")
        for idx in range(args.warmup_runs):
            warmup = run_generation(
                base_url,
                timeout_sec=args.request_timeout,
                prompt=args.prompt,
            )
            print(f"[smoke] Warm-up {idx + 1}/{args.warmup_runs}: {warmup.elapsed_ms:.1f} ms")

        samples: list[SmokeSample] = []
        for idx in range(args.runs):
            sample = run_generation(
                base_url,
                timeout_sec=args.request_timeout,
                prompt=args.prompt,
            )
            if not sample.text:
                print("[smoke] Generation returned empty text", file=sys.stderr)
                return 1
            samples.append(sample)
            print(f"[smoke] Run {idx + 1}/{args.runs}: {sample.elapsed_ms:.1f} ms")

        metrics = summarize_samples(samples)
        total_elapsed_s = time.monotonic() - overall_started_at
        first_response = samples[0].text
        print(
            "[smoke] Metrics:",
            f"ready_s={ready_at:.2f}",
            f"first_ms={metrics['first_ms']:.1f}",
            f"avg_ms={metrics['avg_ms']:.1f}",
            f"min_ms={metrics['min_ms']:.1f}",
            f"max_ms={metrics['max_ms']:.1f}",
            f"p95_ms={metrics['p95_ms']:.1f}",
            f"total_s={total_elapsed_s:.2f}",
        )
        sanitized_preview = strip_reasoning_artifacts(first_response)
        print(f"[smoke] Raw response: {first_response}")
        print(f"[smoke] Sanitized response: {sanitized_preview or '<empty>'}")
        if args.json:
            print(
                json.dumps(
                    {
                        "ready_s": round(ready_at, 3),
                        "first_ms": round(metrics["first_ms"], 1),
                        "avg_ms": round(metrics["avg_ms"], 1),
                        "min_ms": round(metrics["min_ms"], 1),
                        "max_ms": round(metrics["max_ms"], 1),
                        "p95_ms": round(metrics["p95_ms"], 1),
                        "total_s": round(total_elapsed_s, 3),
                        "warmup_runs": args.warmup_runs,
                        "runs": args.runs,
                        "response_preview": first_response[:200],
                        "sanitized_response_preview": sanitized_preview[:200],
                    },
                    ensure_ascii=False,
                )
            )
        return 0
    finally:
        if started_here and not args.keep_running:
            stopped = runtime.stop()
            print(f"[smoke] Runtime stopped status={stopped.get('status')}")


if __name__ == "__main__":
    raise SystemExit(main())
