"""Explicit non-thinking mode must reach the API without changing call limits."""
import io
import json
from core.model_provider import OpenAICompatibleProvider


def test_disabled_thinking_is_sent_without_overriding_token_cap(monkeypatch):
    bodies = []
    def respond(request, **kwargs):
        bodies.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "Done"}}]}).encode())
    monkeypatch.setattr("urllib.request.urlopen", respond)
    provider = OpenAICompatibleProvider(api_key="fixture", thinking=False)
    result = provider.generate([{"role": "user", "content": "Finish"}], max_tokens=300)
    assert result.text == "Done"
    assert bodies[0]["thinking"] == {"type": "disabled"}
    assert bodies[0]["max_tokens"] == 300
    default = OpenAICompatibleProvider(api_key="fixture")
    default.generate([{"role": "user", "content": "Finish"}])
    assert "thinking" not in bodies[1]
