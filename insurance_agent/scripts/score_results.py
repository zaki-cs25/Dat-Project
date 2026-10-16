#!/usr/bin/env python3
"""
score_results.py — Score agent results against gold.jsonl ground truth.

Computes all KPIs defined in dataset/public/METRICS.md and generates
a structured report.

Usage:
    python3 scripts/score_results.py --results results.jsonl

    # Custom output:
    python3 scripts/score_results.py --results results.jsonl --output reports/report.md
"""

import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict, Counter
from itertools import combinations

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Paths
DATASET_DIR = PROJECT_ROOT / "dataset"
GOLD_FILE = DATASET_DIR / "gold.jsonl"
DEFAULT_RESULTS = PROJECT_ROOT / "results.jsonl"
DEFAULT_REPORT = PROJECT_ROOT / "reports" / "evaluation_report.md"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_gold(path: str) -> list[dict]:
    gold = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                gold.append(json.loads(line))
    return gold


def load_results(path: str) -> list[dict]:
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def verdict_match(pred: str | None, gold: str) -> bool:
    return pred == gold


def amount_exact_match(pred: int | None, gold: int) -> bool:
    return pred is not None and pred == gold


def amount_within_tolerance(pred: int | None, gold: int, tol: float = 0.01) -> bool:
    if pred is None or gold == 0:
        return pred == gold == 0
    return abs(pred - gold) / gold <= tol


def clause_precision_recall_f1(pred: list[str], gold: list[str]):
    """Compute precision, recall, F1 for clause sets (order-insensitive)."""
    pred_set = set(pred) if pred else set()
    gold_set = set(gold) if gold else set()

    if not pred_set and not gold_set:
        return 1.0, 1.0, 1.0

    tp = len(pred_set & gold_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) > 0 else 0.0)

    return precision, recall, f1


def fully_correct(pred: dict, gold: dict) -> bool:
    """Verdict AND amount AND clause set all correct."""
    if not pred.get("completed"):
        return False
    return (
        verdict_match(pred.get("verdict"), gold["verdict"])
        and amount_exact_match(pred.get("payable"), gold["payable"])
        and set(pred.get("clauses", []) or []) == set(gold.get("clauses", []) or [])
    )


