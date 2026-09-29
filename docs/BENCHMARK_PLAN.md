# Kage Benchmark Plan

## Goal

Kage should be evaluated as a local LLM Agent Runtime, not only as a desktop companion. The benchmark should answer:

- Did the router choose the correct lane?
- Did the command fast path reduce latency?
- Did the system avoid empty or silent responses?
- Did the tool call succeed?
- Did second-turn follow-up remain grounded in pending state?

## Metrics

| Metric | Definition | Target Direction |
|---|---|---|
| `route_accuracy` | Percentage of eval cases where predicted route/reason matches the expected route. | Higher |
| `command_latency_p50` | Median response time for high-confidence deterministic commands. | Lower |
| `command_latency_p95` | P95 response time for deterministic commands. | Lower |
| `info_latency_p50` | Median response time for weather/video/info fast paths. | Lower |
| `info_latency_p95` | P95 response time for weather/video/info fast paths. | Lower |
| `fallback_rate` | Percentage of cases that fall back from intended fast path to generic agent/chat. | Lower |
| `empty_response_rate` | Percentage of cases producing empty/silent user-visible response. | Lower |
| `tool_success_rate` | Percentage of routed tool calls that execute successfully. | Higher |
| `second_turn_grounded_rate` | Percentage of follow-up cases that correctly use pending dialog state. | Higher |

## Eval Case Coverage

`eval/eval_cases.json` should cover:

- command: volume, brightness, Wi-Fi, Bluetooth, screenshot, app launch
- weather/info: weather, time, search-like queries
- video: YouTube/Bilibili/video queries and follow-up correction
- background: organize downloads, summarize/analyze folders
- agent: file search, multi-step desktop tasks
- chat: casual conversation
- pending: confirmation, cancellation, inferred command correction, video result follow-up

## Runner Stages

### Stage 1: Static route benchmark

`scripts/kage_eval_runner.py` imports the realtime lane classifier directly and checks route/reason matches. This stage is cheap, deterministic, and can run without launching the full app.

```bash
python scripts/kage_eval_runner.py
```

### Stage 2: Text-only E2E benchmark

Use the existing WebSocket text-only benchmark to test full runtime behavior with local model calls disabled or minimized where possible.

```bash
KAGE_TEXT_ONLY=1 KAGE_BENCH_TEXT_ONLY=1 python scripts/kage_e2e_benchmark.py --include-system
```

### Stage 3: Route A/B benchmark

Use the existing route A/B benchmark to compare rule-only routing against model-assisted routing.

```bash
python scripts/route_ab_benchmark.py
```

## Gates

Suggested gates before claiming an optimization helped:

- No route accuracy regression.
- Command fast path P95 does not regress by more than 10%.
- Empty response rate does not increase.
- Tool success rate does not decrease.
- Medium-confidence command confirmation remains intact.

## Interview Talking Point

The important point is not that Kage has one benchmark script. The important point is that agent reliability is decomposed into measurable surfaces: routing, latency, tool success, fallback behavior, empty responses, and dialog-state grounding.
