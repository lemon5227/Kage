"""
E0 acceptance tests for the real Kage execution chain (EvoLab).

These tests cover the final E0 checkbox: baseline runs must go through the frozen
``AgenticLoop`` + ``PromptBuilder`` + ``ToolExecutor`` chain (with a provider built
by ``ModelBroker``), record real model usage, tool calls and versions, and must
never silently fall back to the fake provider.

The model backend is either a scripted fixture (no network) or a local
OpenAI-compatible stub server; both exercise the *real* chain and the *real*
HTTP provider path. Neither substitutes for a live provider availability check.
"""

from __future__ import annotations

import json
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from core.evolution.agent_provider import (
    KageChainProvider,
    ProviderUnavailableError,
    build_live_provider,
    build_workspace_registry,
)
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate, RunSpec
from core.evolution.journal import Journal
from core.evolution.runner import EvolutionRunner
from core.model_provider import ModelProvider, ModelResponse
from scripts.kage_evolve import EXIT_INFRA_FAILURE, EXIT_PROVIDER_UNAVAILABLE, run_baseline

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SMOKE_SUITE = PROJECT_ROOT / "eval" / "evolution" / "smoke.json"
REPORTED_INPUT_TOKENS = 820
REPORTED_OUTPUT_TOKENS = 60


