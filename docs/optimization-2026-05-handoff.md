# Kage Production-Readiness Optimization — 2026-05

> 4-round optimization session covering security, performance, correctness, and AI slop cleanup.
> All 355 tests pass. New benchmarks recorded in `scripts/perf_benchmark.py`.

## Summary

| Round | Focus | Files touched | Tests |
|-------|-------|---------------|-------|
| 1 | Security hardening + bug fixes | web_ops, file_ops, memory, local_model_runtime, mouth, server | +15 new security tests |
| 2 | Hot-path performance | memory, chat_polisher, agentic_loop, prompt_builder, web_ops, route_classifier, server | All passing |
| 3 | Correctness bugs + caching | agentic_loop, tool_registry, tool_executor, web_ops, server | All passing |
| 4 | AI slop / dead code | server, agentic_loop, chat_polisher, tool_executor, web_ops | All passing |

## Round 1 — Security & Critical Bugs

### Critical (security)
- **`web_ops.exec_command`**: missing `subprocess` import (was crash-on-call). Added module import. Added `_BLOCKED_COMMAND_PATTERNS` regex blocking `rm -rf /`, `mkfs`, `curl|sh`, `shutdown`, `reboot`, etc. Switched from `shell=True` to `["/bin/sh", "-c", ...]` with controlled `PATH`.
- **`web_ops.web_fetch`**: no response size limit → OOM risk. Added `_MAX_RESPONSE_BYTES = 1MB` with `Content-Length` check + chunked read with size cap.
- **`file_ops`**: no path traversal protection → arbitrary writes to `/etc/passwd`, `/usr/bin/*`, etc. Added `_is_path_allowed()` + `_validate_path()` enforcing home-dir or tempdir scope, blocking `/etc /usr /bin /sbin /System /Library`. Applied to `fs_move/fs_rename/fs_write/fs_trash/fs_apply`.

### High (robustness)
- **`memory.MemorySystem`**: no thread safety, no eviction. Added `threading.Lock` around all mutations + `max_entries=10000` cap with importance-weighted eviction. BM25 index now batches rebuilds (every 10 inserts) instead of per-insert.
- **`local_model_runtime.is_running()`**: log file handle leak when llama-server crashes immediately. Now cleans up log handle and resets state when `proc.poll()` returns non-None.

### Tests
- 15 new tests in `tests/test_security_hardening.py` covering: command blocklist, path validation, response size limit, memory thread safety, eviction.

## Round 2 — Hot-Path Performance

### Memory
- **`_tokenize`**: regex moved to module-level `_TOKEN_RE`. Was recompiled on every call (called thousands of times during search).
- **`add_memory`**: switched from `_rebuild_bm25(force=True)` (rebuild every insert) to `force=False` (batch every 10).
- **`bm25_search`/`recall`**: added explicit flush of dirty BM25 index before query.

### chat_polisher
- 7 patterns precompiled as `_RE_USER_ASSISTANT_ECHO`, `_RE_USER_LINE`, `_RE_CAPABILITY_BRAG`, etc.
- `_BLOCKED_RE` single-pass regex replaces 20× `string.replace()` (saves ~20 string copies per response).

### agentic_loop
- `detect_repetition` rewritten from O(n²) (`text.count(sub)` inside a loop) to O(n) (dict counter with early exit).

### prompt_builder
- Keyword sets extracted to module-level `frozenset` constants (`_FILE_KEYWORDS`, `_SYSTEM_KEYWORDS`, etc.) so they're not rebuilt on every call.
- `_select_tool_names()` accepts a pre-computed `route` parameter to avoid redundant `classify_route()` invocation.

### web_ops
- 4 redundant function-level `import subprocess` / `import datetime` removed; lifted to module-level.

### server.py
- `_extract_city`: 50+ `string.replace()` calls collapsed into single `_CITY_STOPWORDS_RE.sub("")` (4.3× faster).
- `_quick_chat_response`: location regexes precompiled as `_RE_LOCATION_CORRECTION` and `_RE_LOCATION_SET`.

