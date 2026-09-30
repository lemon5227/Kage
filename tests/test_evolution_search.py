"""The CLI search must produce measured improvement and an explicit provider mode."""
import json
import subprocess
import sys
import shutil
import pytest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_search_cli_runs_full_fixture_loop_and_reuses_active_skill(tmp_path):
    config = tmp_path / "pilot.json"
    template = ROOT / "eval/evolution/pilot.json"
    assert template.exists(), "E1 pilot config missing"
    settings = json.loads(template.read_text())
    settings["output_dir"] = str(tmp_path / "runs")
    settings["execution_mode"] = "process"
    config.write_text(json.dumps(settings))
    result = subprocess.run([sys.executable, "scripts/kage_evolve.py", "search", "--config", str(config),
                             "--provider", "fixture"], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    report_path = tmp_path / "runs" / "fixture" / "pilot" / "seed-42" / "report.json"
    report = json.loads(report_path.read_text())
    assert report["provider_mode"] == "fixture"
    assert report["comparisons"][0]["parent_score"] == 0.5
    assert report["comparisons"][0]["child_score"] == 1
    assert report["reuse"][0]["score"] == 1
    assert report["usage_by_type"]["optimizer"]["calls"] == 1
    assert (report_path.parent / "active.json").exists()
    rerun = subprocess.run([sys.executable, "scripts/kage_evolve.py", "search", "--config", str(config),
                            "--provider", "fixture"], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert rerun.returncode == 0, rerun.stderr
    resumed = json.loads(report_path.read_text())
    assert resumed["total_api_calls"] == report["total_api_calls"]


def test_live_unreachable_endpoint_returns_infrastructure_exit_code(tmp_path):
    if not shutil.which("docker") or subprocess.run(
        ["docker", "image", "inspect", "kage-evolution:local"], capture_output=True, timeout=5).returncode:
        pytest.skip("local container image required for live-path integration")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"model": {
        "cloud_api": {"api_key": "local-test-not-real", "provider_type": "openai",
                      "model_name": "stub-model", "base_url": "http://127.0.0.1:9/v1"},
        "broker": {"background_provider": "cloud"}}}))
    config = json.loads((ROOT / "eval/evolution/pilot.json").read_text())
    config.update({"settings": str(settings), "output_dir": str(tmp_path / "runs")})
    config_path = tmp_path / "pilot.json"
    config_path.write_text(json.dumps(config))
    result = subprocess.run([sys.executable, "scripts/kage_evolve.py", "search", "--config", str(config_path),
                             "--provider", "live"], cwd=ROOT, capture_output=True, timeout=20)
    assert result.returncode == 3
    report = json.loads((tmp_path / "runs/live/pilot/seed-42/report.json").read_text())
    assert all(run["status"] == "crashed" for run in report["baseline"])
    assert report["usage_by_type"]["optimizer"]["calls"] == 0
    changed = json.loads(settings.read_text())
    changed["model"]["cloud_api"]["model_name"] = "different-model"
    settings.write_text(json.dumps(changed))
    retry = subprocess.run([sys.executable, "scripts/kage_evolve.py", "search", "--config", str(config_path),
                            "--provider", "live"], cwd=ROOT, capture_output=True, timeout=20)
    assert retry.returncode == 1, "changing the effective model must not reuse the old report"
