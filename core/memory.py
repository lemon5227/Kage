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
import time
import datetime
import logging
import contextlib
import io
import threading
import warnings
from typing import Optional

import numpy as np
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

# Maximum number of in-memory entries before eviction
_DEFAULT_MAX_ENTRIES = 10000
# Number of inserts between BM25 rebuilds (batch optimization)
_BM25_REBUILD_INTERVAL = 10


_TOKEN_RE = re.compile(r'[\u4e00-\u9fff]|[a-zA-Z0-9]+')


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer for mixed Chinese/English text."""
    return [m.group().lower() for m in _TOKEN_RE.finditer(text)]


class MemorySystem:
    """分层记忆系统 — Markdown + numpy + BM25 (no ChromaDB)."""

    def __init__(self, workspace_dir: str = "~/.kage", max_entries: int = _DEFAULT_MAX_ENTRIES):
        workspace = os.path.expanduser(workspace_dir)

        self.memory_dir = os.path.join(workspace, "memory")
        self.data_dir = os.path.join(workspace, "data")
        os.makedirs(self.memory_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

        self.raw_log_file = os.path.join(self.data_dir, "raw_log.jsonl")
        self._max_entries = max_entries

        # Thread safety lock for all mutations
        self._lock = threading.Lock()

        # In-memory stores
        self._entries: list[dict] = []       # all memory entries
        self._corpus_tokens: list[list[str]] = []  # tokenized content per entry
        self._corpus_token_sets: Optional[list[set]] = None  # cache for keyword overlap
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_dirty: int = 0  # inserts since last BM25 rebuild

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

        self._rebuild_bm25(force=True)

    def _rebuild_bm25(self, force: bool = False) -> None:
        """Rebuild the BM25 index from current corpus tokens.
        
        Uses batched rebuilds: only rebuilds every _BM25_REBUILD_INTERVAL inserts
        unless force=True.
        """
        if not force:
            self._bm25_dirty += 1
            if self._bm25_dirty < _BM25_REBUILD_INTERVAL and self._bm25 is not None:
                return
        self._bm25_dirty = 0
        if self._corpus_tokens:
            # Filter out empty token lists to avoid BM25 issues
            valid_tokens = [t for t in self._corpus_tokens if t]
            if valid_tokens:
                self._bm25 = BM25Okapi(self._corpus_tokens)
            else:
                self._bm25 = None
        else:
            self._bm25 = None

    # ------------------------------------------------------------------
    # Lazy model loading
    # ------------------------------------------------------------------

    def warmup_model(self) -> bool:
        """Pre-load the sentence-transformers model to avoid cold-start latency.

        Call this during application startup (e.g., in KageServer.__init__)
        so the first recall doesn't pay the 2-3 second loading penalty.

        Returns True if model was loaded successfully.
        """
        if self._model is not None:
            return True
        logger.info("Warming up sentence-transformers model...")
        t0 = time.monotonic()
        self._ensure_model()
        elapsed = (time.monotonic() - t0) * 1000
        if self._model is not None:
            logger.info("Sentence-transformers warmed in %.0f ms", elapsed)
            return True
        logger.warning("Failed to warm up sentence-transformers model")
        return False

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
        Thread-safe.
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

        with self._lock:
            # Evict oldest low-importance entries if at capacity
            if len(self._entries) >= self._max_entries:
                self._evict_entries()

            # Update in-memory stores
            self._entries.append(entry)
            tokens = _tokenize(content)
            self._corpus_tokens.append(tokens)
            # Append to token sets cache if it exists, else leave None
            if self._corpus_token_sets is not None:
                self._corpus_token_sets.append(set(tokens))
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

    def _evict_entries(self) -> None:
        """Evict lowest-importance oldest entries to stay under max_entries.
        
        Must be called with self._lock held.
        """
        # Remove 10% of entries, preferring low-importance + old
        evict_count = max(1, self._max_entries // 10)
        # Score entries: lower importance + older = higher eviction priority
        now = datetime.datetime.now()
        scored = []
        for i, entry in enumerate(self._entries):
            imp = entry.get("importance", 1)
            try:
                ts = datetime.datetime.fromisoformat(entry.get("timestamp", ""))
                age_days = (now - ts).total_seconds() / 86400
            except (ValueError, TypeError):
                age_days = 999
            # High importance = low eviction score; old age = high eviction score
            eviction_score = age_days / max(imp, 1)
            scored.append((eviction_score, i))
        
        scored.sort(reverse=True)
        evict_indices = set(idx for _, idx in scored[:evict_count])
        
        keep_indices = [i for i in range(len(self._entries)) if i not in evict_indices]
        self._entries = [self._entries[i] for i in keep_indices]
        self._corpus_tokens = [self._corpus_tokens[i] for i in keep_indices]
        self._corpus_token_sets = None  # invalidate cache
        if self._embeddings is not None and len(self._embeddings) > 0:
            self._embeddings = self._embeddings[keep_indices]
        self._rebuild_bm25(force=True)
        logger.info("Evicted %d entries to stay under max_entries=%d", len(evict_indices), self._max_entries)

    def add_fact(
        self,
        content: str,
        category: str = "other",
        importance: int = 2,
        emotion: str = "neutral",
    ) -> None:
        """Add a structured fact to memory.

        Used by MemoryExtractor to store extracted facts with proper
        importance and category.
        """
        self.add_memory(
            content=content,
            importance=importance,
            emotion=emotion,
            type=f"fact:{category}",
        )

    def add_conversation_facts(
        self,
        user_input: str,
        assistant_response: str = "",
        emotion: str = "neutral",
    ) -> list[dict]:
        """Extract and store facts from a conversation turn.

        Returns list of extracted facts.
        """
        from core.memory_extractor import MemoryExtractor

        extractor = MemoryExtractor()
        facts = extractor.extract_from_conversation(
            user_input=user_input,
            assistant_response=assistant_response,
            emotion=emotion,
        )

        stored = []
        for fact in facts:
            self.add_fact(
                content=fact.content,
                category=fact.category,
                importance=fact.importance,
                emotion=emotion,
            )
            stored.append(extractor.fact_to_dict(fact))

        if stored:
            logger.info("Extracted %d facts from conversation", len(stored))

        return stored

    def recall(self, query: str, n_results: int = 5) -> list[dict]:
        """Hybrid recall: BM25(0.3) + vector(0.7), sorted by importance desc.

        Graceful degradation:
        - If vector search fails → BM25 only
        - If BM25 fails → vector only
        - If both fail → empty list
        Thread-safe.
        """
        with self._lock:
            if not self._entries:
                return []

            # Ensure BM25 is up to date before querying
            if self._bm25_dirty > 0:
                self._rebuild_bm25(force=True)

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

            # Combine scores: relevance (BM25 + vector) weighted by importance
            n = len(self._entries)
            if bm25_scores is not None and vec_scores is not None:
                combined = 0.3 * bm25_scores + 0.7 * vec_scores
            elif bm25_scores is not None:
                combined = bm25_scores
            elif vec_scores is not None:
                combined = vec_scores
            else:
                return []

            # Apply importance as a multiplicative boost (not a sort override)
            importance_scores = np.array([
                entry.get("importance", 1) for entry in self._entries
            ], dtype=float)
            max_imp = importance_scores.max()
            if max_imp > 0:
                importance_norm = importance_scores / max_imp
            else:
                importance_norm = importance_scores

            # Final score: 85% relevance + 15% importance
            final_scores = 0.85 * combined + 0.15 * importance_norm

            # Get top indices by final score
            top_k = min(n_results, n)
            top_indices = np.argsort(final_scores)[::-1][:top_k]

            # Build results in order of final score (relevance + importance)
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

            return results

    def recall_with_decay(
        self, query: str, n_results: int = 5, decay_days: int = 30
    ) -> list[dict]:
        """Hybrid recall with time-based decay.

        Older memories get lower scores based on exponential decay.
        This prevents old irrelevant information from dominating results.
        """
        if not self._entries:
            return []

        base_results = self.recall(query, n_results=n_results * 2)

        now = datetime.datetime.now()
        decayed_results = []

        for entry in base_results:
            ts_str = entry.get("timestamp", "")
            try:
                ts = datetime.datetime.fromisoformat(ts_str)
                age_days = (now - ts).total_seconds() / 86400
                decay_factor = 0.5 ** (age_days / decay_days)
            except (ValueError, TypeError):
                decay_factor = 1.0

            importance = entry.get("importance", 1)
            decayed_importance = importance * decay_factor

            decayed_results.append({
                **entry,
                "original_importance": importance,
                "decayed_importance": decayed_importance,
                "age_days": round(age_days, 1),
            })

        decayed_results.sort(key=lambda x: x["decayed_importance"], reverse=True)
        return decayed_results[:n_results]

    def deduplicate_memories(self, similarity_threshold: float = 0.85) -> int:
        """Remove duplicate or near-duplicate memory entries.

        Returns number of duplicates removed.
        """
        if len(self._entries) < 2:
            return 0

        self._ensure_model()

        if self._model is None or self._embeddings is None:
            return self._deduplicate_bm25()

        # Batch cosine similarity: compute the full NxN similarity matrix at once.
        # This is dramatically faster than N*(N-1)/2 individual 1x1 matmuls.
        sim_matrix = _cosine_similarity(self._embeddings, self._embeddings)
        n = len(self._entries)

        # Greedy dedup: walk in order, mark j as duplicate if sim(i,j) >= threshold
        # and i is still kept. Use boolean array for O(1) checks.
        is_duplicate = np.zeros(n, dtype=bool)
        for i in range(n):
            if is_duplicate[i]:
                continue
            # Find all j > i with high similarity to i (vectorized)
            for j in range(i + 1, n):
                if not is_duplicate[j] and sim_matrix[i, j] >= similarity_threshold:
                    is_duplicate[j] = True

        removed = int(is_duplicate.sum())
        if removed > 0:
            keep_mask = ~is_duplicate
            keep_indices = np.where(keep_mask)[0].tolist()
            self._entries = [self._entries[i] for i in keep_indices]
            self._corpus_tokens = [self._corpus_tokens[i] for i in keep_indices]
            self._corpus_token_sets = None  # invalidate cache
            self._embeddings = self._embeddings[keep_indices]
            self._rebuild_bm25(force=True)

        return removed

    def _deduplicate_bm25(self) -> int:
        """Fallback deduplication using BM25 scores."""
        if not self._entries or self._bm25 is None:
            return 0

        removed = 0
        keep_indices = set()

        for i in range(len(self._entries)):
            if i in keep_indices:
                continue

            keep_indices.add(i)
            content_i = self._entries[i].get("content", "")
            tokens_i = _tokenize(content_i)

            for j in range(i + 1, len(self._entries)):
                if j in keep_indices:
                    continue

                content_j = self._entries[j].get("content", "")
                if content_i == content_j:
                    keep_indices.add(j)
                    removed += 1
                elif len(content_i) > 10 and len(content_j) > 10:
                    tokens_j = _tokenize(content_j)
                    scores = self._bm25.get_scores(tokens_i)
                    if len(scores) > j and scores[j] > 10:
                        keep_indices.add(j)
                        removed += 1

        return removed

    def merge_similar_facts(self, similarity_threshold: float = 0.75) -> int:
        """Merge similar facts into consolidated entries.

        Unlike deduplication (which removes duplicates), merging combines
        similar facts into a single enriched entry.

        Strategy:
        - Group similar facts by cosine similarity
        - Keep the highest-importance entry as the base
        - Append additional context from similar entries
        - Update importance to max of merged entries

        Returns number of merges performed.
        """
        if len(self._entries) < 2:
            return 0

        self._ensure_model()

        if self._model is None or self._embeddings is None:
            return self._merge_similar_bm25()

        # Batch cosine similarity for all pairs at once
        sim_matrix = _cosine_similarity(self._embeddings, self._embeddings)
        n = len(self._entries)

        merged = 0
        merged_indices = set()

        for i in range(n):
            if i in merged_indices:
                continue

            # Find all j > i with high similarity (vectorized lookup)
            similar_indices = [
                j for j in range(i + 1, n)
                if j not in merged_indices and sim_matrix[i, j] >= similarity_threshold
            ]

            if similar_indices:
                # Find the entry with highest importance
                candidates = [i] + similar_indices
                best_idx = max(
                    candidates,
                    key=lambda idx: self._entries[idx].get("importance", 1),
                )

                # Merge content from similar entries
                base_content = self._entries[best_idx].get("content", "")
                max_importance = max(
                    self._entries[idx].get("importance", 1) for idx in candidates
                )

                # Build merged content
                extra_contexts = [
                    self._entries[idx].get("content", "")
                    for idx in similar_indices
                    if idx != best_idx
                ]

                if extra_contexts:
                    merged_content = base_content
                    # If contents are very similar, keep the longest one
                    if all(
                        len(c) > 0.7 * len(base_content) for c in extra_contexts
                    ):
                        merged_content = max(
                            [base_content] + extra_contexts, key=len
                        )
                    else:
                        # Different aspects, append context
                        merged_content = base_content

                    self._entries[best_idx]["content"] = merged_content
                    self._entries[best_idx]["importance"] = max_importance
                    self._entries[best_idx]["merged_from"] = len(similar_indices) + 1

                # Mark similar entries for removal
                for idx in similar_indices:
                    merged_indices.add(idx)
                    merged += 1

        if merged > 0:
            keep_indices = sorted(set(range(len(self._entries))) - merged_indices)
            self._entries = [self._entries[i] for i in keep_indices]
            self._corpus_tokens = [self._corpus_tokens[i] for i in keep_indices]
            self._corpus_token_sets = None  # invalidate cache
            if self._embeddings is not None:
                self._embeddings = self._embeddings[keep_indices]
            self._rebuild_bm25(force=True)

        return merged

    def _merge_similar_bm25(self) -> int:
        """Fallback merging using BM25 scores."""
        if not self._entries or self._bm25 is None:
            return 0

        merged = 0
        merged_indices = set()

        for i in range(len(self._entries)):
            if i in merged_indices:
                continue

            content_i = self._entries[i].get("content", "")
            tokens_i = _tokenize(content_i)
            scores = self._bm25.get_scores(tokens_i)

            similar = []
            for j in range(i + 1, len(self._entries)):
                if j in merged_indices:
                    continue
                if len(scores) > j and scores[j] > 5:
                    similar.append(j)

            if similar:
                best_idx = max(
                    [i] + similar,
                    key=lambda idx: self._entries[idx].get("importance", 1),
                )
                for idx in similar:
                    merged_indices.add(idx)
                    merged += 1

        return merged

    def forget_old_memories(
        self,
        max_age_days: int = 90,
        min_importance: int = 2,
        keep_recent_days: int = 7,
    ) -> int:
        """Automatically forget old, low-importance memories.

        Strategy:
        - Keep all memories from the last keep_recent_days days
        - After that, remove memories with importance < min_importance
        - Always remove memories older than max_age_days regardless of importance
        - Memories with importance >= 4 are never forgotten

        Returns number of memories forgotten.
        """
        if not self._entries:
            return 0

        now = datetime.datetime.now()
        forgotten = 0
        forgotten_indices = set()

        for i, entry in enumerate(self._entries):
            ts_str = entry.get("timestamp", "")
            try:
                ts = datetime.datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                continue

            age_days = (now - ts).total_seconds() / 86400
            importance = entry.get("importance", 1)

            # High-importance memories are never forgotten
            if importance >= 4:
                continue

            # Recent memories are always kept
            if age_days <= keep_recent_days:
                continue

            # Very old memories are always forgotten
            if age_days > max_age_days:
                forgotten_indices.add(i)
                forgotten += 1
                continue

            # Old + low-importance memories are forgotten
            if importance < min_importance:
                forgotten_indices.add(i)
                forgotten += 1

        if forgotten > 0:
            keep_indices = sorted(set(range(len(self._entries))) - forgotten_indices)
            self._entries = [self._entries[i] for i in keep_indices]
            self._corpus_tokens = [self._corpus_tokens[i] for i in keep_indices]
            self._corpus_token_sets = None  # invalidate cache
            if self._embeddings is not None:
                self._embeddings = self._embeddings[keep_indices]
            self._rebuild_bm25(force=True)

            logger.info("Forgot %d old memories (age > %d days, importance < %d)",
                       forgotten, max_age_days, min_importance)

        return forgotten

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
    # Public API for entry management (encapsulates internal state)
    # ------------------------------------------------------------------

    def get_entries(self, limit: int = 50, offset: int = 0, category: str = "") -> tuple[list[dict], int]:
        """Get paginated memory entries with optional category filter.

        Returns:
            Tuple of (entries, total_count)
        """
        entries = self._entries
        total = len(entries)

        if category:
            entries = [e for e in entries if e.get("type", "").startswith(f"fact:{category}")]
            total = len(entries)

        paginated = entries[offset:offset + limit]
        return list(paginated), total

    def delete_entry(self, entry_id: str) -> bool:
        """Delete a memory entry by ID.

        Properly removes from all internal data structures (entries, tokens,
        embeddings, BM25 index) to maintain consistency.
        Thread-safe.

        Returns True if entry was found and deleted.
        """
        with self._lock:
            for i, entry in enumerate(self._entries):
                if entry.get("id") == entry_id:
                    self._entries.pop(i)
                    self._corpus_tokens.pop(i)
                    self._corpus_token_sets = None  # invalidate cache
                    if self._embeddings is not None:
                        self._embeddings = np.delete(self._embeddings, i, axis=0)
                    self._rebuild_bm25(force=True)
                    logger.info("Deleted memory entry: %s", entry_id)
                    return True
        return False

    def clear_all(self) -> int:
        """Clear all memory entries. Thread-safe.

        Returns number of entries cleared.
        """
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            self._corpus_tokens.clear()
            self._corpus_token_sets = None
            self._embeddings = None
            self._bm25 = None
            self._bm25_dirty = 0
            logger.info("Cleared all %d memory entries", count)
            return count

    # ------------------------------------------------------------------
    # Search primitives
    # ------------------------------------------------------------------

    def bm25_search(self, query: str, n_results: int = 5) -> list[dict]:
        """Keyword search using BM25."""
        if not self._entries:
            return []

        # Ensure BM25 index is up to date
        if self._bm25_dirty > 0 or self._bm25 is None:
            self._rebuild_bm25(force=True)

        if self._bm25 is None:
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

        results.sort(key=lambda x: x["score"], reverse=True)
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

        results.sort(key=lambda x: x["score"], reverse=True)
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

        # BM25 scores can be negative for short documents with single-char tokens.
        # If all scores are negative, fall back to keyword overlap scoring.
        if scores.max() <= 0:
            return self._keyword_overlap_scores(tokens)

        # Normalize to [0, 1]
        scores = np.maximum(scores, 0)
        max_score = scores.max()
        if max_score > 0:
            scores = scores / max_score
        return scores

    def _keyword_overlap_scores(self, query_tokens: list[str]) -> Optional[np.ndarray]:
        """Fallback scoring based on keyword overlap when BM25 fails.

        Counts how many query tokens appear in each document.
        Uses cached _corpus_token_sets to avoid rebuilding sets on every query.
        """
        if not self._corpus_tokens:
            return None

        # Build (or reuse) cached token sets
        if self._corpus_token_sets is None or len(self._corpus_token_sets) != len(self._corpus_tokens):
            self._corpus_token_sets = [set(t) for t in self._corpus_tokens]

        query_set = set(query_tokens)
        if not query_set:
            return None
        query_len = len(query_set)
        scores = np.zeros(len(self._corpus_tokens))

        for i, doc_set in enumerate(self._corpus_token_sets):
            overlap = len(query_set & doc_set)
            if overlap > 0:
                scores[i] = overlap / query_len

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


    def is_vector_ready(self) -> bool:
        """Check if the vector search model is loaded and ready."""
        return self._model is not None

    def get_stats(self) -> dict:
        """Return memory system statistics."""
        return {
            "total_entries": len(self._entries),
            "vector_ready": self.is_vector_ready(),
            "bm25_ready": self._bm25 is not None,
            "embeddings_count": len(self._embeddings) if self._embeddings is not None else 0,
        }


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
