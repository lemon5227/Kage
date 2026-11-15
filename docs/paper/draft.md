---
title: 'Interface Design, Teacher Guidance, and Consolidation in a 4B Computer-Use Agent: An Empirical Study'
author: Wenbo Yan
date: 'October 2026 · v0.4'
---

## Abstract

Improving a small computer-use agent requires distinguishing missing knowledge from failures of observation, action representation, and instruction adoption. We present a diagnostic case study of Kage, an Agents-A1-4B agent evaluated on file-editing tasks, browser fixtures, and native macOS applications. Developer-designed interface changes produced large descriptive gains: explicitly representing unchecked boxes increased settings success from 1/18 to 14/18 executions, and line-based editing tools increased TextEdit success from 4/18 to 17/18. Teacher lessons placed beside the task with an explicit planning instruction achieved 10/15 executions, compared with 3/15 without lessons and 6/15 with planning alone, although this comparison covers only five distinct tasks. Separately, LoRA consolidation of 1,900 action-level examples from 151 unique tasks increased in-family file success from 30/72 to 64/72, while held-out-family success fell from 15/36 to 1/36. Follow-up variants show that retaining reasoning text alone does not prevent this degradation, but do not isolate a single cause. The final desktop configuration achieved 41/45 executions on 15 tasks reused during development; this is not an untouched test of generalization. We report these findings as exploratory evidence, distinguish repeated executions from independent tasks, and separate automated learning from developer intervention. A deployment case study illustrates the additional distinction between intent classification and end-to-end task success. The results motivate interface diagnosis before capability attribution and retention evaluation before deploying consolidated weights.

## 1. Introduction

A personal agent built around a small local model should benefit from experience without becoming less reliable on unfamiliar requests. Failures, however, admit several explanations. The model may lack a procedure, fail to use a retrieved procedure, misinterpret the observation, or be unable to express a correct action through the available tool. Fine-tuning before distinguishing these cases can optimize the wrong behavior.

Kage provides a setting in which to examine these explanations. Its student edits files, operates local web fixtures, and interacts with macOS applications. A cloud teacher supplies demonstrations or lessons, and verified guided executions can become training data. During development, failures initially attributed to model capability were sometimes resolved by changes to the interface alone. Conversely, successful consolidation on familiar task families accompanied substantial losses on two families excluded from training.

This paper contributes a trace-grounded account of these findings rather than a new general-purpose self-improvement algorithm. We examine three questions: which failures respond to interface changes; whether the presentation of teacher guidance affects adoption; and how consolidation changes familiar and unfamiliar task performance. The experiments combine automated teacher calls and training pipelines with developer-designed tools, prompts, and follow-up experiments. They do not establish autonomous recursive self-improvement, nor a universally optimal ordering of interface design, teaching, and training.

## 2. System and evidence boundaries

**Student.** The principal student is Agents-A1-4B in Q4_K_M format, served through llama.cpp. File and browser evaluations ran on Kaggle T4 GPUs; desktop evaluations ran on an Apple M4 Mac. Consolidation training used a Colab A100. Only one student model is evaluated in the results reported here.

**Execution budgets.** The file benchmark permits up to five loop steps, six local model requests, and twelve tool dispatches per attempt, with a 150-second limit. The browser protocol uses eight steps and ten model requests. Desktop tasks have task-specific limits of six to twenty steps, recorded in the Desktop-v1 manifest; the desktop loop issues a model request on each step. These are different protocols, not a common compute budget across domains. The historical file baseline and desktop loop use temperature 0.7. Their observed variation is not evidence about temperature-zero determinism.

**Learning and guidance.** Following a failed file or browser attempt, a teacher demonstration can be stored as trajectory memory or converted into a parameterized, verified skill. A TF-IDF relevance gate selects items using instruction similarity. A separate lesson mechanism extracts short procedural rules from failures. In G0, four lessons were generated from failed training tasks and reused in subsequent desktop comparisons.

**Checker access.** Programmatic checkers evaluate outcomes outside the student's prompt. This boundary differs from the teacher's feedback boundary: the recorded G0 teaching prompts include the training task's expected result and observed checker findings. Thus G0 uses privileged training feedback to a teacher, not merely a binary reward. The student subsequently receives general lessons rather than the test-task answer. Student-unseen tasks may nevertheless be developer-seen: repeated inspection of evaluation failures informed interface and prompt revisions.

