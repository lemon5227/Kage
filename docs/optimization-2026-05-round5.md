# Kage Optimization Round 5 — 2026-05

> Continuation of the 4-round optimization session, with two additional iterations focused on:
> latent NameError bugs, more dead-code removal, response-shape unification, asyncio offload of
> blocking handlers, and removing AI-slop test patterns.
>
> All 373 tests pass (was 355). New: +18 tests in `tests/test_round5_cleanup.py`. Pyflakes core/ clean.

## Iteration 5a — Latent bug fixes

### Real NameErrors that would crash on call

1. **`core/server.py`** had `urllib.request.Request(...)` and `urllib.request.urlopen(...)` used
   in 5 weather-fetch helpers but only `from urllib.parse import quote, urlencode` was imported.
   Calling any of them would raise `NameError: name 'urllib' is not defined`.
   - Fix: replaced with `import urllib.request` (which transitively binds `urllib.parse.urlencode`
     so the existing `urllib.parse.urlencode(...)` call sites still work).

2. **`core/prompt_builder.py:158`** — `if (not is_open) or is_weather:` referenced `is_weather`
   which was never defined. Triggered when a query matched both web (e.g. `天气`) and open (e.g.
   `打开`) keywords, producing `NameError`.
   - Fix: added `is_weather = "天气" in text` and corrected the surrounding logic so
     `is_open` no longer re-adds the browser-open tools that the weather branch just discarded
     (`if is_open and not is_weather:`).

3. **`core/server.py:1153`** — `AudioOrchestrator(...)` was instantiated but the class was never
   imported. Would crash at `KageServer.__init__`.
   - Fix: added `from core.audio_orchestrator import AudioOrchestrator`.

### Dead modules removed

- **`core/intent_keywords.py`** (60 lines). The module was only imported by
  `core/agentic_loop.py:29`, but `AgenticLoop` redefines both `_needs_tool_action` and
  `_primitive_tool_hint` as staticmethods using precompiled regex. The imports were dead, and the
  module duplicated logic that the staticmethods already supersede. Deleted module + dead import.
- **`core/tools/system_ops.py`**. Every function (`exec_command`, `open_url`, `open_app`,
  `open_website`, `take_screenshot`, `get_time`, `system_control`, `system_capabilities`)
  duplicated the implementation in `core/tools/web_ops.py`. `core/tools/__init__.py` only
  imports from `web_ops`, so `system_ops` was never reachable. Deleted.
- **`core/tools/memory_ops.proactive_agent`**. Duplicate of `core/tools/agent_ops.proactive_agent`
  (which is what `__init__.py` actually exports). Removed.
- **`core/tools_impl.py:13`** — `from core.tools import *` (wildcard) plus an explicit re-export.
  The wildcard was redundant (`__all__` already covered every name); deleted.

### Other slop and unused names

- `core/server.py`: removed 9 unused top-level imports (`signal`, `contextlib` (bare), `urlencode`,
  `strip_reasoning_artifacts`, `is_cancel_text`, `is_confirm_text`, `classify_route`,
  `extract_location_from_text`, plus `is_bad_chat_response`, `fallback_chat_response`,
  `short_care_phrase`, `filter_chat_text`, `collapse_repeats`).
- `core/server.py`: removed `global kage_server` declaration in `runtime_start` (it never assigned).
- `core/server.py`: removed dead locals `model_path`, `cloud_cfg`, `model_cfg` (in `__init__`).
- `core/server.py`: 3× `except Exception as e:` where `e` was unused → bare `except Exception:`.
- `core/agentic_loop.py:29`: dead intent_keywords import.
- `core/agentic_loop.py:948, 977`: redundant `import re` inside functions (already module-level).
- `core/memory.py`: unused locals `tokens_j`, `best_idx`.
- `core/memory_extractor.py`: unused imports (`json`, `field`, `Optional`).
- `core/memory_llm_extractor.py`: unused imports (`re`, `Optional`).
- `core/media_controller.py`: dead inner `send_media_key()` function that imported Quartz CGEvent
  symbols and immediately did `pass`. Replaced with a comment explaining the stub status; AppleScript
  fallback already covers per-app control.
