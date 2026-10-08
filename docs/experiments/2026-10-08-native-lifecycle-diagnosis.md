# Bounded native lifecycle diagnosis — 2026-10-08

The two deterministic no-model probes did **not reproduce document disappearance**. Both exact owned document windows remained in TextEdit's AXWindows, with a stable application PID, through every passive sample and final active observation. Both accepted the complete requested text including its terminal newline. Neither exposed a usable Save command after the semantic document-menu press, so neither issued Save; disk still matched the initial fixture at each recorded probe completion. A later read-only disk audit found both files matching the expected edit, without a logged Save action; the actor and cause of that later change are unestablished. This identifies a narrower observable menu/target-availability failure; its underlying cause remains unestablished. It does not explain the earlier controlled2 window disappearance.

The old controlled2 capability result remains **0/2 passed, 2 unknown**, with its documents unchanged. These deterministic probes are diagnostic controls and carry no model capability score.

## Frozen protocol and provenance

Source commits: `6ded6f5` (diagnostic implementation), `3e373d4` (failure-evidence retention), reviewed before execution. Base: `5a0c35a`, branch `codex/c2-learning-loop`. No production runtime files changed.

Actual invocation:

```sh
.venv-computer-use/bin/python -m scripts.experiments.native_lifecycle_diagnosis --output artifacts/native-lifecycle/2026-10-08-dev1
```

The invocation completed with exit 0, meaning the fixed diagnostic sequence finished; it is not a successful Save or capability claim. The fresh artifact directory contains `freeze.json`, `summary.json`, and each context's `timeline.jsonl`, `ax-trace.jsonl`, `runtime-tools.jsonl`, `report.json`, and dedicated `.txt` file. Artifacts are locally retained under the ignored `artifacts/` directory. Frozen manifest records Python/platform, full git SHA, exact initial/expected text, metrics, protocol, invocation template and source hashes.

Exactly two probes, with no retries: initial observation → wait 10 seconds → fill with initial actual refs → wait 10 seconds → fresh observe → wait 10 seconds → fresh observe and semantic document-menu press → Save using actual returned refs, if uniquely available. A separate read-only MacOSAXDriver samples every 2 seconds, at most 21 samples per probe; it does not invalidate the active driver's cached refs. Active primitive guard is 3 attempts. A final bounded fresh observation gathers state without rescue. All errors remain in evidence. Zero model requests, zero cloud calls, no inference or model-service startup.

Owned identity requires both the dedicated filename and exact resolved file URL. Only that document's title/URL/content is logged; other window details are reduced to a scalar count. No app quit, global keystrokes, arbitrary document actions, or speculative production fix occurred.

Source SHA-256:

| File | SHA-256 |
| --- | --- |
| scripts/experiments/native_lifecycle_diagnosis.py | bf64be9b42c1860e39cd6b37016119185133639daeaa3bab28c19a3b1f8cd076 |
| tests/test_native_lifecycle_diagnosis.py | 8e96ab677771c5bf72b75d70dfb95d1bc735df88f62aa9c606f8579a702ab3c8 |
| core/computer_use/native_ax.py | fd41fbd94ed2fa44e431a896f54a372dd9a668fb7bdab85f0250b2e8ab6e2872 |
| core/computer_use/native_model.py | a70633b6de85fe448b061509787df4ab4706ece0c1e12430940e0b825639ee33 |
| core/evolution/agent_provider.py | 3168d474fbeab7fc97aa40ecef9674bbac57b572643a67c0043d05945fc7db23 |

## Actual evidence

| Evidence | Main asyncio | run_sync worker branch |
| --- | --- | --- |
| Thread | MainThread / 8466319744 | ThreadPoolExecutor-0_0 / 6199209984 |
| Elapsed seconds | 32.256297 | 31.620348 |
| Initial observation | 1.089462 s | 0.549629 s |
| AX fill applied | 11.268293 s | 10.748110 s |
| Second-delay observe | 21.342305 s | 20.799015 s |
| Fresh pre-menu observe | 31.408670 s | 30.875491 s |
| Menu press | applied, post-observation error at 31.897305 s | applied, success at 31.241142 s |
| Save stage | zero matching semantic targets; no dispatch | zero matching semantic targets; no dispatch |
| Primitive attempts | 2 | 2 |
| Passive samples | 16 | 16 |
| App PID throughout | 2832 | 2832 |
| AXWindows scalar count | 1 | 2 |
| Owned window membership / main-window identity | true in all samples | true in all samples |
| Final fresh observation | success at 32.255740 s | success at 31.619561 s |
| Save applied / disk matches | false / false | false / false |

