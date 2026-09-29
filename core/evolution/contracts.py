"""
Contracts and data structures for Kage EvoLab.
Follows the minimal interface specifications in master plan v2.1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


CandidateTarget = Literal['skill', 'prompt', 'workflow', 'recovery', 'retrieval', 'planner']
RunStatus = Literal['passed', 'failed', 'timeout', 'budget_exhausted', 'crashed']
EventType = Literal[
    'action',
    'observation',
    'diagnosis',
    'mutation',
    'evaluation',
    'promotion',
    'budget_stop',
    'rollback',
    'stagnation',
]


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    parent_ids: tuple[str, ...]
    target: CandidateTarget
    bundle_path: str
    digest: str
    hypothesis: str = ""  # DeepMind Co-Scientist: causal explanation of proposed modification
    island_id: str = "island-0"  # DeepMind FunSearch: population island identifier


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    candidate_id: str
    task_id: str
    seed: int = 42
    max_steps: int = 5
    timeout_s: int = 120


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: RunStatus
    score: float
    trace_path: str
    usage: dict[str, Any] = field(default_factory=dict)
    final_state_path: str = ""
    progress_stagnant: bool = False  # ByteDance Aime: observation flag for stagnation
    rollback_count: int = 0  # Tencent WebCoT: number of rollbacks executed


@dataclass(frozen=True)
class EvolutionEvent:
    run_id: str
    candidate_id: str
    task_id: str
    step: int
    event_type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