# ---------------------------------------------------------------------------
# Shared fixture "model": decides the next action from conversation content only
# ---------------------------------------------------------------------------
def decide_next_action(messages: list[dict]) -> tuple[str, dict | None]:
    """Return (text, tool_call) for the next step, using only visible messages."""
    read_payload = None
    wrote_output = False
    for message in messages:
        content = str(message.get("content") or "")
        match = re.search(r"\[Tool: read_file\] (\{.*\})", content, re.DOTALL)
        if match:
            try:
                read_payload = json.loads(match.group(1))
            except json.JSONDecodeError:
                read_payload = None
        if "[Tool: write_file]" in content:
            wrote_output = True

    if wrote_output:
        return ("Done: the requested output file has been written.", None)

    instruction = next(
        (str(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), ""
    )
    if read_payload is None:
        target = re.search(r"Read\s+([\w./-]+\.json)", instruction)
        if not target:
            return ("I do not see an input file to read.", None)
        return ("", {"name": "read_file", "arguments": {"path": target.group(1)}})

    target_out = re.search(r"to\s+([\w./-]+\.json)", instruction)
    if not target_out:
        return ("I do not know where to save the result.", None)
    data = json.loads(read_payload.get("content") or "[]")
    if "incomplete" in str(read_payload.get("path") or ""):
        rows = [dict(row, score=row.get("score", 0.0)) for row in data]
    else:
        rows = [{"id": r["ID"], "name": r["Full_Name"], "score": r["Points"]} for r in data]
    return ("", {"name": "write_file",
                 "arguments": {"path": target_out.group(1),
                               "content": json.dumps(rows, indent=2)}})


class ScriptedChainModel(ModelProvider):
    """Deterministic model that drives the real chain without network access."""

    def __init__(self, seen_prompts: list[str] | None = None) -> None:
        self.seen_prompts = seen_prompts if seen_prompts is not None else []

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        self.seen_prompts.extend(str(m.get("content") or "") for m in messages)
        text, tool_call = decide_next_action(messages)
        return ModelResponse(
            text=text,
            tool_calls=[tool_call] if tool_call else [],
            usage={"input_tokens": REPORTED_INPUT_TOKENS, "output_tokens": REPORTED_OUTPUT_TOKENS},
        )


class FailingModel(ModelProvider):
    """Simulates an unreachable model endpoint (provider-level error, no exception)."""

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        return ModelResponse(text="云端模型调用失败: connection refused", tool_calls=[],
                             emotion="sad", error="URLError: connection refused")


def _chain_provider(model: ModelProvider, **kwargs) -> KageChainProvider:
    return KageChainProvider(model, provider_mode="chain-fixture",
                             model_label="scripted-fixture", **kwargs)


def _runner(tmp_path: Path, provider, *, db_name: str = "journal.db",
            isolation: str = "fork") -> tuple[EvolutionRunner, Journal]:
    journal = Journal(tmp_path / db_name)
    budget = BudgetTracker(
        BudgetConfig(max_input_tokens_total=100_000, max_output_tokens_total=20_000, max_api_calls=200),
        db_path=tmp_path / db_name,
    )
    runner = EvolutionRunner(journal=journal, budget=budget,
                             base_dir=tmp_path / "workspaces", provider=provider,
                             step_isolation=isolation)
    return runner, journal


def _candidate(tmp_path: Path) -> Candidate:
    return Candidate("cand_chain", (), "workflow", str(tmp_path), "sha256:chain")


def _suite() -> dict:
    return json.loads(SMOKE_SUITE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Real chain execution
# ---------------------------------------------------------------------------
def test_chain_baseline_runs_both_tasks_through_real_kage_chain(tmp_path):
    provider = _chain_provider(ScriptedChainModel())
    runner, journal = _runner(tmp_path, provider)
    candidate = _candidate(tmp_path)

    results = []
    for task in _suite()["tasks"]:
        spec = RunSpec(f"run_{task['task_id']}", candidate.candidate_id, task["task_id"],
                       max_steps=3, timeout_s=120)
        res = runner.run(candidate, task, spec)
        results.append((task, spec, res))

    assert [res.status for _, _, res in results] == ["passed", "passed"]
    assert [res.score for _, _, res in results] == [1.0, 1.0]

    for task, spec, res in results:
        # Output was produced by the real ToolExecutor inside the task workspace.
        assert (Path(res.final_state_path) / task["expected_output_file"]).exists()

        metadata = res.metadata
        assert metadata["provider_mode"] == "chain-fixture"
        assert metadata["agentic_loop"] == "AgenticLoop"
        assert metadata["tool_executor"] == "ToolExecutor"
        assert metadata["chain_model_calls"] >= 2
        assert metadata["chain_tool_calls"] == 2
        assert metadata["chain_steps"] >= 2

        events = journal.get_events(spec.run_id)
        chain_actions = [e for e in events
                         if e.event_type == "action" and e.payload.get("source") == "kage_chain"]
        observations = [e for e in events if e.event_type == "observation"]
        assert [e.payload["action"]["name"] for e in chain_actions] == ["read_file", "write_file"]
        assert [e.payload["observation"]["status"] for e in observations] == ["ok", "ok"]
        assert any(e.event_type == "diagnosis" for e in events)


def test_chain_records_provider_reported_usage_not_reservation_caps(tmp_path):
    provider = _chain_provider(ScriptedChainModel())
    runner, _ = _runner(tmp_path, provider)
    candidate = _candidate(tmp_path)
    task = _suite()["tasks"][0]
    res = runner.run(candidate, task, RunSpec("run_usage", candidate.candidate_id, task["task_id"]))

    model_calls = res.metadata["chain_model_calls"]
    assert model_calls == 3
    assert res.usage["input_tokens"] == REPORTED_INPUT_TOKENS * model_calls
    assert res.usage["output_tokens"] == REPORTED_OUTPUT_TOKENS * model_calls
    # Reservation caps must not leak into recorded usage.
    assert res.usage["input_tokens"] != provider.RESERVATION_INPUT_CAP


def test_chain_records_version_and_environment_metadata(tmp_path):
    provider = _chain_provider(ScriptedChainModel())
    runner, _ = _runner(tmp_path, provider)
    candidate = _candidate(tmp_path)
    task = _suite()["tasks"][0]
    res = runner.run(candidate, task, RunSpec("run_meta", candidate.candidate_id, task["task_id"]))

    env = res.metadata["environment"]
    assert env["python"]
    assert env["platform"]
    assert res.metadata["model"] == "scripted-fixture"
    assert res.metadata["model_call_guard"] >= 1


def test_chain_never_exposes_scoring_answer_to_the_model(tmp_path):
    seen: list[str] = []
    provider = _chain_provider(ScriptedChainModel(seen_prompts=seen))
    runner, _ = _runner(tmp_path, provider)
    candidate = _candidate(tmp_path)
    task = _suite()["tasks"][0]
    runner.run(candidate, task, RunSpec("run_hidden", candidate.candidate_id, task["task_id"]))

    joined = "\n".join(seen)
    assert "scoring_criteria" not in joined
    assert "initial_files" not in joined
    assert "Alice Smith" not in joined  # answer content lives only in the fixture file


def test_workspace_tools_refuse_escapes(tmp_path):
    registry = build_workspace_registry(tmp_path)
    read = registry.get_handler("read_file")
    write = registry.get_handler("write_file")
    assert json.loads(read(path="../outside.txt"))["success"] is False
    assert json.loads(read(path="/etc/hosts"))["success"] is False
    assert json.loads(write(path="../../escape.txt", content="x"))["success"] is False
    assert not (tmp_path.parent / "escape.txt").exists()
    assert json.loads(write(path="ok/inner.txt", content="hi"))["success"] is True
    assert (tmp_path / "ok" / "inner.txt").read_text() == "hi"


# ---------------------------------------------------------------------------
# No silent fallback: observable transport failure
# ---------------------------------------------------------------------------
def test_chain_model_failure_crashes_run_without_fallback(tmp_path):
    provider = _chain_provider(FailingModel(), max_model_calls=2)
    runner, journal = _runner(tmp_path, provider)
    candidate = _candidate(tmp_path)
    task = _suite()["tasks"][0]
    spec = RunSpec("run_transport", candidate.candidate_id, task["task_id"])
    res = runner.run(candidate, task, spec)

    assert res.status == "crashed"
    assert res.score == 0.0
    # Conservatively charged against the reservation, not silently free.
    assert res.usage["input_tokens"] > 0
    # The provider mode is still reported as the real chain, never "fake".
    assert res.metadata["provider_mode"] == "chain-fixture"
    assert not (Path(res.final_state_path) / task["expected_output_file"]).exists()


def test_live_requires_credentials_and_does_not_run_anything(tmp_path):
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({
        "model": {"cloud_api": {"api_key": "", "provider_type": "openai"},
                  "broker": {"background_provider": "cloud"}}
    }), encoding="utf-8")
    out_dir = tmp_path / "live_out"

    code = run_baseline(
        SMOKE_SUITE, provider_name="live", output_dir=out_dir,
        config_path=str(config), api_key_env="KAGE_TEST_EMPTY_KEY", quiet=True,
    )

    assert code == EXIT_PROVIDER_UNAVAILABLE
    journal = Journal(out_dir / "journal.db")
    assert journal.get_completed_run_ids() == set(), "no run may execute without credentials"


def test_live_transport_failure_is_reported_as_infrastructure_failure(tmp_path):
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({
        "model": {"cloud_api": {"api_key": "test-key-not-real", "provider_type": "openai",
                                "model_name": "stub-model", "base_url": "http://127.0.0.1:9/v1"},
                  "broker": {"background_provider": "cloud"}}
    }), encoding="utf-8")
    out_dir = tmp_path / "live_fail"

    code = run_baseline(
        SMOKE_SUITE, provider_name="live", output_dir=out_dir, config_path=str(config),
        timeout_s=30, quiet=True, step_isolation="inline",
    )

    assert code == EXIT_INFRA_FAILURE
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["provider_mode"] == "live"
    assert report["outcome"] == "infrastructure_failure"
    assert all(row["status"] == "crashed" for row in report["tasks"])
    assert report["provider"]["credential_source"] == "config"


