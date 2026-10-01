"""External task completion and bounded behavioral checks, independent of model claims."""
from __future__ import annotations
import json
import os
from pathlib import Path
import signal
import subprocess
import sys


def completion_summary(score: float, stop_reason: str, *, stagnant: bool = False,
                       run_status: str = "failed") -> dict:
    passed = score >= 1.0
    if run_status in {"timeout", "budget_exhausted", "crashed"}:
        stop_reason = {"crashed": "call_error"}.get(run_status, run_status)
    if passed:
        status = "completed"
    elif stop_reason in {"timeout", "budget_exhausted", "call_error"}:
        status = stop_reason
    elif stagnant or stop_reason == "repetition":
        status = "no_progress"
    elif stop_reason in {"step_limit", "call_limit"}:
        status = stop_reason
    else:
        status = "incomplete"
    return {"status": status, "stop_reason": stop_reason, "check_passed": passed}


# Runs candidate code in a separate, time-bounded process. This is process
# isolation for experiments, not a security sandbox or a restriction on Python.
FUNCTION_CHECK = '''import json, runpy, sys
criteria = json.loads(sys.stdin.read())
f = runpy.run_path(sys.argv[1])[criteria["function"]]
assert criteria["cases"], "no checks"
for case in criteria["cases"]:
    try:
        value = f(*case.get("args", []), **case.get("kwargs", {}))
    except Exception as exc:
        assert "raises" in case and type(exc).__name__ == case["raises"], type(exc).__name__
    else:
        assert "raises" not in case, "expected exception"
        assert value == case["expected"], repr(value)
'''


def check_python_function(path: Path, criteria: dict) -> float:
    proc = subprocess.Popen([sys.executable, "-I", "-c", FUNCTION_CHECK, str(path.resolve())],
                            cwd=path.parent, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, text=True, start_new_session=True)
    try:
        proc.communicate(json.dumps(criteria), timeout=2)
        return 1.0 if proc.returncode == 0 else 0.0
    except subprocess.TimeoutExpired:
        return 0.0
    finally:
        # Candidate imports may spawn descendants; terminate the entire check group.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
