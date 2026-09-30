"""Candidate-private executable skills, discovered through two stable tools.

Manifest v1: {version: 1, skills: [{skill_id, description, parameters,
entrypoint: "file.py:function", digest}]}. A digest covers canonical metadata
(excluding digest) + newline + exact Python bytes. Catalogs snapshot those bytes;
later bundle edits cannot silently change the implementation of a running task.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator, ValidationError

from core.evolution.sandbox import ProcessSkillRunner
from core.tool_registry import ToolDefinition, ToolRegistry


class SkillCatalog:
    def __init__(self, entries: dict, runner: ProcessSkillRunner):
        self._entries = entries
        self.runner = runner

    @property
    def digests(self) -> dict[str, str]:
        return {skill_id: entry[1] for skill_id, entry in self._entries.items()}

    @classmethod
    def from_bundle(cls, bundle: Path, timeout_s: float = 5, runner=None) -> "SkillCatalog":
        root = Path(bundle).resolve()
        manifest = json.loads((root / "manifest.json").read_text())
        if manifest.get("version") != 1 or not isinstance(manifest.get("skills"), list):
            raise ValueError("unsupported skill manifest")
        entries = {}
        for item in manifest["skills"]:
            descriptor = {key: item[key] for key in
                          ("skill_id", "description", "parameters", "entrypoint")}
            skill_id = descriptor["skill_id"]
            if not isinstance(skill_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", skill_id):
                raise ValueError("invalid skill_id")
            if skill_id in entries:
                raise ValueError("duplicate skill_id")
            filename, function = descriptor["entrypoint"].split(":")
            code_path = (root / filename).resolve()
            if not code_path.is_relative_to(root) or code_path.suffix != ".py" or not function.isidentifier():
                raise ValueError("invalid skill entrypoint")
            schema = descriptor["parameters"]
            if not isinstance(schema, dict) or schema.get("type") != "object":
                raise ValueError("skill parameters must be an object schema")
            Draft202012Validator.check_schema(schema)
            source = code_path.read_bytes()
            canonical = json.dumps(descriptor, sort_keys=True, separators=(",", ":"), allow_nan=False)
            digest = hashlib.sha256(canonical.encode() + b"\n" + source).hexdigest()
            if item.get("digest") != digest:
                raise ValueError(f"skill digest mismatch: {skill_id}")
            entries[skill_id] = (descriptor, digest, source, function)
        return cls(entries, runner or ProcessSkillRunner(timeout_s=timeout_s))

    def search(self, query: str, limit: int = 5) -> dict:
        terms = str(query).casefold().split()
        matches = []
        for skill_id, (descriptor, digest, _, _) in sorted(self._entries.items()):
            if all(term in f"{skill_id} {descriptor['description']}".casefold() for term in terms):
                matches.append({"skill_id": skill_id, "digest": digest,
                                "description": descriptor["description"],
                                "parameters": descriptor["parameters"]})
        return {"success": True, "skills": json.loads(json.dumps(matches[:max(1, min(10, limit))]))}

    def call(self, skill_id: str, digest: str, arguments: dict, workspace: Path) -> dict:
        entry = self._entries.get(skill_id)
        if entry is None:
            return {"success": False, "error": "UnknownSkill", "outcome": "rejected"}
        descriptor, expected, source, function = entry
        if digest != expected:
            return {"success": False, "error": "DigestMismatch", "outcome": "rejected"}
        try:
            Draft202012Validator(descriptor["parameters"]).validate(arguments)
        except ValidationError as exc:
            return {"success": False, "error": "InvalidArgument", "message": exc.message, "outcome": "rejected"}
        result = self.runner.run(source, function, arguments, workspace)
        return {**result, "success": result.get("success", True), "skill_id": skill_id, "digest": expected}

    def register_tools(self, registry: ToolRegistry, workspace: Path) -> None:
        def skill_search(query: str, limit: int = 5) -> str:
            return json.dumps(self.search(query, limit), ensure_ascii=False)

        def skill_call(skill_id: str, digest: str, arguments: dict) -> str:
            return json.dumps(self.call(skill_id, digest, arguments, workspace), ensure_ascii=False)

        registry.register(ToolDefinition(
            name="skill_search", description="Discover executable skills in this candidate; returns schemas and digests.",
            parameters={"type": "object", "properties": {
                "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}},
                "required": ["query"]}, handler=skill_search,
        ))
        registry.register(ToolDefinition(
            name="skill_call", description="Execute a discovered skill by its exact digest in the task workspace.",
            parameters={"type": "object", "properties": {
                "skill_id": {"type": "string"}, "digest": {"type": "string"},
                "arguments": {"type": "object"}}, "required": ["skill_id", "digest", "arguments"]},
            handler=skill_call,
        ))
