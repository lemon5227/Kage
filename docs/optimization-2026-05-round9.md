# Kage Optimization Round 9 — 2026-05

> Continuation of the iterative optimization series. Round 9 focused on:
> a latent AttributeError bug in `AvatarAnimation` and hot-path regex
> hoisting across 5 previously-untouched modules.
>
> Result: **448 tests pass** (was 427, +21 new), 0 actionable warnings.

## Iteration 9a — Latent AttributeError fix in `AvatarAnimation`

`AvatarAnimation.select_motion()` accessed `self.motion.emotion_weights`, but
the `emotion_weights` field is defined on `ExpressionConfig`, not
`MotionConfig`. On first call after cooldown expired, the function would
raise `AttributeError: 'MotionConfig' object has no attribute 'emotion_weights'`.

Reproduction (before fix):

```python
from core.avatar_animation import AvatarAnimation
av = AvatarAnimation()
av.select_motion('happy')
# AttributeError: 'MotionConfig' object has no attribute 'emotion_weights'
```

Fix:

```python
# Before
weights_map = self.motion.emotion_weights.get(emotion_key, self.motion.weights)

# After
weights_map = self.expression.emotion_weights.get(emotion_key, self.motion.weights)
```

This bug went unnoticed because there were **no tests for `avatar_animation`**.
Three new tests added in `TestAvatarAnimationSelectMotion`.

## Iteration 9b — Hot-path regex hoisting

5 modules had inline `re.sub` / `re.search` / `re.match` calls in functions
called at conversation speed. All patterns hoisted to precompiled module-level
constants.

### `core/realtime_handlers.py`

8 inline patterns across `normalize_video_query_for_search`,
`extract_video_subject`, `video_subject_match_score`, and
`extract_video_followup_correction_text`. All called per video query / per
follow-up turn. Hoisted to:

- `_RE_NVQ_TRAILING_OPEN_LONG` / `_SHORT` / `_PLAIN` (3 normalization patterns)
- `_RE_EVS_PREFIX_NEGATION` / `_REQUEST` / `_VERB`
- `_RE_EVS_SUFFIX_VIDEO` / `_PLATFORM`
- `_RE_HAS_CJK` (used in scoring for CJK token weighting)
- `_RE_CORRECTION_PREFIX`

Also extracted `_QUERY_STRIP_CHARS` constant to avoid 4 inline duplicates of
the same long character set passed to `str.strip()`.

### `core/mouth.py`

`KageMouth.clean_text_for_tts()` is called for every TTS turn. The two
patterns (`_RE_TTS_DISALLOWED_CHARS` for the character whitelist and
`_RE_TTS_REPEATED_CHARS` for run collapsing) were recompiled on every call.
Hoisted to module level.

### `core/realtime_lane.py`

`extract_correction_text()` runs on every conversational turn that might
contain a correction. Hoisted `_RE_CORRECTION` and `_CORRECTION_STRIP_CHARS`.

### `core/router.py`

`KageRouter.classify()` is the legacy router still used by some unit tests.
Two `re.search` calls and an inline list literal of negative keywords. All
hoisted (`_RE_SCREENSHOT`, `_RE_OPEN_APP`, `_OPEN_APP_NEGATIVE_KEYWORDS`).

### `core/tools/html_ops.py`

`strip_html_tags()` falls back to a 3-step regex pipeline when
`HTMLTextExtractor` raises. Hoisted `_RE_HTML_SCRIPT`, `_RE_HTML_STYLE`,
`_RE_HTML_TAG`.

## New tests

`tests/test_round9_cleanup.py` — 21 tests across six classes:

| Class | Tests | Covers |
|-------|-------|--------|
| `TestAvatarAnimationSelectMotion` | 3 | `select_motion` no longer crashes; returns valid index for known/unknown emotions |
| `TestRealtimeHandlersHoistedPatterns` | 4 | Patterns exist as `re.Pattern`; behavior preserved (normalize, extract, scoring) |
| `TestMouthHoistedPatterns` | 3 | Patterns exist; whitelist strips emoji; run collapse works |
| `TestExtractCorrectionTextHoisted` | 3 | Pattern hoisted; correction extraction + empty fallback |
| `TestRouterHoistedPatterns` | 5 | Patterns hoisted; screenshot / open-app / open-website / chat fallback |
| `TestHtmlOpsHoistedPatterns` | 3 | Patterns hoisted; HTML stripping basic + script removal |

## Self-check

```
$ python -m pyflakes core/ tests/test_round9_cleanup.py
(no output)

$ python -m pytest tests/ -q
448 passed, 4 skipped, 1 warning, 8 subtests passed in ~47s
```

The 1 remaining warning is a `pkg_resources` deprecation from pygame (third
party), not actionable from this codebase.

## Files modified

```
core/avatar_animation.py             — latent AttributeError fix
core/mouth.py                        — 2 hoisted regex patterns
core/realtime_handlers.py            — 10 hoisted regex/string constants
core/realtime_lane.py                — 1 hoisted regex + strip-chars constant
core/router.py                       — 2 hoisted regex + 1 hoisted tuple
core/tools/html_ops.py               — 3 hoisted regex patterns
tests/test_round9_cleanup.py         — NEW (21 tests)
docs/optimization-2026-05-round9.md  — NEW (this file)
```

## Cumulative trajectory (rounds 5-9)

| Round | Tests pass | New tests | Highlight |
|-------|------------|-----------|-----------|
| baseline | 355 | — | — |
| Round 5 | 377 | +22 | NameError + dead code + response shape |
| Round 6 | 401 | +24 | 6 dead methods + memory recall + collapse_repeats |
| Round 7 | 415 | +14 | chat_polisher/route_classifier dead funcs + tool subsets |
| Round 8 | 427 | +12 | tool_registry dead method + portability + closure extract |
| Round 9 | 448 | +21 | AvatarAnimation AttributeError + 5 modules regex hoisted |

Net: **+93 regression tests** across 5 rounds (+26%), pyflakes core/ clean
throughout, three latent bugs fixed (urllib NameError, is_weather NameError,
emotion_weights AttributeError).

## Deferred (still)

1. Decompose `AgenticLoop.run()` (~700 lines).
2. Decompose `KageServer.run_loop()` (~350 lines).
3. Vectorize `_keyword_overlap_scores` in `core/memory.py` (cold fallback).
4. Frontend `kage-avatar/src/main.ts` (untouched; needs TS toolchain).
