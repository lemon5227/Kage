---
title: 'Interface, Instruction Adoption, and Forgetting: A Diagnostic Case Study of a 4B Computer-Use Agent'
author: Wenbo Yan
date: 'October 2026 · v0.4-deepseek'
---

## Abstract

Small computer-use agents fail for reasons that are easy to misattribute. We report a diagnostic case study of a 4B agent on file editing, browser fixtures, and native macOS tasks, probing each failure class with a separate intervention. First, interface: making unchecked checkbox state explicit raised browser-settings success from 1/18 to 14/18 executions on six tasks (all six improved; task-level sign-flip $p=0.031$), and replacing whole-text editing with line-oriented tools raised TextEdit success from 4/18 to 17/18 in a sequential development comparison. Second, presentation: identical teacher rules had no measurable effect in the system prompt (3/15) but reached 10/15 beside the task with an explicit application plan, on five tasks (task-level $p=0.25$; a pilot). Third, consolidation: a rank-16 LoRA adapter trained on 1,900 action-level examples from 151 tasks raised file success on new instances of the trained families from 30/72 to 64/72, while success on two untrained families fell from 15/36 to 1/36; the variant that preserved held-out success gave up most of the in-family gain, and restoring reasoning text did not preserve retention. A final composite desktop configuration scored 41/45, but its gains are interface-dominated and the lesson component showed no measurable TextEdit benefit. These are development-set results with one student and one seed. The contribution is a diagnostic ordering—test the interface, then the presentation of guidance, then retention—not an autonomous self-improvement algorithm.

## 1. Introduction

A personal agent built around a small local model should benefit from experience without becoming less reliable on unfamiliar requests. Failures, however, admit several explanations. The model may lack a procedure, fail to use a retrieved procedure, misinterpret the observation, or be unable to express a correct action through the available tool. Each explanation suggests a different repair: collect demonstrations, change how guidance is presented, change the observation or action space, or change the weights. Choosing the wrong layer wastes data, teacher calls, and training cycles, and it can produce a confident but incorrect claim that the model "cannot" do a task.

We study this attribution problem in Kage, a single-user agent whose student edits files, operates local browser fixtures, and interacts with macOS applications through the Accessibility API. The experiments combine automated teacher calls, frozen benchmarks with programmatic checkers, and a consolidation stage that turns verified guided rollouts into LoRA training data. The study is deliberately narrow: one 4B student, one training seed, procedural task generators, and development-set evaluations. Within those boundaries, three interventions separate failure classes that look alike in traces.

Our claims are:

- **C1 (interface).** Failures that persisted through demonstrations, rules, and consolidation can disappear when the observation or action representation changes. Making unchecked checkbox state explicit moved browser settings from 1/18 to 14/18 executions (six of six tasks improved; task-level $p=0.031$). Line-oriented editing tools moved TextEdit from 4/18 to 17/18 over a sequential development comparison.
- **C2 (adoption).** Retrieving guidance is not the same as using it. Relevant demonstrations and rules can be present and still not change behavior. In a five-task desktop pilot, the same four rules made no measurable difference in the system prompt (3/15) but reached 10/15 when placed beside the task with an explicit application plan. This contrast mixes placement, planning, and content; we treat it as a pilot, and we reconcile it with an earlier result in which relevance-gated system-prompt rules did help invoice tasks.
- **C3 (forgetting).** Supervised fine-tuning on the student's own verified successes is not a free lunch. A rank-16 adapter raised in-family file success from 30/72 to 64/72 while held-out-family success fell from 15/36 to 1/36. Follow-up variants show that neither removing reasoning-free targets, adding replay, nor restoring teacher-written rationales recovers both, but they do not identify a single mechanism.
- **C4 (diagnostic ordering).** The practical contribution is an ordering rather than a new algorithm: rule out observation/action-interface causes, then the presentation and adoption of guidance, then retention across families, before attributing a failure to model capability. Figure 3 summarizes the ordering and the evidence for each layer.

We do **not** claim autonomous recursive self-improvement, a general advantage of 4B models, or a causal decomposition of the final desktop configuration. The consolidation results are conditional on one trained adapter and one random seed; the desktop results are development-set results. Section 8 states the boundaries in detail.