- `core/weather_service.py`: unused `time`, `Any`, and local `desc`.
- `core/tools/web_ops.py`: unused `shlex`.
- `core/heartbeat.py`: unused `re`.
- `core/ears.py`: unused `numpy as np`.
- `core/model_provider.py`: unused `os`.
- `core/memory_profile.py`, `core/config.py`: unused `Optional`.
- `core/realtime_handlers.py`, `core/pending_handlers.py`: unused `Awaitable`.
- `core/background_lane.py`: unused `JOB_STATUS_QUEUED`.
- `core/identity_store.py`, `core/system_control.py`, `core/server.py`: f-strings without placeholders.
- `core/session_manager.py`: `with open(...) as f: pass` → `with open(...): pass` (unused name).

### Correctness fix in BM25 fallback

- **`core/memory._merge_similar_bm25`** was silently broken. It computed a `best_idx` (unused),
  tagged similar entries via `merged_indices`, and then... did nothing. Entries were never removed
  and content was never updated. Callers got a non-zero count but the data was unchanged.
  - Fix: actually apply the merge (pick highest-importance entry as base, take longest content
    as the consolidated form, set merged_from count, then drop the rest and rebuild BM25).

### Performance: hoisted scores in BM25 dedup

- **`core/memory._deduplicate_bm25`** computed `bm25.get_scores(tokens_i)` inside the inner `j`
  loop. Since `tokens_i` only changes with `i`, this was O(n²) BM25 score calls. Hoisted to one
  call per outer `i` (O(n) calls).

### Tool response shape unified

`core/tools/_response.py` already had `ok()` / `err()` builders. Converted every error/success
return in:
- `core/tools/web_ops.py` (was `{"error": "X", "message": "Y"}` — no `success` key)
- `core/tools/skill_ops.py`
- `core/tools/shortcuts_ops.py`
- `core/tools/memory_ops.py`
- `core/tools/agent_ops.py`

`file_ops.py` already used the canonical `{"success": False, "error": ...}` shape and was left
alone. All tool responses now have `{"success": True/False, ...}`.

## Iteration 5b — Performance & true parallelism

### asyncio.to_thread for blocking tool handlers

`ToolExecutor.execute()` invoked sync handlers (e.g. `urllib.request.urlopen`, `subprocess.run`)
directly in the event loop. With `asyncio.gather(_exec_one(c) for c in calls)` in the agentic
loop's parallel path, every handler still ran serially because each blocked the loop.

Fix:

```python
if asyncio.iscoroutinefunction(handler):
    raw_result = await handler(**arguments)
else:
    raw_result = await asyncio.to_thread(handler, **arguments)
```

Now two parallel `web_fetch` calls actually overlap. Verified in
`tests/test_round5_cleanup.py::TestToolExecutorThreadOffload::test_parallel_sync_handlers_overlap`:
two 50ms blocking calls finish in <90ms (was ~100ms serial).

### MemoryExtractor pattern compilation hoisted

`MemoryExtractor.__init__` recompiled all 17 regex patterns on every instantiation. Because
`MemorySystem.add_conversation_facts()` builds a fresh `MemoryExtractor()` per turn, this added
~50–100µs of regex compilation per conversation turn.

Fix: hoisted compiled patterns to module-level constants (`_PREFERENCE_PATTERNS`, `_HABIT_PATTERNS`,
etc., bundled into `_CATEGORY_PATTERNS`). `__init__` now just aliases the singleton dict.

## Iteration 5c — Test hygiene

Removed `return True` / `return False` from `pytest` test bodies across 6 files (triggered
`PytestReturnNotNoneWarning`):
- `tests/test_memory_round7_features.py` (4 occurrences)
- `tests/test_memory_improvements.py` (4 occurrences)
- `tests/test_memory_e2e_integration.py` (1 occurrence)
- `tests/test_memory_user_experience.py` (1 occurrence)
- `tests/test_memory_llm_extraction.py` (2 occurrences)
- `tests/test_server_helpers.py` (1 occurrence)