**Consolidation.** The student re-executes practice tasks with demonstrations and lessons; successful executions are converted into action-level supervised examples after removing the guidance. LoRA training uses response-only loss, rank 16 adapters on attention-output and MLP projections, and no reinforcement learning. Evaluation of the resulting adapters uses neither retrieved guidance nor teacher assistance.

**Cost scope.** The project's cloud-teacher budget was capped at US$4. The preceding project report records US$1.83 of cloud usage, including decision-model calls valued at list price; this revision does not independently reconcile that private ledger. The cap excludes GPU training, student inference, hardware, and developer effort. The five saved R3-series training configurations total approximately 5.8 hours of training wall time, excluding data collection, evaluation, and other runs. A small teacher bill is therefore not a total research-cost estimate.

## 3. Benchmarks and evaluation protocol

Kage-Stream contains four learned file families (subset selection, interval merge, log aggregation, and CSV transformation), two families excluded from consolidation training (text normalization and configuration migration), and three read-only negative families. Kage-Web contains invoice, notification-settings, and hotel-selection fixtures, a held-out profile-form family, and read-only lookups. Desktop-v1 contains fifteen tasks: six Calculator tasks, six TextEdit tasks, and three read-only System Settings tasks. G0 operates through the Accessibility API; later deployment handlers use additional mechanisms and are not part of that protocol.

Table 1 distinguishes task counts from execution counts. Fixed manifests support repeatability but do not make a dataset untouched after its failures have informed development.

| Experiment | Evaluation units | Repetition and interpretation |
|----------------|--------------------------|----------------------------------------|
| E-1/E-2 files | 24 in-family, 12 held-out-family, 12 negative tasks per evaluation | Two learning streams; raw baseline outcomes reused in the original comparisons |
| C4 browser | 30 tasks: 6 per family | Three inference repeats per arm; follow-up design informed by earlier results |
| G0 | 10 training tasks and 5 variants | Three repeats per task; variants reused during development |
| R3 series | 24 learned-file, 12 held-out-file, 18 learned-web tasks | Three inference repeats per adapter; one training seed per variant |

*Table 1. Units and scope of the principal evaluations. D7 uses 30 authored utterances per set, evaluated once for intent classification.*

**Statistical interpretation.** We report counts and per-run results as descriptive evidence. Repeated executions of the same task are not independent samples of new tasks. Previous reports used Fisher tests over execution counts and, for E-1, paired tests with a reused baseline. We do not carry those significance claims into the main results. Section 5 provides a task-level sensitivity analysis for G0. A comprehensive cluster-aware analysis and new confirmation set remain future work; absence of significance is not evidence of equivalence.

**Sessions and selection.** C4 comparisons within a round and the original R3 adapter-versus-base comparison were run in the same Kaggle session. R3b through R3e were evaluated in later sessions with a single base-model anchor each, while each adapter received three repeats. Cross-version comparisons are consequently not all matched-session comparisons. The two held-out file families were excluded from training, but their scores were examined to design later variants. They measure retention during development, not final untouched generalization.

## 4. Learning in context and interface diagnosis

### 4.1 Demonstration reuse

In E-1, after a 60-task learning stream, trajectory memory achieved 42/48 in-family executions and a skill library 39/48, compared with 14/48 for the reused raw baseline and 12/48 for budget-matched retries. The learning arms' denominator combines two stream states evaluated on the same 24 in-family tasks; the raw baseline is duplicated for that comparison. Later raw evaluations ranged from 7 to 13 successes on those 24 tasks. These results support an in-family benefit in the observed setting, but do not demonstrate skill-library superiority or equivalence to memory.

On browser tasks, relevant retrieved demonstrations were not consistently enacted. In the C3 report, procedural invoice lessons accompanied an increase from 0/24 to 14/24 executions. Settings tasks remained difficult until their observation format changed. The contrast motivated examination of interfaces rather than an immediate claim that the student could not learn the procedure.

E-2 also exposed limits to the broader learning system. Proactive help triggered only once in 120 stream tasks. Background maintenance achieved 45/48 in-family executions with fixed selection rules; adding an architect that proposed selection policies yielded 41/48 in its follow-up run. Single-run validation on a small task set admitted policies that weakened the relevance gate. These observations do not establish a benefit from proactive help or autonomous policy evolution.

