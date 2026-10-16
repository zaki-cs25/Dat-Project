"""Coding scorer — placeholder.
    
    Replace with actual scoring logic once the coding dataset is defined.
    
    Options:
    - Diff-based: does the patch fix the failing test?
    - AST-based: structural match on the fix
    - LLM-judge: compare output fix to reference fix
"""

from harness.scorers.base import Scorer


class CodingScorer(Scorer):
    """Placeholder: exact string match (useless in practice, replace me)."""

    def score(self, final_output, ground_truth) -> tuple[float, dict]:
        match = str(final_output) == str(ground_truth)
        return (1.0 if match else 0.0), {"exact_match": match}
