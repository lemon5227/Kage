![Kage — an anime companion and evolving agent](docs/assets/readme/companion-cover.png)

<p align="center"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

<p align="center">
  <strong>Toward Self-Evolving General-Purpose Computer Agents</strong><br>
  Computer use · Continual learning · Procedural memory · Agent self-modification
</p>

<p align="center">
  <a href="#toward-a-self-evolving-personal-agent">Vision</a> ·
  <a href="#research-program">Research</a> ·
  <a href="#get-started">Get started</a> ·
  <a href="#demo">Demo</a> ·
  <a href="#latest-october-2026">Latest</a> ·
  <a href="#results-a-4b-local-model-that-learns-from-a-teacher">Results</a> ·
  <a href="docs/report/kage-tech-report.md">Report</a> ·
  <a href="roadmap.md">Roadmap</a> ·
  <a href="docs/project-guide.en.md">Full guide</a>
</p>

## Demo

<p align="center">
  <a href="docs/assets/demo/kage-live-demo.mp4"><img src="docs/assets/demo/kage-live-demo.gif" width="800" alt="Kage live desktop demo"></a><br>
  <em>Live run, 66 s, real time: local 4B model with Calendar, weather, Zhihu, Calculator and WeChat (a misspelled contact name is resolved and confirmed before sending). Click for the <a href="docs/assets/demo/kage-live-demo.mp4">full-resolution video</a>. Teaching-loop demo: <a href="docs/assets/demo/kage-demo.mp4">83 s</a>.</em>
</p>

## Latest (October 2026)

