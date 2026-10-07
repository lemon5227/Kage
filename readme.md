![Kage — an anime companion and evolving agent](docs/assets/readme/companion-cover.png)

<p align="center"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

<p align="center"><sub>Haru-inspired concept illustration · Current cover character, not a permanent Kage identity · <a href="docs/assets/readme/VISUAL_STYLE.md">Visual style guide</a></sub></p>

<p align="center">
  <strong>Your companion. Your evolving agent.</strong><br>
  Live2D presence · Voice interaction · Personal memory · Evolving capabilities
</p>

<p align="center">
  <a href="docs/agent-memory-evolution-master-plan-2026-09-29.md">Research roadmap</a> ·
  <a href="docs/experiments/README.md">Experimental evidence</a> ·
  <a href="#try-the-browser-teaching-flow">Get started</a> ·
  <a href="https://github.com/lemon5227/Kage/issues">Contribute</a>
</p>

## An anime companion with an agent mind

**Kage (影) is an anime-style personal assistant for macOS:** a Live2D presence on your desktop, a voice to talk to, a personality to interact with, and an agent runtime for getting things done.

Its ambition is to grow from a desktop companion into a personal agent that works across browsers, files, and native apps, remembers useful experience, learns from teaching, and improves selected parts of its own execution system. The character makes that experience personal; memory, tools, and learning make it useful.

**Kage is not a fixed character.** The current free Live2D model is a demonstration asset, not the project's permanent face or canonical identity. Appearance, persona configuration, and agent capabilities are separate concerns. A different character should not require redefining the assistant's memory, skills, or evolution mechanisms.

### Companion first. Capabilities underneath.

- **Presence and conversation:** Live2D expressions, optional speech input/output, and a configurable interaction persona.
- **Personal assistance:** system controls, file tools, and model/tool workflows behind a desktop interface.
- **Teaching and memory:** capture corrections and verified experience, then build reusable procedures.
- **An agent that can grow:** explore skill learning, cloud teaching, and selected scaffold changes through independent experiments.

The target experience is a companion that becomes more useful as you work together. The research loop underneath is **act → verify → remember → learn → evaluate → reuse**. Local small models, optional cloud teachers, and modest Mac hardware provide the development setting.

## Research agenda

### Computer use as an open-ended action environment

Connect structured browser perception, macOS accessibility, and eventually visual grounding into an agent that can operate across application boundaries. Study task completion, recovery, and transfer through changes in content, layout, and initial state—not only whether an action API returns success.

### Continual adaptation through experience and teaching

Turn failed attempts, successful executions, human corrections, and cloud-teacher interventions into learning signals. The target is an agent that needs less assistance as useful experience accumulates. Episodic retrieval, procedural learning, and eventual model distillation are distinct adaptation mechanisms to evaluate.

### Procedural memory: from trajectories to executable capabilities

Move beyond storing conversations. Convert verified demonstrations into parameterized, composable procedures that can be discovered and applied in new situations. Bind skills to their source evidence, execution semantics, and versions, then test whether they improve transfer, reliability, or inference cost.

### Self-modifying agent scaffolds

Explore evolution of the agent's planning, retrieval, recovery, and workflow modules—not only its final answers. Generate candidate changes in isolated execution environments, load the actual changed code, compare parent and child behavior, and preserve both improvements and regressions. A recovery-module pilot is implemented; broader module evolution is the next research direction.

### Failure-conditioned evolution

Develop a mechanism for choosing **what to improve**: retrieve an experience, repair a procedure, create a skill, revise an agent module, or request teaching. Compare failure-conditioned selection with fixed rules and alternative search policies under explicit budgets. This routing method remains a planned experiment.

### Resource-aware local–cloud co-evolution

Use local models for affordable execution and cloud models for selective teaching and candidate generation. Study how verified teacher experience can become local capabilities, and measure the trade-off between assistance, task success, latency, tokens, and learning cost. Weight distillation becomes a separate experiment when trajectory quality and training/export support are sufficient.

