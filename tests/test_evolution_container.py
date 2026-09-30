"""Real Docker execution; skips only when the locally built image is unavailable."""
import shutil
import subprocess
import importlib
import json

import pytest


@pytest.fixture(scope="module")
def runner_class():
    if not shutil.which("docker"):
        pytest.skip("docker CLI unavailable")
    probe = subprocess.run(["docker", "image", "inspect", "kage-evolution:local"],
                           capture_output=True, timeout=5)
    if probe.returncode:
        pytest.skip("build sandbox/evolution/Dockerfile as kage-evolution:local to run container tests")
    module = importlib.import_module("core.evolution.sandbox")
    return module


def test_container_writes_real_artifact_and_resets_module_state(runner_class, tmp_path):
    assert hasattr(runner_class, "DockerSkillRunner"), "E1 container runner missing"
    runner = runner_class.DockerSkillRunner(timeout_s=5)
    code = b'''import json
from pathlib import Path
counter = 0
def run(arguments, context):
    global counter
    counter += 1
    Path(context["workspace_dir"], "artifact.json").write_text(json.dumps(arguments))
    return {"success": True, "counter": counter, "workspace": context["workspace_dir"]}
'''
    for workspace, value in ((tmp_path / "a", 7), (tmp_path / "b", 19)):
        result = runner.run(code, "run", {"value": value}, workspace)
        assert result["success"] and result["counter"] == 1
        assert json.loads((workspace / "artifact.json").read_text()) == {"value": value}
        assert result["workspace"] == "/workspace"


def test_container_timeout_and_next_call(runner_class, tmp_path):
    assert hasattr(runner_class, "DockerSkillRunner"), "E1 container runner missing"
    runner = runner_class.DockerSkillRunner(timeout_s=2)
    result = runner.run(b'import time\ndef run(arguments, context):\n    time.sleep(30)\n', "run", {}, tmp_path)
    assert result["success"] is False and result["error"] == "Timeout"
    recovered = runner.run(b'def run(arguments, context):\n    return {"success": True, "value": 17}\n', "run", {}, tmp_path)
    assert recovered["value"] == 17
