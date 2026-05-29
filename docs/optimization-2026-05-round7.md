# Kage Optimization Round 7 — 2026-05

> Continuation of the iterative optimization series. Round 7 focused on:
> dead-function removal across previously-untouched modules and hot-path
> constant hoisting in `agentic_loop`, `prompt_builder`, `tool_executor`,
> and `tools/file_ops`.
>
> Result: **415 tests pass** (was 401), 0 warnings, pyflakes core/ clean.

## Iteration 7a — Dead module-level functions removed

Survey via `grep -rn` confirmed these functions had only their `def` line as
their sole reference across `core/`, `tests/`, and `scripts/`:

| Function | Module | Lines | Notes |
|----------|--------|-------|-------|
| `extract_location_from_text` | `route_classifier` | 25 | Server already uses inline `_RE_LOCATION_*` patterns. |
| `is_bad_chat_response` | `chat_polisher` | 37 | Quality heuristic never wired into the response pipeline. |
| `fallback_chat_response` | `chat_polisher` | 5 | Hardcoded fallback never reached. |
| `short_care_phrase` | `chat_polisher` | 3 | "Care phrase" generator that nothing imports. |

Constants that became dead with the functions:

- `route_classifier._LOCATION_FILLER`
- `chat_polisher._RE_HAS_LATIN`
- `chat_polisher._BAD_RESPONSE_PHRASES`
- `chat_polisher._SHORT_OK_RESPONSES`
- `chat_polisher._GENERIC_ACKNOWLEDGEMENTS`
- `chat_polisher._CARE_PHRASES`

Imports that became unused:

- `core/chat_polisher.py`: `import random` (only `short_care_phrase` used it)
- `core/route_classifier.py`: `import re` (only `extract_location_from_text` used it)

## Iteration 7b — Hot-path constant hoisting

### `core/agentic_loop._can_parallelize_tool_calls`

The "read-only tool" set used to gate parallel execution was being rebuilt on
**every tool batch check** as an inline `set(...)` literal:

```python
def _can_parallelize_tool_calls(calls):
    ...
    read_only = {"smart_search", "search", "web_fetch", ...}  # rebuilt each call
    for tc in calls:
        if str(tc.get("name") or "").strip() not in read_only:
            return False
```

Hoisted to a module-level frozenset (`_READ_ONLY_TOOLS`). Constant set
construction happens once at import.

### `core/prompt_builder._select_tool_names`

The function had four inline set literals on the chosen-tool fast path:

```python
chosen.update({"smart_search", "web_fetch"})
chosen.update({"open_url", "open_website", "open_app"})
chosen.update({"fs_search", "fs_preview", "fs_apply", "fs_move", ...})
chosen.update({"system_control", "take_screenshot"})
```

Plus an early-return path that always called `sorted(core)` on a freshly-built
set. Hoisted all five subsets to module-level constants:

- `_TOOLS_WEB`, `_TOOLS_OPEN`, `_TOOLS_FILE`, `_TOOLS_SYSTEM` — frozensets used
  via `chosen |= _TOOLS_X` (faster set-union).
- `_TOOLS_INFO_DEFAULT`, `_TOOLS_INFO_WEATHER` — pre-sorted lists; the
  `sorted()` call is now done once at import time, not per call.

### `core/tool_executor._normalize_arguments`

Two issues:

1. A nested closure `_first_value(d, keys)` was being **redefined on every
   tool execution**. Moved to module-level function.
2. The `fs_apply` op kind synonym map was a dict literal **inside the inner
   loop**, allocated for every op:
   ```python
   for op in ops:
       ...
       kind_map = {"mv": "move", "rename": "rename", ...}
       kind = kind_map.get(kind, kind)
   ```
   Hoisted to module-level `_FS_APPLY_KIND_MAP`.
3. All key lookup lists (`["src", "source", "from", "path"]`) changed to
   tuples — Python iterates tuples slightly faster and they're immutable.

### `core/tools/file_ops._is_path_allowed`

Was re-resolving home + tempdir on **every fs operation**:

```python
def _is_path_allowed(path):
    ...
    home = os.path.realpath(os.path.expanduser("~"))   # syscalls every call
    if real == home or real.startswith(home + "/"):
        return True
    import tempfile                                     # function-level import
    tmp = os.path.realpath(tempfile.gettempdir())       # more syscalls
    if real == tmp or real.startswith(tmp + "/"):
        return True
```

Hoisted both to module-level `_HOME_REAL` and `_TMP_REAL` (resolved once at
import). Moved `import tempfile` up too.

## New tests

`tests/test_round7_cleanup.py` — 14 tests across three classes:

| Class | Tests | Covers |
|-------|-------|--------|
| `TestDeadFunctionsRemoved` | 7 | All 4 functions + 5 constants + the `random` import all gone |
| `TestModuleLevelConstants` | 5 | Hoisted constants exist with correct types; helpers callable |
| `TestBehaviorPreserved` | 2 | `_select_tool_names` still returns sorted lists; `_normalize_arguments` still maps every alias correctly across all tools (incl. `fs_apply` synonyms) |

## Self-check

```
$ python -m pyflakes core/ tests/test_round7_cleanup.py
(no output)

$ python -m pytest tests/ -q
415 passed, 4 skipped, 8 subtests passed in ~43s
```

## Files modified

```
core/agentic_loop.py             — hoisted _READ_ONLY_TOOLS frozenset
core/chat_polisher.py            — removed 3 dead funcs + 5 dead constants + random import
core/prompt_builder.py           — hoisted 4 tool subsets + 2 sorted lists
core/route_classifier.py         — removed extract_location_from_text + _LOCATION_FILLER + re import
core/tool_executor.py            — _first_value module function + _FS_APPLY_KIND_MAP
core/tools/file_ops.py           — _HOME_REAL + _TMP_REAL hoisted, import tempfile up
tests/test_round7_cleanup.py     — NEW (14 tests)
docs/optimization-2026-05-round7.md — NEW (this file)
```

## Cumulative trajectory (rounds 1-7)

| Round | Tests pass | New tests | Pyflakes |
|-------|------------|-----------|----------|
| baseline | 355 | — | many warnings |
| Round 5 | 377 | +22 | clean |
| Round 6 | 401 | +24 | clean |
| Round 7 | 415 | +14 | clean |

server.py: 2574 → 2484 → 2484 lines (stayed flat in round 7; chat_polisher
shrunk by ~40 lines instead).

## Deferred (still)

1. Decompose `AgenticLoop.run()` (700 lines).
2. Decompose `KageServer.run_loop()` (~350 lines).
3. Vectorize `_keyword_overlap_scores` in `core/memory.py` (cold fallback path).