### 4.2 Browser observations: explicit checkbox state

The original compact browser observation omitted the `checked` key for unchecked boxes. C4 changed this field while retaining the raw student and providing no learned guidance. Table 2 reports the first round, on six settings tasks and thirty total tasks, each repeated three times.

| Interface | Settings (/18) | All tasks (/90) |
|---|---:|---:|
| V1: unchecked state implicit | 1 | 29 |
| V2: explicit true/false state | 14 | 41 |
| V2 plus context packing | 14 | 36 |
| V2 plus packing and state table | 17 | 39 |

*Table 2. C4 first-round counts. The single-field change yields 14/18; 17/18 includes additional interventions.*

The V1-to-V2 comparison isolates a concrete observation change and yields a large descriptive improvement. Packing and the state table are separate changes and must not be included in the single-field estimate. A second round re-evaluated the full V2-plus-packing-plus-state-table configuration, obtaining 18/18 settings and 41/90 overall successes. A pre-save checker using decision-model goal extraction made no intervention in 59 checks; this benchmark therefore provides no evidence of an incremental completion benefit from that checker.

Hotel failures persisted. Trace inspection showed that the student often selected a hotel without opening its rating details. An earlier explanation blaming context packing was revised because the missing action also occurred without packing. This is a procedural hypothesis grounded in traces, not proof that a particular lesson will fix the family.

### 4.3 Desktop actions: line-oriented text editing

With a whole-text `fill` action, TextEdit failures commonly involved missing trailing newlines or literal backslash-n sequences. The developer introduced replacement and line-oriented tools so that the program, rather than the model's JSON string, constructs line breaks.

| Tool interface | Typo fixes (/6) | Appends (/6) | Writes (/6) | Total (/18) |
|--------------------------------------|---------------:|---------------:|---------------:|---------------:|
| Whole-text fill | 0 | 3 | 1 | 4 |
| Add replace/append text | 6 | 2 | 0 | 8 |
| Replace text and line-list actions | 6 | 5 | 6 | 17 |

*Table 3. Six distinct TextEdit tasks, each repeated three times. These sequential development comparisons are not a fresh post-selection test.*

The append and write task instructions explicitly require final newlines; this requirement is not solely a hidden checker condition. The failures and tool changes support an action-representation explanation for much of this improvement. They do not show that every small model needs line-oriented tools, or that teacher guidance is irrelevant under other interfaces. The numerical gains here came from developer-authored tools, not from an agent inventing its own interface.

## 5. Grounded lessons: promising but exploratory

Calculator chain tasks exposed a missing procedure: entering addition followed by multiplication without first resolving the addition gave the wrong grouping. A teacher lesson advised pressing Equals after the addition. Three additional lessons addressed text preservation and newlines. On five task variants not used to generate these lessons, the study compared four prompting conditions under interface v2.

| Prompt condition | Calculator (/6) | TextEdit (/9) | Total (/15) |
|--------------------------------------------------|----------------:|----------------:|----------------:|
| No lessons | 1 | 2 | 3 |
| Lessons in system prompt | 1 | 2 | 3 |
| Plan first, no lessons | 4 | 2 | 6 |
| Lessons beside task; explain their application, then act | 5 | 5 | 10 |

*Table 4. Two Calculator and three TextEdit variants, three executions each.*

The combined intervention is numerically strongest. Planning alone accounts for much of the observed Calculator improvement. However, the last condition changes both lesson placement and planning requirements; it does not isolate rule content, location, or extra deliberation. In particular, these data do not establish that grounding is necessary for adoption or that rules alone caused the TextEdit difference.

**Sensitivity to the unit of analysis.** Averaging the three repeats within each task, the combined intervention minus no lessons gives success-rate differences of 2/3, 2/3, 1, 0, and 0. Enumerating all 32 sign assignments to these five paired differences gives a two-sided task-level sign-flip value of 0.25, compared with the earlier execution-level Fisher value of 0.025. This is a sensitivity check under task-level sign symmetry, not a preregistered randomized test. It illustrates how little independent task coverage underlies the nominal execution-level significance.

