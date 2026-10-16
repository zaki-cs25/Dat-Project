"""Shared types for the benchmark harness."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Case:
    """One evaluation case — the universal dataset format."""
    id: str
    input: str  # the content the agent works on
    ground_truth: Any  # expected answer/label (structure varies by domain)
    metadata: dict = field(default_factory=dict)  # extra fields the adapter may need


@dataclass
class TargetConfig:
    """Everything that changes between frontier / self-hosted / gateway."""
    endpoint: str
    model: str
    api_key: str
    system_prompt: str | None = None  # None = use agent's default


@dataclass
class CallRecord:
    """One model call made during a task."""
    model_used: str
    input_tokens: int
    output_tokens: int


@dataclass
class Timing:
    """Task-level timing."""
    start_time: float  # epoch
    end_time: float
    wall_clock_seconds: float = 0.0

    def __post_init__(self):
        if self.wall_clock_seconds == 0.0:
            self.wall_clock_seconds = self.end_time - self.start_time


@dataclass
class AdapterResult:
    """What every adapter must return."""
    final_output: Any
    calls: list[CallRecord]
    timing: Timing


@dataclass
class CaseResult:
    """One row of results — what gets written to per_case.csv."""
    case_id: str
    score: float
    score_details: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    computed_cost: float = 0.0
    gateway_reported_cost: float = 0.0
    latency_seconds: float = 0.0
    steps: int = 0  # number of model calls
    models_used: str = ""
    tag: str = ""
    final_output: Any = None
    raw: dict = field(default_factory=dict)


@dataclass
class PriceEntry:
    """Price per 1M tokens for one model."""
    model: str
    price_per_1m_input: float
    price_per_1m_output: float


@dataclass
class RunConfig:
    """Full run configuration — written to run_config.json for reproducibility."""
    agent: str
    dataset: str
    target: str
    endpoint: str
    model: str
    api_key_masked: str
    price_table_path: str
    out_dir: str
    workers: int
    limit: int | None
    system_prompt: str | None
    tag: str | None
    price_table: dict
    timestamp: str = ""
