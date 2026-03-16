# Kage Refactor Plan (Companion-Grade Personal Assistant)

This document is the agreed refactor plan and execution checklist.

> Note (2026-02-11): For the latest orchestration strategy, phased execution details,
> and handoff instructions, read:
> - `docs/HANDOFF_FOR_NEXT_MODEL.md`
> - `docs/agent_orchestration_playbook.md`
> - `docs/agent_progress_log.md`

## Goals

- Local-first: local runtime is primary; optional cloud fallback when needed.
- Companion-grade UX: stable multi-turn, reliable commands, real-time short replies, background long tasks, meaningful completion notifications.
- Voice UX: interruptible speech, barge-in, and eventual full-duplex conversation are explicit product goals rather than optional polish.
- Companion memory: long-term profile, episodic memory, persona memory, and relationship memory become first-class architecture concerns.
- Avatar evolution: do not bind expression capability to Live2D only; preserve a migration path toward richer avatar drivers such as VRM.
- Maintainable: clear architecture boundaries; tests and smoke harnesses gate each step.

## Current Reality (2026-03-16)

- `core/server.py` has been significantly thinned, but it is still the orchestration hub and remains the largest structural hotspot.
- Local runtime is now owned by Kage itself (`LocalModelRuntime`) rather than depending on LM Studio as a runtime host.
- Realtime lane, pending handlers, dialog state, background lane, and job events all exist as real modules, not just plan items.
- Audio work has started:
  - interruptible TTS exists
  - text input can interrupt playback
  - lightweight voice-activity barge-in preparation exists
- Local model smoke is now real and latency-aware:
  - `Qwen3.5 9B` has been validated via Kage-managed `llama-server`
  - with `reasoning=off`, short response latency dropped from multi-second thinking output to a usable short-answer path
- Model roles have started to become explicit through `ModelBroker`, but routing policy is still early-stage and not yet fully enforced at every callsite.
- Companion memory is still architecture-defined but not yet implementation-led.

## What We Learned

- Latency must be treated as a first-class product constraint, not as an afterthought.
- Runtime launch success is not enough; we need `ready_s`, request latency, and interruption behavior recorded as hard metrics.
- Qwen-style local models may look “too slow” or “too verbose” until runtime flags are tuned correctly; `reasoning=off` changed both output quality and latency materially.
- The cleanest improvements so far came from extracting reusable boundaries:
  - pending handlers
  - realtime handlers
  - background lane
  - response sanitization
  - model broker
- We should avoid pushing more logic back into `server.py`, even for “small shortcuts”; new behavior should prefer dedicated modules with narrow roles.

## Adjusted Priorities

The original milestone order was directionally right, but reality changed the best next move:

1. Finish the model-role split using the new broker and real latency budgets.
2. Keep improving audio toward near-duplex, but do it on top of clear provider roles and measured timing.
3. Start companion memory only after foreground responsiveness is stable enough that memory recall does not degrade UX.
4. Keep avatar abstraction and VRM as a deliberate later phase, not as a distraction from core orchestration quality.

## Target Architecture

### Orchestration (State Machine)

Explicit runtime states:

- `IDLE` (wake word)
- `LISTENING`
- `THINKING`
- `EXECUTING`
- `SPEAKING`

Session context lives in a single `SessionState` object:

- short-term `history` (recent turns)
- `pending_action` (clarification / repair)
- `last_action` (what was executed + last result)

### Routing + Planning

- Router is only a gate: decide `CHAT` vs `ACTION` vs `CLARIFY`.
- ACTION planning is done by the model via tool-calls (OpenAI-compatible tool-call format).
- Executor validates parameters and performs side-effectful work.
- Recovery loop: tool errors or missing parameters -> ask 1 clarification -> next user reply resumes.

### Memory (Layered)

