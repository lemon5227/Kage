# Kage Optimization Round 10 — 2026-05

> Round 10 pivot: from mechanical pattern-tests to **real companion-assistant
> scenarios**. The user's critique was right — earlier rounds tested "is the
> regex hoisted?" but not "does Kage actually behave like a personal companion?"
>
> This round adds **92 new scenario tests** across 4 batches and ships **one
> real product bug fix** (confirm/cancel text recognition).

## What "deeply-embedded personal companion" means in tests

The earlier test files were mostly:

- "function exists / pattern is hoisted"
- "trivial input/output checks"
- "module attribute exists"

A 二次元 personal companion needs tests for:

- Multi-turn memory continuity (what user said 5 turns ago must come back)
- Persona consistency under prompt budget pressure
- Pending state machine (confirm/cancel/correction across turns)
- Fast-path latency contract (commands skip LLM)
- Empty-reply guards (avatar bubble must never go blank for non-empty input)
- Profile injection ordering (SOUL → USER → time → memory → tools)

All four batches in this round target these gaps, with no LLM calls (all
tests are deterministic + offline).

## Batch A — `tests/test_companion_continuity.py` (26 + 1 xfail)

Multi-turn memory + profile + persona + bubble fit + route-aware sizing.

| Class | Tests | What it pins |
|-------|-------|---|
| `TestMultiTurnPreferenceRecall` | 2 | Stated preference recallable many turns later; correction stays in top-2 |
| `TestProfileInjectionIntoSystemPrompt` | 4 | food / city / sleep / relationship from MemoryProfile reach system prompt |
| `TestProfileDurabilityAcrossReload` | 2 | Profile survives MemoryProfile re-instantiation (process restart) |
| `TestNeverEmptyChatReply` | 8 + 1 | polish_chat_response recovers to "嗯" for any non-empty dirty input; empty in → empty out is intentional |
| `TestPersonaGlyphPreservation` | 3 | ✨😤💖 + Chinese punct survive; 🎵 (disallowed) gets stripped |
| `TestPolishBubbleFit` | 2 | Reply ≤ `_MAX_CHAT_RESPONSE_LEN` chars |
| `TestRouteAwarePromptSizing` | 4 + 1 xfail | info/command routes skip memory recall; minimal tool sets; **xfail: classifier doesn't recognise colloquial '截个屏'** (only literal '截屏') |

### Real product gap discovered (xfail)

```python
@pytest.mark.xfail(strict=True, reason="...documented gap...")
def test_classifier_recognises_colloquial_screenshot(self):
    assert builder.classify_route("帮我截个屏") == "command"
```

`prompt_builder.classify_route` matches `_SYSTEM_KEYWORDS` (which contains
`"截屏"`) by substring, but `"帮我截个屏"` contains `"截个屏"`, not `"截屏"`.
Documented as a known weakness so we notice if the classifier improves.

## Batch B — `tests/test_companion_pending_state.py` (35)

Pending state machine: confirm / cancel / correction / undo across turns.

| Class | Tests | What it pins |
|-------|-------|---|
| `TestPendingActionLifecycle` | 5 | SessionState.set/clear/has_pending; pending_kind dispatch for all 4 types |
| `TestConfirmCancelClassification` | 16 | Recognises 好/嗯/对/确认/可以/yes/ok and 不/算了/取消/不行/no — most common Chinese affirmatives + cancellations |
| `TestCorrectionExtraction` | 5 | "不是这个，是 X" extracts X cleanly |
| `TestPendingVideoFollowup` | 3 | "打开" alone reuses cached URL; failure prompts retry; empty URL never opens "" |
| `TestPendingVideoCorrection` | 2 | Correction triggers re-search with new query; empty results don't fall back to old wrong URL |
| `TestPendingConfirmTool` | 4 | Confirm runs tool; cancel doesn't; undo doesn't; unrecognized reply doesn't auto-execute |

### Real product bug fixed

`is_confirm_text("嗯")` returned False. `"嗯"` / `"对"` / `"可以"` are among
the most common ways Chinese speakers say "yes". A user saying "嗯" to
confirm a `fs_trash` operation would not have been recognised as confirmation,
silently breaking the confirm flow.

```python
# core/realtime_lane.py — before
return s in ("确认", "确定", "好", "行", "执行", "是", "ok", "okay", "yes")

# after
return s in ("确认", "确定", "好", "好的", "行", "执行", "是", "对", "嗯", "可以",
             "ok", "okay", "yes")
```

