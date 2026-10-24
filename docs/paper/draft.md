# Interface First, Then Teach, Then Consolidate: Self-Evolution of a 4B Local Computer-Use Agent on a Four-Dollar Teacher Budget

*Draft v0.1, 2026-10-24. Every number is taken from a file under `evidence/` (cited in brackets). Concurrent
work (Terminal-RSI, Harness²) is discussed in §7. Statistical tests are two-sided Fisher exact tests over task
runs unless stated; small samples are marked as directional.*

## Abstract

We study how far a 4-billion-parameter local model (Agents-A1-4B, 4-bit, llama.cpp) can improve itself at
computer-use tasks — file editing, web forms and native macOS applications — when a cloud teacher is available
but capped at US$4 for the whole project (US$1.78 spent). Four findings, each from controlled same-session
comparisons on frozen benchmarks with programmatic checkers:

1. **Learning from demonstrations works in context, on file tasks.** Trajectory memory or verified skills raise
   in-family success from 14/48 to 39–42/48 after a 60-task stream; skills are not better than plain memory.
2. **On web and desktop tasks, small students retrieve guidance but do not follow it.** Correct teacher
   guidance is present in the prompt, yet the student's actions do not change. Before calling this a capability
   gap, we found that several "capability" failures were *interface* failures: making one observation field
   explicit takes a settings task from 1/18 to 17/18 (p < 1e-5); replacing free-text editing with line-based
   tools takes desktop TextEdit tasks from 4/18 to 17/18 (p = 2e-5).
3. **Teacher lessons are adopted only when the student must ground them in the current task.** On unseen desktop
   tasks, lessons in the system prompt change nothing (3/15 vs 3/15); asking the student to first write how each
   lesson applies to this task gives 10/15 (p = 0.025), and a plan-only control separates the two effects.
4. **Consolidating guided successes into LoRA weights removes the need for guidance in-family (30/72 → 65/72)
   but erodes held-out code-writing (15/36 → 1/36).** Across five ablations, gain and forgetting come from the
   *same* training samples; replay (random or gradient-selected) protects only capabilities its data covers, and
   the trained student stops verifying its own output (48/72 → 0).

With the resulting interface and grounded lessons, the student solves 41/45 native macOS tasks through the
Accessibility API (baseline 19/30 on the training tasks, 3/15 on unseen variants). We argue that a
self-improving small agent should, in order: rule out interface causes, teach procedures in a form the student
adopts, and only then consolidate — while monitoring held-out behaviour, not just in-family scores.

## 1. Introduction

Small local models are private, cheap and always available, but weak. A useful personal agent built on one
should improve with use: notice failures, get help at bounded cost, keep what it learns, and not apply it where
it does not belong. Recent self-improvement work either changes the *harness* around a strong model (prompts,
skills, memory; Harness², Meta-Harness) or changes the *weights* of a mid-size model with large compute
(Terminal-RSI, 27B). Both implicitly assume the model follows the guidance it is given.

We test that assumption at the other end of the scale: a 4B model on consumer hardware (Kaggle T4, an Apple M4
laptop), a teacher (DeepSeek) behind a global US$4 ledger, and three task domains with hidden checkers. Our
contribution is less a new method than a set of controlled findings about *where* a small self-improving agent
fails and what fixes each failure:

- an **adoption gap**: retrieval is reliable, adoption is not (§4);
- **interface artefacts** that masquerade as capability gaps, found with one-field ablations (§5);
- **grounded lessons**: a cheap prompting change that makes teacher rules effective on unseen tasks (§5.3);
- **consolidation trade-offs**: a five-version ablation that localises forgetting to the samples that carry the
  gain (§6).

All code, frozen benchmarks, raw runs and per-experiment reports are public; negative results are reported.

## 2. System

**Student and loop.** Agents-A1-4B (Q4_K_M) served by llama.cpp; an agentic loop with at most 5–8 steps and
6–10 model calls per task; tools depend on the domain (workspace file tools; browser observe/act on DOM
snapshots; macOS Accessibility press/fill/menu). The checker never reaches the agent.

**Learning loop.** After a failure the teacher solves the task from a clean state (cached per task instance);
a verified demonstration becomes trajectory memory and/or a parameterised, sandbox-verified skill. A TF-IDF
relevance gate shows learned items only for tasks close to where they were verified; when nothing passes, the
request is byte-identical to the raw student's.

**Lessons.** After a failure the teacher compares the student's actions with the checker's finding and writes
one or two general imperative rules without task-specific values; rules are gated like memory.

**Consolidation loop (R).** Following RSR-style re-execution: the student re-attempts practice variants *with*
guidance (demonstration + rules), only verified successes are kept, the guidance is removed, and the student is
fine-tuned with LoRA (rank 16 on attention-output and MLP projections, response-only loss) and evaluated
without guidance.

**Budget.** Every cloud call reserves against a global ledger before it is sent (US$4 total; US$1.78 spent over
all experiments, including void runs) [ledger, `core/evolution/teacher_budget.py`].

## 3. Benchmarks

