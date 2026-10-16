"""Abstract scorer interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Scorer(ABC):
    @abstractmethod
    def score(self, final_output: Any, ground_truth: Any) -> tuple[float, dict]:
        """
        Score a final output against ground truth.

        Returns:
            (score, details) where score is 0.0-1.0 and details
            is a dict of sub-metrics for the report.
        """
