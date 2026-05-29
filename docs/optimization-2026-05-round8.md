# Kage Optimization Round 8 — 2026-05

> Continuation of the iterative optimization series. Round 8 focused on:
> dead-method removal in `tool_registry`, a portability bug fix (hardcoded
> developer path), extraction of an inner closure to a method, and one more
> hot-path constant hoist.
>
> Result: **427 tests pass** (was 415), 0 warnings, pyflakes core/ clean.

## Iteration 8a — Dead method on `ToolRegistry`

`ToolRegistry.get_tool_descriptions()` was added in Round 3 with caching
support, but no caller exists across `core/`, `tests/`, or `scripts/`. The
method along with its `_descriptions_cache` field and the corresponding
cache-invalidation line in `register()` were removed.

`get_all_schemas()` and its cache are unaffected (still tested and used).

## Iteration 8b — Portability fix in MCP config path

`_register_mcp_dynamic_aliases()` had a hardcoded fallback path:

```python
path = str(mcp_cfg_path or os.environ.get("KAGE_MCP_CFG")
           or "/Users/wenbo/Kage/config/mcp.json")  # ← original developer's path
```

This breaks for any user other than the original developer when neither the
`KAGE_MCP_CFG` env var nor the explicit `mcp_cfg_path` argument is provided.

Replaced with a module-relative default:

```python
default_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "mcp.json",
)
path = str(mcp_cfg_path or os.environ.get("KAGE_MCP_CFG") or default_path)
```

Now resolves to `<repo>/config/mcp.json` regardless of where the repo is
checked out. A static-source check
(`TestMcpConfigPathPortability::test_no_hardcoded_user_path_in_source`) was
added to prevent regression.

## Iteration 8c — `_exec_one` extracted from `run()` closure

`AgenticLoop.run()` defined an `async def _exec_one(call)` closure inside its
main loop body. Every parallel-tool batch invocation re-allocated this closure
object. Because `_exec_one` only captured `self` (via `self.tools`), it was a
clean candidate for extraction:

```python
# OLD: inside run()
async def _exec_one(call: dict) -> dict:
    n = str(call.get("name") or "")
    a = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
    try:
        r = await self.tools.execute(n, a)
        return {...}
    except Exception as exc:
        return {...}

parallel_rows = await asyncio.gather(*[_exec_one(tc) for tc in tool_calls if isinstance(tc, dict)])
```

```python
# NEW: method on AgenticLoop
async def _exec_one(self, call: dict) -> dict:
    ...

parallel_rows = await asyncio.gather(*[
    self._exec_one(tc) for tc in tool_calls if isinstance(tc, dict)
])
```

Side benefit: `_exec_one` is now independently testable (5 new tests covering
success, exception handling, missing arguments, and `asyncio.gather` overlap).

## Iteration 8d — Hoist `_SKILL_LIFECYCLE_TOOLS`

The same 4-tuple `("skills_find_remote", "web_fetch", "skills_install",
"skills_read")` was inlined at three call sites in `agentic_loop.py`. Hoisted
to a module-level frozenset `_SKILL_LIFECYCLE_TOOLS`. All three sites now use
`name not in _SKILL_LIFECYCLE_TOOLS`.

## New tests

`tests/test_round8_cleanup.py` — 12 tests across four classes:

| Class | Tests | Covers |
|-------|-------|--------|
| `TestDeadToolRegistryMethod` | 3 | `get_tool_descriptions` and `_descriptions_cache` gone; `get_all_schemas` cache still works |
| `TestMcpConfigPathPortability` | 2 | Default path is module-relative; source has no hardcoded `/Users/<name>/` literal |
| `TestExecOneExtracted` | 5 | `_exec_one` is a class method, returns expected shape on success and exception, normalizes missing args, parallelizes via gather |
| `TestSkillLifecycleToolsHoisted` | 2 | Module-level frozenset exists with expected contents |

## Self-check

```
$ python -m pyflakes core/ tests/test_round8_cleanup.py
(no output)

$ python -m pytest tests/ -q
427 passed, 4 skipped, 8 subtests passed in ~51s
```

## Files modified

```
core/agentic_loop.py             — _exec_one method + _SKILL_LIFECYCLE_TOOLS hoist
core/tool_registry.py            — removed get_tool_descriptions + _descriptions_cache; portable MCP path
tests/test_round8_cleanup.py     — NEW (12 tests)
docs/optimization-2026-05-round8.md — NEW (this file)
```

## Cumulative trajectory (rounds 5-8)

| Round | Tests pass | New tests | Pyflakes |
|-------|------------|-----------|----------|
| baseline | 355 | — | many warnings |
| Round 5 | 377 | +22 | clean |
| Round 6 | 401 | +24 | clean |
| Round 7 | 415 | +14 | clean |
| Round 8 | 427 | +12 | clean |

Net: 72 new regression tests (+20%), pyflakes core/ from many warnings to clean,
core/server.py 2574 → 2484 lines (Round 6), various other modules slimmed down.

## Deferred (still)

1. Decompose `AgenticLoop.run()` (still ~700 lines after `_exec_one` extracted).
2. Decompose `KageServer.run_loop()` (~350 lines).
3. Vectorize `_keyword_overlap_scores` in `core/memory.py` (cold fallback).
4. Frontend `kage-avatar/src/main.ts` (untouched; needs TS toolchain to verify).