def confusion_matrix(results: list[dict], gold_map: dict) -> dict[str, dict[str, int]]:
    """Build 4x4 confusion matrix: gold -> predicted."""
    verdicts = ["APPROVE", "PARTIAL", "REJECT", "ESCALATE"]
    matrix = {v: {v2: 0 for v2 in verdicts} for v in verdicts}
    matrix["NONE"] = {v2: 0 for v2 in verdicts}  # for incomplete runs

    for r in results:
        gid = r["case_id"]
        if gid not in gold_map:
            continue
        gold_v = gold_map[gid]["verdict"]
        pred_v = r.get("verdict") or "NONE"
        if pred_v not in matrix:
            pred_v = "NONE"
        matrix[gold_v][pred_v] += 1

    return matrix


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def compute_metrics(results: list[dict], gold_map: dict):
    """Compute all KPIs from METRICS.md."""

    # Group by case_id (for k runs)
    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_case[r["case_id"]].append(r)

    total_cases = len(by_case)
    if total_cases == 0:
        return {}

    # Per-case metrics (use run 0 for single-case metrics)
    case_results = []
    for gid, runs in by_case.items():
        if gid not in gold_map:
            continue
        g = gold_map[gid]
        r = runs[0]  # first run for per-case scoring

        v_match = verdict_match(r.get("verdict"), g["verdict"])
        a_exact = amount_exact_match(r.get("payable"), g["payable"])
        a_tol = amount_within_tolerance(r.get("payable"), g["payable"])
        p, rec, f1 = clause_precision_recall_f1(r.get("clauses"), g["clauses"])
        fc = fully_correct(r, g)

        # Wrong approve / wrong reject
        wrong_approve = (g["verdict"] in ("APPROVE", "PARTIAL", "REJECT")
                         and r.get("verdict") == "APPROVE"
                         and g["verdict"] == "REJECT")
        wrong_reject = (g["verdict"] in ("APPROVE", "PARTIAL")
                        and r.get("verdict") == "REJECT")

        case_results.append({
            "case_id": gid,
            "difficulty": g.get("difficulty", "unknown"),
            "product_id": g.get("product_id", "unknown"),
            "scenario": g.get("scenario", "unknown"),
            "scenario_tags": g.get("scenario_tags", []),
            "gold_verdict": g["verdict"],
            "pred_verdict": r.get("verdict"),
            "gold_payable": g["payable"],
            "pred_payable": r.get("payable"),
            "gold_clauses": g.get("clauses", []),
            "pred_clauses": r.get("clauses", []),
            "verdict_match": v_match,
            "amount_exact": a_exact,
            "amount_within_1pct": a_tol,
            "clause_precision": p,
            "clause_recall": rec,
            "clause_f1": f1,
            "fully_correct": fc,
            "wrong_approve": wrong_approve,
            "wrong_reject": wrong_reject,
            "completed": r.get("completed", False),
            "round_trips": r.get("usage", {}).get("round_trips", 0),
            "input_tokens": r.get("usage", {}).get("input_tokens", 0),
            "output_tokens": r.get("usage", {}).get("output_tokens", 0),
            "wall_clock": r.get("wall_clock_seconds", 0),
            # Multi-run metrics
            "n_runs": len(runs),
            "all_runs_fc": all(fully_correct(run, g) for run in runs),
        })

    # Confusion matrix
    cm = confusion_matrix(results, gold_map)

    # Aggregation helper
    def mean(vals):
        return sum(vals) / len(vals) if vals else 0

    def group_by_key(key_fn):
        groups = defaultdict(list)
        for cr in case_results:
            key = key_fn(cr)
            groups[key].append(cr)
        return groups

    # Overall metrics
    n_completed = sum(1 for cr in case_results if cr["completed"])
    metrics = {
        "total_cases": len(case_results),
        "total_runs": sum(cr["n_runs"] for cr in case_results),
        "completion_rate": n_completed / len(case_results) if case_results else 0,
        "verdict_accuracy": mean([cr["verdict_match"] for cr in case_results]),
        "amount_exact_match": mean([cr["amount_exact"] for cr in case_results]),
        "amount_within_1pct": mean([cr["amount_within_1pct"] for cr in case_results]),
        "clause_precision": mean([cr["clause_precision"] for cr in case_results]),
        "clause_recall": mean([cr["clause_recall"] for cr in case_results]),
        "clause_f1": mean([cr["clause_f1"] for cr in case_results]),
        "fully_correct": mean([cr["fully_correct"] for cr in case_results]),
        "wrong_approve_rate": sum(1 for cr in case_results if cr["wrong_approve"])
            / len(case_results) if case_results else 0,
        "wrong_reject_rate": sum(1 for cr in case_results if cr["wrong_reject"])
            / len(case_results) if case_results else 0,
        # pass@k metrics
        "pass_at_k": mean([cr["all_runs_fc"] for cr in case_results]),
        "pass_at_1": mean([cr["fully_correct"] for cr in case_results]),
        # Escalation metrics
        "escalation_recall": 0,
        "false_escalation_rate": 0,
        # Cost
        "avg_input_tokens": mean([cr["input_tokens"] for cr in case_results]),
        "avg_output_tokens": mean([cr["output_tokens"] for cr in case_results]),
        "avg_round_trips": mean([cr["round_trips"] for cr in case_results]),
        "avg_wall_clock": mean([cr["wall_clock"] for cr in case_results]),
        # Tool calls on success
        "avg_tool_calls_on_success": 0,
        # Confusion matrix
        "confusion_matrix": cm,
        # Breakdowns
        "by_difficulty": {},
        "by_product": {},
        "by_scenario": {},
        # Raw case results for drill-down
        "_case_results": case_results,
    }

    # Escalation metrics
    esc_gold = [cr for cr in case_results if cr["gold_verdict"] == "ESCALATE"]
    esc_pred = [cr for cr in case_results if cr["pred_verdict"] == "ESCALATE"]
    non_esc_gold = [cr for cr in case_results if cr["gold_verdict"] != "ESCALATE"]

    if esc_gold:
        metrics["escalation_recall"] = sum(
            1 for cr in esc_gold if cr["pred_verdict"] == "ESCALATE"
        ) / len(esc_gold)

    if non_esc_gold:
        metrics["false_escalation_rate"] = sum(
            1 for cr in non_esc_gold if cr["pred_verdict"] == "ESCALATE"
        ) / len(non_esc_gold)

    # Tool calls on success
    success_cases = [cr for cr in case_results if cr["fully_correct"] and cr["completed"]]
    if success_cases:
        # Approximate tool calls as round_trips - 1 (first turn doesn't have tool response)
        metrics["avg_tool_calls_on_success"] = mean(
            [cr["round_trips"] - 1 for cr in success_cases]
        )

    # Breakdowns
    def summarize_group(group):
        return {
            "n": len(group),
            "verdict_accuracy": mean([cr["verdict_match"] for cr in group]),
            "amount_exact": mean([cr["amount_exact"] for cr in group]),
            "amount_within_1pct": mean([cr["amount_within_1pct"] for cr in group]),
            "clause_f1": mean([cr["clause_f1"] for cr in group]),
            "fully_correct": mean([cr["fully_correct"] for cr in group]),
        }

    for diff, group in group_by_key(lambda cr: cr["difficulty"]).items():
        metrics["by_difficulty"][diff] = summarize_group(group)

    for prod, group in group_by_key(lambda cr: cr["product_id"]).items():
        metrics["by_product"][prod] = summarize_group(group)

    for scenario, group in group_by_key(lambda cr: cr["scenario"]).items():
        metrics["by_scenario"][scenario] = summarize_group(group)

    return metrics


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def fmt(p: float) -> str:
    """Format percentage."""
    return f"{p*100:.1f}%"


