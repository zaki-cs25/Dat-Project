#!/usr/bin/env python3
"""
Agent Benchmark Harness — CLI entry point.

Self-hosted (--target self-hosted):
    python -m harness \
        --agent coding \
        --dataset ./datasets/coding/cases.jsonl \
        --target self-hosted \
        --endpoint http://localhost:9000/v1 \
        --model Qwen3.6-27B \
        --api-key not-needed \
        --gpu-cost-per-hour 500 \
        --out-dir ./results/coding-selfhosted

Frontier / gateway (price-table required):
    python -m harness \
        --agent finance \
        --dataset ./datasets/finance/cases.jsonl \
        --target frontier \
        --endpoint https://api.openai.com/v1 \
        --model gpt-4o \
        --api-key $OPENAI_KEY \
        --price-table ./harness/price_table.json \
        --out-dir ./results/finance-frontier

Concurrency sweep (self-hosted):
    for w in 1 4 8 16; do
        python -m harness \
            --agent coding \
            --dataset ./datasets/coding/cases.jsonl \
            --target self-hosted \
            --endpoint http://localhost:9000/v1 \
            --model Qwen3.6-27B \
            --api-key not-needed \
            --gpu-cost-per-hour 500 \
            --workers $w \
            --out-dir ./results/coding-w${w}
    done
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure repo root is on sys.path so adapters can import agent code
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from harness.cost import load_price_table
from harness.dataset import load_dataset
from harness.runner import run_harness
from harness.types import TargetConfig


# ---------------------------------------------------------------------------
# Adapter / scorer registry
# ---------------------------------------------------------------------------

def _get_adapter(agent_name: str):
    if agent_name == "insurance":
        from harness.adapters.insurance import InsuranceAdapter
        return InsuranceAdapter()
    elif agent_name == "finance":
        from harness.adapters.finance import FinanceAdapter
        return FinanceAdapter()
    elif agent_name == "coding":
        from harness.adapters.coding import CodingAdapter
        return CodingAdapter()
    else:
        raise ValueError(f"Unknown agent: {agent_name}. Use: insurance, finance, coding")


def _get_scorer(agent_name: str):
    if agent_name == "insurance":
        from harness.scorers.insurance import InsuranceScorer
        return InsuranceScorer()
    elif agent_name == "finance":
        from harness.scorers.finance import FinanceScorer
        return FinanceScorer()
    elif agent_name == "coding":
        from harness.scorers.coding import CodingScorer
        return CodingScorer()
    else:
        raise ValueError(f"Unknown agent: {agent_name}. Use: insurance, finance, coding")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Agent Benchmark Harness — evaluate agents across targets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Required
    p.add_argument("--agent", required=True, choices=["insurance", "finance", "coding"],
                   help="Which domain agent to run (selects adapter + scorer)")
    p.add_argument("--dataset", required=True,
                   help="Path to dataset JSONL file (id, input, ground_truth, metadata)")
    p.add_argument("--target", required=True, choices=["frontier", "self-hosted", "gateway"],
                   help="Target type")
    p.add_argument("--endpoint", required=True,
                   help="Base URL for the agent's model calls")
    p.add_argument("--model", required=True,
                   help="Model name to request")
    p.add_argument("--api-key", required=True,
                   help="API key for the endpoint")
    p.add_argument("--price-table", default=None,
                   help="Path to price table JSON (required for frontier/gateway)")
    p.add_argument("--out-dir", required=True,
                   help="Where results are written")

    # Optional
    p.add_argument("--workers", type=int, default=1,
                   help="Cases to run concurrently (default: 1)")
    p.add_argument("--limit", type=int, default=None,
                   help="Run only the first N cases")
    p.add_argument("--system-prompt", default=None,
                   help="Override the agent's default system prompt")
    p.add_argument("--tag", default=None,
                   help="Label written onto every result row")
    p.add_argument("--gpu-cost-per-hour", type=float, default=None,
                   help="GPU cost/hr for self-hosted. Cost = batch_wall_clock * rate / 3600 / tasks_solved.")

    args = p.parse_args()

    # Validate: price-table required for frontier/gateway, gpu-cost-per-hour for self-hosted
    if args.target in ("frontier", "gateway") and not args.price_table:
        p.error("--price-table is required for frontier/gateway targets")
    if args.target == "self-hosted" and args.gpu_cost_per_hour is None:
        p.error("--gpu-cost-per-hour is required for self-hosted target")

    price_table = load_price_table(args.price_table) if args.price_table else {}
    gpu_cost = args.gpu_cost_per_hour if args.target == "self-hosted" else None

    cases = load_dataset(args.dataset)
    if args.limit:
        cases = cases[: args.limit]

    print("=" * 60)
    print(f"  Agent: {args.agent}  |  Target: {args.target}")
    print(f"  Model: {args.model}  |  Endpoint: {args.endpoint}")
    print(f"  Cases: {len(cases)}  |  Workers: {args.workers}")
    if gpu_cost:
        print(f"  GPU cost: {gpu_cost}/hr")
    print(f"  Output: {args.out_dir}")
    if args.tag:
        print(f"  Tag: {args.tag}")
    print("=" * 60)

    adapter = _get_adapter(args.agent)
    scorer = _get_scorer(args.agent)

    target_config = TargetConfig(
        endpoint=args.endpoint,
        model=args.model,
        api_key=args.api_key,
        system_prompt=args.system_prompt,
    )

    asyncio.run(
        run_harness(
            adapter=adapter,
            scorer=scorer,
            cases=cases,
            config=target_config,
            price_table=price_table,
            out_dir=args.out_dir,
            tag=args.tag,
            workers=args.workers,
            gpu_cost_per_hour=gpu_cost,
        )
    )


if __name__ == "__main__":
    main()
