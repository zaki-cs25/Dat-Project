"""Finance scorer — placeholder.
    
    Replace with actual scoring logic once the finance dataset and
    expected output format are defined.
    
    Options:
    - Exact match on verdict (Overvalued/Fairly Valued/Undervalued)
    - LLM-judge if outputs are free-text analysis
    - Numeric tolerance on price target
"""

from harness.scorers.base import Scorer


class FinanceScorer(Scorer):
    """Placeholder: returns 1.0 if output contains ground_truth verdict."""

    def score(self, final_output, ground_truth) -> tuple[float, dict]:
        if isinstance(final_output, dict):
            output_text = str(final_output.get("verdict", ""))
        else:
            output_text = str(final_output)

        gold_verdict = str(ground_truth.get("verdict", "") if isinstance(ground_truth, dict) else ground_truth)
        match = gold_verdict.upper() in output_text.upper()

        return (1.0 if match else 0.0), {
            "verdict_match": match,
            "pred": output_text[:200],
            "gold": gold_verdict,
        }
