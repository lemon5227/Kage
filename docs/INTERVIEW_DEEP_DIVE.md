# Kage Interview Deep Dive: Local LLM Agent Runtime

## 1. One-sentence Positioning

Kage is a macOS local LLM Agent Runtime / Desktop Agent System.

It is not just a chatbot or a Live2D desktop pet. It converts voice or text input into controlled desktop actions through task routing, confidence gating, structured tool execution, dialog state, safety confirmation, local model inference, ASR/TTS, and a Tauri + Live2D interface.

## 2. Project Background

The original goal was to build a local AI companion that can stay on a Mac and help users with:

- system control
- weather and web queries
- video search
- file operations
- application and web page launching
- casual chat
- TTS and Live2D feedback

During implementation, the hard problem changed. Sending every request directly to an LLM caused simple commands to become slow, tool calls to become unstable, and risky desktop actions to lack clear safety boundaries.

The real engineering question became:

> How do we turn a local LLM that can chat into an Agent Runtime that can reliably execute desktop tasks?

## 3. Core Architecture

```text
Voice/Text Input
    -> ASR / WebSocket Input
    -> Realtime Lane Classifier
    -> Route + Confidence
        -> Command Fast Path
        -> Weather / Video Fast Path
        -> Background Task Queue
        -> AgenticLoop
              -> ToolRegistry / ToolExecutor
              -> Observation / Responder
    -> TTS + Live2D + UI State
```

Key modules:

- `core/server.py`: main runtime, WebSocket, ASR/TTS integration, routing, state, and AgenticLoop wiring.
- `core/realtime_lane.py`: fast classification for weather, video, system commands, background work, and general agent work.
- `core/prompt_builder.py`: route-aware prompt construction, tool pruning, token budgeting, and command-path memory controls.
- `core/tool_registry.py`: tool schemas, arguments, descriptions, handlers, and safety levels.
- `core/tool_executor.py`: tool-call parsing, fuzzy matching, argument normalization, execution, safety checks, and logs.
- `core/agentic_loop.py`: model -> tool -> observation -> response loop for complex tasks.
- `core/interaction_state.py`: pending confirmations, video follow-ups, inferred commands, tool confirmations, and chat follow-ups.

## 4. My Main Work

- Designed and implemented the backend Agent Runtime.
- Built realtime lane classification for command, weather, video, background, and agent tasks.
- Designed route + confidence gating so high-confidence commands execute directly, medium-confidence commands ask for confirmation, and low-confidence/complex tasks enter AgenticLoop.
- Implemented command fast path for volume, brightness, Wi-Fi, Bluetooth, screenshots, app launch, and similar deterministic actions.
- Built ToolRegistry and ToolExecutor to normalize tool schemas, parse model tool calls, validate arguments, apply safety gates, and record audit logs.
- Implemented AgenticLoop for multi-step model/tool/observation workflows.
- Designed pending action/dialog state for confirmation, cancellation, follow-up, and correction turns.
- Connected local model runtime, ASR/TTS, WebSocket, Tauri, and Live2D interaction.
- Started benchmark and trace direction for route accuracy, latency, fallback rate, empty response rate, and tool success rate.

## 5. Five Core Selling Points

### 5.1 Route + Confidence

Kage does not send all tasks to the LLM. It first classifies input into routes such as:

- command
- weather/info
- video
- background
- agent
- chat

For system commands, Kage also scores confidence:

```text
confidence >= 0.9       execute directly
0.5 <= confidence < 0.9 ask for confirmation
confidence < 0.5        fall back to general agent/chat
```

This balances speed, safety, and generality.

### 5.2 Command Fast Path

Volume, brightness, Wi-Fi, Bluetooth, screenshots, and app opening are deterministic. They should not require multi-turn LLM reasoning.

The command fast path:

- reduces latency
- avoids unnecessary model calls
- avoids memory recall noise
- reduces misoperation risk
- makes the system feel like a local desktop application

### 5.3 ToolRegistry / ToolExecutor

ToolRegistry defines what the agent is allowed to do:

- tool name
- description
- argument schema
- handler
- safety level

ToolExecutor turns model intent into execution:

- parse JSON, bracket, ACTION, and Pythonic call formats
- fuzzy-match tool names when local models are inconsistent
- normalize arguments
- execute handlers
- record tool logs
- require confirmation or preview for risky operations

This is important because local or small models are often less stable with structured tool calling than hosted frontier models.

### 5.4 AgenticLoop

AgenticLoop handles complex workflows:

```text
PromptBuilder builds messages
    -> model generates tool intent
    -> ToolExecutor executes
    -> observation is appended
    -> model continues or returns final answer
```

The loop is bounded to avoid infinite execution. Fast paths and deterministic fallbacks cover simple command/info workflows so the loop is used where it adds real value.

### 5.5 Dialog State / Pending Action

Desktop users often say incomplete follow-ups:

```text
confirm
cancel
open this
not this one, the other one
the second result
```

Kage keeps pending state for:

- pending video follow-up
- pending inferred command confirmation
- pending tool confirmation
- pending chat follow-up

This lets the system handle correction, confirmation, and two-turn workflows instead of treating every message as isolated.