The worker's count of 2 includes the preserved first diagnostic document; no unrelated window details were recorded. The worker probe explicitly invokes existing `run_sync` from inside a running asyncio loop, exercising its ThreadPoolExecutor branch. The earlier controlled2 CLI invoked run_sync synchronously without a running loop, so its actual execution context corresponds to the main-thread control. These are descriptive observations from one probe per context, not a statistical comparison.

The main menu result preserved `action_applied=true` together with `AXDriverError: AX attribute discovery failed: -25204` (AXCannotComplete). The adapter's error-path fresh observation retained the owned window and full text but no Save command. The worker menu returned success and applied true, yet likewise exposed no command-s target. Consequently the deterministic selector recorded `RuntimeError: expected one semantic target, found 0` in each Save stage. That is a missing semantic target, not an issued Save action. No stale-identity or permission failure was observed, and window membership evidence does not support external disappearance during these runs.

The exact value pipeline succeeded: expected and observed AX text had 67 characters, 2 actual newline characters, and a terminal newline; SHA-256 `74ae6be3ab959a2757925c71f6df8b4e3dab82df99d78c1cec8aabdb614dbc75`. At their recorded probe completions, both disk files still matched the 50-character initial fixture with 2 newlines and a terminal newline; SHA-256 `bf5d967be773349f5244b397d5df27424e474630676887eb34c15c03134a4dda`. The directly bound fill value confirms that this diagnostic does not repeat the model's earlier missing-terminal-newline output. It is not evidence of weight learning.

Cleanup deliberately preserved both owned documents whose Save/disk state was unverified at probe completion. Trusted close/reopen/readback was gated on a verified applied Save and matching disk, so it was not attempted. The diagnostic neither answered a destructive prompt nor modified old controlled2 documents.

A later read-only filesystem audit at **2026-10-08T03:48:49.452919+00:00** found both retained files matching the 67-character expected text and hash `74ae6be3ab959a2757925c71f6df8b4e3dab82df99d78c1cec8aabdb614dbc75`. Main file mtime was `2026-10-08T03:46:09.009576+00:00`; worker file mtime was `2026-10-08T03:46:40.395854+00:00`. This later observation is separately retained as `postprobe-disk-audit.json`; frozen manifests, stage timelines and probe summaries remain immutable. No desktop actions were performed for this audit. The logs do not establish what caused the later disk changes. TextEdit autosave is a hypothesis, not a verified explanation. Later disk equality does not retroactively establish an issued semantic Save or independent close/reopen verification.

## Limits and next investigation

The evidence supports successful delayed AX fill and continuing owned-window membership, followed by missing Save target availability in both contexts. It does not establish why menu targets were unavailable, why the main post-action attribute request returned AXCannotComplete, or why the earlier controlled2 windows disappeared. AX main-window identity was sampled; application activation/frontmost state was not. A separately reviewed bounded follow-up could add read-only activation/frontmost evidence and command enabled-state diagnostics for the owned main document. No production fix is justified by the current evidence alone.

## Verification

```sh
.venv-computer-use/bin/python -m pytest tests/test_native_lifecycle_diagnosis.py tests/test_native_ax.py tests/test_native_model_chain.py tests/test_native_controlled_cli.py -q
```

Before frozen live execution: **50 passed in 0.58 seconds**. Coverage includes exact-URL ownership, fixed contexts/delays/no-model bounds, provenance/dirty-source refusal, passive error preservation without snapshots, stage/action ordering and fresh refs, and an unavailable first file retaining its report while the second context still executes. The prior production verification of **1036 passed, 4 skipped, 1 xfailed** remains applicable; no production runtime edits required a new full-suite run.
