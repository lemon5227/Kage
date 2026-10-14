"""T14 (E2.1): every compared candidate records parent, generation, source and result."""

import json
import sqlite3
from pathlib import Path

from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.search import run_search

ROOT = Path(__file__).resolve().parents[1]


def _c(cid, digest, parent_ids=()):
    return Candidate(cid, tuple(parent_ids), "skill", f"/bundles/{cid}", digest * 64, hypothesis=f"h-{cid}")


def test_three_generation_chain_is_traceable(tmp_path):
    journal = Journal(tmp_path / "j.sqlite")
    root, child, grandchild = _c("root", "a"), _c("child", "b", ["root"]), _c("grand", "c", ["child"])
    assert journal.record_lineage(child, root, source={"failed_task_id": "t1"},
                                  compare={"promoted": True}) == 1
    assert journal.record_lineage(grandchild, child, compare={"promoted": False}) == 2
    chain = journal.lineage("c" * 64)
    assert [item["candidate_id"] for item in chain] == ["grand", "child", "root"]
    assert [item["generation"] for item in chain] == [2, 1, 0]
    assert chain[1]["source"] == {"failed_task_id": "t1"} and chain[1]["compare"] == {"promoted": True}
    assert chain[0]["hypothesis"] == "h-grand"
    assert [item["candidate_id"] for item in journal.lineage_all()] == ["root", "child", "grand"]


def test_old_journal_without_lineage_table_still_opens(tmp_path):
    db = tmp_path / "old.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, task_id TEXT NOT NULL,"
                 " status TEXT NOT NULL, score REAL NOT NULL, trace_path TEXT NOT NULL, usage_json TEXT NOT NULL,"
                 " final_state_path TEXT NOT NULL, progress_stagnant INTEGER NOT NULL DEFAULT 0,"
                 " rollback_count INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL)")
    conn.commit()
    conn.close()
    journal = Journal(db)
    assert journal.lineage("x" * 64) == []


def test_search_records_lineage_of_promoted_candidate(tmp_path):
    config = json.loads((ROOT / "eval/evolution/pilot.json").read_text())
    config["output_dir"] = str(tmp_path / "runs")
    path = tmp_path / "pilot.json"
    path.write_text(json.dumps(config))
    report = run_search(path, "fixture", "process")
    root = Path(report["report_path"]).parent
    chain = Journal(root / "journal.sqlite").lineage(report["active_candidate"]["digest"])
    assert [item["generation"] for item in chain] == [1, 0]
    assert chain[0]["compare"]["promoted"] is True
    assert chain[0]["source"]["failed_task_id"] == "repair-whitespace"
    assert chain[0]["hypothesis"]
