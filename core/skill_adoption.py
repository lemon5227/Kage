"""Promoted skill -> user consent -> daily ToolRegistry.

Only a candidate that the Promoter promoted (recorded by the EvolutionScheduler)
can be adopted, and only after the user accepts the proactive offer. Adoption:

  1. verifies the candidate bundle still has the digest the Promoter evaluated;
  2. copies it into an immutable snapshot under ``~/.kage/skills/adopted/<digest>``
     and verifies the copy again (what was evaluated is what will run);
  3. registers each skill as ``custom_<skill_id>`` via ``ToolRegistry.register_custom``
     (fixed namespace, never overrides an existing tool);
  4. executes calls through SkillCatalog's runner — Docker by default — so generated
     code never runs inside the Kage process.

``~/.kage/skills/adopted.json`` lists adopted snapshots; ``restore()`` re-verifies
and re-registers them at startup.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Optional

from core.evolution.mutator import bundle_digest
from core.evolution.skills import SkillCatalog
from core.tool_registry import ToolDefinition, ToolRegistry

DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def tool_name_for(skill_id: str) -> str:
    return "custom_" + re.sub(r"[^A-Za-z0-9_]", "_", skill_id).lower()


def default_runner_factory():
    from core.evolution.sandbox import DockerSkillRunner
    return DockerSkillRunner()  # raises when Docker/the image is unavailable: never falls back to host


class SkillAdoption:
    def __init__(self, registry: ToolRegistry, *, workspace_dir: str = "~/.kage",
                 runner_factory: Callable[[], Any] = default_runner_factory,
                 now_fn: Callable[[], float] = time.time) -> None:
        self.registry = registry
        self.runner_factory = runner_factory
        self.now_fn = now_fn
        self.base = Path(os.path.expanduser(workspace_dir)) / "skills"
        self.snapshots = self.base / "adopted"
        self.index_path = self.base / "adopted.json"
        self.exec_workspace = self.base / "workspace"

    # ------------------------------------------------------------------ index
    def adopted(self) -> list[dict]:
        try:
            rows = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return rows if isinstance(rows, list) else []

    def _write_index(self, rows: list[dict]) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.index_path)

    # --------------------------------------------------------------- adoption
    def _register(self, snapshot: Path, digest: str) -> list[str]:
        if bundle_digest(snapshot) != digest:
            raise ValueError("adopted snapshot digest mismatch")
        catalog = SkillCatalog.from_bundle(snapshot, runner=self.runner_factory())
        self.exec_workspace.mkdir(parents=True, exist_ok=True)
        names = []
        for skill_id, skill_digest in sorted(catalog.digests.items()):
            descriptor = catalog._entries[skill_id][0]

            handler = self._handler(catalog, skill_id, skill_digest)

            name = tool_name_for(skill_id)
            self.registry.register_custom(ToolDefinition(
                name=name,
                description=f"[自学技能] {descriptor['description']}",
                parameters=descriptor["parameters"],
                handler=handler,
                safety_level="SAFE",  # runs in the isolated runner, not in-process
            ))
            names.append(name)
        return names

    def _handler(self, catalog: SkillCatalog, skill_id: str, skill_digest: str) -> Callable[..., str]:
        # Bound by closure (not default arguments) so model-supplied keys cannot redirect the call.
        def handler(**arguments) -> str:
            return json.dumps(catalog.call(skill_id, skill_digest, arguments, self.exec_workspace),
                              ensure_ascii=False)
        return handler

    def adopt(self, candidate: dict, *, source_run: str = "") -> dict:
        """Adopt a promoted candidate (dict with ``bundle_path`` and ``digest``)."""
        digest = str(candidate.get("digest") or "")
        if not DIGEST_RE.fullmatch(digest):
            raise ValueError("candidate digest must be 64 hex characters")
        if any(row.get("digest") == digest for row in self.adopted()):
            raise ValueError("candidate already adopted")
        bundle = Path(str(candidate.get("bundle_path") or ""))
        if not (bundle / "manifest.json").is_file():
            raise ValueError("candidate bundle missing")
        if bundle_digest(bundle) != digest:
            raise ValueError("candidate bundle changed since it was evaluated")
        snapshot = self.snapshots / digest
        if snapshot.exists():
            shutil.rmtree(snapshot)
        shutil.copytree(bundle, snapshot, symlinks=False)
        try:
            names = self._register(snapshot, digest)
        except Exception:
            shutil.rmtree(snapshot, ignore_errors=True)
            raise
        row = {"digest": digest, "candidate_id": candidate.get("candidate_id"), "tools": names,
               "snapshot": str(snapshot), "source_run": source_run, "adopted_at": self.now_fn()}
        self._write_index(self.adopted() + [row])
        return row

    def restore(self) -> list[str]:
        """Re-register adopted skills at startup; entries failing verification are skipped."""
        restored: list[str] = []
        for row in self.adopted():
            try:
                restored += self._register(Path(row["snapshot"]), str(row["digest"]))
            except Exception:
                continue
        return restored

    def revoke(self, digest: str) -> bool:
        rows = self.adopted()
        keep = [r for r in rows if r.get("digest") != digest]
        if len(keep) == len(rows):
            return False
        for row in rows:
            if row.get("digest") == digest:
                for name in row.get("tools", []):
                    self.registry.unregister(name)
        self._write_index(keep)
        return True
