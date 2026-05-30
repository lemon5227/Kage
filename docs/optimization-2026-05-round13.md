# Kage Optimization Round 13 — 2026-05  ·  Live Settings Reload + Connection Test

> Round 13 closes two real UX gaps left over from Round 11–12:
>
>   1. Saving hybrid settings used to require a process restart before
>      the new key / provider took effect.
>   2. Users had no way to check that their cloud key actually worked
>      until they made a real chat request.
>
> Both are fixed. **624 tests pass** (was 604, +20 new). pyflakes clean.

## What's new for the user

```
[ ✅ ] Enable hybrid fallback to cloud
[ Anthropic        ▼ ]
[ Detect from env ] [ Test connection ]   ✅ anthropic/claude-3-5-haiku-latest responded in 412ms
[ ••••              ] (already set)
```

- **Test connection** button: one-click probe that issues a 4-token ping
  to whichever provider is configured (or just-typed) and reports
  `✅ provider/model in 412ms` or `❌ <actionable error>`. Latency is
  measured server-side so the UI shows real round-trip cost.
- **Save** now hot-reloads the model broker. The next chat turn uses
  the new settings — no need to restart Kage.

## Implementation

### `core/provider_test.py` — new

```python
def probe_provider(provider_type, api_key, model_name="", base_url="") -> ProviderTestResult:
    # 1. Short-circuit on missing key.
    # 2. Build provider via _make_probe_provider (same dispatch as broker).
    # 3. Issue ONE generate() call: messages=[{"role":"user","content":
    #    "Reply with the single word: ok"}], max_tokens=4, temperature=0.0.
    # 4. Wrap result in ProviderTestResult(ok, provider_type, model,
    #    latency_ms, error, text_sample).
```

The function is named `probe_provider` (not `test_provider`) so pytest's
test-discovery doesn't grab it as a fixture parameter. The class
`ProviderTestResult` carries a `to_dict()` that explicitly enumerates
which fields are exposed — no chance of leaking `api_key` into the
response.

### `KageServer.reload_model_broker()`

```python
def reload_model_broker(self) -> None:
    cfg = _load_effective_config()
    broker = ModelBroker(cfg)

    self.model_broker            = broker
    self.routing_model_provider  = broker.routing_provider
    self.realtime_model_provider = broker.realtime_provider
    self.background_model_provider = broker.background_provider
    self.model_provider          = self.background_model_provider
    self.fallback_model_provider = broker.fallback_provider

    agentic = getattr(self, "agentic_loop", None)
    if agentic is not None:
        agentic.model = self.background_model_provider

    logger.info("ModelBroker reloaded — modes: ...")
```

The key insight: `AgenticLoop` was constructed with a captured reference
to the model provider at startup. Without explicitly updating
`agentic_loop.model`, the next turn would still use the old provider.
The reload is **the** cheap part of the change — the cost (sub-millisecond
broker rebuild) lets settings apply atomically per save.

### Settings API

- **POST `/api/settings/hybrid`** now also returns `reload: applied |
  skipped | failed: <reason>`. `applied` means the running KageServer
  picked up the change. `skipped` means no live server (e.g. control-plane
  mode pre-runtime boot) — save still succeeded.
- **POST `/api/settings/test_provider`** new endpoint:

    ```json
    {
      "provider_type": "openai" | "anthropic",
      "api_key":       "sk-..."          // optional
      "use_env_key":   "anthropic"       // optional fallback
      "use_stored":    true              // probe the saved config
      "model_name":    "..."             // optional override
      "base_url":      "..."             // optional override
    }
    ```

    Returns:

    ```json
    { "ok": true, "provider_type": "anthropic",
      "model": "claude-3-5-sonnet-latest",
      "latency_ms": 412.5, "error": null, "text_sample": "ok" }
    ```

    The endpoint never echoes the API key — it's used to build the
    provider, then discarded.

### UI (`settings.html`)

- New "Test connection" button next to the existing "Detect from
  environment" button.
- The button:
  1. Reads the form (provider type, key if typed, model, base URL).
  2. If the user typed a key, probes that. Otherwise sends
     `use_stored: true` so the server probes the currently-saved key.
  3. Shows `✅ provider/model in Xms` (green) or `❌ <error>` (red)
     in the same status line used by the env-detect button.

## Tests

`tests/test_provider_test_and_reload.py` — 20 tests, all run offline.

| Class | Tests | What it pins |
|-------|-------|---|
| `TestMakeProbeProvider` | 4 | Dispatch by provider_type; default fill-in; explicit overrides |
| `TestProviderProbeFunction` | 7 | Missing/whitespace key short-circuits; success returns ok=True; failure surfaces error; Anthropic dispatch; result.to_dict has no secrets; text_sample truncated to 80 chars |
| `TestProviderTestEndpoint` | 4 | Explicit key probed; `use_stored` pulls saved key; `use_env_key` reads from env; bad payload doesn't 5xx |
| `TestReloadModelBroker` | 3 | Reload picks up config change; agentic_loop ref updated to NEW provider object; safe when no agentic_loop attribute |
| `TestHybridSaveAutoReload` | 2 | Save without server returns reload=skipped; save with server returns reload=applied AND broker actually flips to hybrid |

## Self-check

```
$ python -m pyflakes core/ tests/test_provider_test_and_reload.py
(no output)

$ python -m pytest tests/ -q
624 passed, 4 skipped, 1 xfailed, 1 warning, 8 subtests passed in ~60s
```

## Files modified / created

```
core/provider_test.py                — NEW (137 lines)
core/server.py                       — KageServer.reload_model_broker, 2 new endpoints, hybrid save calls reload
kage-avatar/public/settings.html     — Test-connection button + JS
tests/test_provider_test_and_reload.py — NEW (20 tests)
docs/optimization-2026-05-round13.md — this file
```

## Cumulative trajectory

| Round | Tests | Δ | Highlight |
|-------|-------|---|---|
| baseline | 355 | — | — |
| 5–9 cleanup | 448 | +93 | hot-path perf + dead code |
| 10 | 540 | +92 | companion-assistant scenarios + bug fix |
| 11 | 565 | +25 | hybrid local+cloud mode |
| 12 | 604 | +39 | multi-provider + Claude/Codex env adoption |
| **13** | **624** | **+20** | **Live broker reload + connection test** |

Net: **+269 regression tests** (+76% over baseline), 4 latent bugs fixed,
3 production features shipped (hybrid · multi-provider · live reload +
connection test).

## What's left for hybrid mode

- **Telemetry**: track per-turn whether the request went local / cloud /
  escalated, so the user can tune `escalate_keywords` from data.
- **Race-and-take-first**: start local + cloud in parallel and use
  whichever returns first. More complex error handling; lower priority
  because most local turns are fast.
- **Provider streaming**: the API endpoint test waits for full response.
  For chat the agentic loop does the same. Streaming would improve
  perceived latency but is a much larger refactor.
