#!/usr/bin/env python3
"""
run_evaluation.py — Run the health claims adjudicator on sampled cases.

Usage:
    # Sample run (60 cases, equally distributed, k=1):
    python3 scripts/run_evaluation.py --sample 60 --runs 1

    # Full run (1000 cases, k=4):
    python3 scripts/run_evaluation.py --runs 4

    # Specific cases:
    python3 scripts/run_evaluation.py --case-ids case-000000 case-000010 --runs 1

Output: results.jsonl (one JSON object per case per run, per METRICS.md format)
"""

import argparse
import json
import os
import random
import sys
import asyncio
from pathlib import Path
from collections import Counter

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.benchmark_adapter import run_case

# Paths
DATASET_DIR = PROJECT_ROOT / "dataset"
PUBLIC_DIR = DATASET_DIR / "public"
GOLD_FILE = DATASET_DIR / "gold.jsonl"
INDEX_FILE = PUBLIC_DIR / "index.jsonl"
AGENT_BRIEF_FILE = PUBLIC_DIR / "AGENT_BRIEF.md"
DEFAULT_OUTPUT = PROJECT_ROOT / "results.jsonl"


def load_gold_truth() -> list[dict]:
    """Load gold.jsonl ground truth."""
    gold = []
    with open(GOLD_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                gold.append(json.loads(line))
    return gold


def load_index() -> list[dict]:
    """Load index.jsonl (case_id, product_id, wording, documents)."""
    cases = []
    with open(INDEX_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def load_agent_brief() -> str:
    """Load AGENT_BRIEF.md text."""
    return AGENT_BRIEF_FILE.read_text()


def sample_cases(cases: list[dict], gold: list[dict],
                 n: int = 60, seed: int = 42) -> list[dict]:
    """
    Sample N cases equally distributed by difficulty and product.

    gold provides difficulty/product info not in index.jsonl.
    """
    # Build lookup: case_id -> gold info
    gold_map = {g["case_id"]: g for g in gold}

    # Group by (difficulty, product)
    groups: dict[tuple, list[dict]] = {}
    for c in cases:
        gid = c["case_id"]
        g = gold_map.get(gid, {})
        diff = g.get("difficulty", "unknown")
        prod = c.get("product_id", "unknown")
        key = (diff, prod)
        groups.setdefault(key, []).append(c)

    # Sample equally from each group
    n_groups = len(groups)
    base_per_group = n // n_groups
    remainder = n % n_groups

    sampled = []
    keys = sorted(groups.keys())
    random.seed(seed)

    for i, key in enumerate(keys):
        group = groups[key]
        take = base_per_group + (1 if i < remainder else 0)
        take = min(take, len(group))
        chosen = random.sample(group, take)
        sampled.extend(chosen)
        print(f"  {key[0]:8s} | {key[1]:30s} : {take}/{len(group)} cases sampled")

    # Sort by case_id for deterministic ordering
    sampled.sort(key=lambda c: c["case_id"])
    print(f"\n  Total sampled: {len(sampled)} cases across {n_groups} groups")
    return sampled


async def run_single_case(case_info: dict, agent_brief: str,
                           base_dir: str, run_index: int,
                           temperature: float = 0) -> dict:
    """Run one case through the agent."""
    case_id = case_info["case_id"]
    documents = case_info.get("documents", [])
    wording = case_info.get("wording", "")

    case_dir = os.path.join(base_dir, "cases", case_id)

    result = await run_case(
        case_id=case_id,
        case_info=case_info,
        wording_path=wording,
        documents=documents,
        agent_brief_text=agent_brief,
        case_dir=case_dir,
        base_dir=base_dir,
        max_turns=30,
        temperature=temperature,
    )
    result["run_index"] = run_index
    return result


async def main():
    parser = argparse.ArgumentParser(
        description="Run claims adjudicator evaluation"
    )
    parser.add_argument(
        "--sample", type=int, default=0,
        help="Sample N cases (equally distributed by difficulty/product). "
             "0 = use all cases."
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Number of independent runs per case (k). Default: 1."
    )
    parser.add_argument(
        "--case-ids", nargs="*", default=None,
        help="Run only these specific case IDs."
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for sampling."
    )
    parser.add_argument(
        "--output", type=str, default=str(DEFAULT_OUTPUT),
        help="Output JSONL file path."
    )
    parser.add_argument(
        "--temperature", type=float, default=0,
        help="LLM temperature. Default: 0."
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  EMA Claims Adjudication — Evaluation Runner")
    print("=" * 70)

    # Load data
    print("\nLoading data...")
    gold = load_gold_truth()
    print(f"  Gold truth: {len(gold)} cases")

    index = load_index()
    print(f"  Index: {len(index)} cases")

    agent_brief = load_agent_brief()
    print(f"  Agent brief: {len(agent_brief)} chars")

    # Select cases
    cases = index
    if args.case_ids:
        cases = [c for c in cases if c["case_id"] in args.case_ids]
        print(f"\n  Filtered to {len(cases)} specific cases")
    elif args.sample > 0:
        print(f"\n  Sampling {args.sample} cases (seed={args.seed})...")
        cases = sample_cases(cases, gold, n=args.sample, seed=args.seed)

    print(f"\n  Running {len(cases)} cases x {args.runs} run(s) = "
          f"{len(cases) * args.runs} total invocations")
    print(f"  Temperature: {args.temperature}")
    print(f"  Output: {args.output}")

    # Run cases
    results = []
    completed_count = 0
    success_count = 0

    for i, case_info in enumerate(cases):
        case_id = case_info["case_id"]
        product = case_info.get("product_id", "?")

        for k in range(args.runs):
            completed_count += 1
            try:
                result = await run_single_case(
                    case_info=case_info,
                    agent_brief=agent_brief,
                    base_dir=str(PUBLIC_DIR),
                    run_index=k,
                    temperature=args.temperature,
                )
                results.append(result)

                if result["completed"]:
                    success_count += 1
                    v = result["verdict"] or "NONE"
                    a = result["payable"]
                    print(f"  [{completed_count:>4d}] {case_id} run={k} "
                          f"-> {v} payable={a} ({result['usage']['round_trips']} turns, "
                          f"{result['wall_clock_seconds']}s)")
                else:
                    print(f"  [{completed_count:>4d}] {case_id} run={k} "
                          f"-> FAILED to complete")

            except Exception as e:
                print(f"  [{completed_count:>4d}] {case_id} run={k} "
                      f"-> ERROR: {e}")
                # Record a failed result
                results.append({
                    "case_id": case_id,
                    "run_index": k,
                    "product_id": product,
                    "agent_version": "benchmark-adapter-0.1.0",
                    "model": "vllm/Qwen3.6-27B",
                    "prompt_id": "claims-ref-1",
                    "verdict": None,
                    "payable": None,
                    "clauses": [],
                    "explanation": f"Error: {e}",
                    "completed": False,
                    "trace": [],
                    "usage": {"input_tokens": 0, "output_tokens": 0, "round_trips": 0},
                    "wall_clock_seconds": 0,
                })

    # Write results
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("\n" + "=" * 70)
    print("  Results written to:", output_path)
    print(f"  Total runs: {len(results)}")
    print(f"  Completed: {success_count}/{len(results)} "
          f"({100*success_count/len(results):.1f}%)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