- Working memory: in-memory recent turns + `pending_action` + `last_action`.
- Profile memory: structured user preferences/facts/habits, not vector-first.
- Persona memory: Kage personality constraints, tone adjustments, and user feedback on relationship style.
- Relationship memory: important shared moments, recurring emotional patterns, milestone events.
- Episodic memory: events (vector + metadata + decay/TTL).
- Raw log: immutable transcript log for replay/migration.
- Companion recall policy: chat/emotional support/planning can recall; command/realtime control should default recall off.

### Avatar Layer

- Introduce a unified `AvatarDriver` abstraction.
- `Live2DDriver` remains the current implementation for lightweight facial expression, gaze, lipsync, and limited motions.
- Reserve a `VRMDriver` path for future 3D avatar support when richer body motion becomes necessary.
- Avatar capabilities must not be hard-coded into the orchestration layer.

### Tools (Safety + Speakable Results)

- Tools are schema-driven; arguments are validated.
- `run_cmd` is template/allowlist-based (weather/ip/safe queries). No free-form shell.
- Tool results should be directly user-facing; avoid empty wrappers like "command succeeded".

### Cloud Fallback (Future)

- Handoff only: cloud plans/answers; local tool layer executes.
- Trigger: repeated failures, low confidence, or explicit user request.
- Trace every handoff with a reason.

### Background Execution

- Realtime lane handles wakeword, confirmations, short commands, short replies.
- Background lane handles long searches, organization tasks, multi-step tool plans, and long-running reports.
- Completion strategy: short acknowledgement first, background execution second, brief notification when done.

### Audio Orchestration

- ASR should evolve from turn-based capture to streaming or near-streaming input.
- TTS must become interruptible and preemptible.
- Barge-in is a first-class behavior: user speech interrupts current playback and returns the system to listening.
- Full-duplex is a target capability:
  - short-term goal: near-duplex with low interruption latency
  - long-term goal: simultaneous listen/speak orchestration with conflict policy

## Milestones

### M1: Conversation Loop Productization (Multi-turn stability)

- Introduce `SessionState` and gradually move logic out of `core/server.py` monolithic loop.
- Generalize clarification mechanism:
  - command repair (`open_app` etc)
  - chat followups (moments/apology/reply/howto/tonight)
- Inject short-term history into chat prompts.
- Ensure pending followup is not wrongly consumed when the user switches topic.

Tests required before moving on:

- `python -m py_compile core/server.py core/router.py core/model_provider.py core/tool_executor.py core/tool_registry.py core/agentic_loop.py`
- `python -m unittest tests/test_chat_sanitization.py -v`
- `python -m unittest tests/test_fast_command_routing.py -v`
- `python -m unittest tests/test_tool_call_parsing.py -v`
- `python -m unittest tests/test_tool_call_parsing.py -v`
- `python -m unittest tests/test_tool_call_parsing_multi.py -v`
- `python -m unittest tests/test_tool_call_parsing_multi.py -v`
- `python -m unittest tests/test_search_and_open_normalize.py -v`
- `python -m unittest tests/test_mcp_client_routing.py -v`

### M2: Move Command Understanding to Unified Planner (Controlled)

- Router stays a gate; ACTION always goes through unified model tool-calling.
- Option: model-first auto routing (model chooses tool-call vs chat).
- Add `smart_search` tool (race MCP vs local web search) for resilient web queries.
- MCP config must avoid hard-coded absolute paths (use `{KAGE_ROOT}` placeholders).
- Keep only a small deterministic fast-path for critical safety/latency if needed.
- Tool errors feed back into the planner (repair loop).

Tests required:

- Expand smoke suite with more command variants and ASR slips.
- Ensure `run_cmd` cannot execute free-form shell.

### M3: Interaction + Runtime State Cleanup

- Move pending/confirm/followup logic out of `core/server.py`.
- Explicit dialog state snapshot, trace fields, and frontend-visible runtime state.
- Establish reusable state/event pathways before background execution grows.

### M4: Background Lane (Async tasks)

- Add job schema, queue, worker, event stream, and frontend-visible status.
- Route long tasks into background lane instead of blocking the foreground loop.
- Add completion notification policy (short spoken or visual ping, not long full readouts).

Tests required:

