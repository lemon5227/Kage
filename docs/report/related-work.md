# Related work (W6-1)

*2026-10-16. Each entry: what it does, and how Kage differs. Figures quoted are the papers' own abstract-level
claims (checked against the arXiv/proceedings pages listed); details beyond the abstract should be re-checked
before citing in the final report.*

## 1. Skill libraries

- **Voyager** — Wang et al., NeurIPS 2023. [arXiv:2305.16291](https://arxiv.org/abs/2305.16291).
  A GPT-4 Minecraft agent with an automatic curriculum, iterative prompting with environment feedback and
  self-verification, and a growing library of executable code skills retrieved by embedding similarity.
  *Kage:* the learner is a 4B local model and skills come from a teacher's verified demonstration; we compare a
  skill library against plain trajectory memory under the same teacher budget (§5.2 of the report: no
  difference), and gate skills by relevance because irrelevant skills hurt a small model (§5.3).

## 2. Experience / trajectory memory

- **ExpeL** — Zhao et al., AAAI 2024. [arXiv:2308.10144](https://arxiv.org/abs/2308.10144).
  Agents gather experience across training tasks and reuse it as in-context examples plus extracted
  natural-language insights; performance improves as experience accumulates.
- **Agent Workflow Memory (AWM)** — Wang, Mao, Fried, Neubig, ICML 2025. [arXiv:2409.07429](https://arxiv.org/abs/2409.07429).
  Induces reusable workflows from past trajectories, offline or online, and feeds them back to the agent;
  reports 24.6% and 51.1% relative success gains on Mind2Web and WebArena.
  *Kage:* A3 is an ExpeL/AWM-style memory baseline (verified teacher demonstrations retrieved by instruction
  similarity); it matched the skill library on our benchmark.

## 3. Self-improving agents and harness search

- **ADAS (Automated Design of Agentic Systems)** — Hu, Lu, Clune. [arXiv:2408.08435](https://arxiv.org/abs/2408.08435).
  A meta agent programs new agents in code, evaluates them and keeps them in an archive that guides later designs.
- **Gödel Agent** — Yin et al. [arXiv:2410.04444](https://arxiv.org/abs/2410.04444).
  A self-referential agent that reads and modifies its own code at runtime using environment feedback.
- **SICA (A Self-Improving Coding Agent)** — Robeyns, Szummer, Aitchison, ICLR 2025 workshop.
  [arXiv:2504.15228](https://arxiv.org/abs/2504.15228). A coding agent edits its own code; reports 17% → 53% on a
  SWE-bench Verified subset.
- **Darwin Gödel Machine (DGM)** — Zhang, Hu et al., ICLR 2026. [arXiv:2505.22954](https://arxiv.org/abs/2505.22954).
  An open-ended archive of self-modifying coding agents validated on benchmarks; SWE-bench 20.0% → 50.0%,
  Polyglot 14.2% → 30.7%.
- **Huxley-Gödel Machine (HGM)** — ICLR 2026. [arXiv:2510.21614](https://arxiv.org/abs/2510.21614).
  Argues a node's own benchmark score is a poor guide for which self-modification to expand, and estimates
  clade-level metaproductivity (how well descendants do) instead. *Kage:* `core/evolution/lineage.py` selects
  parents by subtree mean of smoothed validation scores in this spirit.
- **Meta-Harness** — Lee, Nair, Zhang, Lee, Khattab, Finn. [arXiv:2603.28052](https://arxiv.org/abs/2603.28052).
  Outer-loop search over harness code in which a coding-agent proposer reads earlier candidates' source,
  scores and raw execution traces from a filesystem rather than compressed feedback.
  *Kage:* the A6 architect follows this design at a much smaller scale (read-only ls/cat/grep over a scrubbed
  archive, one evolvable policy, ≤ US$0.015 per proposal, promotion only without regression on held-out
  validation tasks, and a fixed-rule control arm A6-fixed).
  *Difference across this group:* these systems use strong models and large budgets to rewrite the agent;
  Kage keeps the executor small and local, spends a capped teacher budget, and tests each evolvable part
  against a human-written control.

## 4. Self-practice and task generation

- **Self-Challenging Language Model Agents** — Zhou, Levine, Weston, Li, Sukhbaatar, NeurIPS 2025.
  [arXiv:2506.01716](https://arxiv.org/abs/2506.01716). The agent writes its own Code-as-Task problems
  (instruction, verifier, example solution, failure cases) and trains on them with RL; over two-fold gains for
  Llama-3.1-8B on M3ToolEval and TauBench. *Kage:* practice is in-context only (no weight updates), uses
  environment generators for the clusters the competence model marks as near the learning frontier, and feeds
  failures to skill repair.

## 5. Knowing when to ask, and proactive agents

- **KnowNo (Robots That Ask For Help)** — Ren et al., CoRL 2023. [arXiv:2307.01928](https://arxiv.org/abs/2307.01928).
  Conformal prediction calibrates an LLM planner's uncertainty so it asks a human for help only when needed,
  with completion guarantees. *Kage:* asks before attempting from a per-cluster Beta posterior and an expected
  loss vs help cost rule, and stops asking where help has proven unlearnable; no formal guarantee.
- **Proactive Agent** — Lu et al., ICLR 2025. [arXiv:2410.12361](https://arxiv.org/abs/2410.12361).
  Trains agents to anticipate and offer tasks from observed user activity (ProactiveBench, 6,790 events; F1
  66.47%). *Kage:* proactivity here means asking for help and reporting what was learned, not anticipating
  user goals.

## 6. Distillation into small agents

- **FireAct** — Chen et al. [arXiv:2310.05915](https://arxiv.org/abs/2310.05915). Fine-tuning Llama2-7B on 500
  GPT-4 agent trajectories gives a 77% HotpotQA improvement. *Kage:* all learning so far is non-parametric
  (skills, memory, policies); LoRA distillation of accepted demonstrations is the planned P4 extension.
