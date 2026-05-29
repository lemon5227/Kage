# Kage Optimization Round 6 — 2026-05

> Round 6 builds on Rounds 1–5. Continued iteration on dead code removal and
> hot-path performance, with explicit before/after benchmark numbers.
>
> Result: 401 tests pass (was 377), 0 warnings, pyflakes core/ clean.
> server.py shrank from 2574 → 2484 lines (-90, -3.5%).

## Iteration 6a — Dead methods removed from `KageServer`

Six methods on `KageServer` had no callers anywhere in `core/`, `tests/`, or
`scripts/`. They were AI slop / leftover scaffolding:

| Method | Lines | Notes |
|--------|-------|-------|
| `_think_report` | 17 | Never called. |
| `_quick_chat_plan` | 30 | Never called. |
| `_repair_chat_response` | 30 | Never called; second-pass LLM rewrite. |
| `_should_try_tools` | 3 | Thin wrapper around imported `should_try_tools`. |
| `_strip_cmd_output` | 7 | No call sites. |
| `_send_random_motion` | 4 | Thin async delegator with no `self.` callers. |

Verified via:
- `grep -rE "self\._X\b\|server\._X\b" core/ tests/ scripts/` returning only the
  `def` line for each.
- New tests in `tests/test_round6_cleanup.py::TestServerDeadMethodsRemoved` that
  assert `not hasattr(KageServer, "_think_report")`, etc.

`_sanitize_for_speech` was kept as a test-friendly thin wrapper around
`sanitize_for_speech_text`.

Two transitively-unused imports were removed:
- `from core.interaction_state import make_pending_chat_followup` (only used by
  the removed `_quick_chat_plan`)
- `from core.route_classifier import should_try_tools` (only the deleted wrapper
  used it)

## Iteration 6b — `MemorySystem.recall()` performance

Two issues:

1. The importance vector was rebuilt with `np.array([entry.get("importance", 1)
   for entry in self._entries], dtype=float)` on every recall — O(n) Python
   list comprehension over the entire memory store on every prompt build.
2. Top-k selection used `np.argsort(...)[::-1][:top_k]` — O(n log n) when k is
   typically 5 and n can grow into the thousands.

Fixes:

- **Importance cache** (`self._importance_cache: Optional[np.ndarray]`).
  - Built lazily on first recall via `_get_importance_array()`.
  - Invalidated by a single helper `_invalidate_caches()` (called from
    eviction, dedup, merge, forget paths — replaced 8 inline
    `self._corpus_token_sets = None` resets).
  - On `add_memory`, the new importance value is appended in place via
    `np.append`, avoiding a full rebuild on the next recall.

- **Top-k via `np.argpartition`**.
  - For `top_k < n`: `np.argpartition(scores, n - top_k)[-top_k:]` finds the top
    candidates in O(n), then sorts only those k entries.
  - For `top_k >= n`: falls back to `np.argsort(-scores)`.

The argpartition saving is real (O(n) vs O(n log n)) but the absolute gain is
hidden in the benchmark by the SentenceTransformer encoding cost (~5ms). The
optimization shines once n grows past 1k entries on the BM25-only path.

## Iteration 6c — `chat_polisher.collapse_repeats`

Old implementation: 11-line per-character Python loop.

```python
output = []
last_char = None
repeat_count = 0
for ch in text:
    if ch == last_char: repeat_count += 1
    else: repeat_count = 0
    last_char = ch
    if repeat_count < 2: output.append(ch)
return "".join(output)
```

New implementation: single precompiled regex.

```python
_REPEAT_RE = re.compile(r"(.)\1{2,}")

def collapse_repeats(text: str) -> str:
    if not text: return text
    return _REPEAT_RE.sub(r"\1\1", text)
```

Measured (`scripts/perf_benchmark.py`):

| Input | Old loop | Regex sub |
|-------|----------|-----------|
| 9 chars with runs | ~1.2 µs | 0.53 µs |
| 90 chars with runs | ~10 µs | 3.56 µs |
| 18 chars no runs | ~1.0 µs | 0.44 µs |

Behavior is preserved (covered by 6 new tests in `TestCollapseRepeats`).

## Iteration 6d — `PromptBuilder._enforce_budget`

The old loop recomputed `count_tokens(messages)` (a full sum across the message
list) after every `messages.pop(1)` — quadratic in the number of pops. The
common case is a slow chat with growing history, where this adds up.

```python
# OLD:
while len(messages) > 5 and self.count_tokens(messages) > budget:
    messages.pop(1)
```

```python
# NEW: precompute per-message token counts, subtract on pop.
per_msg = [max(1, len(m.get("content", "")) // _AVG_CHARS_PER_TOKEN) for m in messages]
total = sum(per_msg)
...
while len(messages) > 5 and total > budget:
    removed = per_msg.pop(1)
    messages.pop(1)
    total -= removed
```

Now O(n) for the trim, regardless of how many messages must be popped.

Behavior preserved (covered by 3 new tests in `TestEnforceBudget`).

## New benchmarks added

`scripts/perf_benchmark.py` now also reports:

```
=== collapse_repeats (chat_polisher.py) ===
  collapse_repeats 9 chars with runs                       0.53 µs/call
  collapse_repeats 90 chars with runs                      3.56 µs/call
  collapse_repeats 18 chars no runs                        0.44 µs/call

=== Memory operations (memory.py) ===
  recall 5 results from 1000 entries (BM25-only path)      ...
```

## New tests

`tests/test_round6_cleanup.py` — 24 tests covering every change:

| Class | Tests | Covers |
|-------|-------|--------|
| `TestServerDeadMethodsRemoved` | 7 | All 6 removed methods + 1 kept (`_sanitize_for_speech`) |
| `TestImportanceCache` | 4 | Cache lifecycle (none → built → appended → invalidated) |
| `TestRecallTopKArgpartition` | 4 | top-k correctness for `k<n`, `k>=n`, empty, and ordering |
| `TestCollapseRepeats` | 6 | Empty / no runs / two repeats kept / 3+ collapsed / mixed / pipeline |
| `TestEnforceBudget` | 3 | Under-budget no-op / minimum protection / oldest-first trim |

## Self-check

```
$ python -m pyflakes core/
(no output)

$ python -m pyflakes tests/test_round6_cleanup.py
(no output)

$ python -m pytest tests/ -q
401 passed, 4 skipped, 8 subtests passed in ~43s
```

## Files changed

```
core/server.py                       — 6 dead methods + 2 unused imports removed (-90 lines)
core/memory.py                       — importance cache + np.argpartition + _invalidate_caches helper
core/chat_polisher.py                — collapse_repeats: char loop → regex
core/prompt_builder.py               — _enforce_budget: O(n²) → O(n) incremental
scripts/perf_benchmark.py            — added collapse_repeats + recall benchmarks
tests/test_round6_cleanup.py         — NEW (24 tests)
docs/optimization-2026-05-round6.md  — NEW (this file)
```

## Deferred (still)

1. Decompose `AgenticLoop.run()` (700 lines, multiple retry/parallel branches).
2. Decompose `KageServer.run_loop()` (~350 lines).
3. Vectorize `_keyword_overlap_scores` (currently a Python set-intersection
   loop). Cold path — only triggered when BM25 returns all <=0 scores.
