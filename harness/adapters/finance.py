"""Finance agent adapter — wraps the finance_research_agent pipeline."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from harness.adapters.base import AgentAdapter
from harness.types import Case, AdapterResult, TargetConfig, CallRecord, Timing

_FINANCE_ROOT = Path(__file__).resolve().parents.joinpath("Finance_research_agent")
if str(_FINANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_FINANCE_ROOT))


class FinanceAdapter(AgentAdapter):
    """Runs the finance research agent on a case.
    
    Dataset format (in metadata):
    - ticker: stock ticker to analyze
    - filing_path: path to uploaded SEC filing (optional)
    """

    async def run(self, case: Case, config: TargetConfig) -> AdapterResult:
        start_time = time.time()

        # Point the finance agent at the target endpoint.
        # It reads from Settings which uses env vars.
        provider_map = {
            "frontier": "openai",
            "self-hosted": "vllm",
            "gateway": "openai",  # gateway is OpenAI-compatible
        }
        os.environ["LLM_PROVIDER"] = provider_map.get(config.target, "openai")
        os.environ["LLM_MODEL"] = config.model
        os.environ["VLLM_BASE_URL"] = config.endpoint
        os.environ["OPENAI_API_KEY"] = config.api_key

        meta = case.metadata
        ticker = meta.get("ticker", case.input)
        filing_path = meta.get("filing_path", "")

        # Import after env vars are set so Settings picks them up
        from agent.pipeline.pipeline import run_research

        result = await run_research(
            ticker=ticker,
            filing_path=filing_path or None,
            user_question=case.input,
            system_prompt=config.system_prompt,
        )

        end_time = time.time()

        # Extract call records from the pipeline result.
        # The finance pipeline may return per-call usage; fall back to aggregate.
        calls = self._extract_calls(result)

        return AdapterResult(
            final_output=result,
            calls=calls,
            timing=Timing(start_time=start_time, end_time=end_time),
        )

    def _extract_calls(self, result: dict) -> list[CallRecord]:
        """Pull call records from the finance pipeline result."""
        # Placeholder: the finance pipeline needs to expose per-call usage.
        # For now, record a single aggregate call.
        usage = result.get("usage", {})
        return [
            CallRecord(
                model_used=result.get("model", "unknown"),
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )
        ] if usage else []