## From memory to self-modification

![Four adaptation layers: episodic memory, procedural memory, scaffold evolution and future parametric learning](docs/assets/readme/learning-companion.svg)

**L0 / Episodic memory** retrieves relevant experience. **L1 / Procedural memory** turns behavior into executable skills. **L2 / Scaffold evolution** changes selected components of the agent itself. **L3 / Parametric learning** is the future distillation path into local-model adapters or weights.

The central question is which layer produces **persistent, transferable capability growth**—and at what cost.

## An execution loop coupled to an evolution loop

![Coupled execution and evolution loops: observe, execute and verify feed memory, candidate generation, comparison and capability transfer](docs/assets/readme/architecture-companion.svg)

The action loop and experiment loop share execution and evidence infrastructure. Browser workflows resolve semantic targets on the current page; they do not replay old element IDs or coordinates. Independent checks inspect actual saved state where a reliable checker exists. Tasks without one remain **unknown**, rather than being labeled successful because the agent stopped.

Skill execution, cloud takeover, source modification and weight training are reported separately. Promotion requires the applicable comparison to pass; an unpromoted skill can be explicitly tested without becoming a default capability.

## Try the browser teaching flow

Prerequisites: Apple Silicon macOS, Python 3.10+, Node.js 18+, and installed Chromium for Playwright. The latest verified Python environment is 3.13.11. Native Tauri development also needs its Rust/build tooling; the browser Launcher below can be used separately.

```sh
git clone https://github.com/lemon5227/Kage.git
cd Kage
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-computer-use.txt
python -m playwright install chromium
```

The full dependency set includes optional audio/model packages; microphone support may require PortAudio on macOS.

Start the control API:

```sh
KAGE_MODE=control KAGE_BROWSER_PYTHON="$PWD/.venv/bin/python" \
  python -m uvicorn core.server:app --host 127.0.0.1 --port 12345
```

In another terminal, from the repository root:

```sh
cd kage-avatar
npm install
npm run dev
```

Open **http://localhost:1420/launcher.html** and find the **Browser teaching** panel. The current Launcher UI uses Chinese labels; the [Chinese guide](README.zh-CN.md#体验浏览器教学流程) lists the corresponding panel name.

1. Choose a teaching task and the human-declared source, then start.
2. Wait until the dedicated browser is ready. Follow the visible goal, correct any mistakes, and save.
3. Finish the demonstration to run the independent check and extract a candidate.
4. Choose the new-input task, edit the JSON parameters to match its goal, and replay on a fresh page.

Recording and direct workflow replay need **no model server or cloud key**. The executor is labeled `workflow_engine`; this proves the capture/reuse path, not that a model has learned it. The separate model-consumption experiment records whether the local model actually calls the skill.

Teaching evidence defaults to `~/.kage/browser-demonstrations`; override it with `KAGE_BROWSER_DEMONSTRATIONS_DIR`. `KAGE_BROWSER_PYTHON` selects the browser-capable interpreter. The dedicated human browser is visible; automation captures are labeled separately.

For the full voice/desktop runtime, activate the environment and run `python main.py`; the native frontend can be started with `npm run tauri dev` from `kage-avatar`. Model, audio assets and macOS permissions must be configured for the chosen runtime. Do not assume the browser teaching flow configures all of them.

## Models and cloud configuration

Runtime settings are read from `~/.kage/config.json`. Local inference uses `model.local_runtime`; cloud settings use `model.cloud_api`, with optional `model.hybrid` routing. Start a compatible local server and configure its model name/host/port, or configure your chosen cloud provider. Keep API credentials outside the repository.

Cloud-assisted task learning is an explicit experimental chain. Existing runtime fallback settings are not evidence that every failed computer task automatically becomes a verified learning episode. Optional speech and cloud features may contact external services; local execution does not imply every feature is offline.

## Experimental evidence and reproducibility

<details>
<summary><strong>Implementation status and measured results</strong></summary>

