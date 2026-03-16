"""Tests for the new MemorySystem (Markdown + numpy + BM25, no ChromaDB)."""

import json
import os
import datetime
import tempfile
import shutil
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from core.memory import MemorySystem, _tokenize, _cosine_similarity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace directory."""
    return str(tmp_path)


@pytest.fixture
def mem(workspace):
    """Create a fresh MemorySystem with an empty workspace."""
    return MemorySystem(workspace_dir=workspace)


# ---------------------------------------------------------------------------
# Tokenizer tests
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_english_words(self):
        tokens = _tokenize("hello world")
        assert tokens == ["hello", "world"]

    def test_chinese_characters(self):
        tokens = _tokenize("你好世界")
        assert tokens == ["你", "好", "世", "界"]

    def test_mixed_chinese_english(self):
        tokens = _tokenize("打开 Safari 浏览器")
        assert "打" in tokens
        assert "开" in tokens
        assert "safari" in tokens
        assert "浏" in tokens

    def test_punctuation_stripped(self):
        tokens = _tokenize("hello, world! 你好。")
        assert "," not in tokens
        assert "!" not in tokens
        assert "。" not in tokens

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_numbers(self):
        tokens = _tokenize("test123 456")
        assert "test123" in tokens
        assert "456" in tokens


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors(self):
        a = np.array([[1.0, 0.0, 0.0]])
        sims = _cosine_similarity(a, a)
        assert sims.shape == (1, 1)
        assert abs(sims[0, 0] - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = np.array([[1.0, 0.0]])
        b = np.array([[0.0, 1.0]])
        sims = _cosine_similarity(a, b)
        assert abs(sims[0, 0]) < 1e-6

    def test_batch(self):
        a = np.array([[1.0, 0.0], [0.0, 1.0]])
        b = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        sims = _cosine_similarity(a, b)
        assert sims.shape == (2, 3)


# ---------------------------------------------------------------------------
# MemorySystem — add_memory & raw_log.jsonl
# ---------------------------------------------------------------------------

class TestAddMemory:
    def test_writes_to_raw_log(self, mem, workspace):
        mem.add_memory("hello world", importance=3, emotion="happy", type="chat")

        raw_log = os.path.join(workspace, "data", "raw_log.jsonl")
        assert os.path.exists(raw_log)

        with open(raw_log, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1

        entry = json.loads(lines[0])
        assert entry["content"] == "hello world"
        assert entry["importance"] == 3
        assert entry["emotion_data"]["emotion"] == "happy"
        assert entry["type"] == "chat"
        assert "id" in entry
        assert "timestamp" in entry

    def test_updates_in_memory_index(self, mem):
        mem.add_memory("first entry")
        mem.add_memory("second entry")
        assert len(mem._entries) == 2
        assert len(mem._corpus_tokens) == 2

    def test_default_values(self, mem):
        mem.add_memory("test")
        entry = mem._entries[0]
        assert entry["importance"] == 1
        assert entry["emotion_data"]["emotion"] == "neutral"
        assert entry["type"] == "chat"

    def test_backward_compatible_format(self, mem, workspace):
        """Ensure the raw_log.jsonl format matches the old ChromaDB-era format."""
        mem.add_memory("compat test", importance=2, emotion="sad", type="system")
        raw_log = os.path.join(workspace, "data", "raw_log.jsonl")
        with open(raw_log, "r", encoding="utf-8") as f:
            entry = json.loads(f.readline())

        # Old format fields that must be present
        assert "id" in entry
        assert "timestamp" in entry
        assert "content" in entry
        assert "emotion_data" in entry
        assert "type" in entry
        assert "importance" in entry
        assert entry["emotion_data"]["emotion"] == "sad"
        assert entry["emotion_data"]["emotion_conf"] == 1.0


# ---------------------------------------------------------------------------
# MemorySystem — BM25 search
# ---------------------------------------------------------------------------

class TestBM25Search:
    def test_basic_search(self, mem):
        mem.add_memory("打开 Safari 浏览器", importance=2)
        mem.add_memory("今天天气很好", importance=1)
        mem.add_memory("Safari 是苹果的浏览器", importance=3)

        results = mem.bm25_search("Safari", n_results=3)
        assert len(results) >= 1
        # At least one result should mention Safari
        contents = [r["content"] for r in results]
        assert any("Safari" in c for c in contents)

    def test_empty_corpus(self, workspace):
        mem = MemorySystem(workspace_dir=workspace)
        results = mem.bm25_search("anything")
        assert results == []

    def test_no_match(self, mem):
        mem.add_memory("hello world")
        results = mem.bm25_search("zzzznotfound")
        # Should return empty since no tokens match
        assert results == []

    def test_importance_ordering(self, mem):
        mem.add_memory("python programming language", importance=1)
        mem.add_memory("python is great for data science", importance=5)
        mem.add_memory("python web development", importance=3)

        results = mem.bm25_search("python", n_results=3)
        importances = [r["importance"] for r in results]
        assert importances == sorted(importances, reverse=True)

    def test_chinese_search(self, mem):
        # BM25 IDF needs enough documents for meaningful scores.
        # With only 2 docs, IDF = log((n-df+0.5)/(df+0.5)) ≈ 0 for terms
        # appearing in 1 of 2 docs.  Use a larger corpus.
        mem.add_memory("今天天气很好，适合出门", importance=2)
        mem.add_memory("我喜欢吃苹果和香蕉", importance=1)
        mem.add_memory("明天要下雨记得带伞", importance=3)
        mem.add_memory("学习编程很有趣", importance=1)
        mem.add_memory("周末去公园散步", importance=1)

        results = mem.bm25_search("天气", n_results=5)
        assert len(results) >= 1
        # The entry about weather should be in results
        contents = [r["content"] for r in results]
        assert any("天气" in c for c in contents)


# ---------------------------------------------------------------------------
# MemorySystem — recall (hybrid search)
# ---------------------------------------------------------------------------

class TestRecall:
    def test_recall_empty(self, workspace):
        mem = MemorySystem(workspace_dir=workspace)
        results = mem.recall("anything")
        assert results == []

    def test_recall_bm25_fallback_when_no_model(self, mem):
        """When vector model is not loaded, recall should fall back to BM25 only."""
        mem.add_memory("hello world", importance=2)
        mem.add_memory("goodbye world", importance=1)

        # Model is not loaded (lazy), so vector search returns None
        results = mem.recall("hello", n_results=2)
        assert len(results) >= 1
        assert any("hello" in r["content"] for r in results)

    def test_recall_importance_ordering(self, mem):
        mem.add_memory("apple fruit", importance=1)
        mem.add_memory("apple computer", importance=5)
        mem.add_memory("apple pie recipe", importance=3)

        results = mem.recall("apple", n_results=3)
        importances = [r["importance"] for r in results]
        assert importances == sorted(importances, reverse=True)

    def test_recall_with_mocked_vector_search(self, mem):
        """Test hybrid recall with mocked vector scores."""
        mem.add_memory("machine learning basics", importance=2)
        mem.add_memory("deep learning neural networks", importance=4)
        mem.add_memory("cooking recipes", importance=1)

        # Mock vector scores to favor "deep learning"
        fake_scores = np.array([0.3, 0.9, 0.1])
        with patch.object(mem, '_vector_scores', return_value=fake_scores):
            results = mem.recall("neural network", n_results=3)

        assert len(results) >= 1
        # Results should be sorted by importance
        importances = [r["importance"] for r in results]
        assert importances == sorted(importances, reverse=True)

    def test_recall_result_fields(self, mem):
        mem.add_memory("test content", importance=3, emotion="happy", type="chat")
        results = mem.recall("test", n_results=1)
        assert len(results) == 1
        r = results[0]
        assert "content" in r
        assert "emotion" in r
        assert "timestamp" in r
        assert "importance" in r
        assert "type" in r

    def test_recall_n_results_limit(self, mem):
        for i in range(10):
            mem.add_memory(f"entry number {i}", importance=i % 5 + 1)

        results = mem.recall("entry", n_results=3)
        assert len(results) <= 3


# ---------------------------------------------------------------------------
# MemorySystem — flush_daily_log
# ---------------------------------------------------------------------------

class TestFlushDailyLog:
    def test_creates_daily_file(self, mem, workspace):
        mem.flush_daily_log("Today we discussed Python.")

        today = datetime.date.today().isoformat()
        filepath = os.path.join(workspace, "memory", f"{today}.md")
        assert os.path.exists(filepath)

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Today we discussed Python." in content
        assert today in content

    def test_appends_to_existing_file(self, mem, workspace):
        mem.flush_daily_log("First summary.")
        mem.flush_daily_log("Second summary.")

        today = datetime.date.today().isoformat()
        filepath = os.path.join(workspace, "memory", f"{today}.md")
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        assert "First summary." in content
        assert "Second summary." in content

    def test_file_has_header(self, mem, workspace):
        mem.flush_daily_log("test")

        today = datetime.date.today().isoformat()
        filepath = os.path.join(workspace, "memory", f"{today}.md")
        with open(filepath, "r", encoding="utf-8") as f:
            first_line = f.readline()
        assert first_line.startswith("# ")


# ---------------------------------------------------------------------------
# MemorySystem — consolidate_old_logs
# ---------------------------------------------------------------------------

class TestConsolidateOldLogs:
    def test_consolidates_important_old_entries(self, mem, workspace):
        # Manually add entries with old timestamps
        old_ts = (datetime.datetime.now() - datetime.timedelta(days=10)).isoformat()
        recent_ts = datetime.datetime.now().isoformat()

        mem._entries = [
            {"content": "old important", "importance": 4, "timestamp": old_ts},
            {"content": "old unimportant", "importance": 1, "timestamp": old_ts},
            {"content": "recent important", "importance": 5, "timestamp": recent_ts},
        ]

        mem.consolidate_old_logs(days_threshold=7)

        memory_file = os.path.join(workspace, "memory", "MEMORY.md")
        assert os.path.exists(memory_file)

        with open(memory_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "old important" in content
        assert "old unimportant" not in content
        assert "recent important" not in content

    def test_no_entries_to_consolidate(self, mem, workspace):
        mem.add_memory("recent entry", importance=5)
        mem.consolidate_old_logs(days_threshold=7)

        memory_file = os.path.join(workspace, "memory", "MEMORY.md")
        assert not os.path.exists(memory_file)


# ---------------------------------------------------------------------------
# MemorySystem — loading from existing raw_log
# ---------------------------------------------------------------------------

class TestLoadFromRawLog:
    def test_loads_existing_entries(self, workspace):
        # Pre-populate raw_log.jsonl
        data_dir = os.path.join(workspace, "data")
        os.makedirs(data_dir, exist_ok=True)
        raw_log = os.path.join(data_dir, "raw_log.jsonl")

        entries = [
            {"id": "1", "timestamp": "2025-01-01T00:00:00", "content": "hello",
             "emotion_data": {"emotion": "neutral", "emotion_conf": 1.0},
             "type": "chat", "importance": 2},
            {"id": "2", "timestamp": "2025-01-01T00:01:00", "content": "world",
             "emotion_data": {"emotion": "happy", "emotion_conf": 1.0},
             "type": "chat", "importance": 4},
        ]
        with open(raw_log, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

        mem = MemorySystem(workspace_dir=workspace)
        assert len(mem._entries) == 2
        assert mem._entries[0]["content"] == "hello"
        assert mem._entries[1]["content"] == "world"

    def test_skips_malformed_lines(self, workspace):
        data_dir = os.path.join(workspace, "data")
        os.makedirs(data_dir, exist_ok=True)
        raw_log = os.path.join(data_dir, "raw_log.jsonl")

        with open(raw_log, "w", encoding="utf-8") as f:
            f.write('{"content": "good line", "importance": 1}\n')
            f.write('this is not json\n')
            f.write('{"content": "another good", "importance": 2}\n')

        mem = MemorySystem(workspace_dir=workspace)
        assert len(mem._entries) == 2

    def test_empty_raw_log(self, workspace):
        data_dir = os.path.join(workspace, "data")
        os.makedirs(data_dir, exist_ok=True)
        raw_log = os.path.join(data_dir, "raw_log.jsonl")
        with open(raw_log, "w") as f:
            pass  # empty file

        mem = MemorySystem(workspace_dir=workspace)
        assert len(mem._entries) == 0


# ---------------------------------------------------------------------------
# MemorySystem — vector search with mocked model
# ---------------------------------------------------------------------------

class TestVectorSearch:
    def test_vector_search_with_mock(self, mem):
        """Test vector_search with a mocked sentence-transformers model."""
        mem.add_memory("machine learning", importance=3)
        mem.add_memory("cooking recipes", importance=1)
        mem.add_memory("deep learning", importance=5)

        # Create a mock model
        mock_model = MagicMock()
        # Fake embeddings: 3 entries, 4-dim vectors
        fake_embeddings = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.9, 0.1, 0.0, 0.0],
        ])
        # Query embedding close to entry 0 and 2
        mock_model.encode.return_value = np.array([[0.95, 0.05, 0.0, 0.0]])

        mem._model = mock_model
        mem._embeddings = fake_embeddings

        results = mem.vector_search("machine learning concepts", n_results=2)
        assert len(results) == 2
        # Results sorted by importance
        importances = [r["importance"] for r in results]
        assert importances == sorted(importances, reverse=True)

    def test_vector_search_no_model(self, mem):
        """When model can't be loaded, vector_search returns empty."""
        mem.add_memory("test")
        # Don't load model — _model stays None
        # Patch _ensure_model to do nothing (simulating model load failure)
        with patch.object(mem, '_ensure_model'):
            results = mem.vector_search("test")
        assert results == []