- **Kage-Stream (files)**: 4 learned families, 2 held-out families (text normalisation, config migration) and 3
  read-only negative families; procedurally generated, frozen by hash, calibrated so the raw student passes
  10–50% [`eval/stream_v1`].
- **Kage-Web**: local fixtures for invoices (hidden rows), notification settings, hotel catalogue (ratings behind
  "Details"), a two-step profile form (held-out) and read-only lookups [`eval/stream_web_v1`].
- **Desktop-v1 (macOS)**: Calculator (4 + 2 unseen chain variants), TextEdit (3 + 3 unseen variants, dedicated
  files) and read-only System Settings (3), driven only through the Accessibility API — no keyboard events, no
  coordinates; checkers read the app or the disk themselves [`eval/desktop_v1`].

**Evaluation discipline.** GPU inference is not bit-reproducible even at temperature 0: four identical raw-student
evaluations gave 7–13/24 in-family [`docs/report/kage-tech-report.md` §5.4]. We therefore compare arms in the
same session with ≥ 3 runs and treat differences inside that range as noise.

## 4. Learning in context, and the adoption gap

**Files (E-1).** After a 60-task stream, trajectory memory reaches 42/48 and a skill library 39/48 in-family
against 14/48 for the raw student and 12/48 for a budget-matched retry baseline (skills vs raw: p = 6e-8;
skills vs memory: 5 vs 8 discordant pairs, p = 0.58) for US$0.07–0.20 per arm. Learned knowledge distracted the
student on held-out families until the relevance gate restored them to the raw student's range with zero
misuse [tech report §5].

**Web (C2, C3).** The same memory barely helps on web tasks (learned arms 20/72 vs raw 12/54, p = 0.54). Per-task
inspection shows retrieval is not the problem: every evaluation prompt contained the relevant demonstration, yet
the student followed it in 1–2 of 6 invoice tasks [`evidence/reports/c2`]. Teacher-written rules fix a
*missing-step* failure (invoices: 0/24 → 14/24 with rules) [`evidence/reports/c3`]; guided re-execution also
helps only where a step or idiom is missing (guided 71/112 vs unguided 34/112, p = 1e-6, but settings 6 vs 6 and
hotels 7 vs 8) [`evidence/reports/r2`].

## 5. Interface first

### 5.1 Web: one field (C4)

Settings tasks resisted demonstrations, rules and consolidation, and we had cited them as "knows but cannot do".
Our compact observation omitted `checked: false` for unchecked boxes. With the raw student and no guidance
[`evidence/reports/c4/analysis.md`]:

| Interface | Settings (/18) | Total (/90) | Max input tokens |
|---|---|---|---|
| v1 (unchecked boxes have no `checked` key) | 1 | 29 | 7,545 |
| v2 (explicit `checked: true/false`) | 14 | 41 | 7,406 |
| v2 + context packing + state table | 17 | 39 | 3,946 |

A second round [`evidence/reports/c4/round2.md`] re-baselined the benchmark on v2 (41/90, settings 18/18). A
pre-save checker — Clef extracts per-item goals (48/48 correct), a program compares them with the page — never
fired (0 of 59 checks): once the interface was fixed there was nothing left for it to catch. Hotel failures,
which we first attributed to context packing, are procedural: the student never opens "Details" to compare
ratings, with or without packing (7 vs 4/18, p = 0.47).

### 5.2 Desktop: line-based editing (G0)

Driving TextEdit through the Accessibility API with a `fill(text)` tool, the student fails 14 of 18 edits, all
on line breaks: it drops the final newline or writes a literal `\n`. Teacher rules plus planning do not help
(4/12) — the student *states* that each line ends with a newline and still emits the wrong JSON string. Tools
that remove the need to encode control characters solve it [`evidence/reports/g0/analysis.md` §5]:

| TextEdit tools | Fix typo (/6) | Append line (/6) | Write lines (/6) | Total |
|---|---|---|---|---|
| `fill` (whole text) | 0 | 3 | 1 | 4/18 |
| + `replace_text`, `append_text` | 6 | 2 | 0 | 8/18 |
| `replace_text` + `append_lines` / `set_lines` | 6 | 5 | 6 | **17/18** |

Two smaller interface slips on the desktop (the student passed a control's id or the whole observation line as
its reference) were fixed by accepting both.

### 5.3 Grounded lessons (G0)

