"""Abstract adapter interface — every agent adapter implements this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from harness.types import Case, AdapterResult, TargetConfig


class AgentAdapter(ABC):
    @abstractmethod
    async def run(self, case: Case, config: TargetConfig) -> AdapterResult:
        """
        Run the agent on one case.

        Args:
            case: the input case (id, input, ground_truth, metadata)
            config: target config (endpoint, model, api_key, system_prompt)

        Returns:
            AdapterResult with final_output, calls (list of CallRecord),
            and timing.
        """
