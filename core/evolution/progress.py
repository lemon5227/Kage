"""
Progress tracking and stagnation detection for Kage EvoLab.
Inspired by ByteDance Aime progress management paradigm, aligned with Section 4.5.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _normalize_dict(d: dict[str, Any] | None) -> str:
    """Produce a deterministic normalized string representation of a dictionary."""
    if not d:
        return ""
    try:
        return json.dumps(d, sort_keys=True, default=str)
    except Exception:
        return str(sorted(d.items()))


class ProgressTracker:
    """
    Monitors step progression, tracks evidence acquisition, and detects stagnation.
    Only uses agent-visible inputs and observations. Does NOT access ground-truth scores.
    """

    def __init__(self, stagnation_threshold: int = 3) -> None:
        self.stagnation_threshold = stagnation_threshold
        self._history: list[tuple[str, str, str]] = []  # (norm_action, norm_obs, state_digest)
        self._seen_observations: set[str] = set()
        self._repeat_count: int = 0

    def reset(self) -> None:
        """Reset internal history for a new task execution."""
        self._history.clear()
        self._seen_observations.clear()
        self._repeat_count = 0

    def observe(
        self,
        action: dict[str, Any] | None,
        observation: dict[str, Any] | None,
        state_digest: str = "",
    ) -> dict[str, Any]:
        """
        Record one step and evaluate progression.
        Returns:
            {
                "new_evidence": bool,
                "repeated_cycle": bool,
                "stagnant": bool,
                "repeat_count": int
            }
        """
        norm_action = _normalize_dict(action)
        norm_obs = _normalize_dict(observation)

        # Check if observation brings new evidence
        obs_hash = hashlib.sha256(norm_obs.encode("utf-8")).hexdigest() if norm_obs else ""
        new_evidence = False
        if obs_hash and obs_hash not in self._seen_observations:
            new_evidence = True
            self._seen_observations.add(obs_hash)

        # Check repetition against immediate previous step
        repeated_cycle = False
        if self._history:
            prev_action, prev_obs, prev_state = self._history[-1]
            if norm_action == prev_action and norm_obs == prev_obs:
                self._repeat_count += 1
                repeated_cycle = True
            else:
                self._repeat_count = 1
        else:
            self._repeat_count = 1

        self._history.append((norm_action, norm_obs, state_digest))

        # Stagnant condition: repeated cycle reaches threshold AND no new evidence
        stagnant = (self._repeat_count >= self.stagnation_threshold) and (not new_evidence)

        return {
            "new_evidence": new_evidence,
            "repeated_cycle": repeated_cycle,
            "stagnant": stagnant,
            "repeat_count": self._repeat_count,
        }