# ---------------------------------------------------------------------------
# MemorySystem — graceful degradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def test_recall_when_bm25_fails(self, mem):
        """If BM25 fails, recall should still work via vector scores."""
        mem.add_memory("test entry", importance=3)

        fake_vec_scores = np.array([0.8])
        with patch.object(mem, '_bm25_scores', side_effect=Exception("BM25 error")):
            with patch.object(mem, '_vector_scores', return_value=fake_vec_scores):
                results = mem.recall("test", n_results=1)
        assert len(results) == 1

    def test_recall_when_vector_fails(self, mem):
        """If vector search fails, recall should still work via BM25."""
        mem.add_memory("test entry", importance=3)

        with patch.object(mem, '_vector_scores', side_effect=Exception("Vector error")):
            results = mem.recall("test", n_results=1)
        assert len(results) >= 1

    def test_recall_when_both_fail(self, mem):
        """If both searches fail, recall returns empty list."""
        mem.add_memory("test entry", importance=3)

        with patch.object(mem, '_bm25_scores', side_effect=Exception("BM25 error")):
            with patch.object(mem, '_vector_scores', side_effect=Exception("Vec error")):
                results = mem.recall("test", n_results=1)
        assert results == []


# ---------------------------------------------------------------------------
# Directory initialization
# ---------------------------------------------------------------------------

class TestDirectoryInit:
    def test_creates_directories(self, workspace):
        mem = MemorySystem(workspace_dir=workspace)
        assert os.path.isdir(os.path.join(workspace, "memory"))
        assert os.path.isdir(os.path.join(workspace, "data"))
