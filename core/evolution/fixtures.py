"""Explicitly synthetic E1 demo providers; never substituted for live models."""
import json

from core.model_provider import ModelProvider, ModelResponse


_CODE = '''import json
from pathlib import Path
def run(arguments, context):
    root = Path(context["workspace_dir"])
    rows = json.loads((root / arguments["input_file"]).read_text())
    rows = [dict(row, name=str(row["name"]).strip()) for row in rows]
    (root / arguments["output_file"]).write_text(json.dumps(rows))
    return {"success": True, "count": len(rows)}
'''


class FixtureOptimizer(ModelProvider):
    def generate(self, messages, **kwargs):
        return ModelResponse(text=json.dumps({
            "hypothesis": "Reusable name trimming should repair whitespace failures while preserving other fields.",
            "skill_id": "normalize", "description": "normalize record names by trimming whitespace",
            "parameters": {"type": "object", "properties": {
                "input_file": {"type": "string"}, "output_file": {"type": "string"}},
                "required": ["input_file", "output_file"], "additionalProperties": False},
            "code": _CODE,
        }), usage={"input_tokens": 80, "output_tokens": 40})


class FixtureAgent(ModelProvider):
    def generate(self, messages, **kwargs):
        observed = {}
        for message in messages:
            content = str(message.get("content", ""))
            for name in ("skill_search", "skill_call", "read_file", "write_file"):
                prefix = f"[Tool: {name}] "
                if content.startswith(prefix):
                    observed[name] = json.loads(content[len(prefix):])
        if "write_file" in observed or "skill_call" in observed:
            return ModelResponse(text="output.json written", usage={"input_tokens": 30, "output_tokens": 5})
        if "skill_search" not in observed:
            call = {"name": "skill_search", "arguments": {"query": "normalize"}}
        elif observed["skill_search"].get("skills"):
            skill = observed["skill_search"]["skills"][0]
            call = {"name": "skill_call", "arguments": {"skill_id": skill["skill_id"],
                    "digest": skill["digest"], "arguments": {"input_file": "input.json", "output_file": "output.json"}}}
        elif "read_file" not in observed:
            call = {"name": "read_file", "arguments": {"path": "input.json"}}
        else:
            call = {"name": "write_file", "arguments": {"path": "output.json",
                    "content": observed["read_file"]["content"]}}
        return ModelResponse(text="", tool_calls=[call], usage={"input_tokens": 30, "output_tokens": 15})