## 6. Design Trade-offs

### Why not send everything to the LLM?

Because deterministic tasks do not need open-ended reasoning. Sending everything to an LLM increases latency, cost, format instability, and safety risk. Route + confidence lets Kage keep fast local behavior while preserving a general agent path.

### Why disable memory recall on command paths?

Commands usually depend on the current user input, not long-term memory. For "lower the volume" or "turn on Wi-Fi", memory recall can add irrelevant context and make the model choose worse tools. Kage keeps command execution narrow and current-turn grounded.

### Why tool pruning?

Passing every tool schema to the model increases prompt length, latency, and wrong-tool probability. Kage prunes tools by route so command, info, weather, video, and chat tasks see only relevant capabilities.

### Why pending confirmation?

Desktop actions can have side effects. Delete, move, batch edit, shell execution, and ambiguous inferred commands must be previewed or confirmed before execution.

## 7. 3-minute Interview Pitch

Kage is a macOS local LLM Agent Runtime. It started as a voice desktop assistant, but the core problem became how to make an AI reliably execute desktop tasks such as system control, weather queries, video search, file operations, and chat.

The backend first receives voice/text through ASR or WebSocket. It then runs realtime lane classification. High-confidence system commands go through a command fast path. Weather and video use specialized fast paths. Long-running tasks enter a background queue. Complex or low-confidence tasks enter AgenticLoop.

I designed it this way because sending every request to an LLM is slow and risky. Adjusting volume or brightness is deterministic, so it should not require multi-step reasoning. Route + confidence gives three behaviors: high-confidence execute, medium-confidence confirm, low-confidence general agent.

I also built ToolRegistry and ToolExecutor. ToolRegistry defines tool schemas and safety levels. ToolExecutor parses model tool calls, normalizes arguments, executes handlers, records logs, and gates dangerous operations. This matters because local models often produce inconsistent tool-call formats.

The main lesson is that Agent engineering is not just prompt writing. A useful agent needs routing, state, tool boundaries, safety checks, logs, and evals. My next improvement is to make evaluation first-class: route accuracy, latency, fallback rate, empty response rate, and tool success rate.

## 8. High-frequency Interview Q&A

### Q1: Why not send all requests to the LLM?

Many desktop tasks are deterministic. System control via LLM adds latency and risk. Kage uses fast paths for high-confidence commands and saves AgenticLoop for ambiguous or complex tasks.

### Q2: How does route + confidence work?

The system classifies input into command, weather/info, video, background, agent, or chat. Command routes receive a confidence score. High confidence executes; medium confidence asks for confirmation; low confidence falls back.

### Q3: What problem does ToolRegistry solve?

It defines the agent's capability boundary. Tools have names, descriptions, parameter schemas, handlers, and safety levels, so the model interacts with structured capabilities instead of arbitrary code.

### Q4: What problem does ToolExecutor solve?

It handles messy model outputs. It parses multiple tool-call formats, normalizes arguments, checks safety, executes handlers, and returns structured observations.

### Q5: What does AgenticLoop do?

It runs bounded multi-step workflows where the model chooses a tool, the tool returns an observation, and the model continues or answers.

### Q6: How do you handle tool failures?

Tool failures become structured observations. The agent can retry or choose another tool. For common routes, deterministic fallback and template responses prevent silent empty turns.

### Q7: How do you prevent dangerous operations?

Risky tools require confirmation or preview. Tool execution is logged, and medium-confidence inferred commands ask the user before execution.

### Q8: What would you improve if you rebuilt it?

I would introduce evals earlier. Agent systems grow quickly, and without route accuracy, latency, fallback, empty response, and tool success metrics, it is hard to prove that changes improve reliability.

## 9. Resume Version

```text
Kage - macOS Local LLM Agent Runtime | Python / FastAPI / llama.cpp / Tauri / FunASR

- Designed and implemented a local LLM Agent Runtime supporting voice/text input, task routing, structured tool execution, system control, background tasks, and TTS/Live2D feedback.
- Built route + confidence gating: high-confidence commands use fast path, medium-confidence actions require confirmation, and complex workflows enter AgenticLoop.
- Implemented ToolRegistry / ToolExecutor for tool schemas, parsing, argument normalization, safety checks, audit logs, and compatibility with JSON/bracket/ACTION/Pythonic tool-call formats.
- Implemented model -> tool -> observation -> response loops with deterministic fallbacks for weather, video, file, and system-control workflows.
- Integrated local Qwen GGUF / llama-server, ASR/TTS, WebSocket, Tauri v2, and Live2D for a local-first desktop AI interaction chain.
```

## 10. Production Agent References

The project direction matches common production-agent guidance:

- OpenAI eval guidance emphasizes traces, datasets, graders, and repeatable eval runs for agent workflows.
- Anthropic's "Building Effective Agents" highlights routing as a core workflow pattern when different inputs should be handled by specialized paths.
- Google Cloud's recent agent platform materials emphasize runtime state, governance, observability, and evaluation as production concerns.

Kage maps those ideas into a local desktop runtime: route first, keep tool use structured, preserve state where user workflows need it, and measure reliability with repeatable eval cases.