**Final configuration.** Combining the line-oriented tools, reference-handling fixes, and task-adjacent lessons with planning yielded 41/45 executions: 29/30 on ten training tasks and 12/15 on the five variants; family totals were Calculator 17/18, TextEdit 15/18, and read-only Settings 9/9. The corresponding earlier baselines were 19/30 and 3/15 under different interface versions. Because failures on these variants informed the final configuration, the variants are development evaluation tasks. The final G0 configuration uses contextual lessons and interface changes; this result is not evidence of a desktop benefit from the separately trained LoRA adapters.

## 6. Consolidation and retention

### 6.1 Data and training units

The R2 training archive contains 1,900 action-level examples from 151 unique task IDs. Each row pairs a conversation context with a target response; multiple rows can come from one successful execution. The four collection reports record 704 attempts and 472 successes in total before sample filtering, while the retained archive contains 446 distinct task/source/attempt combinations. These are different quantities: 1,900 is neither the number of independent tasks nor the number of successful trajectories.

R3 splits the action-level data by task into 1,677 training and 223 validation examples. The adapter is trained for two epochs at learning rate 1e-4, rank 16, and maximum sequence length 8,192. Later variants add base-student examples and external replay, filter targets, or add teacher-written rationales. Each saved training configuration uses seed 0; the three evaluation repeats do not provide replication over training seeds.

### 6.2 Observed trade-offs

| Version | Main change | Learned files (/72) | Held-out files (/36) | Learned web (/54) |
|-------------|-----------------------------------------|----------------:|----------------:|----------------:|
| Base, v26 | No adapter | 30 | 15 | 10 |
| R3 | Guided-success targets | 64 | 1 | 21 |
| R3b | Filter targets; random replay | 34 | 15 | 31 |
| R3c | Filter targets; LESS-style replay | 34 | 2 | 22 |
| R3d | Restore targets with rationales; LESS-style replay | 62 | 6 | 20 |
| R3e | Restore targets with rationales; random replay | 65 | 1 | 22 |

*Table 5. Each file column aggregates 24 or 12 fixed tasks over three inference runs; learned web aggregates 18 tasks over three runs. R3 and the displayed base were evaluated in v26. R3b–R3e came from separate sessions.*

The same-session R3 comparison shows in-family file gains in every repeat (22, 22, 20 out of 24 versus 9, 12, 9 for the base) and a held-out-family decline (1, 0, 0 out of 12 versus 5, 5, 5). R3e repeats were 22, 21, 22 in-family and 1, 0, 0 held-out; its same-session base anchor was 11/24 and 7/12, measured once. The large descriptive gain and retention loss are visible without treating repeated tasks as independent trials.

Under the second-round browser interface, R3e achieved 7/18 invoice executions versus 0/18 for the same-interface raw arm with the same checker. The often-quoted 0/54 pools three raw interface arms and is not the matched comparator. This result suggests that some invoice behavior survives the interface change; it does not establish broad interface-invariant transfer. A 30-question general-ability check scored 27–28 across variants, too small and narrow to establish general capability preservation.

### 6.3 What the variants do not identify

Filtering reasoning-free targets disproportionately removed file solutions: the report identifies 202 reasoning-free `write_file` targets and 101 with reasoning. It did not remove every file-writing example. Restoring the filtered targets with rationales recovered much of the in-family gain, while held-out performance remained low. This rules out the simple account that merely restoring visible reasoning text is sufficient to prevent degradation in these configurations.

It does not prove that gain and forgetting have a single shared cause. R3b and R3c both filter targets and achieve 34/72 learned-file executions, yet their held-out results differ sharply, 15/36 versus 2/36. Random replay contains 1,400 examples, whereas the LESS-style selection retains 879 with a different source mixture. Training sizes and optimizer steps differ as well (Table 6). These are exploratory configuration comparisons, not a balanced factorial ablation of replay selection.

| Version | Training examples | Replay examples | Optimizer steps |
|---|---:|---:|---:|
| R3 | 1,677 | 0 | 420 |
| R3b | 2,781 | 1,400 | 696 |
| R3c | 2,266 | 879 | 567 |
| R3d | 2,736 | 879 | 684 |
| R3e | 3,251 | 1,400 | 813 |

*Table 6. Training counts from saved train-config files; replay counts from the corresponding reports. All variants use two epochs and training seed 0. Counts describe examples, not equal token budgets.*

