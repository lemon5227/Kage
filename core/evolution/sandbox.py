"""JSON skill execution in fresh local processes or ARM64 Docker containers."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile


_WORKER = '''import importlib.util, json, sys
from pathlib import Path
code, function, request, output = sys.argv[1:]
try:
    spec = importlib.util.spec_from_file_location("candidate_skill", code)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = json.loads(Path(request).read_text())
    result = getattr(module, function)(data["arguments"], data["context"])
    if not isinstance(result, dict):
        raise TypeError("skill must return a JSON object")
    encoded = json.dumps(result, allow_nan=False)
except BaseException as exc:
    encoded = json.dumps({"success": False, "error": "SkillExecutionError",
                          "message": type(exc).__name__ + ": " + str(exc)})
Path(output).write_text(encoded)
'''


class ProcessSkillRunner:
    def __init__(self, timeout_s: float = 5, max_output_bytes: int = 1_000_000):
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be finite and positive")
        self.timeout_s = timeout_s
        self.max_output_bytes = max_output_bytes

    def _workspace_context(self, workspace: Path) -> str:
        return str(workspace)

    def _start(self, stage, workspace, stdout, stderr):
        request = json.loads((stage / "request.json").read_text())
        return subprocess.Popen(
            [sys.executable, "-I", str(stage / "worker.py"), str(stage / "skill.py"),
             request["function"], str(stage / "request.json"), str(stage / "result.json")],
            cwd=workspace, stdout=stdout, stderr=stderr, start_new_session=True,
            env={"PATH": os.defpath, "LANG": "en_US.UTF-8"},
        )

    def _cleanup(self, proc, stage):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # On macOS the Docker CLI may have exited during container removal;
            # its old process group is no longer signalable. Reap the child first.
            if proc.poll() is None:
                proc.kill()
        proc.wait()

    def run(self, source: bytes, function: str, arguments: dict, workspace: Path) -> dict:
        workspace = Path(workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="kage-skill-") as temporary:
            stage = Path(temporary)
            (stage / "skill.py").write_bytes(source)
            (stage / "worker.py").write_text(_WORKER)
            request = {"arguments": arguments, "function": function,
                       "context": {"workspace_dir": self._workspace_context(workspace)}}
            (stage / "request.json").write_text(json.dumps(request, allow_nan=False))
            output = stage / "result.json"
            # Logs go to disk, separate from the result protocol; printed text cannot
            # masquerade as a returned JSON object or fill the parent's memory.
            with (stage / "stdout.log").open("wb") as stdout, (stage / "stderr.log").open("wb") as stderr:
                proc = self._start(stage, workspace, stdout, stderr)
                try:
                    proc.wait(timeout=self.timeout_s)
                except subprocess.TimeoutExpired:
                    return {"success": False, "error": "Timeout", "message": "skill exceeded wall time"}
                finally:
                    # Also clean up descendants of a normally completed skill.
                    self._cleanup(proc, stage)
            if proc.returncode != 0 or not output.is_file():
                return {"success": False, "error": "SkillProcessError",
                        "message": f"skill process exited with code {proc.returncode}"}
            if output.stat().st_size > self.max_output_bytes:
                return {"success": False, "error": "OutputLimit", "message": "skill output too large"}
            try:
                payload = json.loads(output.read_text())
                if not isinstance(payload, dict):
                    raise ValueError("result must be an object")
                return payload
            except (ValueError, OSError) as exc:
                return {"success": False, "error": "SkillProtocolError", "message": str(exc)}


class DockerSkillRunner(ProcessSkillRunner):
    """One ephemeral container per call. Missing Docker never falls back to host execution."""
    def __init__(self, timeout_s=10, max_output_bytes=1_000_000, image="kage-evolution:local"):
        super().__init__(timeout_s, max_output_bytes)
        probe = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=10)
        if probe.returncode:
            raise RuntimeError("Docker image unavailable; build sandbox/evolution/Dockerfile as " + image)
        self.image = image
        self.image_id = json.loads(probe.stdout)[0]["Id"]

    def _workspace_context(self, workspace):
        return "/workspace"

    def _start(self, stage, workspace, stdout, stderr):
        request = json.loads((stage / "request.json").read_text())
        return subprocess.Popen([
            "docker", "run", "--rm", "--pull=never", "--name", stage.name,
            "--platform", "linux/arm64", "--network", "none", "--read-only",
            "--memory", "256m", "--cpus", "1", "--pids-limit", "64",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--mount", f"type=bind,source={stage},target=/runtime",
            "--mount", f"type=bind,source={workspace},target=/workspace",
            self.image_id, "python", "-I", "/runtime/worker.py", "/runtime/skill.py",
            request["function"], "/runtime/request.json", "/runtime/result.json",
        ], stdout=stdout, stderr=stderr, start_new_session=True)

    def _cleanup(self, proc, stage):
        # Stopping the CLI alone does not stop its container.
        try:
            subprocess.run(["docker", "rm", "--force", stage.name],
                           capture_output=True, timeout=10)
        finally:
            super()._cleanup(proc, stage)
