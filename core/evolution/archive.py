"""Minimal E2 episode index in the existing journal database; large evidence stays in files."""
from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time


class ExperienceArchive:
    def __init__(self, journal):
        self.journal = journal
        with journal._get_connection() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS episodes (
                episode_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, family TEXT NOT NULL,
                split TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL,
                created_at REAL NOT NULL)''')

    def record(self, task_def, result):
        root = Path(result.final_state_path).resolve()
        trace = Path(result.trace_path).resolve()
        identity = {"task_id": task_def["task_id"], "run_id": result.run_id, "trace": str(trace)}
        episode_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        browser = None
        if task_def.get('fixture') and result.metadata.get('environment_kind') == 'resettable-local-http-browser':
            from core.computer_use.episodes import normalize_browser_episode
            browser = normalize_browser_episode(task_def, result, root)
        paths = [p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix not in {".jsonl", ".sqlite"}]
        if browser:
            paths.extend(Path(browser['evidence'][name]['path']) for name in ('actor-tools.jsonl', 'browser.jsonl'))
            existing = {path.resolve() for path in paths} | {trace}
            for ref in browser['evidence'].values():
                path = Path(ref['path'])
                if path.resolve() not in existing:
                    paths.append(path)
                    existing.add(path.resolve())
        paths.append(trace)
        setup_dir = root.parent / ".episode-setups"
        setup_dir.mkdir(exist_ok=True)
        setup = setup_dir / (episode_id + ".json")
        setup_fields = ("task_id", "family", "split", "instruction", "initial_files")
        if browser:
            setup_fields += ("fixture", "scoring_criteria")
        encoded_setup = json.dumps({key: task_def[key] for key in setup_fields if key in task_def},
            sort_keys=True, ensure_ascii=False)
        if setup.exists() and setup.read_text() != encoded_setup:
            raise ValueError("episode setup identity reused with different inputs")
        setup.write_text(encoded_setup)
        paths.append(setup)
        for chain in result.metadata.get("chain", []):
            snapshot = chain.get("takeover", {}).get("failure_state_ref")
            if snapshot:
                paths.extend(p for p in sorted(Path(snapshot).rglob("*")) if p.is_file())
        refs = [{"path": str(p.resolve()), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                 "bytes": p.stat().st_size} for p in paths]
        status = "verified" if result.status == "passed" and result.score >= 1 else "failed"
        payload = {"version": 1, "episode_id": episode_id, "task_id": task_def["task_id"],
                   "family": task_def.get("family", "unknown"), "split": task_def.get("split", "unknown"),
                   "goal": task_def.get("instruction", ""), "run": asdict(result), "evidence": refs}
        if browser:
            payload['browser'] = browser
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        with self.journal._get_connection() as conn:
            previous = conn.execute("SELECT payload_json FROM episodes WHERE episode_id=?", (episode_id,)).fetchone()
            if previous and previous[0] != encoded:
                raise ValueError("episode identity reused with changed evidence")
            conn.execute("INSERT OR IGNORE INTO episodes VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (episode_id, payload["task_id"], payload["family"], payload["split"], status, encoded, time.time()))
        return episode_id

    def list_episodes(self):
        with self.journal._get_connection() as conn:
            rows = conn.execute("SELECT payload_json, status FROM episodes ORDER BY created_at, episode_id").fetchall()
        return [{**json.loads(r[0]), "status": r[1]} for r in rows]

    def retrieve(self, family, limit=3, *, failure_status=None, environment=None):
        if limit < 1:
            return []
        matches = []
        seen = set()
        for episode in self.list_episodes():
            if episode["status"] != "verified" or episode["split"] != "dev" or episode["family"] != family:
                continue
            metadata = episode["run"]["metadata"]
            recorded_environment = metadata.get("environment") or metadata.get("student", {}).get("environment", {})
            if environment and any(recorded_environment.get(key) != value for key, value in environment.items()):
                continue
            if failure_status is not None and episode.get('browser', {}).get('failure_status') != failure_status and not any(
                chain.get("takeover", {}).get("student_check", {}).get("status") == failure_status
                for chain in metadata.get("chain", [])):
                continue
            try:
                intact = all(hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest() == ref["sha256"]
                             for ref in episode["evidence"])
            except OSError:
                intact = False
            if not intact:
                with self.journal._get_connection() as conn:
                    conn.execute("UPDATE episodes SET status='stale' WHERE episode_id=?", (episode["episode_id"],))
                continue
            signature = (episode["goal"], tuple(sorted(ref["sha256"] for ref in episode["evidence"])))
            if signature in seen:
                continue
            seen.add(signature)
            matches.append(episode)
            if len(matches) >= limit:
                break
        return matches