### Benchmark deltas (before → after)
| Function | Before | After | Speedup |
|----------|--------|-------|---------|
| `add_memory` | 710 µs | 378 µs | 1.9× |
| `bm25_search` (1000 entries) | 851 µs | 450 µs | 1.9× |
| `filter_chat_text` | 32 µs | 14.5 µs | 2.2× |
| `_extract_city` | 23.4 µs | 2.7 µs | 8.6× |
| `is_route_ambiguous` | 4.8 µs | 1.8 µs | 2.6× |
| `classify_route` | 10.2 µs | 6.0 µs | 1.7× |
| `detect_repetition` | 16.7 µs | 8.0 µs | 2.1× |

## Round 3 — Correctness Bugs + Caching

### HIGH severity bug fixes
1. **`agentic_loop._flush_facts_if_needed`** was silently dropping all batched LLM-extracted facts. The function checked the threshold, logged "flushing N facts", then just called `_pending_facts.clear()` — never persisted. Now persists via `memory.add_fact()` before clearing.
2. **`agentic_loop._extract_facts_sync`** called `loop.run_until_complete()` from inside an already-running async event loop. On Python 3.10+ this raises `RuntimeError: This event loop is already running`. Replaced with native `await self._llm_extractor.extract_facts(...)`. Made `_extract_memory_if_available` async.
3. **`agentic_loop.flush_pending_facts`** (shutdown handler) had the same drop-on-clear bug; same fix.

### Caching
- **`tool_registry.get_all_schemas()`**: cached, invalidated on `register()`. Was rebuilding ~30 dicts on every agentic loop step (5× per user turn).
- **`tool_registry.get_tool_descriptions()`**: same caching pattern.
- **`tool_executor._fuzzy_match_tool_name`**: bounded dict cache (256 entries) — same hallucinated tool name now returns cached result instead of running `difflib.get_close_matches()` again.

### Pattern hoisting
- **`agentic_loop`**: 14 hot-path regexes hoisted to module-level constants (`_RE_FILE_ACTION`, `_RE_WEB_INFO`, `_RE_SYSTEM_CTL`, `_RE_NEGATIONS` list, weather city patterns, whitespace, CJK detection).
- **`tool_executor`**: bracket tool-call regex hoisted to `_BRACKET_TOOL_CALL_RE`.
- **`web_ops`**: 5 patterns hoisted (`_QUERY_TOKEN_RE`, `_DUCKDUCKGO_RE`, `_DUCKDUCKGO_TAG_RE`, `_YOUTUBE_VIDEO_RE`, `_BILIBILI_RE`).

### JSON round-trip elimination
- `web_ops.search()` video auto path was doing 6× `json.dumps` + 6× `json.loads` per search (one per provider per variant, 3 variants × 2 providers). Added raw variants `_youtube_html_search_raw` / `_search_provider_bilibili_raw` returning `list[dict]` directly. JSON wrappers preserved for backward compat.

### Bounded fast cache
- `server._set_fast_cache`: was unbounded. Now caps at `_FAST_CACHE_MAX=256` with two-stage eviction (drop entries older than `_FAST_CACHE_STALE_SEC=600s`, then drop oldest 25% if still oversized).

## Round 4 — AI Slop / Dead Code Cleanup

### Duplicate method definitions (Python silently keeps the last one)
- **`KageServer._should_try_tools`** defined twice — first one delegated to `route_classifier.should_try_tools`, second was a copy of that same logic inlined. Kept the delegation.
- **`KageServer._send_random_motion`** defined twice — first delegated to `speech_engine._send_random_motion`, second was an identical inline copy. Kept the delegation.

### Zero-value wrapper methods
- `_filter_chat_text`, `_collapse_repeats`, `_short_care_phrase` all just delegated to module-level functions. Deleted (no callers via `self.`).

