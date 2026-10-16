#!/usr/bin/env python3
"""
evaluate_single_case.py — Debug tool: run and score a single case.

Usage:
    python3 scripts/evaluate_single_case.py --case-id case-000000
"""

import argparse
import json
import sys
import asyncio
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.benchmark_adapter import run_case


def load_agent_brief():
    return (PROJECT_ROOT / "dataset" / "public" / "AGENT_BRIEF.md").read_text()


def load_index():
    index = []
    with open(PROJECT_ROOT / "dataset" / "public" / "index.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                index.append(json.loads(line))
    return index


def load_gold():
    gold = []
    with open(PROJECT_ROOT / "dataset" / "gold.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                gold.append(json.loads(line))
    return gold


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()

    case_id = args.case_id
    index = load_index()
    gold = load_gold()

    case_info = None
    for c in index:
        if c["case_id"] == case_id:
            case_info = c
            break

    if not case_info:
        print(f"Case {case_id} not found in index.jsonl")
        sys.exit(1)

    gold_info = None
    for g in gold:
        if g["case_id"] == case_id:
            gold_info = g
            break

    if not gold_info:
        print(f"Case {case_id} not found in gold.jsonl")
        sys.exit(1)

    agent_brief = load_agent_brief()

    print(f"Case: {case_id}")
    print(f"Product: {case_info['product_id']}")
    print(f"Documents: {case_info.get('documents', [])}")
    print(f"Gold: verdict={gold_info['verdict']} payable={gold_info['payable']} "
          f"clauses={gold_info['clauses']}")
    print()

    base_dir = str(PROJECT_ROOT / "dataset" / "public")

    for k in range(args.runs):
        print(f"--- Run {k} ---")
        result = await run_case(
            case_id=case_id,
            case_info=case_info,
            wording_path=case_info["wording"],
            documents=case_info.get("documents", []),
            agent_brief_text=agent_brief,
            case_dir=f"{base_dir}/cases/{case_id}",
            base_dir=base_dir,
            max_turns=30,
            temperature=0,
        )
        result["run_index"] = k

        print(f"Completed: {result['completed']}")
        print(f"Verdict: {result['verdict']}")
        print(f"Payable: {result['payable']}")
        print(f"Clauses: {result['clauses']}")
        print(f"Explanation: {result['explanation'][:200]}...")
        print(f"Round trips: {result['usage']['round_trips']}")
        print(f"Wall clock: {result['wall_clock_seconds']}s")

        if not result["completed"]:
            print("Trace:")
            print(json.dumps(result["trace"], indent=2))

        # Quick scoring
        if result["completed"]:
            v_match = result["verdict"] == gold_info["verdict"]
            a_match = result["payable"] == gold_info["payable"]
            c_match = (set(result["clauses"] or []) ==
                       set(gold_info["clauses"] or []))
            fc = v_match and a_match and c_match
            print(f"\n  Verdict match: {v_match}")
            print(f"  Amount match: {a_match}")
            print(f"  Clauses match: {c_match}")
            print(f"  FULLY CORRECT: {fc}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
