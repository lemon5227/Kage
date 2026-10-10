# G1 persistent recovery loop engineering package (2026-10-09)

Base: `36f9c1c`, branch `codex/c2-learning-loop`, existing worktree preserved. Implements the approved recovery-only loop; G1 remains awaiting real growth evidence.

## Connection and API

`RecoveryLoop(promoter, mutator_factory, root, bootstrap_candidate, validation_tasks, max_candidates=2, max_evaluations=12)` owns one single-worker durable stream. `mutator_factory(slot_path)` constructs existing `RecoveryMutator`. `run_task(task)` returns JSON-compatible candidate/result/comparison/failure_kind/stop_reason. Existing Promoter/Runner/Journal retain execution, external scoring and artifacts. Continuous dev tasks can trigger learning; reuse/test tasks cannot generate. Validation tasks are explicit, isolated by task IDs, and supplied only to Promoter comparison. `Promoter.compare(..., promotion_split='validation')` is opt-in; default explicit dev split remains supported.

`active.json` atomically stores active plus last_verified_parent. The durable verified ancestry (bootstrap plus at most two generated versions) excludes all disabled digests. A crash after disable persistence cannot reactivate that digest; faults in successive parents reach an eligible ancestor or stop without execution. Unknown active children require the hash-checked durable promoted comparison with matching lineage and frozen validation run IDs before adoption. `recovery_state.json` fixes protocol, stores spent candidate/evaluation counts, disabled versions and task outcomes. Loaders verify bundle hash, skill schema/source hash, recovery compatibility and unchanged frozen skill manifest. Invalid active falls back before evaluating. Runtime recovery errors/tracebacks disable active for the next task; legitimate safe `action: stop` is not a runtime fault. Current task is never automatically replayed.

Reservations precede task execution/proposal/validation: interrupted work remains spent. Task IDs have immutable payload fingerprints; changed payloads are rejected before dispatch. Repeated identical task submissions return saved report, including interrupted markers, without replaying possible writes or regenerating a network-failed candidate. Validation reservation is conservative: all paired slots are reserved even if Journal later serves cached parent results. No parallel-writer support is claimed.

`KageChainProvider(max_tool_actions=12)` adds a dispatch guard cumulative across provider invocations. All tool dispatches count, including failed attempts; calls after the ceiling do not reach handlers. Existing defaults use no extra bound. Cap is in cache identity/metadata and attempted/executed/limit fields appear in chain records. Teacher request JSON is capped at 12000 UTF-8 bytes before any model call; existing 3000 output cap, three proposal/format attempts, BudgetTracker and billing remain in use.

## Engineering evidence

TDD red/green checks covered missing loop API, dispatch bound, validation transport-error rejection, interrupted-report handling, teacher byte ceiling and infrastructure permission classification. Focused command:

`.venv-computer-use/bin/python -m pytest tests/test_recovery_loop.py tests/test_evolution_promotion.py tests/test_evolution_self_modify.py tests/test_evolution_agent_chain.py tests/test_chain_stop_reasons.py -q`

Result: **49 passed**, zero paid/model/desktop experiments. `git diff --check` clean.

The principal integration uses real `KageChainProvider → AgenticLoop → RecoveryPolicy(ProcessSkillRunner) → skill_call → unchanged skill → real workspace output`, existing `EvolutionRunner`/Journal/external evaluator/Promoter and real `RecoveryMutator`, with deterministic responses at the model boundary. A fresh subprocess loads protocol/bootstrap from durable state, automatically consumes active recovery, executes the skill and exposes matching executed module digest. Tests inspect recovery actor, output score, source digest and teacher hidden-field exclusion. Simpler providers exercise failure/cap edges. These are trusted synthetic fixtures, not natural learning evidence.

Other evidence: rejected no-gain candidate preserves parent; two candidate slots and evaluation limit persist across restart; corrupted/incompatible active falls back; broken parent fails closed; partial-run transport errors do not generate/promote; runtime policy error disables without current-task side-effect replay; interrupted and network-failed proposals do not regenerate on resubmission; thirteenth tool write does not occur.

## Limits and next evidence

No live generated code was executed. Production generated source requires the existing Docker runners, explicit cost ceiling and frozen protocol before paid calls. Inline runner does not forcibly interrupt a hung model call; deployment must choose a boundary that enforces deadlines. Single-worker callers must serialize access. Infrastructure classification uses actual runner status, chain model/resource signals and failed observations with explicit service/permission/timeout errors; it is intentionally conservative, not a general failure router.

No real failure-to-autonomous-generation, real new-process task improvement, independent migration or growth cost evidence exists from this package. Parent review/full regression and a separately frozen authorized real experiment remain required; do not mark G1 complete from these tests.

Review corrections: disabled-pointer crash boundary, two-level fallback exhaustion, unverified active rejection, changed-task-ID rejection, actual real-chain PermissionError suppression, baseline runtime fault stop, and validation normalized machine-tool-error rejection are now regression-covered. Failed tool error types/messages are preserved in runner observations and normalized chain tool_errors; no task hint drives classification.

## One bounded G1 support fix: typed argument parse failures (2026-10-10)

Base `6a7018f`. Run1 remains frozen and untouched; no rescore, candidate change, model request or desktop action was performed in this package. The reported trigger was a successful recovered validation output being rejected solely for `InvalidToolArguments: write_file (finish_reason=length)` in its chain model_errors. This string is emitted by the existing local OpenAI-compatible response parser for malformed tool arguments, rather than a transport/permission fault.

A shared helper in existing `agent_provider.py` now treats only strings with the local typed `InvalidToolArguments: ` prefix as capability errors. Unknown/nonstring/API/HTTP/timeout errors, including a mixture with a parse error, still fail closed. RecoveryLoop source classification and Promoter selection use the same rule. KageChainProvider's no-usable-tool guard follows it too: parse-only failure receives external scoring and may trigger bounded recovery generation; infrastructure errors retain the unavailable/crashed behavior. Original error lists stay in traces unchanged. Status, tool-action/resource caps, tool infrastructure failures, recovery-version faults, nonregression and strict improvement remain required.

TDD: first observed failures in the real-chain malformed-argument promotion variant, two narrow-classification rows and parse-only/no-tool source generation. Fixed those branches, then focused command above reports **59 passed**, `git diff --check` clean. The integration feeds truncated tool-argument JSON through the actual OpenAICompatibleProvider parser with urllib substituted only at its network response boundary; RecoveryPolicy/skill/runner/Promoter remain real and a checked child output promotes. Correct outputs accompanied by mixed parse+HTTP or timeout errors still reject. Controlled fixtures remain engineering evidence, not a replacement for versioned live experiment evidence. Parent owns remaining-budget accounting and any subsequent separately frozen authorized run.