`return True` at the end of a test body was replaced by either an `assert` or just removed.

## New tests

`tests/test_round5_cleanup.py` — 22 regression tests covering:

| Class | Tests | Covers |
|-------|-------|--------|
| `TestSelectToolNamesIsWeather` | 3 | `is_weather` NameError + open/weather logic |
| `TestServerUrllibImport` | 2 | `urllib.request` + `AudioOrchestrator` reachable |
| `TestDeadModuleRemoved` | 2 | `intent_keywords` and `tools.system_ops` deleted |
| `TestToolResponseShape` | 6 | canonical `success: True/False` shape |
| `TestMergeSimilarBM25` | 2 | BM25 fallback actually merges entries |
| `TestDeduplicateBM25` | 1 | hoisted scores still correct |
| `TestAgenticLoopStatics` | 2 | staticmethods work after dead-import removal |
| `TestToolExecutorThreadOffload` | 2 | `asyncio.to_thread` parallel + async handlers |
| `TestMemoryExtractorModuleCompile` | 2 | hoisted compiled patterns shared, extraction works |

## Self-check results

```text
$ python -m pyflakes core/
(no output — clean)

$ python -m pytest tests/ -q
373 passed, 4 skipped, 8 subtests passed in ~30s
```

## Files modified

```
core/agentic_loop.py        — dead imports, redundant import re removed
core/audio_orchestrator.py  — (no changes)
core/background_lane.py     — unused import
core/config.py              — unused Optional
core/ears.py                — unused numpy
core/heartbeat.py           — unused re
core/identity_store.py      — f-string without placeholders
core/media_controller.py    — dead Quartz stub cleaned
core/memory.py              — _merge_similar_bm25 correctness, _deduplicate_bm25 hoisted scores,
                              unused vars removed
core/memory_extractor.py    — patterns hoisted to module level
core/memory_llm_extractor.py — unused imports
core/memory_profile.py      — unused Optional
core/model_provider.py      — unused os
core/pending_handlers.py    — unused Awaitable
core/prompt_builder.py      — is_weather fix + correct open/weather logic
core/realtime_handlers.py   — unused Awaitable
core/server.py              — urllib.request + AudioOrchestrator imports, ~15 unused names removed,
                              global kage_server cleaned, unused locals removed, f-string fix
core/session_manager.py     — unused with-as bindings
core/system_control.py      — f-string without placeholders
core/tool_executor.py       — asyncio.to_thread for sync handlers
core/tools/__init__.py      — (no changes; references unchanged)
core/tools/agent_ops.py     — uses ok()/err() helpers
core/tools/memory_ops.py    — uses ok()/err() helpers, dropped duplicate proactive_agent
core/tools/shortcuts_ops.py — uses ok()/err() helpers
core/tools/skill_ops.py     — uses ok()/err() helpers
core/tools/web_ops.py       — uses ok()/err() helpers
core/tools_impl.py          — removed wildcard import
core/weather_service.py     — unused imports + local desc
tests/test_round5_cleanup.py — NEW (22 tests)
tests/test_memory_*.py      — removed `return True/False` from test bodies
tests/test_server_helpers.py — removed `return True` from test body

DELETED:
core/intent_keywords.py     — dead module (60 lines)
core/tools/system_ops.py    — dead duplicate of web_ops (8 functions)
```

## Deferred (still)

1. **Decompose `AgenticLoop.run()`** — currently 700 lines, 5 retry/parallel branches. Working
   correctly; high risk to refactor in one pass. A staged refactor could extract per-step helpers
   (`_pre_check_step`, `_run_parallel_batch`, `_run_serial_batch`, `_apply_extracted_facts`).
2. **Decompose `KageServer.run_loop()`** — 350 lines mixing voice / text / fast paths. Same
   considerations; suggest extracting `_handle_text_input`, `_handle_voice_input`,
   `_dispatch_route` first.
3. **API authentication** — localhost-only, low priority.