def fmt_num(v: float) -> str:
    """Format a number."""
    if v >= 1:
        return f"{v:,.0f}"
    return f"{v:.4f}"


def generate_report(metrics: dict, output_path: str):
    """Generate a Markdown evaluation report."""
    lines = []

    def w(text=""):
        lines.append(text)

    w("# EMA Claims Adjudicator — Evaluation Report")
    w()
    w(f"**Cases evaluated:** {metrics['total_cases']}")
    w(f"**Total runs:** {metrics['total_runs']}")
    w(f"**Completion rate:** {fmt(metrics['completion_rate'])}")
    w()

    # Executive Summary
    w("---")
    w()
    w("## Executive Summary")
    w()
    w("| Metric | Value |")
    w("|---|---|")
    w(f"| **Fully Correct** (verdict + amount + clauses) | **{fmt(metrics['fully_correct'])}** |")
    w(f"| Verdict Accuracy | {fmt(metrics['verdict_accuracy'])} |")
    w(f"| Amount Exact Match | {fmt(metrics['amount_exact_match'])} |")
    w(f"| Amount Within ±1% | {fmt(metrics['amount_within_1pct'])} |")
    w(f"| Clause Precision | {fmt(metrics['clause_precision'])} |")
    w(f"| Clause Recall | {fmt(metrics['clause_recall'])} |")
    w(f"| Clause F1 | {fmt(metrics['clause_f1'])} |")
    w(f"| Wrong Approve Rate | {fmt(metrics['wrong_approve_rate'])} |")
    w(f"| Wrong Reject Rate | {fmt(metrics['wrong_reject_rate'])} |")
    w()

    # Confusion Matrix
    w("---")
    w()
    w("## Confusion Matrix")
    w()
    w("(Gold → Predicted)")
    w()
    cm = metrics["confusion_matrix"]
    verdicts = ["APPROVE", "PARTIAL", "REJECT", "ESCALATE"]
    header = "| Gold \\ Predicted | " + " | ".join(verdicts) + " |"
    w(header)
    w("|" + "|".join(["---"] * (len(verdicts) + 1)) + "|")
    for gold_v in verdicts:
        row = f"| {gold_v} |"
        for pred_v in verdicts:
            val = cm.get(gold_v, {}).get(pred_v, 0)
            highlight = " **" + str(val) + "**" if gold_v == pred_v else f" {val}"
            row += highlight + " |"
        w(row)
    if "NONE" in cm:
        none_row = "| **None (incomplete)** |"
        for pred_v in verdicts:
            val = cm["NONE"].get(pred_v, 0)
            none_row += f" {val} |"
        none_row += f" {cm['NONE'].get('NONE', 0)} |"
        w(none_row)
    w()

    # Reliability (pass@k)
    w("---")
    w()
    w("## Reliability (k-runs)")
    w()
    w(f"| Metric | Value |")
    w("|---|---|")
    w(f"| **Pass@k** (correct in ALL runs) | {fmt(metrics['pass_at_k'])} |")
    w(f"| **Pass@1** (mean single-run) | {fmt(metrics['pass_at_1'])} |")
    w(f"| Gap (Pass@1 − Pass@k) | {fmt(metrics['pass_at_1'] - metrics['pass_at_k'])} |")
    w()

    # Escalation
    w("---")
    w()
    w("## Escalation")
    w()
    w("| Metric | Value |")
    w("|---|---|")
    w(f"| **Escalation Recall** | {fmt(metrics['escalation_recall'])} |")
    w(f"| **False Escalation Rate** | {fmt(metrics['false_escalation_rate'])} |")
    w()

    # Cost
    w("---")
    w()
    w("## Cost & Efficiency")
    w()
    w("| Metric | Value |")
    w("|---|---|")
    w(f"| Avg Input Tokens / Case | {fmt_num(metrics['avg_input_tokens'])} |")
    w(f"| Avg Output Tokens / Case | {fmt_num(metrics['avg_output_tokens'])} |")
    w(f"| Avg LLM Round Trips / Case | {metrics['avg_round_trips']:.1f} |")
    w(f"| Avg Wall Clock / Case | {metrics['avg_wall_clock']:.1f}s |")
    w(f"| Avg Tool Calls (on success) | {metrics['avg_tool_calls_on_success']:.1f} |")
    w()

    # Breakdown by difficulty
    w("---")
    w()
    w("## Breakdown by Difficulty")
    w()
    w("| Difficulty | Cases | Verdict Acc | Amt Exact | Clause F1 | Fully Correct |")
    w("|---|---|---|---|---|---|")
    for diff in ["easy", "medium", "hard"]:
        d = metrics["by_difficulty"].get(diff, {})
        if d:
            w(f"| {diff} | {d['n']} | {fmt(d['verdict_accuracy'])} "
              f"| {fmt(d['amount_exact'])} | {fmt(d['clause_f1'])} "
              f"| **{fmt(d['fully_correct'])}** |")
    w()

    # Breakdown by product
    w("---")
    w()
    w("## Breakdown by Product")
    w()
    w("| Product | Cases | Verdict Acc | Amt Exact | Clause F1 | Fully Correct |")
    w("|---|---|---|---|---|---|")
    for prod, d in sorted(metrics["by_product"].items()):
        short_prod = prod[:25] + "..." if len(prod) > 28 else prod
        w(f"| {short_prod} | {d['n']} | {fmt(d['verdict_accuracy'])} "
          f"| {fmt(d['amount_exact'])} | {fmt(d['clause_f1'])} "
          f"| **{fmt(d['fully_correct'])}** |")
    w()

    # Breakdown by scenario
    w("---")
    w()
    w("## Breakdown by Scenario")
    w()
    w("| Scenario | Cases | Verdict Acc | Amt Exact | Clause F1 | Fully Correct |")
    w("|---|---|---|---|---|---|")
    # Sort by number of cases descending
    for scenario, d in sorted(
        metrics["by_scenario"].items(),
        key=lambda x: x[1]["n"], reverse=True
    ):
        short_sc = scenario[:22] + "..." if len(scenario) > 25 else scenario
        w(f"| {short_sc} | {d['n']} | {fmt(d['verdict_accuracy'])} "
          f"| {fmt(d['amount_exact'])} | {fmt(d['clause_f1'])} "
          f"| {fmt(d['fully_correct'])} |")
    w()

    # Top failure cases
    w("---")
    w()
    w("## Top 10 Failure Cases")
    w()
    case_results = metrics.get("_case_results", [])
    failures = [cr for cr in case_results if not cr["fully_correct"]]
    # Sort by: wrong_approve first, then wrong_reject, then others
    failures.sort(key=lambda cr: (
        0 if cr["wrong_approve"] else (0 if cr["wrong_reject"] else 1),
        cr["clause_f1"]
    ))

    if failures:
        w("| Case | Difficulty | Scenario | Gold Verdict | Pred Verdict | Gold Amt | Pred Amt | Clause F1 |")
        w("|---|---|---|---|---|---|---|---|")
        for cr in failures[:10]:
            w(f"| {cr['case_id']} | {cr['difficulty']} | {cr['scenario']} "
              f"| {cr['gold_verdict']} | {cr['pred_verdict'] or 'NONE'} "
              f"| {cr['gold_payable']} | {cr['pred_payable'] or '—'} "
              f"| {cr['clause_f1']:.2f} |")
    else:
        w("*All cases fully correct!* 🎉")
    w()

    # Write
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    return output_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Score evaluation results")
    parser.add_argument(
        "--results", type=str, default=str(DEFAULT_RESULTS),
        help="Path to results.jsonl"
    )
    parser.add_argument(
        "--gold", type=str, default=str(GOLD_FILE),
        help="Path to gold.jsonl"
    )
    parser.add_argument(
        "--output", type=str, default=str(DEFAULT_REPORT),
        help="Output report path (Markdown)"
    )
    parser.add_argument(
        "--json-output", type=str, default=None,
        help="Also write metrics as JSON to this path"
    )
    args = parser.parse_args()

    print("Loading data...")
    gold = load_gold(args.gold)
    gold_map = {g["case_id"]: g for g in gold}
    print(f"  Gold: {len(gold)} cases")

    results = load_results(args.results)
    print(f"  Results: {len(results)} runs")

    print("Computing metrics...")
    metrics = compute_metrics(results, gold_map)

    # Generate report
    report_path = generate_report(metrics, args.output)
    print(f"\nReport written to: {report_path}")

    # Also write JSON
    json_out = args.json_output or args.output.replace(".md", ".json")
    # Remove _case_results for the JSON summary (it's large)
    metrics_copy = {k: v for k, v in metrics.items() if not k.startswith("_")}
    with open(json_out, "w") as f:
        json.dump(metrics_copy, f, indent=2, default=str)
    print(f"Metrics JSON: {json_out}")

    # Print summary to console
    print("\n" + "=" * 60)
    print("  QUICK SUMMARY")
    print("=" * 60)
    print(f"  Fully Correct:  {metrics['fully_correct']*100:.1f}%")
    print(f"  Verdict Acc:    {metrics['verdict_accuracy']*100:.1f}%")
    print(f"  Amt Exact:      {metrics['amount_exact_match']*100:.1f}%")
    print(f"  Amt Within 1%:  {metrics['amount_within_1pct']*100:.1f}%")
    print(f"  Clause F1:      {metrics['clause_f1']*100:.1f}%")
    print(f"  Pass@k:         {metrics['pass_at_k']*100:.1f}%")
    print(f"  Esc Recall:     {metrics['escalation_recall']*100:.1f}%")
    print(f"  False Esc:      {metrics['false_escalation_rate']*100:.1f}%")

    # Per-difficulty quick print
    print("\n  By Difficulty:")
    for diff in ["easy", "medium", "hard"]:
        d = metrics["by_difficulty"].get(diff, {})
        if d:
            print(f"    {diff:8s}: FC={d['fully_correct']*100:.1f}%  "
                  f"VA={d['verdict_accuracy']*100:.1f}%  "
                  f"CF1={d['clause_f1']*100:.1f}%")

    print("=" * 60)


if __name__ == "__main__":
    main()