- **A daily desktop assistant, command line first.** Kage now opens apps by what you call them (微信, 飞书, vscode — 20/20), reads and edits the documents open in your apps through their real file paths (11/11, edits limited to the files a request names), sends a 12:30 schedule brief from Calendar and Reminders, lists and summarizes unread Mail with the local model (10/10 summaries factually correct), and reads websites through [OpenCLI](https://github.com/jackwener/opencli) in your logged-in Chrome. A local usage log records every request, what Kage did and whether it worked; after a failure it asks how you did it and keeps that method. ([D-phase evidence](evidence/reports/d0/analysis.md))
- **Interface first, then teach, then consolidate.** One observation field took a web settings task from 1/18 to 17/18; line-based edit tools took macOS TextEdit tasks from 4/18 to 17/18; teacher rules were ignored in the system prompt but used when placed next to the task. LoRA consolidation lifted learned file tasks from 30/72 to 65/72 but cost held-out code writing (15/36 → 1/36): across five ablations, gain and forgetting come from the same samples, and the result reproduced with three training seeds. [Paper v0.8 (PDF)](docs/paper/v0.8/paper.pdf)
- **Pre-registered confirmation on new frozen tasks.** 18 tasks written and hashed before any run, all conditions interleaved in one session. Line tools again took TextEdit from 3/18 to 18/18, and a second student (Nemotron-3-Nano-4B) from 2/18 to 17/18. Calculator rules: none 1/30, system prompt 6/30, next to the task 19/30, next to the task plus a plan 23/30. Where the rule sits matters most, and the planning request adds little. The same placement also makes the student apply the rule where it does not fit (control tasks 18/18 → 8/12). ([evidence](evidence/reports/g0-confirm/README.md), [pre-registration](docs/plans/g0-confirm-prereg.md))
- **Native macOS tasks through the Accessibility API.** Calculator, TextEdit and read-only System Settings: 19/30 → 41/45 with the improved interface and grounded lessons, plus a live "fail → teacher lesson → solve an unseen task" demo ([script](docs/report/demo-g0.md)).

## Toward a self-evolving personal Agent

<strong>Kage explores an Agent that can operate a computer, learn from experience and teaching, and improve parts of the system that drives its decisions.</strong>

The ambition is general-purpose computer use across browsers, files, documents, and native applications. Experience should accumulate as transferable capabilities; failed tasks should inform what the Agent learns or changes next. The project brings <strong>computer-use execution, continual adaptation, and Agent scaffold evolution</strong> into one experimental system.

### Beyond a fixed set of tools

Kage's research direction extends from retrieving useful memories to creating executable skills, revising selected Agent modules, and eventually distilling verified experience into local models. Each layer targets a deeper change in how the Agent solves future tasks.

### Experience as the engine of improvement

When a task fails, a person or cloud teacher can demonstrate a solution. The intended learning chain preserves the actual actions and verified result, extracts reusable knowledge, and tests whether it helps on new tasks. Skills, source-code changes, and future weight updates are evaluated as distinct mechanisms.

### A research platform on personal hardware

Local small models and selective cloud teaching provide a practical setting for studying autonomy, transfer, self-modification, and resource use on modest hardware. The long-term goal is <strong>an Agent that can act, learn, and redesign parts of its own problem-solving system</strong>.

## Research program

### Computer use and procedural memory

- <strong>General-purpose action:</strong> connect browser DOM perception, native macOS accessibility, and future visual grounding. Evaluate completion and recovery as content, layouts, and initial states change.
- <strong>Experience as a capability:</strong> turn trajectories and corrections into parameterized procedures. Test discovery, composition, and transfer to new inputs rather than only replaying the original demonstration.

### Self-modification and failure-driven improvement

- <strong>Evolving the Agent scaffold:</strong> generate isolated candidate changes, load the changed code, and compare parent and child behavior. A recovery-module pilot is implemented; broader module evolution is the next direction.
- <strong>Choosing what to improve:</strong> investigate when to retrieve a memory, repair a skill, revise a module, or request teaching. Failure-conditioned routing is a planned experiment, compared with fixed policies under explicit budgets.

### Continual learning on modest hardware

- <strong>Local–cloud collaboration:</strong> use local small models for affordable execution and cloud teachers for selected difficult tasks and candidate generation. Track task success and assistance cost separately.
- <strong>Learning from teachers:</strong> build verified, diverse trajectories before distilling them into local adapters or weights. Compare memory, skills, and eventual parameter learning as distinct mechanisms.

Development starts on an <strong>Apple Silicon Mac with 16 GB of memory</strong>. The goal is to make capability growth practical under limited resources, with reproducible experiments behind each step.

## How Kage grows

### Execution and evolution, on different timescales

![Execution and adaptation loops](docs/assets/readme/architecture-companion.svg)

<strong>Act → Verify → Remember → Learn → Evaluate → Reuse</strong>

The execution loop observes the environment, chooses actions, and checks the resulting state. The evolution loop uses that evidence to propose skills or module changes, compare behavior, and select useful capabilities for reuse.

Verification is tied to actual outcomes where a reliable checker exists—for example, saved data read back from a browser task. Candidate versions and provenance connect an improvement to its source experience and evaluation.

### Four layers of adaptation

![From episodic memory to procedural skills, scaffold evolution, and future parameter learning](docs/assets/readme/learning-companion.svg)

| Layer | What changes | Intended benefit |
| :--- | :--- | :--- |
| L0 · Episodic memory | The experience retrieved for a task | Relevant context from earlier attempts |
| L1 · Procedural memory | The executable skills available | Reuse and transfer of verified routines |
| L2 · Scaffold evolution | Selected planning, retrieval, or recovery modules | Better ways to solve and recover |
| L3 · Consolidation | Local-model LoRA adapters | Guided successes become ability that no longer needs the guidance in context |

The research objective is <strong>persistent, transferable capability growth</strong>, measured alongside task success, regressions, latency, tokens, and learning cost. L0–L2 are implemented and evaluated; L3 is the current stage ([plan](docs/plans/rsr-consolidation-2026-10-18.md)): the student re-solves fresh variants with a teacher-derived runbook in context, only verified and leak-screened successes are kept, the runbook is removed, and the adapter is accepted only if it beats the raw student *without* guidance on frozen evaluation sets.

## Results: a 4B local model that learns from a teacher

On **Kage-Stream v1**, a frozen benchmark of 60 tasks per stream (4 task families learned in the stream, 2 held-out
families, 3 read-only negative families), the local student is Agents-A1-4B (Q4_K_M, llama.cpp) and the teacher is
DeepSeek. After each failure the teacher demonstrates once, and the agent keeps the demonstration as a verified
skill, a stored trajectory, or both. Evaluation checkpoints switch learning and help off.

![In-family success rate by checkpoint for every arm](docs/assets/readme/growth-curve.png)

| Arm (2 seeds) | In-family, after 60 tasks | Held-out families | Negatives / misuse |
| :--- | :---: | :---: | :---: |
| A0 raw student | 14/48 (29%) | 16/24 | 24/24 · 0 |
| A1 same budget spent on retries | 12/48 (25%) | 10/24 | 24/24 · 0 |
| A3 trajectory memory | 42/48 (88%) | 12/24 | 24/24 · 0 |
| A4 skill library | 39/48 (81%) | 14/24 | 24/24 · 0 |
| A4m skills + memory | 43/48 (90%) | 9/24 | 23/24 · 1 |
| A5 + relevance gate + proactive help | 43/48 (90%) | 12/24 | 24/24 · 0 |
| **A6-fixed + background practice and skill maintenance** | **45/48 (94%)** | 12/24 | 24/24 · 0 |
| A6 + architect evolving skill selection | 41/48 (85%) | 9/24 | 24/24 · 0 |

What the evidence supports:

- **Learning from demonstrations works.** Every learning arm beats the raw student and the retry baseline by a
  wide margin (A4 vs A0: 25 vs 0 discordant pairs, p = 6e-8), at about US$0.07–0.20 of teacher calls per arm.
- **Skills, memory, practice and proactive help are not distinguishable** on this benchmark. The paired
  differences among learning arms are not significant (p ≥ 0.065), and the raw student itself varies by
  ±3 tasks between identical runs.
- **A relevance gate is necessary.** Without it, irrelevant skills and demonstrations distracted the student on
  held-out tasks. With it, an unfamiliar task gets exactly the raw student's request, and no read-only task
  ever triggered a skill.
- **Self-modification needs robust validation.** An LLM architect that rewrites the skill-selection policy got
  2 of 6 proposals promoted on single-run validation. One of them undid the gate, so the arm with the architect
  scored below the arm without it.

### Browser tasks: retrieved but not followed

On **Kage-Stream-Web** (form filling, invoice totals with hidden rows, notification settings, rating-constrained catalog choice, and a read-only negative; 8 steps per task, one page action per step), the same student learns from teacher demonstrations stored as label-level steps.

| Family (6 eval tasks each) | Raw student, 3 runs | Learning arms after 44 tasks (4 runs) |
| :--- | :---: | :---: |
| Invoice total (expand hidden rows first) | 0, 0, 0 | 2, 2, 1, 2 |
| Notification settings | 1, 1, 1 | 0, 0, 1, 1 |
| Catalog choice under a rating floor | 2, 4, 3 | 3, 3, 3, 2 |
| Two-step form (transfer, never learned) | 0, 0, 1 | 0, 0, 0, 0 |
| Read-only question (negative) | 6, 6, 6 | 6, 6, 6, 6 · no misuse |

Retrieval works: every evaluation prompt contained the relevant demonstration. Adoption does not: the student followed the "Show more rows" step in only 1–2 of 6 invoice tasks, and a click list from another instance does not carry rules such as "only toggle boxes whose state differs". Only the family whose procedure is literally identical across instances improved. This is why the next stage teaches rules (C3) and consolidates guided successes into weights (L3). [Analysis](evidence/reports/c2/analysis.md)

### Learning in everyday use

The same loop runs inside the desktop app: every task ends with a 👍/👎; a 👎 offers a teacher redo (US$0.05/day cap); verified successes are reused as experience on similar requests behind a relevance threshold; and when the user is away, Kage practises on teacher-made variants of its real file tasks in a scratch directory and reports what it learned. Trajectories stay in `~/.kage/trajectories` (viewable, deletable, off-switchable); about 1 in 10 real tasks is held out for evaluation.

[Live desktop demo (66 s)](docs/assets/demo/kage-live-demo.mp4) · [Teaching-loop demo (83 s)](docs/assets/demo/kage-demo.mp4) · [Technical report](docs/report/kage-tech-report.md) · [Related work](docs/report/related-work.md) · [Raw evidence and reports](evidence/README.md) · [Work log](docs/worklog/2026-10-claude.md)

### Personal-assistant interface

Kage presents this system through an anime-style macOS assistant with Live2D expressions, optional voice, and a configurable persona. The interface provides a personal way to interact with the Agent. The Haru-inspired cover is temporary concept art; future characters can retain the [visual style](docs/assets/readme/VISUAL_STYLE.md).

## Get started

Try the **browser teaching flow**: demonstrate a task, extract a candidate workflow, and replay it with new inputs. Recording and direct replay need **no model server or cloud key**.

**Requirements:** Apple Silicon macOS · Python 3.10+ · Node.js 18+ · Playwright Chromium.

<details>
<summary><strong>Install and launch</strong></summary>

**1. Install from the repository.**

```sh
git clone https://github.com/lemon5227/Kage.git
cd Kage
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-computer-use.txt
python -m playwright install chromium
```

**2. Start the control API.**

```sh
KAGE_MODE=control KAGE_BROWSER_PYTHON="$PWD/.venv/bin/python" \
  python -m uvicorn core.server:app --host 127.0.0.1 --port 12345
```

**3. In another terminal, start the Launcher from the repository root.**

```sh
cd kage-avatar
npm install
npm run dev
```

Open [the Launcher](http://localhost:1420/launcher.html) and find the **Browser teaching** panel. The current UI uses Chinese labels; see the [Chinese instructions](README.zh-CN.md#体验浏览器教学流程).

Select a task → start the dedicated browser → demonstrate and save → finish verification → edit parameters and replay on a fresh page.

Full desktop/voice setup, optional audio dependencies, model configuration, and teaching evidence paths are covered in the [setup guide](docs/project-guide.en.md#try-the-browser-teaching-flow).

</details>

<details>
<summary><strong>Local models and cloud configuration</strong></summary>

Settings live in `~/.kage/config.json`:

| Setting | Purpose |
| :--- | :--- |
| `model.local_runtime` | Compatible local server and model |
| `model.cloud_api` | Cloud provider configuration |
| `model.hybrid` | Optional routing |

The validated local setup uses **Agents-A1-4B Q4_K_M with llama.cpp**; cloud teaching experiments have used **DeepSeek**. Keep API credentials outside the repository.

See [configuration details](docs/project-guide.en.md#models-and-cloud-configuration). Cloud fallback and verified learning are separate mechanisms.

</details>

## Roadmap

- ✅ <strong>P0–P3, P5:</strong> benchmark, learning arms, relevance gate, proactive help, background evolution, technical report, demo.
- ✅ <strong>A · Learning in everyday use:</strong> notices, 👍/👎, local trajectory store with redacted export, teacher redo, experience reuse, idle practice.
- ✅ <strong>C · Browser families and interfaces:</strong> frozen Kage-Stream-Web; teacher rules (invoices 0/24 → 14/24); interface ablations (settings 1/18 → 18/18).
- ✅ <strong>R · Consolidation:</strong> guided re-execution → LoRA (A100); five ablations of replay and rationalization (R3–R3e).
- ✅ <strong>G0 · macOS apps:</strong> accessibility driver, desktop-v1 tasks with trusted checkers, grounded lessons, live demo.
- ✅ <strong>Paper v0.8</strong> ([PDF](docs/paper/v0.8/paper.pdf)): pre-registered desktop confirmation, a second student, and three training seeds for the LoRA result (gain and forgetting reproduce in all three).
- ⏳ <strong>D · Daily desktop assistant</strong> ([task card](docs/plans/cards/D-desktop.md)): open apps ✅, open documents ✅, schedule brief ✅, mail ✅, websites via OpenCLI ✅ (Bilibili; Zhihu/Xiaohongshu after login), WeChat by screenshot + on-device OCR (in progress), live demo video ✅, arXiv.

<strong>How this project is built:</strong> Claude Code plans experiments, writes task cards and reviews every diff and result; well-specified implementation is delegated to a DeepSeek-V4.1-Flash executor running as an isolated Claude Code process ([deepseek-agent](https://github.com/lemon5227/deepseek-agent)); experiments ran on Kaggle's free T4 GPUs and a Colab A100 under a US$4 teacher ledger (US$1.78 spent). Every step is in the [work log](docs/worklog/2026-10-claude.md).

[Roadmap and current status (start here)](roadmap.md) · [Task book](docs/plans/tasks-2026-10-14.md) · [Design: self-evolving, proactive agent](docs/plans/self-evolving-proactive-agent-2026-10-14.md) · [Kaggle runbook](docs/development/kaggle-runbook.md)

## Explore the project

| Start here | What you will find |
| :--- | :--- |
| [Insights and lessons learned](docs/insights.md) | What the experiments taught us: findings, evidence, root causes, fixes (Chinese) |
| [Full project guide](docs/project-guide.en.md) | Detailed research context, setup, configuration, and implementation boundaries |
| [Experiment archive](docs/experiments/README.md) | Methods, results, failures, and reproduction evidence |
| [Visual style guide](docs/assets/readme/VISUAL_STYLE.md) | Companion artwork direction and future character changes |
| [Issues and ideas](https://github.com/lemon5227/Kage/issues) | Feedback, proposals, and collaboration |

---

MIT License · [Optimization history](docs/optimization_history.md)