- Background queue + worker regression tests.
- Frontend event compatibility checks.
- Main loop must remain stable with worker enabled.

### M5: Audio Orchestrator (Interruptibility + duplex readiness)

- Add interruptible TTS playback control.
- Add streaming or near-streaming ASR pathway.
- Add barge-in policy:
  - user speech interrupts current TTS
  - system returns to listening without waiting for playback to finish
- Add audio state policy for foreground replies vs background notifications.
- Define the path from current half-duplex to eventual full-duplex operation.
- Treat latency as a release gate, not a side note:
  - runtime ready time
  - first foreground reply latency
  - background kickoff latency
  - interruption latency
  - model smoke generation latency

Tests required:

- Interruption latency regression checks.
- TTS cancel/preempt tests.
- ASR partial/stream smoke tests where available.
- Background completion notification must not deadlock foreground listening.
- Manual local-model smoke runs must record timing data, not just pass/fail.

### M5A: Model Role Split + Latency Budgets

- Formalize broker-driven roles:
  - `routing_model`
  - `realtime_model`
  - `background_model`
  - `fallback_cloud_model`
- Migrate remaining foreground callsites away from a single implicit provider.
- Introduce explicit latency budgets:
  - route/classify
  - short foreground reply
  - background kickoff
  - interruption response
- Keep local-first behavior by default.
- Use real smoke data to decide whether a model belongs in foreground, background, or both.

Tests required:

- Broker profile regression tests.
- Smoke runs with recorded latency metrics for the candidate local foreground model.
- Foreground and background paths must remain stable with broker-enabled initialization.

### M6: Memory System Upgrade (Companion memory)

- Add a memory write policy:
  - extract only stable facts/preferences/events unless explicitly marked as transient
  - upsert/update/delete, do not append contradictions
- Separate Profile vs Persona vs Relationship vs Episodic stores.
- Add recency/importance decay.
- Add relationship event tagging and emotional event tagging.
- Add companion recall policy by route:
  - command/realtime control: off by default
  - companion chat/emotional support/planning: on
- Abstract store interface so Chroma can be swapped (e.g. sqlite-vec/Qdrant).

Tests required:

- Add regression conversation set (50-100 turns) and keep it green.

### M7: Avatar Abstraction + Expression Roadmap

- Introduce an `AvatarDriver` interface so orchestration is independent from renderer type.
- Keep `Live2DDriver` as the default current driver.
- Prototype `VRMDriver` compatibility surface without forcing immediate migration.
- Move expression/motion selection policy into avatar layer, not server orchestration.

Tests required:

- Driver contract tests for expression/state/job-event reactions.
- Frontend integration smoke for current Live2D path.

## Execution Rules

- Implement step-by-step.
- After each step: run the required tests and fix failures before continuing.
- No front-end changes required for the core refactor; UI improvements are optional later.
- Prefer small extraction refactors over large rewrites.
- Any new model/runtime behavior must have a measurable latency story.
- Avoid adding new ad-hoc helpers to `core/server.py` when the behavior can live in a dedicated module.
- When a runtime/model issue is discovered, prefer fixing it at the lowest correct layer:
  - runtime flags before prompt hacks
  - provider parsing before endpoint-specific branching
  - shared sanitizer before duplicated string cleanup

## Status

- [x] Add refactor plan document
- [x] Add `SessionState` (`core/session_state.py`) and migrate short-term state from `core/server.py`
- [x] Remove legacy LFM smoke harness and keep E2E benchmark as canonical smoke path
- [x] Establish dialog state snapshot, background lane skeleton, and job event surface
- [x] Add interruptible audio orchestration first cut and local-model smoke harness
- [x] Validate local `Qwen3.5 9B` runtime with real latency measurements
- [x] Add first-pass model broker role structure
- [ ] Finish broker-driven foreground/background provider split with explicit latency budgets
- [ ] Continue audio orchestrator toward near-duplex voice behavior
- [ ] Add companion memory write policy and store separation
- [ ] Add avatar driver abstraction (`Live2DDriver` -> future `VRMDriver`)
