"""Generated candidates must preserve evidence, billing, and parent versions."""
import importlib.util
import json
from pathlib import Path

import pytest

from core.evolution.budget import BudgetConfig, BudgetTracker, BudgetExhaustedError
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.skills import SkillCatalog
from core.model_provider import ModelResponse


PROPOSAL = {"hypothesis": "Trimming names inside a reusable transform should fix whitespace failures.",
            "skill_id": "normalize", "description": "normalize records",
            "parameters": {"type": "object", "properties": {"records": {"type": "array"}},
                           "required": ["records"]},
            "code": 'def run(arguments, context):\n    return {"success": True, "rows": [{"name": r["name"].strip()} for r in arguments["records"]]}\n'}


class _Generator:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.messages = []

    def generate(self, messages, **kwargs):
        self.messages.append(messages)
        return ModelResponse(text=json.dumps(next(self.replies)),
                             usage={"input_tokens": 80, "output_tokens": 40})


def _parent(path):
    path.mkdir()
    (path / "manifest.json").write_text('{"version":1,"skills":[]}')
    assert importlib.util.find_spec("core.evolution.mutator"), "E1 mutator missing"
    from core.evolution.mutator import bundle_digest
    return Candidate("baseline", (), "skill", str(path), bundle_digest(path))


def _mutator(tmp_path, model, budget=None):
    from core.evolution.mutator import Mutator
    return Mutator(model, budget or BudgetTracker(), Journal(tmp_path / "journal.sqlite"),
                   tmp_path / "artifacts")


def test_generated_skill_reuses_unseen_input_without_changing_parent(tmp_path):
    parent = _parent(tmp_path / "parent")
    before = (Path(parent.bundle_path) / "manifest.json").read_bytes()
    budget = BudgetTracker()
    generator = _Generator([PROPOSAL])
    mutator = _mutator(tmp_path, generator, budget)
    feedback = {
        "instruction": "normalize names", "failure_reason": "whitespace remains",
        "scoring_criteria": {"expected": "SECRET_HOLDOUT"},
        "trace": [{"name": "read_file", "result": "observed names", "expected": "SECRET_HOLDOUT"}],
    }
    child = mutator.propose(parent, feedback)
    assert mutator.propose(parent, feedback) == child
    assert "SECRET_HOLDOUT" not in json.dumps(generator.messages)
    assert child.parent_ids == ("baseline",) and child.hypothesis == PROPOSAL["hypothesis"]
    assert (Path(parent.bundle_path) / "manifest.json").read_bytes() == before
    catalog = SkillCatalog.from_bundle(Path(child.bundle_path))
    digest = catalog.digests["normalize"]
    result = catalog.call("normalize", digest, {"records": [{"name": " Grace "}]}, tmp_path / "task")
    assert result["rows"] == [{"name": "Grace"}]
    assert budget.usage_by_type["optimizer"] == {"input": 80, "output": 40, "calls": 1}
    assert list((tmp_path / "artifacts/attempts").glob("*.json"))


def test_invalid_code_gets_repair_feedback_and_every_attempt_is_billed(tmp_path):
    parent = _parent(tmp_path / "parent")
    invalid = {**PROPOSAL, "code": "def broken("}
    model = _Generator([invalid, PROPOSAL])
    budget = BudgetTracker()
    child = _mutator(tmp_path, model, budget).propose(parent, {"failure_reason": "bad names"})
    assert "SyntaxError" in json.dumps(model.messages[1])
    assert budget.usage_by_type["optimizer"]["calls"] == 2
    assert child.digest != parent.digest


def test_repair_limit_and_budget_stop_do_not_create_a_candidate(tmp_path):
    parent = _parent(tmp_path / "parent")
    from core.evolution.mutator import MutationFailed
    model = _Generator([{"code": "invalid"}] * 4)
    budget = BudgetTracker()
    with pytest.raises(MutationFailed):
        _mutator(tmp_path, model, budget).propose(parent, {})
    assert len(model.messages) == 3 and budget.total_api_calls == 3
    assert not list((tmp_path / "artifacts/bundles").glob("*/manifest.json"))
    empty = BudgetTracker(BudgetConfig(max_api_calls=0))
    with pytest.raises(BudgetExhaustedError):
        _mutator(tmp_path / "empty-budget", _Generator([PROPOSAL]), empty).propose(parent, {})


def test_optimizer_real_http_provider_creates_executable_candidate(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from core.model_provider import OpenAICompatibleProvider
    parent = _parent(tmp_path / "parent")
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"choices": [{"message": {"content": json.dumps(PROPOSAL)}}],
                               "usage": {"prompt_tokens": 113, "completion_tokens": 71}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    budget = BudgetTracker()
    try:
        provider = OpenAICompatibleProvider("local-test", "optimizer-stub",
                    f"http://127.0.0.1:{server.server_port}/v1")
        child = _mutator(tmp_path, provider, budget).propose(parent, {"failure_reason": "whitespace"})
        catalog = SkillCatalog.from_bundle(Path(child.bundle_path))
        result = catalog.call("normalize", catalog.digests["normalize"],
                              {"records": [{"name": " New "}]}, tmp_path / "task")
        assert result["rows"] == [{"name": "New"}]
        assert requests[0]["model"] == "optimizer-stub"
        assert budget.usage_by_type["optimizer"] == {"input": 113, "output": 71, "calls": 1}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize('valid_attempt', [1, 3])
@pytest.mark.parametrize('interruption', ['response', 'publication'])
def test_restart_recovers_paid_valid_response_without_another_call(tmp_path, monkeypatch, valid_attempt, interruption):
    from core.evolution import mutator as module
    parent = _parent(tmp_path / 'parent')
    model = _Generator([{'code': 'invalid'}] * (valid_attempt - 1) + [PROPOSAL])
    db = tmp_path / 'budget.sqlite'
    budget = BudgetTracker(db_path=db)
    mutator = _mutator(tmp_path, model, budget)
    real_atomic = module.atomic_json
    def interrupt(path, data):
        if interruption == 'publication' and Path(path).name == 'proposal.json':
            raise KeyboardInterrupt('interrupt before publication')
        real_atomic(path, data)
        if interruption == 'response' and data.get('response') == json.dumps(PROPOSAL):
            raise KeyboardInterrupt('interrupt after response persistence')
    with monkeypatch.context() as patch:
        patch.setattr(module, 'atomic_json', interrupt)
        with pytest.raises(KeyboardInterrupt):
            mutator.propose(parent, {'failure_reason': 'names'})
    resumed_model = _Generator([])
    resumed_budget = BudgetTracker(db_path=db)
    child = _mutator(tmp_path, resumed_model, resumed_budget).propose(parent, {'failure_reason': 'names'})
    assert not resumed_model.messages
    assert resumed_budget.total_api_calls == valid_attempt
    catalog = SkillCatalog.from_bundle(Path(child.bundle_path))
    assert catalog.call('normalize', catalog.digests['normalize'], {'records': [{'name': ' Resume '}]}, tmp_path / 'task')['rows'] == [{'name': 'Resume'}]
