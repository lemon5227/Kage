"""
Memory System — 分层记忆：短期(Session) + 日志(Markdown) + 长期(numpy 向量 + BM25)

存储层：
- ~/.kage/memory/YYYY-MM-DD.md — 每日对话摘要（Markdown）
- ~/.kage/memory/MEMORY.md — 长期精选记忆
- ~/.kage/data/raw_log.jsonl — 原始日志（保留兼容）

检索层：
- BM25 关键词搜索（rank_bm25）
- sentence-transformers 生成 embedding + numpy 余弦相似度
- 混合权重：BM25(0.3) + 向量(0.7)
"""

import json
import uuid
import os
import re
import datetime
import logging
import contextlib
import io
import warnings
from typing import Optional

import numpy as np
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer for mixed Chinese/English text.

    Splits on whitespace and punctuation, keeps Chinese characters as
    individual tokens, and lowercases Latin tokens.  No jieba dependency.
    """
    tokens: list[str] = []
    # Split into runs of CJK chars, ASCII words, or skip punctuation/spaces
    for match in re.finditer(r'[\u4e00-\u9fff]|[a-zA-Z0-9]+', text):
        tokens.append(match.group().lower())
    return tokens


class MemorySystem:
    """分层记忆系统 — Markdown + numpy + BM25 (no ChromaDB)."""

    def __init__(self, workspace_dir: str = "~/.kage"):
        workspace = os.path.expanduser(workspace_dir)

        self.memory_dir = os.path.join(workspace, "memory")
        self.data_dir = os.path.join(workspace, "data")
        os.makedirs(self.memory_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

        self.raw_log_file = os.path.join(self.data_dir, "raw_log.jsonl")

        # In-memory stores
        self._entries: list[dict] = []       # all memory entries
        self._corpus_tokens: list[list[str]] = []  # tokenized content per entry
        self._bm25: Optional[BM25Okapi] = None

        # Vector search (lazy-loaded)
        self._model = None                   # SentenceTransformer model
        self._embeddings: Optional[np.ndarray] = None  # (N, dim) matrix

        # Load existing entries from raw_log.jsonl
        self._load_from_raw_log()

        logger.info("MemorySystem initialized — %d entries loaded from raw_log", len(self._entries))

    # ------------------------------------------------------------------
    # Startup helpers
    # ------------------------------------------------------------------

    def _load_from_raw_log(self) -> None:
        """Load existing entries from raw_log.jsonl into in-memory indices."""
        if not os.path.exists(self.raw_log_file):
            return

        entries: list[dict] = []
        with open(self.raw_log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entries.append(entry)
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed line in raw_log.jsonl")

        for entry in entries:
            content = entry.get("content", "")
            self._entries.append(entry)
            self._corpus_tokens.append(_tokenize(content))

        self._rebuild_bm25()

    def _rebuild_bm25(self) -> None:
        """Rebuild the BM25 index from current corpus tokens."""
        if self._corpus_tokens:
            self._bm25 = BM25Okapi(self._corpus_tokens)
        else:
            self._bm25 = None

    # ------------------------------------------------------------------
    # Lazy model loading
    # ------------------------------------------------------------------

    def _ensure_model(self):
        """Lazy-load the sentence-transformers model on first use."""
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            # Keep CLI output clean: suppress HF hub warnings and transformer load noise.
            warnings.filterwarnings(
                "ignore",
                message=r"You are sending unauthenticated requests to the HF Hub\..*",
            )
            try:
                # Transformers uses its own logger.
                from transformers.utils import logging as _hf_logging

                _hf_logging.set_verbosity_error()
            except Exception:
                pass
            for noisy in ("huggingface_hub", "sentence_transformers", "transformers"):
                try:
                    logging.getLogger(noisy).setLevel(logging.ERROR)
                except Exception:
                    pass

            # Some backends print progress bars to stdout/stderr; silence them.
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self._model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Sentence-transformers model loaded")
            # Encode all existing entries
            if self._entries:
                texts = [e.get("content", "") for e in self._entries]
                self._embeddings = self._model.encode(texts, show_progress_bar=False)
            else:
                self._embeddings = None
        except Exception as exc:
            logger.error("Failed to load sentence-transformers model: %s", exc)
            self._model = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_memory(
        self,
        content: str,
        importance: int = 1,
        emotion: str = "neutral",
        type: str = "chat",
    ) -> None:
        """Add a memory entry.

        Writes to raw_log.jsonl (backward compatible), updates BM25 index,
        and optionally updates the vector index if the model is loaded.
        """
        mem_id = str(uuid.uuid4())
        timestamp = datetime.datetime.now().isoformat()

        entry = {
            "id": mem_id,
            "timestamp": timestamp,
            "content": content,
            "emotion_data": {
                "emotion": emotion,
                "emotion_conf": 1.0,
            },
            "type": type,
            "importance": importance,
        }

        # Persist to raw_log.jsonl
        with open(self.raw_log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Update in-memory stores
        self._entries.append(entry)
        tokens = _tokenize(content)
        self._corpus_tokens.append(tokens)
        self._rebuild_bm25()

        # Update vector index if model is already loaded
        if self._model is not None:
            try:
                vec = self._model.encode([content], show_progress_bar=False)
                if self._embeddings is not None:
                    self._embeddings = np.vstack([self._embeddings, vec])
                else:
                    self._embeddings = vec
            except Exception as exc:
                logger.warning("Failed to encode new memory for vector index: %s", exc)

        logger.info(
            "Memory added: %s importance=%d emotion=%s type=%s",
            mem_id, importance, emotion, type,
        )

    def recall(self, query: str, n_results: int = 5) -> list[dict]:
        """Hybrid recall: BM25(0.3) + vector(0.7), sorted by importance desc.

        Graceful degradation:
        - If vector search fails → BM25 only
        - If BM25 fails → vector only
        - If both fail → empty list
        """
        if not self._entries:
            return []

        bm25_scores = None
        vec_scores = None

        # BM25 scores
        try:
            bm25_results = self._bm25_scores(query)
            if bm25_results is not None:
                bm25_scores = bm25_results
        except Exception as exc:
            logger.warning("BM25 search failed: %s", exc)

        # Vector scores
        try:
            vec_results = self._vector_scores(query)
            if vec_results is not None:
                vec_scores = vec_results
        except Exception as exc:
            logger.warning("Vector search failed: %s", exc)

        # Combine scores
        n = len(self._entries)
        if bm25_scores is not None and vec_scores is not None:
            combined = 0.3 * bm25_scores + 0.7 * vec_scores
        elif bm25_scores is not None:
            combined = bm25_scores
        elif vec_scores is not None:
            combined = vec_scores
        else:
            return []

        # Get top indices by combined score
        top_k = min(n_results, n)
        top_indices = np.argsort(combined)[::-1][:top_k]

        # Build results, sort by importance descending
        results = []
        for idx in top_indices:
            idx = int(idx)
            entry = self._entries[idx]
            results.append({
                "content": entry.get("content", ""),
                "emotion": entry.get("emotion_data", {}).get("emotion", "neutral"),
                "timestamp": entry.get("timestamp", ""),
                "importance": entry.get("importance", 1),
                "type": entry.get("type", "chat"),
            })

        results.sort(key=lambda x: x["importance"], reverse=True)
        return results

    def flush_daily_log(self, summary: str) -> None:
        """Append summary to today's daily log file ~/.kage/memory/YYYY-MM-DD.md."""
        today = datetime.date.today().isoformat()
        filepath = os.path.join(self.memory_dir, f"{today}.md")

        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        block = f"\n## {timestamp}\n\n{summary}\n"

        # Create file with header if it doesn't exist
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"# 对话日志 — {today}\n")

        with open(filepath, "a", encoding="utf-8") as f:
            f.write(block)

        logger.info("Daily log flushed to %s", filepath)

    def consolidate_old_logs(self, days_threshold: int = 7) -> None:
        """Consolidate logs older than *days_threshold* days.

        Extracts entries with importance >= 3 from raw_log.jsonl that are
        older than the threshold and appends them to MEMORY.md (long-term
        curated memory).
        """
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days_threshold)
        memory_file = os.path.join(self.memory_dir, "MEMORY.md")

        important_entries: list[dict] = []
        for entry in self._entries:
            if entry.get("importance", 1) < 3:
                continue
            ts_str = entry.get("timestamp", "")
            try:
                ts = datetime.datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                continue
            if ts < cutoff:
                important_entries.append(entry)

        if not important_entries:
            logger.info("No old important entries to consolidate")
            return

        # Append to MEMORY.md
        if not os.path.exists(memory_file):
            with open(memory_file, "w", encoding="utf-8") as f:
                f.write("# 长期记忆\n\n")

        with open(memory_file, "a", encoding="utf-8") as f:
            f.write(f"\n## 合并于 {datetime.date.today().isoformat()}\n\n")
            for entry in important_entries:
                ts = entry.get("timestamp", "?")
                content = entry.get("content", "")
                imp = entry.get("importance", 1)
                f.write(f"- [{ts}] (重要性 {imp}) {content}\n")

        logger.info("Consolidated %d important entries to MEMORY.md", len(important_entries))

    # ------------------------------------------------------------------
    # Search primitives
    # ------------------------------------------------------------------

    def bm25_search(self, query: str, n_results: int = 5) -> list[dict]:
        """Keyword search using BM25."""
        if not self._entries or self._bm25 is None:
            return []

        tokens = _tokenize(query)
        if not tokens:
            return []

        scores = self._bm25.get_scores(tokens)
        top_k = min(n_results, len(self._entries))
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            idx = int(idx)
            if scores[idx] <= 0:
                continue
            entry = self._entries[idx]
            results.append({
                "content": entry.get("content", ""),
                "emotion": entry.get("emotion_data", {}).get("emotion", "neutral"),
                "timestamp": entry.get("timestamp", ""),
                "importance": entry.get("importance", 1),
                "type": entry.get("type", "chat"),
                "score": float(scores[idx]),
            })

        results.sort(key=lambda x: x["importance"], reverse=True)
        return results

    def vector_search(self, query: str, n_results: int = 5) -> list[dict]:
        """Semantic search using sentence-transformers + numpy cosine similarity."""
        self._ensure_model()

        if self._model is None or self._embeddings is None or len(self._embeddings) == 0:
            return []

        query_vec = self._model.encode([query], show_progress_bar=False)
        sims = _cosine_similarity(query_vec, self._embeddings)[0]

        top_k = min(n_results, len(self._entries))
        top_indices = np.argsort(sims)[::-1][:top_k]

        results = []
        for idx in top_indices:
            idx = int(idx)
            entry = self._entries[idx]
            results.append({
                "content": entry.get("content", ""),
                "emotion": entry.get("emotion_data", {}).get("emotion", "neutral"),
                "timestamp": entry.get("timestamp", ""),
                "importance": entry.get("importance", 1),
                "type": entry.get("type", "chat"),
                "score": float(sims[idx]),
            })

        results.sort(key=lambda x: x["importance"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # Internal scoring helpers (return normalised score arrays)
    # ------------------------------------------------------------------

    def _bm25_scores(self, query: str) -> Optional[np.ndarray]:
        """Return normalised BM25 scores for all entries, or None."""
        if self._bm25 is None:
            return None
        tokens = _tokenize(query)
        if not tokens:
            return None
        scores = self._bm25.get_scores(tokens)
        max_score = scores.max()
        if max_score > 0:
            scores = scores / max_score
        return scores

    def _vector_scores(self, query: str) -> Optional[np.ndarray]:
        """Return normalised vector similarity scores, or None."""
        self._ensure_model()
        if self._model is None or self._embeddings is None or len(self._embeddings) == 0:
            return None
        query_vec = self._model.encode([query], show_progress_bar=False)
        sims = _cosine_similarity(query_vec, self._embeddings)[0]
        # Shift to [0, 1] range (cosine sim can be negative)
        min_sim = sims.min()
        max_sim = sims.max()
        if max_sim - min_sim > 0:
            sims = (sims - min_sim) / (max_sim - min_sim)
        else:
            sims = np.zeros_like(sims)
        return sims


# ------------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------------

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between rows of *a* and rows of *b*.

    Returns shape (len(a), len(b)).
    """
    a_norm = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-10)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-10)
    return a_norm @ b_norm.T