### Implemented mechanisms and current validation

| Area | Implemented and observed | Current boundary |
|---|---|---|
| Agent runtime | Multi-step model/tool/observation loop, structured tool contracts, local/cloud provider routing, background jobs and cancellation | Broad task reliability is still under development |
| Desktop assistant | System commands, file tools, optional speech input/output, Tauri and Live2D interface | These features do not establish general GUI competence |
| Browser execution | DOM observations, semantic actions, stale-reference recovery, bounded workflows, actual save/readback checks | Controlled task environments; arbitrary logged-in websites are not yet supported |
| Task and teaching UI | Launcher/API task states, budgets and artifacts; browser recording, corrections, editable parameters and fresh-page replay | Teaching supports single forms with text fields, checkboxes and a save button; actual human acceptance remains pending |
| Experience and skills | Hash-bound episodes, filtered generation feedback, candidate digests, real local/cloud skill execution | Browser generalization gains remain unproven; candidates are not automatically installed |
| Module evolution | A recovery-module self-modification pilot with actual candidate code loading and independent evaluation | Selected experimental module; not ongoing autonomous rewriting of the daily runtime |

The validated local setup uses **Agents-A1-4B Q4_K_M with llama.cpp**. Cloud teaching experiments have used DeepSeek. Backends are configurable; model choice alone does not determine task success.

The latest browser teaching package passed **992 engineering tests** and verified two captures plus two fresh-input workflow replays. Its local 4B model completed both pilot tasks, but made **zero calls to the new skills**. The capture/reuse path works; automatic skill adoption and a learning advantage remain unproven. See the [full report](docs/experiments/2026-10-07-browser-demonstration.md).

</details>

The project records successes **and failures**, including model attempts, actual actions, saved-state checks, tokens, time, candidate versions and provenance. Engineering tests, real-model pilots, new-input transfer and held-out comparisons are separate levels of evidence.

- [Current experiment index](docs/experiments/README.md)
- [Browser task entry](docs/experiments/2026-10-04-browser-task-entry.md)
- [Browser teaching and reuse](docs/experiments/2026-10-07-browser-demonstration.md)
- [Browser transfer experiment, including negative results](docs/experiments/2026-10-03-browser-transfer.md)
- [File skill transfer comparison](docs/experiments/2026-10-01-c4-transfer-ablation.md)
- [Recovery-module self-modification](docs/experiments/2026-10-01-e3-recovery-self-modification.md)

Run engineering checks in an environment with the test dependencies and Playwright installed:

```sh
python -m pip install pytest pytest-asyncio httpx
python -m pytest tests -q
cd kage-avatar
npm run build
```

Most browser integration tests operate real owned Chromium pages and inspect HTTP saves/readback. Scripted actions are engineering evidence, not human demonstrations or AI benchmark scores. Raw experiment artifacts stay outside Git by default; reports identify their locations and hashes. Reproducing model pilots also requires the matching weights, runtime settings and evidence.

## Research trajectory

1. Complete actual human browser teaching acceptance; extend native macOS accessibility execution and reliable document save/readback.
2. Add native demonstrations and browser/native cross-app task families with independent checks.
3. Expand candidate lineage, compatibility and memory selection; evolve additional agent modules and evaluate failure-conditioned evolution routing.
4. Surface version changes, scores and costs; broaden held-out experiments and research reports.
5. Train small distillation adapters when verified, diverse trajectories and GPU/export support justify it. Evaluate visual grounding and inference engines against measured bottlenecks.

The complete E/C task queue and execution order live in the [roadmap](docs/agent-memory-evolution-master-plan-2026-09-29.md) and [handoff](docs/plans/execution-handoff-2026-10-03.md). The long-term aim is an agent that can **operate, learn, and redesign parts of its own problem-solving system**. The research challenge is to turn that ambition into sustained, transferable improvement with reproducible evidence.

## License

MIT. Historical routing and interface notes are retained in [the optimization history](docs/optimization_history.md).