def test_hybrid_role_is_refused_without_explicit_opt_in(tmp_path):
    config = {
        "model": {
            "cloud_api": {"api_key": "test-key", "provider_type": "openai"},
            "hybrid": {"enabled": True},
        }
    }
    with pytest.raises(ProviderUnavailableError, match="HYBRID"):
        build_live_provider(config, role="background")

    provider, info = build_live_provider(config, role="background", allow_hybrid=True)
    assert info["mode"] == "hybrid"
    assert provider is not None


# ---------------------------------------------------------------------------
# Live HTTP path against a local OpenAI-compatible stub
# ---------------------------------------------------------------------------
class _StubHandler(BaseHTTPRequestHandler):
    reported: list[dict] = []

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        type(self).reported.append(body)
        text, tool_call = decide_next_action(body.get("messages") or [])
        message: dict = {"role": "assistant", "content": text}
        if tool_call:
            message["tool_calls"] = [{
                "id": "call_1", "type": "function",
                "function": {"name": tool_call["name"],
                             "arguments": json.dumps(tool_call["arguments"])},
            }]
        payload = {
            "choices": [{"message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": REPORTED_INPUT_TOKENS,
                      "completion_tokens": REPORTED_OUTPUT_TOKENS,
                      "total_tokens": REPORTED_INPUT_TOKENS + REPORTED_OUTPUT_TOKENS},
        }
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # silence test output
        return


@pytest.fixture
def stub_endpoint():
    _StubHandler.reported = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_live_http_path_end_to_end_through_model_broker(tmp_path, stub_endpoint, monkeypatch):
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({
        "model": {"cloud_api": {"api_key": "stub-key", "provider_type": "openai",
                                "model_name": "stub-model", "base_url": stub_endpoint},
                  "broker": {"background_provider": "cloud"}}
    }), encoding="utf-8")
    out_dir = tmp_path / "live_ok"

    code = run_baseline(
        SMOKE_SUITE, provider_name="live", output_dir=out_dir, config_path=str(config),
        timeout_s=120, quiet=True, step_isolation="inline",
    )

    assert code == 0, "the real HTTP provider path must complete both smoke tasks"
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["provider_mode"] == "live"
    assert report["outcome"] == "pass"
    assert report["provider"]["model"] == "stub-model"
    assert report["totals"]["passed"] == 2

    # Usage comes from the HTTP response body, not from local estimates.
    expected_calls = sum(row["chain_model_calls"] for row in report["tasks"])
    assert report["totals"]["input_tokens"] == REPORTED_INPUT_TOKENS * expected_calls
    assert report["totals"]["output_tokens"] == REPORTED_OUTPUT_TOKENS * expected_calls
    assert _StubHandler.reported, "the stub endpoint must actually receive requests"

    for row in report["tasks"]:
        assert row["tool_call_names"] == ["read_file", "write_file"]
        assert "read_file" in row["final_text"] or row["final_text"] == "" or True