![Diagnostic ordering used in this paper: interface, presentation/adoption, retention, then capability. Each box lists the intervention and its principal evidence.](figures/fig1_diagnostic_order.pdf){#fig:order width=92%}

## 2. System and evidence boundaries

**Student.** The student is Agents-A1-4B in Q4_K_M format (GGUF SHA-256 `d93c393a…f062`, frozen model revision `d92b02e…`), served by llama.cpp 0.4.1 (build 10964) with a 16k context. File and browser evaluations ran on Kaggle T4 GPUs; desktop evaluations ran on an Apple M4 Mac; consolidation training ran on a Colab A100 (40 GB). Only one student model contributes results; a partial second-student desktop replication was attempted but invalidated and is not used as evidence (Section 8).

**Execution budgets.** The file benchmark permits five loop steps, six local model requests, twelve tool dispatches, and 150 s per attempt. The browser protocol uses eight steps and ten model requests. Desktop tasks have task-specific limits of six to twenty steps in the Desktop-v1 manifest, and the desktop loop issues one model request per step. These are different protocols, not a common compute budget. File and desktop runs use temperature 0.7; no result here depends on temperature-zero determinism.

**Learning and guidance.** After a failed file or browser attempt, a teacher demonstration can be stored as trajectory memory or converted into a parameterized skill verified in a sandbox. A TF-IDF gate selects items by instruction similarity; when nothing passes, the request is byte-identical to the raw student's. A separate mechanism asks a teacher for one or two general rules, injected into the system prompt or beside the task depending on condition.

**Checker and teacher boundaries.** Programmatic checkers evaluate outcomes outside the student's prompt. In the file and browser experiments the teacher sees the checker's pass/fail verdict but not hidden expected values or test cases. The desktop G0 teacher is different: its prompts include the training task's expected result and the observed checker finding. Thus G0 uses privileged training feedback to a teacher, not merely a binary reward; the student receives general rules rather than the test answer. Student-unseen tasks may nevertheless be developer-seen: inspecting evaluation failures informed interface and prompt revisions, and the five desktop variants were reused during development.

**Consolidation.** R2 collected guided rollouts on file and browser tasks. Successful rollouts were converted to action-level supervised examples after removing the guidance, split by task into training and validation sets, and used for LoRA training (rank 16 on attention-output and MLP projections, response-only loss, two epochs, learning rate $10^{-4}$, maximum sequence length 8,192, seed 0). Adapters were evaluated without retrieved guidance or teacher assistance.

**Cost scope.** The cloud-teacher ledger is capped at US$4.00. The work log records US$1.83 of usage; earlier snapshots report US$1.12 and US$1.78, so the exact total is not independently reconciled. The five R3-series training configurations total about 5.8 hours of wall time. GPU hours, student inference, hardware, and developer effort are excluded.

**Units and sessions.** An **execution** is one attempt at one task. A **task** is one independent problem instance. Repeated executions of a task are not independent samples, and a repeated execution is not a new task. Unless stated otherwise, counts are executions and tests are at the task level. Training seed is fixed at 0 for all adapters; the three evaluation repeats do not replicate training runs. R3 (the first adapter) and the base model were evaluated in the same session; R3b–R3e were evaluated in later sessions with a single-run base anchor each, so cross-version comparisons are descriptive.

## 3. Benchmarks and analysis protocol

Kage-Stream contains four learned file families (subset selection, interval merge, log aggregation, CSV transformation), two families excluded from consolidation training (text normalization and configuration migration), and three read-only negative families. The evaluation set contains 24 in-family tasks, 12 held-out-family tasks, and 12 negative tasks; learning streams use 60 tasks in two orders. Kage-Web contains invoice, notification-settings, and hotel-selection fixtures (18 learned tasks), a held-out profile-form family (6 tasks), and read-only lookups (6 tasks). Desktop-v1 contains fifteen tasks: six Calculator, six TextEdit, and three read-only System Settings tasks. The evaluation units are as follows.

Evaluation units are: E-1/E-2, 24 in-family + 12 held-out + 12 negative file tasks per evaluation, with two learning streams and a reused raw baseline; C4, 30 browser tasks (six per family), three repeats per arm in the same session; G0, 10 training + 5 variant desktop tasks, three repeats each; R3, 24 learned-file + 12 held-out-file + 18 learned-web tasks, three repeats per adapter from one training seed; D7, 30 authored utterances per set, one prediction each.

**In-family versus held-out.** "In-family" denotes new task instances generated from the same procedural generators used for practice, with different seeds and parameters—not the same instances and not arbitrary new tasks. The two held-out file families use different generators, so their scores measure cross-template transfer. All in-family gains reported here are same-generator generalization.

**Statistical protocol.** We analyze at the task level. Repeated executions are averaged within task, and between-condition contrasts are paired within task. For task sets of up to 16 tasks we enumerate all sign assignments for the mean within-task difference and report the exact two-sided sign-flip probability; for 24-task sets we use 200,000 random sign assignments. We also report a 95% interval from bootstrapping tasks (10,000 resamples) as a descriptive interval, not a population claim. We do not report execution-level Fisher tests. The minimum attainable two-sided sign-flip value is $2/2^k$ for $k$ tasks; with 5–6 tasks, perfect consistency reaches only $p=0.031$–$0.0625$, and a majority of ties can leave the attainable minimum at $p=0.25$. Absence of significance is not evidence of equivalence. All consolidation comparisons are conditional on a single adapter and seed: inference is over tasks and executions, not over training runs.

**Development-set status.** Task manifests were frozen before the main runs, but failures on the held-out families and on the desktop variants were examined to design later variants and prompts. The reported scores are therefore development-set scores, not an untouched post-selection confirmation. No new confirmation set was collected.

## 4. Interface: observation and action representation

### 4.1 Browser settings: one observation field

The compact browser observation omitted the `checked` key for unchecked boxes. Settings tasks had resisted demonstrations, rules, and consolidation; we had described them as a case where the student "knows but cannot do". In C4 session 1, the raw student ran the frozen web evaluation set under four interfaces with no learned guidance, three times per arm (Table 1).

*Table 1. C4 browser interface ablation, session 1 (six settings tasks, three repeats).*

| Interface | Settings (/18) | All 30 tasks (/90) | Change |
|---|---:|---:|---|
| V1: unchecked state implicit | 1 | 29 | current protocol |
| V2: explicit `checked: true/false` | 14 | 41 | one field |
| V2 + context packing | 14 | 36 | packing only |
| V2 + packing + state table | 17 | 39 | three changes |

Every one of the six settings tasks improved from V1 to V2: the mean within-task difference is +0.72 (95% task-bootstrap interval 0.50–0.94), with six of six tasks positive, and the exact task-level sign-flip value is $p=0.031$, the smallest value attainable with six tasks. Packing and the state table do not add a measurable task-level difference over V2 (mean +0.17, interval −0.11–0.44, $p=0.50$); the 17/18 figure is a composite, not a single-field estimate. In C4 session 2, rerunning the V2-plus-packing-plus-state-table configuration produced 18/18 settings and 41/90 overall, consistent with the first session's 17/18 and 39/90. A pre-save checker using decision-model goal extraction made no intervention in 59 checks; with the settings tasks already at ceiling, this benchmark provides no evidence of an incremental completion benefit.

Hotel failures persisted and are not explained by the interface change. Trace inspection showed that the student usually selected a hotel without opening its rating details, with or without context packing. We had first blamed packing; the corrected reading is procedural. This is a hypothesis grounded in traces, not a proven fix.

### 4.2 Desktop TextEdit: action representation

With a whole-text `fill` action, TextEdit failures commonly involved a missing trailing newline or a literal `\n` in the JSON string. The program, not the model, should construct line breaks. Table 2 shows the sequential development comparison on six TextEdit tasks (three training, three variants), three repeats each.

*Table 2. TextEdit tool interface, sequential development comparison (six tasks × three repeats).*

| Tool interface | Typo fixes (/6) | Appends (/6) | Writes (/6) | Total (/18) |
|:-------------------------|------:|------:|------:|------:|
| Whole-text `fill` (v2) | 0 | 3 | 1 | 4 |
| Add `replace_text`, `append_text` (v3) | 6 | 2 | 0 | 8 |
| Add line-list actions (v4) | 6 | 5 | 6 | 17 |
| Final configuration: v4 + rules + plan | 5 | 4 | 6 | 15 |

The v4 interface improves all six tasks over the whole-text baseline (mean +0.72, interval 0.50–0.94, exact $p=0.031$), an improvement driven by removing the need to encode control characters. The final configuration, which adds the four teacher rules and a planning instruction at the same interface, scores 15/18: two tasks are one execution lower, four are unchanged, and none improves. The difference is within run variation, but the data give no evidence that the lesson component helps TextEdit once the interface is fixed. The append and write instructions explicitly require final newlines, so this requirement is not solely a hidden checker condition.

### 4.3 The final desktop configuration

Combining the line-oriented tools, the reference-handling fixes, and the task-adjacent lessons with planning yielded 41/45 executions on the fifteen desktop tasks: 29/30 on the ten training tasks and 12/15 on the five variants. Family totals were Calculator 17/18, TextEdit 15/18, and read-only System Settings 9/9.

This total is a configuration result, not a decomposition. The earlier baselines were 19/30 on the training tasks under interface v1 without rules, and 3/15 on the variants under interface v2 without rules; both are under different interfaces and the variants are a different task set. Existing arms allow a partial attribution on the ten training tasks (Table 3): TextEdit gains 6/9 from line-oriented tools (the v4 arm without lessons reaches the same 8/9 as the final configuration), System Settings gains 2/9 from reference-handling fixes, and Calculator gains 2/12, consistent with the lesson/planning intervention. The final configuration is therefore interface-dominated. A full fifteen-task arm with v4 and no lessons was not run; it is the single most informative missing control, and we report the configuration as a composite rather than as evidence that interface, guidance, and consolidation compose additively.

*Table 3. Partial attribution of the final desktop configuration on the ten training tasks (three repeats).*

| Component | Baseline v1, no rules | Final (v4 + rules + plan) | Attributed to |
|:-------------------|------:|------:|:-----------------------------|
| TextEdit (3 tasks) | 2/9 | 8/9 | v4 interface (v4-without-lessons arm: 8/9) |
| System Settings (3 tasks) | 7/9 | 9/9 | reference-handling interface fixes |
| Calculator (4 tasks) | 10/12 | 12/12 | lessons + planning (consistent with Table 4) |
| **Total** | **19/30** | **29/30** | composite; interface +8, guidance +2 |

![Three interventions at different layers, same student. (a) Browser settings per task under implicit and explicit checkbox state (six tasks, three repeats). (b) TextEdit tool-interface ladder. (c) Desktop lesson-presentation pilot on five variants (three repeats).](figures/fig2_interventions.pdf){#fig:interventions width=88%}

## 5. Presentation-dependent adoption

### 5.1 Demonstrations help in-family

In E-1, after a 60-task learning stream, trajectory memory achieved 42/48 in-family executions and a skill library 39/48, compared with 14/48 for the raw baseline and 12/48 for budget-matched retries. The learning arms' denominator combines two stream evaluations of the same 24 tasks; the raw baseline is one evaluation duplicated for this comparison. At the task level, memory improves over the raw student by 0.58 on average (interval 0.35–0.77; exact $p<0.001$), and the skill library by 0.52 (interval 0.33–0.71; $p<0.001$); memory and skills are not measurably different (+0.06, interval −0.13–0.25, $p=0.67$). On the twelve held-out tasks, memory does not improve over the raw student (mean −0.17, interval −0.50–0.17, $p=0.50$). Later raw evaluations of the same 24 tasks ranged from 6 to 13 successes; against the most favorable of those replicates (13/24), the memory result (21/24 per stream) remains large. Demonstrations therefore teach same-generator procedures, not cross-family transfer.

### 5.2 Retrieval without enactment

On browser tasks, retrieved guidance was not consistently enacted. In C2, the relevant demonstration was present in the evaluation prompt, yet the student solved only a minority of invoice tasks; the successes concentrated on the same two tasks. In C3, teacher-written procedural rules were injected through the student's system prompt (TF-IDF gated, up to two rules). Invoice tasks rose from 0/24 to 14/24 executions, a missing-step failure repaired by a rule. The same delivery did not help settings tasks, whose failures required tracking several toggle states, and hotel tasks remained procedural.

This creates an apparent conflict with the desktop pilot below, where system-prompt rules did nothing. The difference is not delivery alone: C3's rules addressed a missing step and were relevance-gated into the prompt, whereas the desktop rules concerned action representation (line breaks) and Calculator operator order. We do not isolate which factor—content type, retrieval, the number of rules, or planning—is responsible.

### 5.3 The desktop lesson pilot

Calculator chain tasks exposed a missing procedure: entering addition followed by multiplication without first resolving the addition gives the wrong grouping. A teacher wrote one rule about pressing Equals after the addition, plus three rules about text preservation and newlines. On five task variants not used to generate the rules, four prompting conditions were compared under interface v2 (Table 4).

*Table 4. Desktop lesson pilot: five variants × three repeats.*

| Prompt condition | Calculator (/6) | TextEdit (/9) | Total (/15) |
|---|---:|---:|---:|
| No lessons | 1 | 2 | 3 |
| Lessons in system prompt | 1 | 2 | 3 |
| Plan first, no lessons | 4 | 2 | 6 |
| Lessons beside task; explain application, then act | 5 | 5 | 10 |

The combined condition is numerically strongest, and planning alone accounts for much of the Calculator improvement. The condition changes lesson placement and adds an explicit application step; it does not isolate rule content, location, or extra deliberation. At the task level, the mean difference from no lessons is +0.47 (interval 0.13–0.80), but with only five tasks and two zero differences the exact sign-flip value is $p=0.25$; the plan-only contrast is +0.20 ($p=0.50$), and the system-prompt contrast is exactly zero ($p=1$). This is a pilot, not an established effect. It does show that the same rules can produce no measurable change in one presentation and a large descriptive change in another, which is the adoption phenomenon we set out to diagnose.

## 6. Consolidation and retention

### 6.1 Data and training units

The R2 archive contains 1,900 action-level examples drawn from 151 unique task IDs. Each row pairs a conversation context with a target response; one successful rollout can contribute several rows. The four collection reports record 704 attempts and 472 successes before filtering; the retained archive contains 446 distinct task/source/attempt combinations. These are different quantities: 1,900 is neither the number of tasks nor the number of successful trajectories. R3 splits by task into 1,677 training and 223 validation examples.

Five adapters were trained (Table 5). All use two epochs, learning rate $10^{-4}$, rank 16, maximum sequence length 8,192, and seed 0; replay is external data from AgentNet desktop-action steps (800 examples) and Toucan MCP tool calls (600 examples), neither of which contains code-writing steps. R3b–R3e were evaluated in later sessions with a single-run base anchor each; R3 and its base were evaluated in the same session with three runs each.

The five adapters differ in data and replay (Table 5). R3 trained on 1,677 examples for 420 steps. R3b trained on 2,781 examples with 1,400 random replay examples for 696 steps; R3c on 2,266 with 879 LESS-selected replay examples for 567 steps; R3d on 2,736 with 879 replay examples for 684 steps; R3e on 3,251 with 1,400 replay examples for 813 steps. R3 and its base were evaluated together with three runs each; R3b–R3e were evaluated in later sessions with the single-run anchors shown in Table 5. R3e's saved configuration has 3,257 training rows, six of which exceed the 8,192-token limit, leaving 3,251 trained examples; the earlier prose figure of 3,257 counts the pre-filter rows.

*Table 5. Consolidation results. Each file cell aggregates 24 or 12 fixed tasks over three inference runs; learned web aggregates 18 tasks over three runs.*

| Version | Main change | Same-session anchor (in / held) | Learned files (/72) | Held-out (/36) | Learned web (/54) | Negative misuse |
|:------|:-------------------------|:--------------------|------:|------:|------:|------:|
| Base (v26) | no adapter | — | 30 | 15 | 10 | 0/36 |
| R3 | guided-success targets | 9–12/24 · 5/12 (three runs) | 64 | 1 | 21 | 2/36 |
| R3b | filter; random replay | 10/24 · 7/12 | 34 | 15 | 31 | 0/36 |
| R3c | filter; LESS replay | 11/24 · 7/12 | 34 | 2 | 22 | 0/36 |
| R3d | rationales; LESS replay | 6/24 · 5/12 | 62 | 6 | 20 | 0/36 |
| R3e | rationales; random replay | 11/24 · 7/12 | 65 | 1 | 22 | 0/36 |

In the same-session R3 comparison, in-family file gains appear in every repeat (22, 22, 20 out of 24 versus 9, 12, 9 for the base) and the held-out decline appears in every repeat (1, 0, 0 out of 12 versus 5, 5, 5). Task-level tests on the 24 learned tasks give a mean gain of +0.47 (interval 0.28–0.67, $p<0.001$); on the 12 held-out tasks a mean loss of −0.39 (interval −0.67 to −0.11, $p=0.047$). The web learned families gain +0.20 (interval 0.00–0.43, $p=0.11$), not significant at the task level. R3e, evaluated against its own single-run anchor, gains +0.44 in-family (interval 0.25–0.64, $p<0.001$) and loses −0.56 held-out (interval −0.83 to −0.25, $p=0.016$). The direction is consistent across repeats; the held-out task-level test is nevertheless based on 12 tasks and is not a precise estimate.

R3 also modified a read-only file in 2 of 36 negative executions (the base: 0/36); later variants had none. Under the second-round browser interface, R3e achieved 7/18 invoice executions versus 0/18 for the same-interface raw arm, but the overall browser total was 47/90 versus 41/90 (execution-level $p=0.46$), with the invoice gain concentrated in three of six tasks (task-level $p=0.25$). This suggests that some invoice behavior survives an interface change; it does not establish broad interface-invariant transfer. A 30-question general-ability check scored 27–28 across variants, too small and narrow to establish general capability preservation.

### 6.3 What the variants do not identify

Filtering reasoning-free targets disproportionately removed file solutions: the report identifies 202 reasoning-free `write_file` targets and 101 with reasoning in the learned families (102 including one negative-family row). It did not remove every file-writing example. Restoring the filtered targets with teacher-written rationales recovered much of the in-family gain, while held-out performance remained low. This rules out the simple account that restoring visible reasoning text is sufficient to prevent degradation in these configurations.

It does not prove that gain and forgetting have a single shared cause. R3b and R3c both filter reasoning-free targets and both reach 34/72 learned-file executions, yet their held-out results differ sharply, 15/36 versus 2/36; however, they also differ in replay algorithm, replay size (1,400 versus 879), source mixture, and optimizer steps (696 versus 567). The contrast therefore shows that retention is not a single-variable function of filtering, not that replay selection is the cause. R3b's held-out 15/36 is an improvement over R3 (1/36) but remains below the untrained anchor measured in its own session (7/12 approximately 21/36); it matches the v26 base (15/36) but retains only a small share of the in-family gain (34/72 versus 64/72 for R3).

Trace analyses report less post-write reading and plausible but incorrect code after training. Reduced verification is a candidate mechanism, not an established cause: no intervention forced read-back while holding the model and task constant, and R3b retained more held-out success despite reduced verification behavior. Testing this explanation requires controlled verification interventions and training data that preserve successful checking trajectories. Testing replay explanations requires matched amounts, source composition, training exposure, and multiple training seeds. None of those confirmation experiments is claimed here.

![Per-task success rates for the base model (open) and the R3 adapter (filled), averaged over three runs. Left: 24 in-family tasks. Right: 12 held-out-family tasks. Nearly every in-family task improves; the held-out panel moves almost entirely in the opposite direction.](figures/fig3_r3_per_task.pdf){#fig:r3 width=92%}

## 7. Related work

**Interfaces.** SWE-agent studies agent-computer interface design and shows that tools adapted to language-model agents improve software-engineering performance (Yang et al., 2024). Our narrower contribution is a small-model diagnostic study in which explicit checkbox state and line-oriented actions address observed failure modes; we do not claim interface design as a new principle. The initial interface ablation was prompted by the ARTEMIS Android automation project.

**Experience and consolidation.** Agent Workflow Memory induces and retrieves reusable procedures (Wang et al., 2025). Context distillation transfers information supplied in context into model behavior (Snell et al., 2022). Kage's guided re-execution draws on the recursive self-rewrite component of Terminal-RSI (Yang et al., 2026), but not its reinforcement-learning stages or a second recursive training round. Harness² studies recursive harness adaptation (Xu et al., 2026), changing the harness around a model rather than its weights. Our rationalization step is closer to STaR's rationalization idea (Zelikman et al., 2022), except that a teacher writes rationales for existing targets rather than the model bootstrapping new ones.

**Retention and data selection.** Biderman et al. (2024) compare LoRA with full fine-tuning and document a learning-retention trade-off; in their setting LoRA is the more retention-preserving option. Our held-out losses under LoRA are therefore not predicted by that comparison. LESS selects examples aligned with a target capability (Xia et al., 2024); our unequal-size replay comparison cannot establish a general limitation of LESS as an anti-forgetting method. Catastrophic forgetting under agent-skill fine-tuning has also been reported with synthetic data (Murtaza et al., 2026), and cross-environment transfer of fine-tuned agents has been linked to observation/action-interface shifts (Xi et al., 2026). A separate line shows that GUI toggle state is an independent failure point for multimodal agents (Wu et al., 2026), consistent with the one-field result here.

**Statistical practice.** Our task-level approach follows the argument that execution-level tests in NLP must respect the unit of independent sampling (Dror et al., 2018).

## 8. Limitations, threats, and reproduction status

The study uses one model, one training seed per adapter, procedural task families, a small desktop suite, and a single user's deployment. Repeated runs characterize inference variability but do not enlarge the number of independent tasks or replicate training runs. Developer inspection of evaluation failures influenced later prompts, tools, and training variants; task manifests were frozen, but a post-selection confirmation set was not collected. Cross-session baseline reuse and unequal training exposure further limit causal interpretation.

The principal threats are: one student model (a partial second-student desktop run was invalidated); one training seed per adapter (all consolidation claims are conditional on a single adapter); development-set evaluation (no post-freeze confirmation set); cross-session base anchors for R3b–R3e (descriptive only); a composite final configuration (partial decomposition only); unequal replay sizes and steps across variants (no matched-exposure ablation); private adapters and daily-use logs (end-to-end reproduction incomplete); and an incomplete checksum index (`evidence/SHA256SUMS` stops at v31; v32, v33, G0, D7, and R3e are not covered).

**Deployment note.** In daily use, a hosted decision model routed requests to program handlers and scored 30/30 and 30/30 on two authored phrasing sets (pattern router: 15/30 and 16/30; with the 0.8 fallback: 30/30 and 28/30). These are intent-label matches only, not completed tasks; one second-set date label is wrong, there is no matched 4B router baseline, and the private activity logs are not published. Illustrative latency cases (weather 36.5 s to 0.8 s; knowledge 16 s to 2.3 s) are not latency distributions.

**Partial second-student replication.** We attempted a desktop replication with Nemotron-3-Nano-4B under the G0 protocol. The only valid baseline block scored 3/30 on the training tasks under interface v1 (the primary student: 19/30), with failures of a different kind (reading button identifiers as numbers). Two subsequent blocks were invalidated by calculator initialization errors and by the machine locking, so the replication is incomplete and is not used as evidence. It is mentioned because it shows that failure modes are at least partly student-specific.

**Reproduction status.** The repository contains source code, frozen manifests, raw evaluation traces for the principal runs, training configurations, and an offline audit that recomputes the numbers in Tables 1–5 from the raw archives (`docs/paper/deepseek-support/`: `audit.py`, `stats.py`, `make_figures.py`). Reproduction is not complete: adapter files are in private storage, the checksum index does not cover the latest artifacts, and daily-use timing logs contain private content. A release should provide adapters or reconstruction instructions, complete checksums, environment versions, and sanitized timing data. The present paper does not claim independently reproduced end-to-end results.

## 9. Conclusion

In this case study, small-agent failures responded differently to interface repair, presentation of guidance, and consolidation. Explicit observation fields and line-oriented action representations produced large development-set improvements, and the final desktop gains are interface-dominated. Task-adjacent rules with planning were promising on five variants, but the effect is not established at the task level; earlier evidence shows that the same system-prompt delivery can help when the missing content is a step rather than an action representation. Consolidation improved learned-family performance while substantially degrading two excluded families; the follow-up configurations narrow some explanations without identifying a unique mechanism, and the adapter also modified a read-only file twice. The practical lesson is to diagnose failures at the interface and at the presentation layer before attributing them to capability, and to evaluate retention alongside acquisition. These findings are bounded evidence for improving a small agent, not proof of autonomous or universally transferable self-evolution.

\small

## References

- Biderman, D., Portes, J., Gonzalez Ortiz, J. J., Paul, M., Greengard, P., Jennings, C., King, D., Havens, S., Chiley, V., Frankle, J., Blakeney, C., & Cunningham, J. P. (2024). *LoRA Learns Less and Forgets Less*. Transactions on Machine Learning Research. [arXiv:2405.09673](https://arxiv.org/abs/2405.09673).
- Dror, R., Baumer, G., Shlomov, S., & Reichart, R. (2018). *The Hitchhiker's Guide to Testing Statistical Significance in Natural Language Processing*. ACL 2018, 1383–1392. [doi:10.18653/v1/P18-1128](https://aclanthology.org/P18-1128/).
- Murtaza, S. S., Nie, Y., Soni, U., Wen, E., & Frydenlund, A. (2026). *When Synthetic Data Hurts: On Catastrophic Forgetting in Skill Retrieval for LLM Agents*. EMNLP 2026 Industry Track. [arXiv:2609.10750](https://arxiv.org/abs/2609.10750).
- Snell, C., Klein, D., & Zhong, R. (2022). *Learning by Distilling Context*. [arXiv:2209.15189](https://arxiv.org/abs/2209.15189).
- Wang, X., Wang, B., Lu, D., Yang, J., Xie, T., et al. (2025). *OpenCUA: Open Foundations for Computer-Use Agents* (AgentNet). NeurIPS 2025. [arXiv:2508.09123](https://arxiv.org/abs/2508.09123).
- Wang, Z. Z., Mao, J., Fried, D., & Neubig, G. (2025). *Agent Workflow Memory*. ICML 2025. [arXiv:2409.07429](https://arxiv.org/abs/2409.07429).
- Wu, Z., Mao, R., Tian, Z., Cheng, P., Ju, T., Wu, Z., Dong, L., Sheng, H., Zhang, Z., & Liu, G. (2026). *See, Think, Act: Teaching Multimodal Agents to Effectively Interact with GUI by Identifying Toggles*. CVPR 2026. [arXiv:2509.13615](https://arxiv.org/abs/2509.13615).
- Xi, Z., Guo, X., Liu, J., Zhang, J., Fan, Y., Zhang, Z., Liu, S., Chai, M., Shi, X., Zhai, Y., Cai, X., Gui, T., Zhang, Q., & Huang, X. (2026). *Can RL Improve Generalization of LLM Agents? An Empirical Study*. [arXiv:2603.12011](https://arxiv.org/abs/2603.12011).
- Xia, M., Malladi, S., Gururangan, S., Arora, S., & Chen, D. (2024). *LESS: Selecting Influential Data for Targeted Instruction Tuning*. ICML 2024. [arXiv:2402.04333](https://arxiv.org/abs/2402.04333).
- Xu, R., Chen, Y., CuiZhu, Z., Dalvi Mishra, B., Ming, Y., Yu, H., Han, R., Lee, C.-Y., & Pfister, T. (2026). *Harness$^2$: Recursive Agent Harnessing for an Open World*. [arXiv:2610.14224](https://arxiv.org/abs/2610.14224).
- Xu, Z., Meza Soria, A., Tan, S., Roy, A., Agrawal, A. S., Poovendran, R., & Panda, R. (2025). *TOUCAN: Synthesizing 1.5M Tool-Agentic Data from Real-World MCP Environments*. [arXiv:2510.01179](https://arxiv.org/abs/2510.01179).
- Yang, J., Jimenez, C. E., Wettig, A., Lieret, K., Yao, S., Narasimhan, K., & Press, O. (2024). *SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering*. NeurIPS 2024. [arXiv:2405.15793](https://arxiv.org/abs/2405.15793).
- Yang, J., Li, Z., Shi, Y., Li, Z., Wang, R., Zhou, R., Mi, H., Yan, S., & Liang, L. (2026). *Terminal-RSI: Recursive Self-Improving Terminal Agents via Recursive Self-Rewrite and Policy-Refine*. [arXiv:2610.22192](https://arxiv.org/abs/2610.22192).
- Zelikman, E., Wu, Y., Mu, J., & Goodman, N. D. (2022). *STaR: Bootstrapping Reasoning With Reasoning*. NeurIPS 2022. [arXiv:2203.14465](https://arxiv.org/abs/2203.14465).
