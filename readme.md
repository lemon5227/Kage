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
  <a href="#results-a-4b-local-model-that-learns-from-a-teacher">Results</a> ·
  <a href="docs/report/kage-tech-report.md">Report</a> ·
  <a href="roadmap.md">Roadmap</a> ·
  <a href="docs/project-guide.en.md">Full guide</a>
</p>

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
| L3 · Parameter learning | Future local-model adapters or weights | Distillation of verified teacher experience |

The research objective is <strong>persistent, transferable capability growth</strong>, measured alongside task success, regressions, latency, tokens, and learning cost. Parameter learning remains a future stage.

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

[Technical report](docs/report/kage-tech-report.md) · [Related work](docs/report/related-work.md) · [Raw evidence and reports](evidence/README.md) · [Work log](docs/worklog/2026-10-claude.md)

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

1. <strong>Finish P5 outputs.</strong> Technical report, demo recording, and this README with curves and ablations.
2. <strong>Make self-modification safe.</strong> Promote evolved policies only after repeated validation runs that also include unfamiliar task types.
3. <strong>Bring verified learning into the local model (P4).</strong> Choose one: LoRA distillation of accepted teacher demonstrations, or browser task families for the stream benchmark.

[Roadmap and current status (start here)](roadmap.md) · [Task book](docs/plans/tasks-2026-10-14.md) · [Design: self-evolving, proactive agent](docs/plans/self-evolving-proactive-agent-2026-10-14.md) · [Kaggle runbook](docs/development/kaggle-runbook.md)

## Explore the project

| Start here | What you will find |
| :--- | :--- |
| [Full project guide](docs/project-guide.en.md) | Detailed research context, setup, configuration, and implementation boundaries |
| [Experiment archive](docs/experiments/README.md) | Methods, results, failures, and reproduction evidence |
| [Visual style guide](docs/assets/readme/VISUAL_STYLE.md) | Companion artwork direction and future character changes |
| [Issues and ideas](https://github.com/lemon5227/Kage/issues) | Feedback, proposals, and collaboration |

---

MIT License · [Optimization history](docs/optimization_history.md)
