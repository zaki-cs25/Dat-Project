"""
Benchmark evaluator for the health claims adjudication agent.

Reads benchmark_run.jsonl + gold.jsonl and computes all KPIs from METRICS.md.
Produces a JSON report and a Markdown report.

Usage:
    python3 backend/scripts/benchmark_evaluator.py
    python3 backend/scripts/benchmark_evaluator.py --runs 1   # single-run mode
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from textwrap import dedent

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATASET_DIR = PROJECT_ROOT / "dataset"
RESULTS_DIR = PROJECT_ROOT / "results"

GOLD_PATH = DATASET_DIR / "gold.jsonl"
RUN_PATH = RESULTS_DIR / "benchmark_run.jsonl"

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_gold():
    gold = {}
    with open(GOLD_PATH) as f:
        for line in f:
            obj = json.loads(line.strip())
            gold[obj["case_id"]] = obj
    return gold


def load_runs():
    runs = defaultdict(list)  # case_id -> [record, ...]
    with open(RUN_PATH) as f:
        for line in f:
            rec = json.loads(line.strip())
            runs[rec["case_id"]].append(rec)
    return runs


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def verdict_match(pred, gold):
    return pred == gold


def payable_exact(pred, gold):
    return pred == gold


def payable_within_1pct(pred, gold):
    if gold == 0:
        return pred == 0
    return abs(pred - gold) / gold <= 0.01


def clause_f1(pred_clauses, gold_clauses):
    p = set(pred_clauses or [])
    g = set(gold_clauses or [])
    tp = len(p & g)
    if tp == 0:
        return 0.0, 0.0, 0.0
    prec = tp / len(p) if p else 0.0
    rec = tp / len(g) if g else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return prec, rec, f1


def fully_correct(rec, gold_rec):
    if not rec.get("completed"):
        return False
    if rec.get("verdict") != gold_rec.get("verdict"):
        return False
    if rec.get("payable") != gold_rec.get("payable"):
        return False
    p = set(rec.get("clauses", []) or [])
    g = set(gold_rec.get("clauses", []) or [])
    return p == g


def compute_metrics(runs, gold):
    """Compute all metrics from METRICS.md."""
    cases = sorted(runs.keys())
    total_cases = len(cases)

    # Per-case, per-run metrics
    all_records = []
    for cid in cases:
        for rec in runs[cid]:
            g = gold.get(cid, {})
            is_fc = fully_correct(rec, g)
            v_match = verdict_match(rec.get("verdict"), g.get("verdict"))
            p_exact = payable_exact(rec.get("payable"), g.get("payable"))
            p_within = payable_within_1pct(rec.get("payable"), g.get("payable"))
            cp, cr, cf = clause_f1(rec.get("clauses"), g.get("clauses"))

            all_records.append({
                "case_id": cid,
                "run_index": rec.get("run_index"),
                "product_id": rec.get("product_id"),
                "verdict_pred": rec.get("verdict"),
                "verdict_gold": g.get("verdict"),
                "payable_pred": rec.get("payable"),
                "payable_gold": g.get("payable"),
                "clauses_pred": rec.get("clauses", []),
                "clauses_gold": g.get("clauses", []),
                "difficulty": g.get("difficulty"),
                "scenario": g.get("scenario"),
                "completed": rec.get("completed", False),
                "v_match": v_match,
                "p_exact": p_exact,
                "p_within": p_within,
                "clause_prec": cp,
                "clause_rec": cr,
                "clause_f1": cf,
                "fully_correct": is_fc,
                "wall_clock": rec.get("wall_clock_seconds", 0),
            })

    # --- Overall ---
    total_runs = len(all_records)
    completed = sum(1 for r in all_records if r["completed"])
    fc_count = sum(1 for r in all_records if r["fully_correct"])
    v_acc = sum(1 for r in all_records if r["v_match"])
    p_exact_c = sum(1 for r in all_records if r["p_exact"])
    p_within_c = sum(1 for r in all_records if r["p_within"])
    avg_cp = sum(r["clause_prec"] for r in all_records) / total_runs
    avg_cr = sum(r["clause_rec"] for r in all_records) / total_runs
    avg_cf = sum(r["clause_f1"] for r in all_records) / total_runs

    # Confusion matrix
    cm = Counter()
    for r in all_records:
        cm[(r["verdict_pred"], r["verdict_gold"])] += 1

    # Escalation
    esc_gold = [r for r in all_records if r["verdict_gold"] == "ESCALATE"]
    esc_recall = sum(1 for r in esc_gold if r["verdict_pred"] == "ESCALATE") / len(esc_gold) if esc_gold else 0
    non_esc_gold = [r for r in all_records if r["verdict_gold"] != "ESCALATE"]
    false_esc = sum(1 for r in non_esc_gold if r["verdict_pred"] == "ESCALATE") / len(non_esc_gold) if non_esc_gold else 0

    # Danger metrics
    wrong_approve = sum(1 for r in all_records if r["verdict_pred"] == "APPROVE" and r["verdict_gold"] == "REJECT")
    wrong_reject = sum(1 for r in all_records if r["verdict_pred"] == "REJECT" and r["verdict_gold"] in ("APPROVE", "PARTIAL"))

    # --- Per-difficulty breakdown ---
    by_difficulty = {}
    for diff in ["easy", "medium", "hard"]:
        subset = [r for r in all_records if r["difficulty"] == diff]
        if not subset:
            continue
        by_difficulty[diff] = {
            "total_runs": len(subset),
            "verdict_accuracy": sum(1 for r in subset if r["v_match"]) / len(subset),
            "fully_correct_rate": sum(1 for r in subset if r["fully_correct"]) / len(subset),
            "payable_exact_rate": sum(1 for r in subset if r["p_exact"]) / len(subset),
            "payable_within_1pct_rate": sum(1 for r in subset if r["p_within"]) / len(subset),
            "clause_f1": sum(r["clause_f1"] for r in subset) / len(subset),
        }

    # --- Per-product breakdown ---
    by_product = {}
    for prod in set(r["product_id"] for r in all_records):
        subset = [r for r in all_records if r["product_id"] == prod]
        if not subset:
            continue
        by_product[prod] = {
            "total_runs": len(subset),
            "verdict_accuracy": sum(1 for r in subset if r["v_match"]) / len(subset),
            "fully_correct_rate": sum(1 for r in subset if r["fully_correct"]) / len(subset),
            "payable_exact_rate": sum(1 for r in subset if r["p_exact"]) / len(subset),
            "payable_within_1pct_rate": sum(1 for r in subset if r["p_within"]) / len(subset),
            "clause_f1": sum(r["clause_f1"] for r in subset) / len(subset),
        }

    # --- Per-scenario breakdown ---
    by_scenario = {}
    for sc in sorted(set(r["scenario"] for r in all_records)):
        subset = [r for r in all_records if r["scenario"] == sc]
        if not subset:
            continue
        by_scenario[sc] = {
            "total_runs": len(subset),
            "verdict_accuracy": sum(1 for r in subset if r["v_match"]) / len(subset),
            "fully_correct_rate": sum(1 for r in subset if r["fully_correct"]) / len(subset),
        }

    # --- Reliability (pass@k) ---
    k_values = Counter(len(v) for v in runs.values())
    k = max(k_values, key=k_values.get) if k_values else 1

    pass_k_fc = 0
    pass_k_verdict = 0
    pass_1_fc = []
    pass_1_verdict = []

    for cid in cases:
        recs = runs[cid]
        g = gold.get(cid, {})
        fc_runs = [fully_correct(r, g) for r in recs]
        v_runs = [verdict_match(r.get("verdict"), g.get("verdict")) for r in recs]

        if all(fc_runs):
            pass_k_fc += 1
        if all(v_runs):
            pass_k_verdict += 1
        pass_1_fc.append(sum(fc_runs) / len(fc_runs))
        pass_1_verdict.append(sum(v_runs) / len(v_runs))

    pass_k_fc_rate = pass_k_fc / total_cases if total_cases else 0
    pass_k_v_rate = pass_k_verdict / total_cases if total_cases else 0
    avg_pass1_fc = sum(pass_1_fc) / len(pass_1_fc) if pass_1_fc else 0
    avg_pass1_v = sum(pass_1_verdict) / len(pass_1_verdict) if pass_1_verdict else 0

    # Variance
    var_fc = sum((x - avg_pass1_fc) ** 2 for x in pass_1_fc) / len(pass_1_fc) if pass_1_fc else 0
    var_v = sum((x - avg_pass1_v) ** 2 for x in pass_1_verdict) / len(pass_1_verdict) if pass_1_verdict else 0

    # --- Cost ---
    avg_wall = sum(r["wall_clock"] for r in all_records) / total_runs if total_runs else 0
    total_wall = sum(r["wall_clock"] for r in all_records)

    # Build overall confusion matrix 4x4
    verdicts = ["APPROVE", "PARTIAL", "REJECT", "ESCALATE"]
    confusion = {}
    for vp in verdicts:
        confusion[vp] = {}
        for vg in verdicts:
            confusion[vp][vg] = cm.get((vp, vg), 0)

    return {
        "dataset": {
            "total_cases": total_cases,
            "total_runs": total_runs,
            "k": k,
            "products": list(set(r["product_id"] for r in all_records)),
        },
        "verdict_accuracy": v_acc / total_runs if total_runs else 0,
        "confusion_matrix": confusion,
        "payable_exact_match_rate": p_exact_c / total_runs if total_runs else 0,
        "payable_within_1pct_rate": p_within_c / total_runs if total_runs else 0,
        "clause_precision": avg_cp,
        "clause_recall": avg_cr,
        "clause_f1": avg_cf,
        "fully_correct_rate": fc_count / total_runs if total_runs else 0,
        "completion_rate": completed / total_runs if total_runs else 0,
        "danger": {
            "wrong_approve_on_reject": wrong_approve,
            "wrong_reject_on_payable": wrong_reject,
        },
        "escalation": {
            "escalation_recall": esc_recall,
            "false_escalation_rate": false_esc,
        },
        "reliability": {
            "pass_k_fully_correct": pass_k_fc_rate,
            "pass_k_verdict": pass_k_v_rate,
            "pass_1_fully_correct": avg_pass1_fc,
            "pass_1_verdict": avg_pass1_v,
            "variance_fully_correct": var_fc,
            "variance_verdict": var_v,
        },
        "cost": {
            "avg_wall_clock_per_case": round(avg_wall, 2),
            "total_wall_clock": round(total_wall, 2),
        },
        "by_difficulty": by_difficulty,
        "by_product": by_product,
        "by_scenario": by_scenario,
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def fmt(p):
    """Format percentage."""
    return f"{p*100:.1f}%"


def render_confusion_matrix(cm):
    verdicts = ["APPROVE", "PARTIAL", "REJECT", "ESCALATE"]
    lines = []
    label = "Predicted \\\\ Actual"
    header = f"{label:>12}" + "".join(f"{v:>12}" for v in verdicts)
    lines.append(header)
    lines.append("-" * len(header))
    for vp in verdicts:
        row = f"{vp:>12}"
        for vg in verdicts:
            row += f"{cm[vp][vg]:>12}"
        lines.append(row)
    return "\n".join(lines)


def generate_markdown_report(metrics):
    md = []
    m = metrics

    md.append("# Benchmark Evaluation Report\n")
    md.append(f"**Agent**: ema-benchmark-0.1.0  ")
    md.append(f"**Model**: vllm/Qwen3.6-27B  ")
    md.append(f"**Prompt**: claims-ref-1  ")
    md.append(f"**Cases**: {m['dataset']['total_cases']}  ")
    md.append(f"**Runs per case**: {m['dataset']['k']}  ")
    md.append(f"**Total runs**: {m['dataset']['total_runs']}\n")

    md.append("---\n")
    md.append("## 1. Core Accuracy\n")
    md.append("| Metric | Value |")
    md.append("|---|---|")
    md.append(f"| Verdict Accuracy | {fmt(m['verdict_accuracy'])} |")
    md.append(f"| Payable Exact Match | {fmt(m['payable_exact_match_rate'])} |")
    md.append(f"| Payable Within ±1% | {fmt(m['payable_within_1pct_rate'])} |")
    md.append(f"| Clause Precision | {fmt(m['clause_precision'])} |")
    md.append(f"| Clause Recall | {fmt(m['clause_recall'])} |")
    md.append(f"| Clause F1 | {fmt(m['clause_f1'])} |")
    md.append(f"| **Fully Correct** | **{fmt(m['fully_correct_rate'])}** |")
    md.append(f"| Completion Rate | {fmt(m['completion_rate'])} |\n")

    md.append("### Confusion Matrix\n")
    md.append("```")
    md.append(render_confusion_matrix(m["confusion_matrix"]))
    md.append("```\n")

    md.append("### Danger Metrics\n")
    md.append(f"- **Wrong APPROVE on REJECT**: {m['danger']['wrong_approve_on_reject']}  ")
    md.append(f"- **Wrong REJECT on APPROVE/PARTIAL**: {m['danger']['wrong_reject_on_payable']}\n")

    md.append("---\n")
    md.append("## 2. Escalation\n")
    md.append(f"- **Escalation Recall**: {fmt(m['escalation']['escalation_recall'])}  ")
    md.append(f"- **False Escalation Rate**: {fmt(m['escalation']['false_escalation_rate'])}\n")

    md.append("---\n")
    md.append("## 3. Reliability\n")
    md.append(f"- **pass@{m['dataset']['k']} (Fully Correct)**: {fmt(m['reliability']['pass_k_fully_correct'])}  ")
    md.append(f"- **pass@{m['dataset']['k']} (Verdict)**: {fmt(m['reliability']['pass_k_verdict'])}  ")
    md.append(f"- **pass@1 (Fully Correct)**: {fmt(m['reliability']['pass_1_fully_correct'])}  ")
    md.append(f"- **pass@1 (Verdict)**: {fmt(m['reliability']['pass_1_verdict'])}  ")
    md.append(f"- **Variance (Fully Correct)**: {m['reliability']['variance_fully_correct']:.6f}\n")

    md.append("---\n")
    md.append("## 4. By Difficulty\n")
    md.append("| Difficulty | Runs | Verdict Acc | Fully Correct | Payable Exact | Payable ±1% | Clause F1 |")
    md.append("|---|---|---|---|---|---|---|")
    for diff in ["easy", "medium", "hard"]:
        if diff in m["by_difficulty"]:
            d = m["by_difficulty"][diff]
            md.append(f"| {diff} | {d['total_runs']} | {fmt(d['verdict_accuracy'])} | {fmt(d['fully_correct_rate'])} | {fmt(d['payable_exact_rate'])} | {fmt(d['payable_within_1pct_rate'])} | {fmt(d['clause_f1'])} |")
    md.append("")

    md.append("---\n")
    md.append("## 5. By Product\n")
    md.append("| Product | Runs | Verdict Acc | Fully Correct | Payable Exact | Payable ±1% | Clause F1 |")
    md.append("|---|---|---|---|---|---|---|")
    for prod, d in m["by_product"].items():
        short = prod[:20]
        md.append(f"| {short} | {d['total_runs']} | {fmt(d['verdict_accuracy'])} | {fmt(d['fully_correct_rate'])} | {fmt(d['payable_exact_rate'])} | {fmt(d['payable_within_1pct_rate'])} | {fmt(d['clause_f1'])} |")
    md.append("")

    md.append("---\n")
    md.append("## 6. By Scenario (Top 15)\n")
    md.append("| Scenario | Runs | Verdict Acc | Fully Correct |")
    md.append("|---|---|---|---|")
    sorted_sc = sorted(m["by_scenario"].items(), key=lambda x: x[1]["total_runs"], reverse=True)
    for sc, d in sorted_sc[:15]:
        md.append(f"| {sc} | {d['total_runs']} | {fmt(d['verdict_accuracy'])} | {fmt(d['fully_correct_rate'])} |")
    md.append("")

    md.append("---\n")
    md.append("## 7. Cost\n")
    md.append(f"- **Avg wall clock per case**: {m['cost']['avg_wall_clock_per_case']}s  ")
    md.append(f"- **Total wall clock**: {m['cost']['total_wall_clock']}s\n")

    return "\n".join(md)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Evaluate benchmark run results")
    parser.add_argument("--output", type=str, default=str(RESULTS_DIR / "benchmark_report.md"))
    args = parser.parse_args()

    if not RUN_PATH.exists():
        print(f"Error: No run file at {RUN_PATH}. Run benchmark_runner.py first.")
        sys.exit(1)

    print("Loading gold...")
    gold = load_gold()
    print("Loading runs...")
    runs = load_runs()
    print(f"  {len(runs)} cases, {sum(len(v) for v in runs.values())} total runs")

    print("Computing metrics...")
    metrics = compute_metrics(runs, gold)

    # Write JSON report
    json_path = RESULTS_DIR / "benchmark_report.json"
    with open(json_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"JSON report: {json_path}")

    # Write Markdown report
    md = generate_markdown_report(metrics)
    with open(args.output, "w") as f:
        f.write(md)
    print(f"Markdown report: {args.output}")

    # Console summary
    print()
    print("=" * 60)
    print("  QUICK SUMMARY")
    print("=" * 60)
    print(f"  Verdict Accuracy:    {fmt(metrics['verdict_accuracy'])}")
    print(f"  Payable Exact Match: {fmt(metrics['payable_exact_match_rate'])}")
    print(f"  Payable Within ±1%:  {fmt(metrics['payable_within_1pct_rate'])}")
    print(f"  Clause F1:           {fmt(metrics['clause_f1'])}")
    print(f"  Fully Correct:       {fmt(metrics['fully_correct_rate'])}")
    print(f"  Completion Rate:     {fmt(metrics['completion_rate'])}")
    print()
    print("  Confusion Matrix:")
    print("  " + "\n  ".join(render_confusion_matrix(metrics["confusion_matrix"]).split("\n")))
    print()
    print(f"  Escalation Recall: {fmt(metrics['escalation']['escalation_recall'])}  ")
    print(f"  False Escalation:  {fmt(metrics['escalation']['false_escalation_rate'])}")
    print()
    print(f"  pass@{metrics['dataset']['k']} FC: {fmt(metrics['reliability']['pass_k_fully_correct'])}  ")
    print(f"  pass@1 FC:   {fmt(metrics['reliability']['pass_1_fully_correct'])}")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