Trace analyses additionally report less post-write reading and plausible but incorrect code after training. Reduced verification is a candidate mechanism, not an established cause: no intervention forced read-back while holding the model and task constant, and R3b retained substantially more held-out success despite reduced verification behavior. Testing this explanation requires controlled verification interventions and training data that preserve successful checking trajectories. Testing replay explanations requires matched amounts, source composition, training exposure, and multiple training seeds. None of those confirmation experiments is claimed here.

## 7. Deployment case study: choices are not completed tasks

The daily-use system routes requests to handlers for calendar, mail, apps, websites, documents, and WeChat. Some handlers execute programmatically; others combine local-model text processing with application interaction. A hosted Clef decision model selects a request category, with uncertain predictions sent to a general local-model path. This deployment is a hybrid system, not a wholly local 4B agent.

| Authored phrasing set | Classes | Pattern router | Clef intent | After confidence fallback |
|------------------------|---------:|--------------------:|--------------------:|---------------------------:|
| Held-out set 1 | 10 | 15/30 | 30/30 | 30/30 |
| Held-out set 2 | 12 | 16/30 | 30/30 | 28/30 |

*Table 7. Exact intent-label matches, one prediction per utterance. Two correct second-set predictions fell below the 0.8 threshold; fallback completion was not evaluated by this metric.*

These scores do not include parameter extraction or execution. One second-set utterance asks whether the user is free the afternoon after tomorrow, but its stored date label is today and the model predicts tomorrow. Both are wrong even though the calendar intent is correct. The retained artifact therefore supports intent accuracy only; date accuracy requires a corrected, versioned annotation set and reevaluation. Set 1 was subsequently reused as development data for the twelve-class router, so the sets are not two replications of one unchanged model configuration.

There is no matched 4B classification baseline with the same options and context. Consequently the comparison supports improvement over the implemented pattern chain, not a claim that small models should never make routing decisions. Examples from one user's activity log include a weather request changing from 36.5 to 0.8 seconds after routing to an existing handler, and a knowledge request changing from a failed 16-second tool loop to a correct 2.3-second response. These are illustrative before/after cases, not latency distributions or controlled estimates. Private activity logs have not been published; aggregate timing artifacts would be needed for independent verification.

Operational failures also informed handler design. A false completion message without a tool call motivated explicit completion-status logging; a document fallback that selected an unrelated open file motivated per-request write scoping. These are engineering observations, not measured safety guarantees. Request text is sent to a hosted router and can itself contain sensitive information, even when stored mail, documents, and screenshots are processed locally.

## 8. Related work

**Interfaces.** SWE-agent studies agent-computer interface design and demonstrates the value of tools adapted to language-model agents (Yang et al., 2024). Our narrower contribution is a small-model diagnostic case study in which explicit checkbox state and line-oriented actions address observed failure modes. We do not claim interface design as a new principle.

**Experience and consolidation.** Agent Workflow Memory induces and retrieves reusable procedures (Wang et al., 2024). Context distillation transfers information supplied in context into model behavior (Snell et al., 2022). Kage's guided re-execution explicitly draws on the recursive self-rewrite component of Terminal-RSI (Yang et al., 2026), but does not reproduce its reinforcement-learning stages or demonstrate a second recursive training round. The present results concern one consolidation round and subsequent developer-selected variants.

**Retention and data selection.** Biderman et al. (2024) compare LoRA with full fine-tuning and document a learning-retention trade-off. Our work has no full-fine-tuning comparator; it adds task-specific observations of behavior changes in an agent. LESS selects examples aligned with a target capability (Xia et al., 2024). Our unequal-size replay comparison cannot establish a general limitation of LESS as an anti-forgetting method.

**Harness optimization.** Meta-Harness searches harness code using prior scores and traces (Lee et al., 2026). Harness² studies recursive harness adaptation (Xu et al., 2026). Kage contains an architect mechanism, but the positive interface results reported here arise from developer interventions. These mechanisms and experimental findings should not be conflated.

## 9. Limitations and next tests

The study uses one model, procedural task families, a small desktop suite, and a single user's deployment. Repeated runs characterize some inference variability but do not enlarge the number of independent tasks or replicate training seeds. Developer inspection of evaluation failures influenced later prompts, tools, and training variants. Task manifests were fixed, but a new post-selection confirmation set was not collected. Cross-session baseline reuse and varying training exposure further limit causal interpretation.

