"""Cost accounting.

Frontier / gateway: token-based (input_tokens × rate_in + output_tokens × rate_out).
Self-hosted: GPU-wall-clock-based (batch_seconds × gpu_rate_per_second / tasks_solved).

Self-hosted cost is computed at batch level in runner.py;
this module handles per-call and per-task token cost for frontier/gateway.
"""

from __future__ import annotations

from harness.types import CallRecord, PriceEntry


def load_price_table(path: str) -> dict[str, PriceEntry]:
    """Load a JSON price table. Format:
    {
      "gpt-4o": {"input": 2.50, "output": 10.00},
      "Qwen3.6-27B": {"input": 0.00, "output": 0.00}
    }
    Keys are model names. Values have input/output price per 1M tokens.
    """
    import json
    entries: dict[str, PriceEntry] = {}
    with open(path) as f:
        raw = json.load(f)
    for model, prices in raw.items():
        entries[model] = PriceEntry(
            model=model,
            price_per_1m_input=prices.get("input", 0.0),
            price_per_1m_output=prices.get("output", 0.0),
        )
    return entries


def compute_call_cost(call: CallRecord, price_table: dict[str, PriceEntry]) -> float:
    """Cost of a single model call (frontier/gateway, token-based)."""
    entry = price_table.get(call.model_used)
    if entry is None:
        return 0.0
    return (
        call.input_tokens / 1_000_000 * entry.price_per_1m_input
        + call.output_tokens / 1_000_000 * entry.price_per_1m_output
    )


def compute_task_cost(calls: list[CallRecord], price_table: dict[str, PriceEntry]) -> float:
    """Sum of call costs for one task (frontier/gateway)."""
    return sum(compute_call_cost(c, price_table) for c in calls)


def compute_self_hosted_cost_per_solved_task(
    batch_wall_clock_seconds: float,
    gpu_cost_per_hour: float,
    tasks_solved: int,
) -> float:
    """Cost per solved task for self-hosted models.

    coding-agent-plan.md "Calculating cost per task for self-hosted models":
        cost per solved task = (batch wall-clock seconds) * (GPU rupees per hour / 3600)
                              / (tasks solved)
    """
    if tasks_solved == 0:
        return float("inf")
    return (batch_wall_clock_seconds * gpu_cost_per_hour / 3600) / tasks_solved


def compute_self_hosted_cost_per_task(
    batch_wall_clock_seconds: float,
    gpu_cost_per_hour: float,
    tasks_attempted: int,
) -> float:
    """Cost per attempted task for self-hosted models (pessimistic)."""
    if tasks_attempted == 0:
        return 0.0
    return (batch_wall_clock_seconds * gpu_cost_per_hour / 3600) / tasks_attempted
