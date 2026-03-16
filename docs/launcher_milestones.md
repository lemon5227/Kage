# Kage Launcher (启动板) - Milestones & Status

Last updated: 2026-01-30

## Quick Dev Commands
- Rust (Tauri): `cd kage-avatar/src-tauri && cargo check`
- Frontend: `cd kage-avatar && npm run build`
- Backend (control plane):
  - `KAGE_NO_TRAY=1 KAGE_MODE=control PYTHONUNBUFFERED=1 ~/miniconda3/bin/conda run -n Kage python -u main.py`
- Unit tests:
  - `~/miniconda3/bin/conda run -n Kage python -m unittest -q tests.test_system_control`

## Product Goal
- 启动板打开后：自动启动轻量 Control Plane（秒开），并实时显示后端 stdout/stderr 日志（终端同款体验）
- 启动板提供完整模型管理：推荐目录 + 高级输入 repo id + 下载队列/进度/取消 + 已安装/删除 + 选 Active Model
- 用户点击 Launch 前：先完成模型下载与预检，避免启动后长时间等待下载/初始化
- Launch：进入重载 Runtime（初始化 KageServer/模型/ASR），并持续输出启动日志；Ready 后切主窗口

## Dev Environment Assumptions
- Conda: Miniconda
- Conda env name: `Kage` (case-sensitive)
- Dev start command for backend:
  - `~/miniconda3/bin/conda run -n Kage python -u main.py`
- Env vars:
  - `KAGE_NO_TRAY=1` (avoid Python tray conflict)
  - `KAGE_MODE=control` for Control Plane (no heavy loads)
  - `PYTHONUNBUFFERED=1` (ensure real-time logs)

## Architecture Decision
- Two-phase backend:
  - Control Plane: lightweight API (config/persona/models/download/status), no heavy initialization
  - Runtime: heavy init (KageServer, LLM, ASR, etc) starts only on user Launch

---

## Milestone M1 - Real-time Logs + Auto-start Control Plane
### Scope
- Tauri auto-starts Control Plane when launcher window opens
- Capture stdout/stderr (backend process) and stream into launcher logs UI
- Backend status events: starting/running/failed/stopped + pid/exit code
- Maintain recent logs buffer so reopening launcher still shows last lines

### Deliverables
- Rust: spawn backend with piped stdout/stderr; emit events:
  - `backend-log` { stream, line, ts }
  - `backend-status` { state, pid?, reason? }
  - `backend-exit` { code, signal? }
  - optional: `get_recent_logs` command
- Launcher UI:
  - Logs panel: append, auto-scroll, pause, clear, copy/export
  - Filtering: All / Backend / Downloader / Errors
  - Highlight stderr
- Backend (Python):
  - Support `KAGE_MODE=control` so startup is fast (no KageServer init)
  - Provide `GET /api/health` (or equivalent) for status display

### Status
- [ ] Not started
- [x] In progress
- [ ] Done

### Implementation Notes (current)
- Tauri dev: auto-start backend via `~/miniconda3/bin/conda run -n Kage python -u main.py`
- Env injected: `KAGE_NO_TRAY=1`, `KAGE_MODE=control`, `PYTHONUNBUFFERED=1`
- Rust streams backend stdout/stderr to launcher via `backend-log` + keeps a 2000-line ring buffer (`get_recent_logs`)
- Launcher subscribes to `backend-log`/`backend-status` and renders logs in UI
- Tauri capability: `kage-avatar/src-tauri/capabilities/http-localhost.json` includes `launcher` so the launcher window can call local API
- Tauri config: `kage-avatar/src-tauri/tauri.conf.json` enables capabilities `["default", "http-localhost"]`
- Launcher invokes Tauri commands via `window.__TAURI__.core.invoke` (fallback to `window.__TAURI__.invoke`)

### Notes / Risks
- If conda not found: show clear error in launcher logs, include expected path `~/miniconda3/bin/conda`

---

## Milestone M2 - Full Model Management (Catalog + Download Queue + Installed + Active)
### Scope
- Recommended model catalog + advanced "repo id" input
- Download manager with queue/progress/cancel/retry
- Installed models list (scan HF cache) + verify status
- Active model selection persisted to user config

### Deliverables
- Frontend:
  - `Models` page: Recommended + Advanced input
  - `Downloads` section: job list + progress bars + cancel/retry
  - `Installed` section: list + delete + (optional) reveal in Finder
  - Active model summary card + set active button
- Backend APIs (Control Plane):
  - `GET/POST /api/config` -> persist `~/.kage/config.json`
  - `GET /api/models` (existing) -> extend with verify/meta if needed
  - `POST /api/models/download` -> returns job_id
  - `GET /api/models/download` / `GET /api/models/download/{job_id}`
  - `POST /api/models/download/{job_id}/cancel`
  - Optional verify endpoint: `POST /api/models/verify`
- Implementation:
  - Use `huggingface_hub.snapshot_download()` for controlled downloads
  - Job state machine: queued/preparing/downloading/verifying/completed/failed/cancelled
  - Prevent delete while downloading/active runtime using that model

### Status
- [ ] Not started
- [x] In progress
- [ ] Done

### Implementation Notes (current)
- Backend (Control Plane): added download job APIs:
  - `GET /api/models/download`
  - `POST /api/models/download` (starts `huggingface_hub.snapshot_download` in a thread)
- Launcher: basic Model Manager UI in `kage-avatar/public/launcher.html` (repo id input + download list + installed list)

### Notes / Risks
- `/api/models` scanning HF cache may include partially-downloaded directories; must verify before showing "Installed"

---

## Milestone M3 - Preflight + Runtime Start + Ready Switch
### Scope
- Preflight checklist before Launch:
  - Active model downloaded & verified
  - disk space ok (optional)
  - port availability (12345) & clear diagnostics
- Runtime start endpoint triggers heavy init; logs streamed
- Once runtime ready: show main window, hide launcher

### Deliverables
- Backend:
  - `POST /api/runtime/start`
  - `GET /api/runtime/status` -> { state: booting/ready/error, detail }
  - Ensure runtime loop starts only once
- Tauri:
  - On ready: `show main` + `hide launcher`
- Fix critical logic bug:
  - Websocket handler must not create multiple `run_loop()` tasks across reconnects

### Status
- [ ] Not started
- [x] In progress
- [ ] Done

### Implementation Notes (current)
- Backend:
  - `GET/POST /api/config` (persists user config to `~/.kage/config.json`)
  - `GET /api/runtime/status`, `POST /api/runtime/start` (boot runtime on demand)
  - Download jobs: `POST /api/models/download`, `GET /api/models/download` (+ job id)
- Launcher:
  - Active model display + `Set Active`
  - Preflight: blocks Launch if active model is not installed
  - Launch now starts runtime (`/api/runtime/start`) and waits for `/api/runtime/status == ready` before switching windows

---

## UX / UI Quality Bar
- Keyboard accessible nav (use `<button>` not clickable `<div>`)
- No `transition: all`
- Clear empty/error states; actionable error messages
- Logs area: `aria-live="polite"`; copy/export
- Preflight: tells user exactly what to do next (download model / fix conda / free disk)

---

## Known Code Issues To Fix (tracked)
- [x] `core/server.py` websocket creates `run_loop()` per connection -> ensure singleton loop via `ensure_main_loop_started()`
- [ ] Config is split/unused (`core/config.py` vs hardcoded values) -> unify so launcher changes apply
- [ ] `settings.html` save() is mock + relies on implicit `event` -> either integrate into launcher or fix
