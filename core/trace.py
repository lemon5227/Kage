import os
import time
import datetime


def enabled() -> bool:
    v = str(os.environ.get("KAGE_TRACE", "")).strip().lower()
    return v in ("1", "true", "yes", "on")


def timing_enabled() -> bool:
    v = str(os.environ.get("KAGE_TIMING_LOG", "")).strip().lower()
    return v in ("1", "true", "yes", "on")


def _log_ts_enabled() -> bool:
    v = str(os.environ.get("KAGE_LOG_TS", "")).strip().lower()
    return v in ("1", "true", "yes", "on")


def _fmt_fields(fields: dict) -> str:
    parts = []
    for k in sorted(fields.keys()):
        v = fields.get(k)
        if v is None:
            continue
        s = str(v)
        s = s.replace("\n", " ").strip()
        if len(s) > 240:
            s = s[:240] + "..."
        parts.append(f"{k}={s}")
    return " ".join(parts)


def log(component: str, event: str, **fields) -> None:
    """Print a single-line trace event when KAGE_TRACE=1."""
    if not (enabled() or timing_enabled()):
        return
    comp = str(component or "trace").strip()
    ev = str(event or "event").strip()
    extra = _fmt_fields(fields)
    if _log_ts_enabled():
        msg = f"TRACE {comp} {ev}"
    else:
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        msg = f"[{ts}] TRACE {comp} {ev}"
    if extra:
        msg += " " + extra
    try:
        print(msg, flush=True)
    except Exception:
        pass


class Span:
    """Convenience timer for tracing."""

    def __init__(self, component: str, event: str, **fields):
        self.component = component
        self.event = event
        self.fields = dict(fields)
        self.t0 = time.monotonic()
        log(component, event + ".start", **fields)

    def end(self, **fields):
        dt_ms = (time.monotonic() - self.t0) * 1000
        out = dict(self.fields)
        out.update(fields)
        out["elapsed_ms"] = f"{dt_ms:.1f}"
        log(self.component, self.event + ".end", **out)
        return dt_ms
