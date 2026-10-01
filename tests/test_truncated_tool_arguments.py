"""Malformed tool JSON must never become a seemingly valid empty-argument action."""
import io
import json
from core.model_provider import OpenAICompatibleProvider


def test_truncated_arguments_are_an_observable_provider_failure(monkeypatch):
    body = {"choices": [{"finish_reason": "length", "message": {"content": "", "tool_calls": [
        {"function": {"name": "write_file", "arguments": '{"path":"out.json","content":"'}}]}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 300}}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: io.BytesIO(json.dumps(body).encode()))
    response = OpenAICompatibleProvider("fixture").generate([{"role": "user", "content": "save"}])
    assert response.tool_calls == []
    assert response.error == "InvalidToolArguments: write_file (finish_reason=length)"
    assert response.usage == {"input_tokens": 10, "output_tokens": 300}
    assert json.loads(response.raw_output)["choices"][0]["finish_reason"] == "length"
