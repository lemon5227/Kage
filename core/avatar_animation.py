"""
Avatar Animation Configuration — Live2D motion & expression mapping.

Keeps animation config out of KageServer so that:
- Modifying animations doesn't require touching server.py
- Different Live2D models can have different configs
- Frontend can query these values via API if needed
"""

import random
import time
from dataclasses import dataclass, field


@dataclass
class MotionConfig:
    """Motion group configuration."""
    groups: dict[str, int] = field(default_factory=lambda: {"Idle": 3, "Tap": 2})
    weights: dict[str, int] = field(default_factory=lambda: {"Idle": 1, "Tap": 3})
    cooldown_sec: float = 4.0
    cooldown_min_sec: float = 2.5
    cooldown_max_sec: float = 6.0


@dataclass
class ExpressionConfig:
    """Expression mapping configuration."""
    mapping: dict = field(default_factory=lambda: {
        "neutral": "f05",
        "happy": {"choices": ["f00", "f01"], "weights": [3, 1]},
        "sad": "f03",
        "angry": "f07",
        "fear": "f06",
        "surprised": "f02",
    })
    emotion_weights: dict = field(default_factory=lambda: {
        "happy": {"Idle": 1, "Tap": 5},
        "surprised": {"Idle": 1, "Tap": 4},
        "sad": {"Idle": 4, "Tap": 1},
        "angry": {"Idle": 2, "Tap": 3},
    })
    duration_base_sec: float = 2.5
    duration_per_char: float = 0.04
    duration_min_sec: float = 2.0
    duration_max_sec: float = 6.0


class AvatarAnimation:
    """Manages Live2D motion and expression selection."""

    def __init__(
        self,
        motion_config: MotionConfig | None = None,
        expression_config: ExpressionConfig | None = None,
    ):
        self.motion = motion_config or MotionConfig()
        self.expression = expression_config or ExpressionConfig()
        self._last_motion_time = 0.0

    def select_motion(self, emotion_key: str = "neutral") -> int | None:
        """Select a motion index based on emotion weights."""
        if not self.motion.groups:
            return None

        now = time.monotonic()
        if now - self._last_motion_time < self.motion.cooldown_sec:
            return None

        # emotion_weights is on ExpressionConfig, not MotionConfig.
        # Falls back to MotionConfig.weights when no per-emotion mapping exists.
        weights_map = self.expression.emotion_weights.get(emotion_key, self.motion.weights)
        group = random.choices(
            list(self.motion.groups.keys()),
            weights=[weights_map.get(g, 1) for g in self.motion.groups],
        )[0]

        max_index = self.motion.groups.get(group, 0)
        if max_index <= 0:
            return None

        self._last_motion_time = now
        return random.randint(0, max_index - 1)

    def update_motion_cooldown(self, text: str) -> None:
        """Adjust cooldown based on response length."""
        duration = self.expression.duration_base_sec + len(text) * self.expression.duration_per_char
        self.motion.cooldown_sec = max(
            self.motion.cooldown_min_sec,
            min(duration, self.motion.cooldown_max_sec),
        )

    def select_expression(self, emotion: str) -> str:
        """Select an expression based on emotion."""
        exp_value = self.expression.mapping.get(emotion, "f05")
        if isinstance(exp_value, dict):
            choices = exp_value.get("choices", ["f05"])
            weights = exp_value.get("weights")
            if weights and len(weights) == len(choices):
                return random.choices(choices, weights=weights)[0]
            return random.choice(choices) if choices else "f05"
        return exp_value

    def calculate_expression_duration(self, text: str) -> float:
        """Calculate how long an expression should last."""
        duration = self.expression.duration_base_sec + len(text) * self.expression.duration_per_char
        return max(
            self.expression.duration_min_sec,
            min(duration, self.expression.duration_max_sec),
        )

    def to_dict(self) -> dict:
        """Export config as dict (for API/serialization)."""
        return {
            "motion": {
                "groups": self.motion.groups,
                "weights": self.motion.weights,
                "cooldown_sec": self.motion.cooldown_sec,
            },
            "expression": {
                "mapping": self.expression.mapping,
                "emotion_weights": self.expression.emotion_weights,
            },
        }
