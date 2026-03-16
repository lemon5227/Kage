# Launcher Design System (Draft)

Scope: `kage-avatar/public/launcher.html`

Last updated: 2026-01-31

## Intent
- “Big company” desktop launcher: calm, legible, low-noise.
- Treat logs as a first-class surface (debuggable, scannable).
- Prefer structure + hierarchy over decoration.

## Visual Foundations

### Typography
- Primary: system UI (macOS) via `-apple-system, BlinkMacSystemFont, SF Pro Display, SF Pro Text, Helvetica Neue`.
- Size scale:
  - H1: 22/28, weight 700
  - Card title: 13/18, weight 700
  - Body: 13/18, weight 450-500
  - Meta: 12/16, muted
  - Mono/log: 12/16, `ui-monospace` stack

### Color
- Background: near-neutral with subtle “air” gradients.
- Accent: Apple blue (`#0a84ff`) for primary actions.
- Success: green (`#10b981`), Danger: `#d92d20`.
- Log surface: deep slate/ink background with high-contrast text.

### Elevation
- Two levels:
  - `--shadow-sm`: default panel/card
  - `--shadow-md`: hover/focus emphasis

### Motion
- Only transform/opacity transitions.
- Respect `prefers-reduced-motion`.

## Components

### Navigation
- Use `<button>` items with visible focus.
- Active state: light panel fill + subtle blue border.

### Cards
- Card title always present.
- Avoid large decorative gradients inside cards; keep them utilitarian.

### Buttons
- Primary: solid accent.
- Secondary: neutral panel fill (optional).
- Destructive: use danger color + confirm.

### Logs
- `role="log"` + `aria-live="polite"`.
- Provide: filter, pause autoscroll, copy/export, and clear.

## Recommended Settings to Add (Product)

### Startup
- Auto-start backend on launcher open (toggle).
- Frontend-only mode (for avatar framing/dev).
- Auto-start at login (platform-specific).

### Audio
- TTS voice picker + “Preview voice” button.
- Microphone device selector.
- Wake word enable/disable + sensitivity.

### Models
- Recommended catalog + search.
- Downloads: progress/ETA/cancel.
- Storage: cache location + pruning policy.

### Diagnostics
- Port, PID, runtime stage.
- “Copy diagnostics” (last N log lines + system info).
