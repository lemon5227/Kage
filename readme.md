![Kage — an anime companion and evolving agent](docs/assets/readme/companion-cover.png)

<p align="center"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

<p align="center">
  <strong>Your companion. Your evolving agent.</strong><br>
  Live2D presence · Voice interaction · Personal memory · Self-evolution
</p>

<p align="center">
  <a href="#get-started">Get started</a> ·
  <a href="#how-kage-grows">Architecture</a> ·
  <a href="docs/agent-memory-evolution-master-plan-2026-09-29.md">Roadmap</a> ·
  <a href="docs/experiments/README.md">Experiments</a> ·
  <a href="docs/project-guide.en.md">Full guide</a>
</p>

## A companion that learns with you

**Kage is an anime-style personal assistant for macOS**, combining a desktop companion with an experimental computer-use Agent. The ambition: work across apps, remember what matters, learn from your guidance, and improve how it solves problems.

- **Connect:** Live2D expressions, voice, and a configurable persona.
- **Act:** browser workflows, file tools, and system controls.
- **Learn:** verified experience, human teaching, and reusable skills.
- **Evolve:** experiments in cloud teaching and Agent self-modification.

<sub>The Haru-inspired cover is a temporary concept illustration. Kage has no fixed character; future artwork can keep the same style with a new appearance. [Visual style guide](docs/assets/readme/VISUAL_STYLE.md).</sub>

## How Kage grows

![Execution and adaptation loops](docs/assets/readme/architecture-companion.svg)

**Act → Verify → Remember → Learn → Evaluate → Reuse**

Execution produces experience. Teaching turns experience into candidate skills. Independent comparisons decide which changes deserve reuse. Local models handle execution; cloud teachers can support selected learning experiments.

![From episodic memory to procedural skills, scaffold evolution, and future parameter learning](docs/assets/readme/learning-companion.svg)

The research goal is **durable, transferable capability growth**—from recalling experience to changing selected parts of the Agent itself. Weight distillation is a future research stage.

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

## In the lab

Browser capture and fresh-input workflow replay are working. A recovery-module self-modification pilot loads and evaluates actual candidate code. Broader autonomy and transfer remain active research.

<details>
<summary><strong>Latest validation and its limits</strong></summary>

| Check | Observed result |
| :--- | :--- |
| Engineering suite | 992 tests passed |
| Browser captures | 2 verified |
| Fresh-input workflow replays | 2 verified |
| Local 4B model pilot | 2 tasks completed; 0 new-skill calls |

Workflow replay demonstrates capture and reuse. **Automatic skill adoption and a learning advantage remain unproven.** Actual human teaching acceptance is pending; browser teaching currently targets controlled single-form tasks.

[Full browser teaching report](docs/experiments/2026-10-07-browser-demonstration.md) · [Implementation boundaries](docs/project-guide.en.md#implemented-mechanisms-and-current-validation) · [Reproduction checks](docs/project-guide.en.md#experimental-evidence-and-reproducibility)

</details>

## What comes next

| Direction | Next milestone |
| :--- | :--- |
| Computer use | Human teaching acceptance, native macOS accessibility, cross-app tasks |
| Memory and skills | Better selection, candidate lineage, and measured transfer |
| Self-evolution | More evolving modules and failure-conditioned improvement |
| Local–cloud learning | Verified teacher trajectories, then small-model distillation |

[Complete E/C task queue](docs/plans/task-queue-2026-10-01.md) · [Research agenda](docs/project-guide.en.md#research-agenda) · [Execution handoff](docs/plans/execution-handoff-2026-10-03.md)

---

**Build with Kage:** [Issues and ideas](https://github.com/lemon5227/Kage/issues) · [Experiment archive](docs/experiments/README.md) · [Optimization history](docs/optimization_history.md)

MIT License.