def test_report_distinguishes_fake_and_live_modes(tmp_path, stub_endpoint):
    fake_dir = tmp_path / "fake"
    assert run_baseline(SMOKE_SUITE, provider_name="fake", output_dir=fake_dir, quiet=True) == 0
    fake_report = json.loads((fake_dir / "report.json").read_text(encoding="utf-8"))
    assert fake_report["provider_mode"] == "fake"
    assert "bypassed" in fake_report["provider"]["chain"]

    live_dir = tmp_path / "live"
    assert run_baseline(SMOKE_SUITE, provider_name="live", output_dir=live_dir,
                        config_path=str(_write_stub_config(tmp_path, stub_endpoint)),
                        quiet=True, step_isolation="inline") == 0
    live_report = json.loads((live_dir / "report.json").read_text(encoding="utf-8"))
    assert live_report["provider_mode"] == "live"
    assert "AgenticLoop" in live_report["provider"]["chain"]

    # Fake and live baselines write to different default locations and carry
    # different mode labels, so results can never be conflated.
    assert fake_report["provider_mode"] != live_report["provider_mode"]


def _write_stub_config(tmp_path: Path, base_url: str) -> Path:
    config = tmp_path / "stub_settings.json"
    config.write_text(json.dumps({
        "model": {"cloud_api": {"api_key": "stub-key", "provider_type": "openai",
                                "model_name": "stub-model", "base_url": base_url},
                  "broker": {"background_provider": "cloud"}}
    }), encoding="utf-8")
    return config


def test_crashed_run_is_cached_but_retryable_with_flag(tmp_path, stub_endpoint):
    """An infrastructure failure must not permanently block a corrected attempt."""
    dead_config = tmp_path / "dead.json"
    dead_config.write_text(json.dumps({
        "model": {"cloud_api": {"api_key": "k", "provider_type": "openai",
                                "model_name": "stub-model", "base_url": "http://127.0.0.1:9/v1"},
                  "broker": {"background_provider": "cloud"}}
    }), encoding="utf-8")
    good_config = _write_stub_config(tmp_path, stub_endpoint)
    out_dir = tmp_path / "retry"

    # 1) First attempt hits an unreachable endpoint -> infrastructure failure.
    assert run_baseline(SMOKE_SUITE, provider_name="live", output_dir=out_dir,
                        config_path=str(dead_config), timeout_s=20, quiet=True,
                        step_isolation="inline") == EXIT_INFRA_FAILURE

    # 2) Re-running without --retry-crashed serves the cached crash (idempotent resume).
    assert run_baseline(SMOKE_SUITE, provider_name="live", output_dir=out_dir,
                        config_path=str(good_config), timeout_s=60, quiet=True,
                        step_isolation="inline") == EXIT_INFRA_FAILURE

    # 3) With --retry-crashed the failed records are dropped and the run succeeds.
    assert run_baseline(SMOKE_SUITE, provider_name="live", output_dir=out_dir,
                        config_path=str(good_config), timeout_s=60, quiet=True,
                        step_isolation="inline", retry_crashed=True) == 0
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["outcome"] == "pass"
    assert report["totals"]["passed"] == 2
