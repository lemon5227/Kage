# Kage Optimization Round 12 — 2026-05  ·  Multi-Provider + Claude Code / Codex Login

> Round 12 extends the hybrid mode with **multi-provider support** and a
> one-click "use my Claude Code / Codex environment key" UX.

## What "登陆 Claude Code / Codex 账户" means here

Honest scope:

- **Out of scope** — implementing real OAuth flows for `claude.ai` /
  `chatgpt.com`. Those tokens are bound to specific client IDs and not
  valid against the public REST APIs.
- **Out of scope** — reading CLI credential files (`~/.claude/...`,
  `~/.openai/...`). Format is undocumented and may break; some files
  store OAuth session tokens unusable from outside the CLI.
- **In scope** — picking up `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` env
  vars that the user already has set (e.g. by Claude Code, the OpenAI
  CLI, or their shell rc). One click in settings → Kage adopts the key
  → Kage talks to Claude or GPT directly via their REST APIs.

This is the cleanest path that:
1. respects each vendor's ToS,
2. does not silently snoop credential files,
3. gives the user a one-click experience if they already have a CLI tool
   configured.

## Design

### `core/anthropic_provider.py` — new

Native Claude Messages API client (no `openai` Python package, no
`anthropic` Python package — just `urllib.request` so Kage stays
zero-runtime-dependency-additions).

Key conversions vs OpenAI format:

- `system` is a top-level field, not a message.
- Messages must alternate user/assistant — consecutive same-role messages
  are merged with a newline separator.
- `max_tokens` is required (no default in the API).
- Tool calls come back as `content` blocks with `type: "tool_use"`,
  not in a separate `tool_calls` array.

The class returns the same `ModelResponse` shape as
`OpenAICompatibleProvider`, so the rest of the codebase (broker,
hybrid, agentic loop) is provider-agnostic.

### `core/credential_helpers.py` — new

```python
detect_provider_credentials(env=None) -> dict
    # {"anthropic": {"present": True, "source": "Anthropic SDK / Claude Code"}, ...}
    # Never returns the raw key value.

read_provider_credential(provider, env=None) -> str
    # Internal helper used by the server when adopting an env key.
```

Recognised env vars (ordered by priority):

| Provider | Env vars |
|----------|---------|
| anthropic | `ANTHROPIC_API_KEY` (Claude Code), `CLAUDE_API_KEY` (legacy) |
| openai | `OPENAI_API_KEY` (OpenAI SDK / Codex CLI) |
| google | `GOOGLE_API_KEY`, `GEMINI_API_KEY` |
| deepseek | `DEEPSEEK_API_KEY` |
| moonshot | `MOONSHOT_API_KEY` |

### `core/model_broker.py`

`_make_cloud_provider(cfg)` dispatches by `provider_type`:

```python
ptype = (cfg.get("provider_type") or "openai").lower()
if ptype == "anthropic":
    return AnthropicProvider(...)
return OpenAICompatibleProvider(...)
```

Anthropic gets sensible defaults when the user picks the provider but
doesn't fill in a model name (`claude-3-5-haiku-latest`) or base URL
(`https://api.anthropic.com/v1`).

### Settings API

```
GET  /api/settings/providers/detect
       → {"providers": {"anthropic": {"present": bool, "source": str}, ...}}

POST /api/settings/hybrid
       Now also accepts:
         cloud_provider_type: "openai" | "anthropic"
         use_env_key: "anthropic" | "openai" | ...
       When use_env_key is set AND no explicit cloud_api_key was passed,
       the server reads the env var and adopts it. Inferred provider_type
       defaults to the env-key provider name.
```

