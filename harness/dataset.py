"""Dataset loader — converts raw dataset files into the universal Case format."""

from __future__ import annotations

import json
from pathlib import Path
from harness.types import Case


def load_dataset(path: str) -> list[Case]:
    """Load a JSONL or JSON dataset.
    
    Expected format (one object per line, or a JSON array):
    {
      "id": "case-001",
      "input": "the content the agent works on",
      "ground_truth": {"verdict": "APPROVE", "payable": 1000, ...},
      "metadata": {"optional": "extra fields the adapter needs"}
    }
    
    Placeholders — replace with actual dataset paths:
    - Insurance: ./insurance_agent/dataset/benchmark_cases.jsonl
    - Finance:   ./datasets/finance/cases.jsonl
    - Coding:    ./datasets/coding/cases.jsonl
    """
    cases: list[Case] = []
    raw = _read_jsonl(path)

    for obj in raw:
        cases.append(Case(
            id=obj["id"],
            input=obj["input"],
            ground_truth=obj.get("ground_truth"),
            metadata=obj.get("metadata", {}),
        ))

    return cases


def _read_jsonl(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    text = p.read_text().strip()
    if not text:
        return []

    # Try JSONL first, then JSON array
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    try:
        return [json.loads(line) for line in lines]
    except json.JSONDecodeError:
        # Try as single JSON array
        return json.loads(text)
