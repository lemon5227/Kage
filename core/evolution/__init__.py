"""
Kage EvoLab Core Evolution Package.
"""

from core.evolution.budget import BudgetConfig, BudgetExhaustedError, BudgetTracker
from core.evolution.contracts import (
    Candidate,
    CandidateTarget,
    EvolutionEvent,
    EventType,
    RunResult,
    RunSpec,
    RunStatus,
)
from core.evolution.journal import Journal
from core.evolution.progress import ProgressTracker
from core.evolution.runner import Evaluator, EvolutionRunner, FakeEvolutionProvider

__all__ = [
    "Candidate",
    "CandidateTarget",
    "EvolutionEvent",
    "EventType",
    "RunResult",
    "RunSpec",
    "RunStatus",
    "ProgressTracker",
    "BudgetConfig",
    "BudgetExhaustedError",
    "BudgetTracker",
    "Journal",
    "Evaluator",
    "EvolutionRunner",
    "FakeEvolutionProvider",
]
