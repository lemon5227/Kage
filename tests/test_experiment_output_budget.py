"""Flexible per-call generation cannot exceed the original total output allowance."""
import io
import json
import pytest
from core.model_provider import ModelCallLimitExceeded
from scripts.experiments.flexible_output_probe import FlexibleLocalProvider


def test_flexible_calls_share_output_allowance_and_do_not_send_after_exhaustion(tmp_path, monkeypatch):
    payloads = []
    def respond(request, **kwargs):
        payloads.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "text"}}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 900}}).encode())
    monkeypatch.setattr("urllib.request.urlopen", respond)
    provider = FlexibleLocalProvider(tmp_path / "model.jsonl", api_key="fixture", total_output_tokens=1800)
    provider.generate([{"role": "user", "content": "solve"}])
    provider.generate([{"role": "user", "content": "continue"}])
    with pytest.raises(ModelCallLimitExceeded):
        provider.generate([{"role": "user", "content": "extra"}])
    assert [p["max_tokens"] for p in payloads] == [1024, 900]