### Latent AttributeError bug found and fixed
- `pending_handlers` callbacks passed `self._polish_chat_response`, `self._infer_chat_topic`, `self._structured_chat_followup` — none of which were defined as methods on `KageServer`. The pending dialog state path would `AttributeError` when triggered. Replaced with the imported standalone `polish_chat_response` / `infer_chat_topic` / `structured_chat_followup`.

### Dead code removal
- **`AgenticLoop._score_skill_page`** (50 lines) — never called. Removed it and its 3 supporting regex constants (`_RE_SKILL_DESC`, `_RE_SKILL_NAME`, `_RE_HAS_CJK`).
- **`web_ops._search_provider_web`** — recursive shell that just called `search()` again with `strategy="web"`. Deleted.

### Constant extraction
- `_MAX_CHAT_RESPONSE_LEN = 40` (`chat_polisher.py`)
- `_FAST_CACHE_MAX = 256`, `_FAST_CACHE_STALE_SEC = 600` (`server.py`)
- `_FUZZY_MATCH_CUTOFF = 0.84`, `_FUZZY_CACHE_MAX = 256` (`tool_executor.py`)

### Code dedup
- `_flush_facts_if_needed` and `flush_pending_facts` had identical 25-line `try/except` persistence loops. Extracted `_persist_pending_facts(*, forced: bool)` helper.

### Logging added at silent failure points
Three highest-impact `except Exception: pass` blocks now log:
- Shutdown: `background_worker.stop()` failure
- Shutdown: `flush_pending_facts()` failure
- `agentic_loop` skill autosave failure

The other ~95 silent excepts in the codebase were left alone — most are legitimate (cleanup paths, optional features).

## Deferred / Future Work

### Not done in this session
1. **Unify error return shape** across `web_ops` / `file_ops`. Currently mixes `{"error": ...}` (no success key) with `{"success": false, "error": ...}`. A helper `core/tools/_response.py` exists with `ok()` / `err()` builders ready to use.
2. **Decompose god functions**: `AgenticLoop.run()` (~280 lines, 5 nested retry levels) and `KageServer.run_loop()` (~350 lines mixing voice/text/fast paths). High cognitive load but works correctly.
3. **API authentication**: server's `/api/*` and `/ws` endpoints have no auth. Acceptable for localhost-only desktop app, but a shared bearer token would be cheap insurance.
4. **`merge_similar_facts`** still O(n²) in the BM25 fallback path (the embedding path was vectorized in Round 3). Cold path so low priority.

### Stale untracked artifacts in repo
- The `~/` directory in repo root was created by some earlier `os.makedirs("~/.cache/...")` without `expanduser`. Cosmetic only.

## Running the benchmark

```bash
cd /Users/wenbo/Kage
python scripts/perf_benchmark.py
```

Outputs per-call µs for each hot-path function. Re-run after future changes to detect regressions.

## Test command

```bash
cd /Users/wenbo/Kage
python -m pytest tests/ -q
# 355 passed, 4 skipped
```

## Files modified in this session

```
core/agentic_loop.py        — perf hoisting + fact persistence bug fix + dead code removal
core/chat_polisher.py       — 7 regex hoisted + filter_chat_text single-pass + constant
core/local_model_runtime.py — log handle cleanup on crash
core/memory.py              — thread safety + eviction + batched BM25 + token-set cache + dedup bug fix
core/mouth.py               — bare except → except OSError
core/prompt_builder.py      — frozenset constants + classify_route reuse
core/server.py              — security/perf/slop fixes (50+ small changes)
core/tool_executor.py       — bracket regex + fuzzy cache + constants
core/tool_registry.py       — schema/description caches
core/tools/file_ops.py      — path traversal protection
core/tools/web_ops.py       — exec_command safety + size limit + JSON round-trip elimination
scripts/perf_benchmark.py   — NEW
tests/test_security_hardening.py — NEW (15 tests)
tests/* (multiple)          — fixed stale tests pointing to old API
```
