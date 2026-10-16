"""Insurance agent adapter — wraps the existing benchmark_adapter."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from harness.adapters.base import AgentAdapter
from harness.types import Case, AdapterResult, TargetConfig, CallRecord, Timing

# Add insurance_agent to path so we can import its modules
_INSURANCE_ROOT = Path(__file__).resolve().parents.joinpath("insurance_agent")
if str(_INSURANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INSURANCE_ROOT))


def _configure_llm(config: TargetConfig):
    """Point the insurance agent's LLM router at the target endpoint.
    
    Clears the config cache so router.py re-reads from env vars.
    """
    os.environ["LLM_BASE_URL"] = config.endpoint
    os.environ["LLM_API_KEY"] = config.api_key
    os.environ["LLM_MODEL"] = config.model

    # Invalidate the router's config cache
    try:
        from backend import router
        router._config_cache = None
    except Exception:
        pass  # module not yet imported or no cache attr


def _extract_call_records(result: dict) -> list[CallRecord]:
    """Pull call records from the insurance adapter's result."""
    usage = result.get("usage", {})
    trace = result.get("trace", [])
    
    # The benchmark_adapter tracks total tokens but not per-call breakdown.
    # We approximate: one CallRecord per round trip, dividing tokens evenly.
    round_trips = usage.get("round_trips", 0)
    total_input = usage.get("input_tokens", 0)
    total_output = usage.get("output_tokens", 0)
    
    if round_trips == 0:
        return []
    
    # Without per-call tracking in the adapter, we record one aggregate call.
    # TODO: benchmark_adapter.py should return per-call usage for accurate accounting.
    return [CallRecord(
        model_used=round(result.get("model", "unknown"), 0) if isinstance(result.get("model"), str) else "unknown",
        input_tokens=total_input,
        output_tokens=total_output,
    )]


class InsuranceAdapter(AgentAdapter):
    """Wraps insurance_agent/backend/agents/benchmark_adapter.py"""

    async def run(self, case: Case, config: TargetConfig) -> AdapterResult:
        from backend.agents.benchmark_adapter import run_case

        _configure_llm(config)

        # Resolve dataset paths from metadata
        meta = case.metadata
        base_dir = meta.get("base_dir", "")
        case_dir = meta.get("case_dir", f"{base_dir}/{case.id}")

        start_time = time.time()
        
        result = await run_case(
            case_id=case.id,
            case_info={
                "case_id": case.id,
                "product_id": meta.get("product_id", "unknown"),
            },
            wording_path=meta.get("wording_path", ""),
            documents=meta.get("documents", []),
            agent_brief_text=meta.get("agent_brief_text", ""),
            case_dir=case_dir,
            base_dir=base_dir,
            max_turns=meta.get("max_turns", 30),
            temperature=meta.get("temperature", 0),
        )

        end_time = time.time()

        calls = [
            CallRecord(
                model_used=result.get("model", "unknown"),
                input_tokens=result.get("usage", {}).get("input_tokens", 0),
                output_tokens=result.get("usage", {}).get("output_tokens", 0),
            )
        ]

        return AdapterResult(
            final_output=result,
            calls=calls,
            timing=Timing(start_time=start_time, end_time=end_time),
        )