Same expansion for `is_cancel_text`: now also matches `"不行"`, `"不可以"`.

## Batch C — `tests/test_companion_persona.py` (9)

Persona / identity injection from disk-backed SOUL.md / USER.md.

| Class | Tests | What it pins |
|-------|-------|---|
| `TestSoulInjection` | 3 | User-customised SOUL.md reaches system prompt verbatim; default has Kage persona; mid-session edits picked up next turn |
| `TestUserMdInjection` | 2 | User name + timezone in USER.md reach prompt |
| `TestPromptOrdering` | 2 | SOUL precedes profile summary; current time present |
| `TestPersonaSurvivesTokenBudget` | 2 | System prompt with persona NEVER trimmed under budget; current user input always last message |

These are critical because Kage's personality is supposed to live in
markdown, not Python. If SOUL.md edits don't reach the prompt, the user
can't actually customise their companion.

## Batch D — `tests/test_companion_fast_command.py` (22)

The fast-path that bypasses the LLM for high-confidence commands.

| Class | Tests | What it pins |
|-------|-------|---|
| `TestFastCommandEmptyInput` | 1 | Empty/whitespace/None → None (caller falls through to agent loop) |
| `TestFastCommandVolume` | 4 | up / down / mute / unmute |
| `TestFastCommandBrightness` | 2 | up / down |
| `TestFastCommandWeather` | 3 | With city / without city (uses effective city) / "上网搜天气" doesn't trigger wifi toggle |
| `TestFastCommandBluetooth` | 2 | on / off |
| `TestFastCommandMedia` | 4 | pause / next / previous / netease preference |
| `TestFastCommandFallthrough` | 3 | Greetings / open-website / questions return None (so LLM handles) |
| `TestPersonaWrap` | 3 | persona_wrap formats the result; unknown cmd_type falls back to default |

Each test inspects the recorded tool calls, so we know fast-path commands
are routed to the **correct** primitive — no hallucination, no LLM call.

## Bonus — flaky timing test

`tests/test_round5_cleanup.py::test_parallel_sync_handlers_overlap` was
sometimes failing on a loaded laptop (131ms vs 90ms budget). Rewrote with
larger delays (100ms each, budget 170ms) so the parallel-vs-serial gap
stays clearly observable even under load. Still strictly less than the
serial path (200ms).

## Self-check

```
$ python -m pyflakes core/ tests/test_companion_*.py
(no output)

$ python -m pytest tests/ -q
540 passed, 4 skipped, 1 xfailed, 1 warning, 8 subtests passed in ~70s
```

The 1 warning is `pkg_resources` deprecation from pygame (third-party).
The 1 xfailed is the documented classifier gap.

## Cumulative trajectory (rounds 5-10)

| Round | Tests | Δ | Highlight |
|-------|-------|---|---|
| baseline | 355 | — | — |
| Round 5 | 377 | +22 | NameError + dead code + response shape |
| Round 6 | 401 | +24 | server dead methods + memory recall + collapse_repeats |
| Round 7 | 415 | +14 | chat_polisher / route_classifier dead funcs |
| Round 8 | 427 | +12 | tool_registry + path portability + closure extract |
| Round 9 | 448 | +21 | AvatarAnimation AttributeError + 5 modules regex hoisted |
| **Round 10** | **540** | **+92** | **Companion-assistant scenarios + confirm/cancel text bug fix** |

Net: **+185 regression tests** (+52% over baseline), pyflakes clean,
**4 latent bugs fixed** (urllib NameError, is_weather NameError,
emotion_weights AttributeError, is_confirm_text recognition gap).

## Files modified

```
core/realtime_lane.py                    — confirm/cancel text recognition expanded
tests/test_companion_continuity.py       — NEW (26 + 1 xfail)
tests/test_companion_pending_state.py    — NEW (35)
tests/test_companion_persona.py          — NEW (9)
tests/test_companion_fast_command.py     — NEW (22)
tests/test_round5_cleanup.py             — relaxed flaky timing test
docs/optimization-2026-05-round10.md     — NEW (this file)
```

## Remaining gaps (deferred)

1. Decompose `AgenticLoop.run()` (~700 lines).
2. Decompose `KageServer.run_loop()` (~350 lines).
3. Voice-barge-in scenarios (`speech_revision` race semantics).
4. Privacy / log scrubbing scenarios (no PII in tool_log.jsonl).
5. Frontend `kage-avatar/src/main.ts` — needs TS toolchain.
6. Fix the colloquial `'截个屏'` classifier gap (token-aware matching).