Calculator chain tasks fail on operator precedence: the student presses `15 + 27 × 3 =` and gets 96. The teacher
wrote one rule from the failure ("when an expression mixes addition and multiplication, press Equals after the
addition…", cost US$0.0005 for all four rules). On five unseen variants (three runs each):

| Arm | Calculator chains (/6) | TextEdit (/9) | Total (/15) |
|---|---|---|---|
| no lessons | 1 | 2 | 3 |
| lessons in the system prompt | 1 | 2 | **3** |
| "write a plan first", no lessons | 4 | 2 | 6 |
| lessons next to the task + "say how each lesson applies, then act" | 5 | 5 | **10** (p = 0.025) |

In the system prompt the rules are ignored: the student still presses `9 + 6 × 4 =`. Requiring it to ground each
rule in the current task (an exact button order) makes it adopt them, and it generalises the addition rule to a
subtraction/division variant ("press Equals to get 36, then divide"). The plan-only control shows that planning
alone explains most of the Calculator gain, while the TextEdit gain needs the rule content.

**Final desktop configuration** (line-based tools, interface fixes, grounded lessons; 15 tasks × 3 runs):
**41/45** — training tasks 29/30 (baseline 19/30, p = 0.003), unseen variants 12/15 (3/15, p = 0.003); Calculator
17/18, TextEdit 15/18, System Settings (read-only) 9/9 [`evidence/reports/g0/analysis.md` §6].

## 6. Consolidation: gain and forgetting come from the same samples

R2 collected 1,900 guided successes (guidance stripped); R3 trains a LoRA adapter and evaluates without guidance
(file sets: 24 in-family + 12 held-out per run, 3 runs; web: 18 learned per run) [`evidence/reports/r3*`]:

| Version | Training change | Files in-family (/72) | Held-out (/36) | Web learned (/54) |
|---|---|---|---|---|
| raw student | — | 30 | 15 (pooled 27/60) | 10 |
| R3 | guided successes | 64 (p = 2.6e-9) | **1** | 21 |
| R3b | drop reasoning-free targets + random replay | 34 | **15** | 31 |
| R3c | drop + gradient-selected (LESS) replay | 34 | 2 | 22 |
| R3d | teacher rationales for reasoning-free targets + LESS replay | 62 | 6 | 20 |
| R3e | rationales + random replay | **65** | **1** | 22 |

General-ability check (30 questions): 27–28/30 for every version. Under the round-2 web interface, R3e solves
7/18 invoices where the raw student solves 0/54 (p = 2e-5): consolidated knowledge survives an interface change.

What the five versions show:

- **Gain and forgetting move together.** Held-out success collapses exactly when the ~300 file-solution steps
  (`write_file` targets, mostly without reasoning in the raw data) are trained (R3, R3d, R3e) and is preserved
  only when they are removed (R3b) — which also removes the in-family gain. Replay type and the presence of
  reasoning do not change this.
- **Replay protects only what it covers.** Our replay data (desktop-action text from AgentNet, MCP tool calls
  from Toucan) contains no code writing; neither random nor gradient-selected replay protected held-out *code*
  tasks. Gradient-influence selection (LESS) picks data aligned with the target — the opposite of what
  anti-forgetting replay needs.
- **The mechanism is code quality plus a lost habit.** On held-out tasks the trained student writes plausible
  but wrong code (e.g. `encode("ascii")` that raises on non-ASCII input) and no longer reads its output back:
  read-back verification after writing drops from 48/72 runs (raw) to 0 for every trained version, because
  training trajectories end as soon as the checker passes. "Not writing reasoning", our first explanation,
  was a symptom: R3d/R3e reason before every call and still forget.

Implications we did not test (compute ended with this study): self-distilled replay of the raw student's own
correct code on other tasks, keeping write-then-verify steps in training trajectories, and gating the adapter
by task family at deployment.

## 7. Related and concurrent work

Skill libraries (Voyager), experience memory and rule extraction (ACE, SkillRL), harness self-improvement
(Meta-Harness; Harness², concurrent), weight-level self-improvement (STaR, context distillation, expert
iteration; Terminal-RSI, concurrent: runbook-guided re-execution, SFT and RL at 27B). Our consolidation loop
borrows RSR's guided re-execution explicitly; the in-context learning and adoption findings predate our reading
of it (worklog timestamps). ARTEMIS (Android automation) prompted the interface ablation. See
`docs/report/related-work.md`.

## 8. Limitations

Small samples (18–90 runs per arm; several p-values are directional); one student model; procedurally generated
tasks with templated instructions (the TF-IDF gate relies on this); desktop tasks are few and partly read-only
for safety; the pre-save checker's goals were extracted once and cached; consolidation used a single LoRA
configuration and no RL. Desktop runs were on one Mac with one llama-server; GPU and CPU non-determinism means
single-run comparisons are unreliable, which is why every comparison here is same-session and replicated.

## 9. Conclusion

For a small local agent, "it retrieved the right guidance and still failed" is common, and the cause is often
not capability. In order: make the observation and tools state what the student needs without inference or
escaping (one field, one tool), make it ground teacher rules in the current task before acting, and only then
consolidate — measuring held-out behaviour, because the samples that teach a family are the ones that overwrite
general skills. On a US$4 budget this took a 4B model to 41/45 on real macOS applications.

---
*Evidence index*: E-1/E-2 `evidence/reports/e1*`, `e2*`; C2 `c2/`; C3 `c3/`; R2 `r2/`; R3–R3e `r3/`, `r3b/`–`r3e/`;
C4 `c4/analysis.md`, `c4/round2.md`; G0 `g0/analysis.md`; raw Kaggle runs `evidence/kaggle/v*-results.tar.gz`.