Explicit `cloud_api_key` always wins over `use_env_key`. Empty key field
is still ignored (so saving other fields doesn't blank a stored key).

### Settings UI (`kage-avatar/public/settings.html`)

- Provider dropdown (`OpenAI / Anthropic`).
- "Detect from environment" button + status line. On click:
  1. `GET /providers/detect` to find what's available.
  2. Pick the env key matching the dropdown selection (or any present).
  3. `POST /settings/hybrid` with `use_env_key` so the key never touches
     the browser.
  4. Refresh the form so the placeholder shows `•••• already set`.
- Existing API-key paste path still works for explicit override.

## Tests

`tests/test_multi_provider.py` — 39 tests, all run offline.

| Class | Tests | What it pins |
|-------|-------|---|
| `TestConvertMessages` | 9 | system separation, role alternation enforcement, multipart content flatten, tool-role drop, empty-input guards |
| `TestConvertTools` | 4 | function → tool_use schema mapping, edge cases |
| `TestExtractAnthropicResponse` | 4 | text-only / tool_use / multi-block / empty body |
| `TestAnthropicProviderErrors` | 2 | no-user-message error, network error sets `ModelResponse.error` |
| `TestCredentialDetection` | 7 | none / each provider / multiple / whitespace-only / **never echoes raw key** |
| `TestReadProviderCredential` | 4 | env read / unknown provider / missing key / strips whitespace |
| `TestBrokerProviderDispatch` | 5 | anthropic class dispatch / openai class / unknown→openai / hybrid wraps anthropic / default Claude model when unset |
| `TestSettingsApiProvidersDetect` | 4 | detect endpoint shape / use_env_key adopts / explicit key wins / missing env doesn't overwrite stored key |

## Self-check

```
$ python -m pyflakes core/ tests/test_multi_provider.py
(no output)

$ python -m pytest tests/ -q
604 passed, 4 skipped, 1 xfailed, 1 warning, 8 subtests passed in ~64s
```

## Files modified / created

```
core/anthropic_provider.py          — NEW (256 lines)
core/credential_helpers.py          — NEW (117 lines)
core/model_broker.py                — _make_cloud_provider dispatch + Anthropic defaults
core/server.py                      — cloud_api defaults + detect endpoint + use_env_key adoption
config/settings.json                — provider_type field added
kage-avatar/public/settings.html    — provider dropdown + "Detect from environment" button + JS
tests/test_multi_provider.py        — NEW (39 tests)
docs/optimization-2026-05-round12.md — this file
```

## Cumulative trajectory

| Round | Tests | Δ | Highlight |
|-------|-------|---|---|
| baseline | 355 | — | — |
| Round 5–9 | 448 | +93 | Cleanup + hot-path perf |
| Round 10 | 540 | +92 | Companion-assistant scenarios + bug fix |
| Round 11 | 565 | +25 | Hybrid local+cloud mode |
| **Round 12** | **604** | **+39** | **Multi-provider + Claude Code / Codex env adoption** |

Net: **+249 regression tests** (+70% over baseline), 4 latent bugs fixed,
2 new production features shipped (hybrid + multi-provider).

## How a user logs in with Claude Code

1. User has Claude Code installed and configured →
   `ANTHROPIC_API_KEY=sk-ant-...` is in their env (the standard
   Claude Code setup).
2. User opens Kage settings → Brain & Models → Hybrid Mode.
3. User clicks **"Detect from environment"**.
4. Kage shows "Adopted Anthropic SDK / Claude Code key — saved.".
5. User checks **"Enable hybrid fallback to cloud"** and clicks Apply.
6. From then on: local Qwen3 stays primary; if it fails, Claude Sonnet
   takes over silently.

For Codex / OpenAI CLI users the flow is identical with
`OPENAI_API_KEY`.

## What the user gets vs Claude Code itself

- Claude Code is a coding-focused CLI; Kage is a desktop companion with
  voice + memory + Live2D avatar.
- Kage uses your same Anthropic key but pays your tokens into your own
  Anthropic account (no proxy, no middleman).
- Privacy: when hybrid is off, **nothing** leaves the local machine —
  not the prompt, not the user message, not the recall results.
