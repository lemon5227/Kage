"""Budgeted model proposals become immutable, candidate-private skill bundles."""
from __future__ import annotations

import ast
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid

from jsonschema import SchemaError

from core.evolution.budget import BudgetTracker
from core.evolution.artifacts import atomic_json
from core.evolution.contracts import Candidate, EvolutionEvent
from core.evolution.journal import Journal
from core.evolution.skills import SkillCatalog


def bundle_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            relative = str(path.relative_to(root)).encode()
            content = path.read_bytes()
            digest.update(len(relative).to_bytes(8, "big") + relative)
            digest.update(len(content).to_bytes(8, "big") + content)
    return digest.hexdigest()


def _visible_feedback(value):
    if isinstance(value, dict):
        return {key: _visible_feedback(item) for key, item in value.items()
                if key not in {"scoring_criteria", "expected", "initial_files"}}
    if isinstance(value, list):
        return [_visible_feedback(item) for item in value]
    return value


class MutationFailed(ValueError):
    pass


class Mutator:
    target = "skill"
    def __init__(self, model, budget: BudgetTracker, journal: Journal, root: Path,
                 input_cap: int = 12_000, output_cap: int = 3_000):
        self.model, self.budget, self.journal = model, budget, journal
        self.root = Path(root)
        self.input_cap, self.output_cap = input_cap, output_cap

    def _messages(self, source, manifest, feedback):
        return [{"role": "system", "content": (
            "Generate a reusable Python standard-library skill from the observed failure. "
            "Return ONLY a JSON object with hypothesis, skill_id, description, parameters "
            "(JSON Schema object), and code. code must define run(arguments, context)->dict. "
            "context['workspace_dir'] is the task directory. Use relative workspace files. "
            "Do not hardcode example answers. Your hypothesis is a proposal, not verified evidence."
        )}, {"role": "user", "content": json.dumps({
            "parent_manifest": manifest,
            "failure": _visible_feedback({key: feedback[key] for key in
                ("task_id", "instruction", "failure_reason", "trace") if key in feedback}),
        }, ensure_ascii=False)}]

    def _validate_parent(self, source):
        SkillCatalog.from_bundle(source)

    def _validate_request(self, messages):
        """Optional protocol-specific request bound before reserving a model call."""

    def _apply_proposal(self, stage, manifest, proposal):
        code = proposal["code"]
        tree = ast.parse(code)
        if not any(isinstance(node, ast.FunctionDef) and node.name == "run" for node in tree.body):
            raise ValueError("code must define run(arguments, context)")
        descriptor = {key: proposal[key] for key in ("skill_id", "description", "parameters")}
        filename = "skill-" + hashlib.sha256(code.encode()).hexdigest() + ".py"
        descriptor["entrypoint"] = filename + ":run"
        canonical = json.dumps(descriptor, sort_keys=True, separators=(",", ":"), allow_nan=False)
        descriptor["digest"] = hashlib.sha256(canonical.encode() + b"\n" + code.encode()).hexdigest()
        (stage / filename).write_text(code)
        updated = {**manifest, "skills": [item for item in manifest["skills"]
                   if item["skill_id"] != descriptor["skill_id"]] + [descriptor]}
        (stage / "manifest.json").write_text(json.dumps(updated, sort_keys=True, allow_nan=False))
        SkillCatalog.from_bundle(stage)

    def propose(self, parent: Candidate, feedback: dict, target=None) -> Candidate:
        target = target or self.target
        if target != self.target:
            raise ValueError(f"mutator supports only {self.target} candidates")
        source = Path(parent.bundle_path)
        if bundle_digest(source) != parent.digest:
            raise ValueError("parent bundle digest mismatch")
        self._validate_parent(source)
        manifest = json.loads((source / "manifest.json").read_text())
        messages = self._messages(source, manifest, feedback)
        fingerprint = hashlib.sha256(json.dumps(messages, sort_keys=True).encode()
                                      + parent.digest.encode()).hexdigest()
        request_path = self.root / "request.json"
        if request_path.exists() and json.loads(request_path.read_text())["fingerprint"] != fingerprint:
            raise ValueError("proposal slot reused with different inputs")
        cache_path = self.root / "proposal.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text())
            if cached["fingerprint"] != fingerprint:
                raise ValueError("proposal slot reused with different inputs")
            data = cached["candidate"]
            data["parent_ids"] = tuple(data["parent_ids"])
            candidate = Candidate(**data)
            if bundle_digest(Path(candidate.bundle_path)) != candidate.digest:
                raise ValueError("cached proposal digest mismatch")
            return candidate
        proposal_id = "mutation-" + uuid.uuid4().hex
        attempts = self.root / "attempts"
        bundles = self.root / "bundles"
        attempts.mkdir(parents=True, exist_ok=True)
        bundles.mkdir(parents=True, exist_ok=True)
        atomic_json(request_path, {"fingerprint": fingerprint})
        def publish(raw, proposal_id, attempt, attempt_path):
            proposal = json.loads(raw)
            hypothesis = proposal["hypothesis"]
            if not isinstance(hypothesis, str) or not hypothesis.strip():
                raise ValueError("non-empty hypothesis required")
            with tempfile.TemporaryDirectory(dir=bundles, prefix="draft-") as temporary:
                stage = Path(temporary)
                shutil.copytree(source, stage, dirs_exist_ok=True)
                self._apply_proposal(stage, manifest, proposal)
                digest = bundle_digest(stage)
                destination = bundles / digest
                if not destination.exists():
                    stage.rename(destination)
                elif bundle_digest(destination) != digest:
                    raise ValueError("existing artifact has mismatched digest")
            child = Candidate(self.target + "-" + digest[:16], (parent.candidate_id,), self.target,
                              str(destination.resolve()), digest, hypothesis.strip(), parent.island_id)
            self.journal.record_event(EvolutionEvent(proposal_id, child.candidate_id,
                str(feedback.get("task_id", "")), attempt, "mutation",
                {"parent_id": parent.candidate_id, "digest": digest, "hypothesis": child.hypothesis,
                 "attempt_path": str(attempt_path), "valid": True}))
            atomic_json(cache_path, {"fingerprint": fingerprint, "candidate": asdict(child)})
            return child

        existing = sorted(attempts.glob("*.json"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
        for saved in existing:
            previous = json.loads(saved.read_text())
            # A persisted response may not have reached validation/publication.
            # Replay it before consuming another paid repair, including attempt 3.
            if previous.get("response") and not previous.get("validation_error") and not previous.get("provider_error"):
                try:
                    return publish(previous["response"], saved.stem.rsplit("-", 1)[0],
                                   previous["attempt"], saved)
                except (ValueError, TypeError, KeyError, SyntaxError, SchemaError) as exc:
                    previous["validation_error"] = f"{type(exc).__name__}: {exc}"
                    atomic_json(saved, previous)
            messages.extend([{"role": "assistant", "content": previous["response"]},
                             {"role": "user", "content": "Repair this candidate: " + previous.get("validation_error", "interrupted attempt")}])
        for attempt in range(len(existing), 3):  # repairs remain bounded after restart
            self._validate_request(messages)
            reservation = self.budget.reserve(self.input_cap, self.output_cap,
                                              call_type="optimizer", run_id=proposal_id)
            attempt_path = attempts / f"{proposal_id}-{attempt}.json"
            atomic_json(attempt_path, {"parent_id": parent.candidate_id, "attempt": attempt,
                "response": "", "usage": {}, "validation_error": "interrupted attempt"})
            response = None
            try:
                response = self.model.generate(messages=messages, max_tokens=self.output_cap)
            finally:
                self.budget.settle(reservation, getattr(response, "usage", None))
            raw = str(getattr(response, "text", "") or "")
            error = getattr(response, "error", None)
            record = {"parent_id": parent.candidate_id, "attempt": attempt,
                      "response": raw, "provider_error": error,
                      "usage": getattr(response, "usage", {})}
            atomic_json(attempt_path, record)
            if error:
                raise RuntimeError(f"optimizer unavailable: {error}")
            try:
                return publish(raw, proposal_id, attempt, attempt_path)
            except (ValueError, TypeError, KeyError, SyntaxError, SchemaError) as exc:
                diagnostic = f"{type(exc).__name__}: {exc}"
                record["validation_error"] = diagnostic
                atomic_json(attempt_path, record)
                self.journal.record_event(EvolutionEvent(proposal_id, parent.candidate_id,
                    str(feedback.get("task_id", "")), attempt, "mutation",
                    {"valid": False, "error": diagnostic, "attempt_path": str(attempt_path)}))
                messages.extend([{"role": "assistant", "content": raw},
                                 {"role": "user", "content": "Repair this candidate: " + diagnostic}])
        raise MutationFailed("candidate invalid after initial proposal and two repairs")
