"""
Benchmark runner for the health claims adjudication agent.

Runs every case from the dataset through the adjudicator k=4 times and
writes results in the benchmark submission format.

Usage:
    python3 backend/scripts/benchmark_runner.py --cases 20     # first 20 cases
    python3 backend/scripts/benchmark_runner.py --all            # all 1000 cases
    python3 backend/scripts/benchmark_runner.py --all --k 1     # single run per case
    python3 backend/scripts/benchmark_runner.py --subset 0-99   # cases 0-99
    python3 backend/scripts/benchmark_runner.py --resume         # continue from last run
"""

import argparse
import asyncio
import json
import os
import sys
import time
from io import BytesIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from pypdf import PdfReader

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.agents.health_adjudicator import adjudicate_benchmark

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATASET_DIR = PROJECT_ROOT / "dataset"
PUBLIC_DIR = DATASET_DIR / "public"
RESULTS_DIR = PROJECT_ROOT / "results"

INDEX_PATH = PUBLIC_DIR / "index.jsonl"
CASES_DIR = PUBLIC_DIR / "cases"
WORDINGS_DIR = PUBLIC_DIR / "wordings"
GOLD_PATH = DATASET_DIR / "gold.jsonl"
OUTPUT_PATH = RESULTS_DIR / "benchmark_run.jsonl"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_index(limit=None, subset=None, resume=False):
    """Load index.jsonl and return list of case entries.

    limit: int — first N cases
    subset: str — e.g. "0-99" or "100-199"
    resume: bool — skip cases already present in OUTPUT_PATH
    """
    entries = []
    with open(INDEX_PATH) as f:
        for line in f:
            entries.append(json.loads(line.strip()))

    # Filter by subset
    if subset:
        lo, hi = subset.split("-")
        lo, hi = int(lo), int(hi)
        entries = [e for e in entries if lo <= int(e["case_id"].split("-")[1]) <= hi]

    if limit:
        entries = entries[:limit]

    if resume and OUTPUT_PATH.exists():
        done_ids = set()
        with open(OUTPUT_PATH) as f:
            for line in f:
                obj = json.loads(line.strip())
                done_ids.add(obj["case_id"])
        entries = [e for e in entries if e["case_id"] not in done_ids]

    return entries


def load_gold():
    """Load gold.jsonl into a dict keyed by case_id."""
    gold = {}
    with open(GOLD_PATH) as f:
        for line in f:
            obj = json.loads(line.strip())
            gold[obj["case_id"]] = obj
    return gold


def extract_pdf_text(pdf_path):
    """Extract text from a PDF file, return string."""
    try:
        pdf = PdfReader(pdf_path)
        pages = []
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text()
            if text:
                pages.append(f"[Page {i}]\n{text}")
        return "\n".join(pages) if pages else "(No extractable text)"
    except Exception as e:
        return f"(Error reading PDF: {e})"


def build_documents_text(entry):
    """Extract all PDFs for a case and return combined text with headers."""
    case_id = entry["case_id"]
    product_id = entry["product_id"]
    parts = []

    # Policy wording
    wording_path = WORDINGS_DIR / entry["wording"]
    if wording_path.exists():
        text = extract_pdf_text(wording_path)
        parts.append(f"=== Document: policy_wording ({wording_path.name}) ===\n\n{text}\n")

    # Case documents
    case_dir = CASES_DIR / case_id / "documents"
    for doc_path_str in entry.get("documents", []):
        doc_path = PUBLIC_DIR / doc_path_str
        if doc_path.exists():
            text = extract_pdf_text(doc_path)
            doc_name = doc_path.name
            # Normalize name for the agent
            base = Path(doc_path_str).stem
            parts.append(f"=== Document: {base} ({doc_name}) ===\n\n{text}\n")
    return "\n".join(parts)


async def run_single_case(case_entry, run_index, gold_entry=None):
    """Run the adjudicator on a single case, return result dict."""
    case_id = case_entry["case_id"]
    product_id = case_entry["product_id"]

    # Build combined document text (cached per case, not per run)
    documents_text = build_documents_text(case_entry)

    start = time.time()
    result = await adjudicate_benchmark(documents_text)
    elapsed = time.time() - start

    # Build submission record
    record = {
        "case_id": case_id,
        "run_index": run_index,
        "product_id": product_id,
        "agent_version": "ema-benchmark-0.1.0",
        "model": "vllm/Qwen3.6-27B",
        "prompt_id": "claims-ref-1",
        "verdict": result.get("verdict"),
        "payable": result.get("payable"),
        "clauses": result.get("clauses", []),
        "explanation": result.get("explanation", ""),
        "completed": result.get("verdict") is not None,
        "trace": [],
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "round_trips": 1,
        },
        "wall_clock_seconds": round(elapsed, 2),
    }

    return record


async def run_all_cases(entries, k=4, concurrency=5):
    """Run all cases k times each with async concurrency."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    gold = load_gold()

    total = len(entries) * k
    completed = 0
    semaphore = asyncio.Semaphore(concurrency)

    async def _run(entry, run_idx):
        nonlocal completed
        async with semaphore:
            rec = await run_single_case(entry, run_idx, gold.get(entry["case_id"]))

            # Write record immediately (append)
            mode = "a"
            # Check if we need to truncate on first write
            if not OUTPUT_PATH.exists():
                mode = "w"

            with open(OUTPUT_PATH, "a") as f:
                f.write(json.dumps(rec) + "\n")

            completed += 1
            pct = completed / total * 100
            status = "OK" if rec["completed"] else "FAIL"
            verdict = rec["verdict"] or "—"
            print(f"  [{status}] {entry['case_id']} run#{run_idx} -> {verdict}  ({completed}/{total} {pct:.0f}%)")
            return rec

    # Build all tasks
    tasks = []
    for entry in entries:
        for run_idx in range(k):
            tasks.append(_run(entry, run_idx))

    # Run in batches via gather
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Print summary
    errors = [r for r in results if isinstance(r, Exception)]
    print(f"\n--- Runner Summary ---")
    print(f"  Cases: {len(entries)}")
    print(f"  Runs per case: {k}")
    print(f"  Total runs: {len(results)}")
    print(f"  Exceptions: {len(errors)}")
    if errors:
        for e in errors[:5]:
            print(f"    {e}")
    print(f"  Output: {OUTPUT_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run benchmark on claims adjudication dataset")
    parser.add_argument("--all", action="store_true", help="Run all 1000 cases")
    parser.add_argument("--cases", type=int, default=20, help="Number of cases to run (default 20)")
    parser.add_argument("--subset", type=str, help="Range e.g. 0-99 or 100-199")
    parser.add_argument("--k", type=int, default=4, help="Runs per case (default 4)")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent async requests (default 5)")
    parser.add_argument("--resume", action="store_true", help="Skip cases already in output file")

    args = parser.parse_args()

    entries = load_index(
        limit=args.cases if not args.all else None,
        subset=args.subset,
        resume=args.resume,
    )

    if not entries:
        print("No cases to run. Check --subset, --cases, --resume flags.")
        return

    print(f"Running {len(entries)} cases x {args.k} runs = {len(entries) * args.k} total runs")
    print(f"Concurrency: {args.concurrency}")
    print(f"Output: {OUTPUT_PATH}")
    print()

    asyncio.run(run_all_cases(entries, k=args.k, concurrency=args.concurrency))


if __name__ == "__main__":
    main()
