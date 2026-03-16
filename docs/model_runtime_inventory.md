# Model Runtime Inventory

Date: 2026-03-15
Scope: M1-1 current-state inventory for Kage local model runtime

## Current ownership

The current local inference runtime is implemented directly inside
`core/server.py`.

Responsibilities currently mixed into the server module:

- Local process lifecycle for `llama-server`
- Runtime state storage (`_llama_state`)
- Model path resolution from managed model metadata
- Command-line construction for llama.cpp
- API handlers for start/stop/status
- Provider activation logic that rewrites config to point at the local endpoint

## Existing runtime APIs

Current endpoints in `core/server.py`:

- `GET /api/models/llama/status`
- `POST /api/models/llama/start`
- `POST /api/models/llama/stop`
- `POST /api/models/activate`

These already make Kage capable of hosting its own local model runtime.
This means the product does not need to depend on external GUI wrappers
such as LM Studio.

## Existing local model flow

1. Model files are downloaded and registered via managed model metadata.
2. A start request resolves `model_id -> local path`.
3. Kage launches `llama-server` directly.
4. Activation rewrites config so the normal OpenAI-compatible provider points
   at the local endpoint.
5. Runtime status is exposed through HTTP and used by frontend surfaces.

## Current strengths

- Kage already owns the local runtime lifecycle.
- The local runtime exposes an OpenAI-compatible endpoint, so upper layers do
  not care whether the provider is local or cloud.
- The launcher/settings UI already has enough control-plane surface to manage
  local models.

## Current problems

- Runtime lifecycle logic is embedded in `core/server.py`.
- Process state, path resolution, and API concerns are coupled together.
- The module owns the subprocess handle and log file handle inline, making the
  server harder to reason about and extend.
- This will become a bottleneck once we introduce separate realtime/background
  model roles.

## Refactor target for M1-2

Extract a dedicated runtime module that owns:

- process lifecycle
- command construction
- model resolution
- runtime state

Keep `core/server.py` responsible only for:

- HTTP request validation
- calling runtime methods
- mapping runtime results into API responses

## Follow-up work

- M1-2: extract `core/local_model_runtime.py`
- M1-3: formalize runtime configuration in `config/settings.json`
- M1-4: align frontend model panels with Kage-owned runtime semantics
