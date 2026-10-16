"""Insurance scorer — wraps existing scoring from score_results.py."""

from __future__ import annotations
import sys
from pathlib import Path

from harness.scorers.base import Scorer

_INSURANCE_ROOT = Path(__file__).resolve().parents.joinpath("insurance_agent")
if str(_INSURANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INSURANCE_ROOT))


def _verdict_match(pred: str | None, gold: str) -> bool:
    return pred == gold


def _amount_exact_match(pred: int | None, gold: int) -> bool:
    return pred is not None and pred == gold


def _amount_within(pred: int | None, gold: int, tol: float = 0.01) -> bool:
    if pred is None or gold == 0:
        return pred == gold == 0
    return abs(pred - gold) / gold <= tol


def _clause_f1(pred, gold):
    pred_set = set(pred) if pred else set()
    gold_set = set(gold) if gold else set()
    if not pred_set and not gold_set:
        return 1.0
    tp = len(pred_set & gold_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)
    p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


class InsuranceScorer(Scorer):
    """Scores insurance claim decisions.
    
    final_output: dict from benchmark_adapter with verdict, payable, clauses
    ground_truth: dict from gold.jsonl with verdict, payable, clauses
    """

    def score(self, final_output, ground_truth) -> tuple[float, dict]:
        verdict = final_output.get("verdict") if isinstance(final_output, dict) else None
        payable = final_output.get("payable") if isinstance(final_output, dict) else None
        clauses = final_output.get("clauses", []) if isinstance(final_output, dict) else []

        gold_verdict = ground_truth.get("verdict")
        gold_payable = ground_truth.get("payable")
        gold_clauses = ground_truth.get("clauses", [])

        v_match = _verdict_match(verdict, gold_verdict)
        a_exact = _amount_exact_match(payable, gold_payable)
        a_within = _amount_within(payable, gold_payable)
        c_f1 = _clause_f1(clauses, gold_clauses)
        fully_correct = v_match and a_exact and (set(clauses or []) == set(gold_clauses or []))

        # Overall score: weighted combination
        # Verdict (40%) + Amount exact (30%) + Clause F1 (30%)
        overall = 0.4 * (1.0 if v_match else 0.0) + 0.3 * (1.0 if a_exact else 0.0) + 0.3 * c_f1

        return overall, {
            "fully_correct": fully_correct,
            "verdict_match": v_match,
            "amount_exact": a_exact,
            "amount_within_1pct": a_within,
            "clause_f1": round(c_f1, 4),
            "pred_verdict": verdict,
            "gold_verdict": gold_verdict,
            "pred_payable": payable,
            "gold_payable": gold_payable,
        }