The most informative next tests are: a fresh desktop set after freezing the interface and lessons; controls separating lesson position, planning, and rule content; a second student under the same protocol; and equal-exposure consolidation comparisons with multiple training seeds. A forced read-back intervention could test the proposed verification mechanism. A deployment evaluation should jointly score intent, parameters, fallback behavior, and completed outcomes. These are pending tests, not prerequisites retrospectively satisfied by the current results.

The repository contains source code, manifests, many raw evaluation traces, and training configuration files. Reproduction is not yet complete: adapter locations in the experiment reports are private, the evidence checksum index does not cover all latest artifacts, and daily-use timing logs contain private content. A release should provide accessible adapters or reconstruction instructions, complete checksums, environment versions, and sanitized timing data. The present paper does not claim independently reproduced end-to-end results.

## 10. Conclusion

In this case study, small-agent failures responded differently to interface repair, contextual guidance, and consolidation. Explicit observations and action representations produced large development-set improvements. Task-adjacent lessons combined with planning were promising on five variants, but their independent effects and generalization remain unresolved. Consolidation improved learned-family performance while substantially degrading two excluded families; the follow-up configurations narrow some explanations without establishing a unique mechanism. The practical lesson is to diagnose failures at the interface as well as the model, and to evaluate retention alongside acquisition. These findings are bounded evidence for improving a small agent, not proof of autonomous or universally transferable self-evolution.

## References

- Biderman, D., Portes, J., et al. (2024). *LoRA Learns Less and Forgets Less*. [arXiv:2405.09673](https://arxiv.org/abs/2405.09673).
- Lee, Y., Nair, R., Zhang, Q., Lee, K., Khattab, O., and Finn, C. (2026). *Meta-Harness: End-to-End Optimization of Model Harnesses*. [arXiv:2603.28052](https://arxiv.org/abs/2603.28052).
- Snell, C., Klein, D., and Zhong, R. (2022). *Learning by Distilling Context*. [arXiv:2209.15189](https://arxiv.org/abs/2209.15189).
- Wang, Z. Z., Mao, J., Fried, D., and Neubig, G. (2024). *Agent Workflow Memory*. [arXiv:2409.07429](https://arxiv.org/abs/2409.07429).
- Xia, M., Malladi, S., Gururangan, S., Arora, S., and Chen, D. (2024). *LESS: Selecting Influential Data for Targeted Instruction Tuning*. [arXiv:2402.04333](https://arxiv.org/abs/2402.04333).
- Xu, R., Chen, Y., CuiZhu, Z., et al. (2026). *Harness²: Recursive Agent Harnessing for an Open World*. [arXiv:2610.14224](https://arxiv.org/abs/2610.14224).
- Yang, J., Jimenez, C. E., Wettig, A., et al. (2024). *SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering*. [arXiv:2405.15793](https://arxiv.org/abs/2405.15793).
- Yang, J., Li, Z., Shi, Y., et al. (2026). *Terminal-RSI: Recursive Self-Improving Terminal Agents via Recursive Self-Rewrite and Policy-Refine*. [arXiv:2610.22192](https://arxiv.org/abs/2610.22192).

## Appendix A. Evidence map

Paths below are relative to the repository root. Historical reports retain their original interpretations; Sections 3–9 state the revised interpretation used in this paper.

| Result | Evidence location |
|---|---|
| File learning and evolution | `evidence/reports/e1-report`, `e2b-report`; `docs/report/kage-tech-report.md` |
| Browser guidance | `evidence/reports/c2`, `c3` |
| Guided training examples | `evidence/reports/r2/sft-v21.jsonl.gz`; four collection statistics files in that directory |
| Consolidation | `evidence/reports/r3`, `r3b`, `r3c`, `r3d`, `r3e`; Kaggle archives v26, v29–v32 |
| Browser interfaces | `evidence/reports/c4`; Kaggle archives v28 and v33 |
| Desktop prompts and tools | `evidence/reports/g0`; per-arm configs, results, traces, and teacher log |
| Routing and deployment | `evidence/reports/d7`; `eval/intent_v1`; private activity-log timings summarized in the D7 report |
| Revision audit | `docs/paper/review-codex-2026-10-27.md`; `docs/paper/v0.4-support` |
