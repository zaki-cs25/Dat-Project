#!/usr/bin/env python3
"""Write the LaTeX results tables of the report from evaluation/results_summary.json.

Usage: python evaluation/make_tables.py --summary evaluation/results_summary.json --out docs/report/tables
"""
import argparse, json
from pathlib import Path

ORDER = ["A", "B", "C", "D", "E", "F"]


def n(v, d=2):
    return f"{v:,.{d}f}"


def healthcare_table(rows):
    r = {x["setup"]: x for x in rows}
    s = [k for k in ORDER if k in r]

    def line(label, fn):
        return label + " & " + " & ".join(fn(r[k]) for k in s) + r" \\"

    disp = lambda x, key: x["pass_by_disposition"].get(key, "--")
    out = [
        r"\begin{tabular}{@{}l" + "r" * len(s) + "@{}}",
        r"\toprule",
        "Setup & " + " & ".join(s) + r" \\",
        "Model & " + " & ".join("27B" if r[k]["model"].startswith("Qwen3.6") else "8B" for k in s) + r" \\",
        "Weights / KV & " + " & ".join(
            f"{r[k]['weights'].replace('_', r'\_')}/{'q8\\_0' if r[k]['kv_cache'] == 'q8_0' else 'default'}" for k in s) + r" \\",
        "Engine & " + " & ".join("vLLM" if r[k]["engine"].startswith("vLLM") else "llama.cpp" for k in s) + r" \\",
        r"\midrule",
        line("Completed plans", lambda x: str(x["completed"])),
        line("Valid grades", lambda x: str(x["graded"])),
        line(r"\textbf{Passed plans}", lambda x: rf"\textbf{{{x['passes']}}}"),
        line("Mean score", lambda x: n(x["mean_score_graded"])),
        line("Critical failures", lambda x: str(x["critical_failures"])),
        line("Pass, routine (/87)", lambda x: disp(x, "routine").split("/")[0]),
        line("Pass, urgent (/12)", lambda x: disp(x, "urgent").split("/")[0]),
        line("Pass, emergency (/1)", lambda x: disp(x, "emergency").split("/")[0]),
        r"\midrule",
        line("Case latency p50 (s)", lambda x: n(x["case_latency_median_s"], 1)),
        line("Case latency p95 (s)", lambda x: n(x["case_latency_p95_s"], 1)),
        line("Care-plan job p50 (s)", lambda x: n(x["careplan_job_median_s"], 1)),
        line("Input tokens/case", lambda x: n(x["input_tokens_per_case"], 0)),
        line("Output tokens/case", lambda x: n(x["output_tokens_per_case"], 0)),
        line("LLM calls", lambda x: str(x["llm_calls"])),
        line("Run wall-clock (s)", lambda x: n(x["wall_clock_s"], 0)),
        r"\midrule",
        line("Cost per case (INR)", lambda x: n(x["cost_per_case"])),
        line(r"\textbf{Cost per pass (INR)}", lambda x: rf"\textbf{{{n(x['cost_per_pass'])}}}"),
        r"\bottomrule",
        r"\end{tabular}",
    ]
    return "\n".join(out) + "\n"


def serving_table(rows):
    r = {x["setup"]: x for x in rows}
    s = [k for k in ORDER if k in r]

    def line(label, fn):
        return label + " & " + " & ".join(fn(r[k]) for k in s) + r" \\"

    out = [
        r"\begin{tabular}{@{}l" + "r" * len(s) + "@{}}",
        r"\toprule",
        "Setup & " + " & ".join(s) + r" \\",
        r"\midrule",
        r"\multicolumn{" + str(len(s) + 1) + r"}{@{}l}{\emph{Care-plan generation calls}} \\",
        line("First output p50 (s)", lambda x: n(x["first_content_p50_s_careplan"])),
        line("Decode p50 (tok/s)", lambda x: n(x["decode_tok_s_p50_careplan"], 1)),
        r"\multicolumn{" + str(len(s) + 1) + r"}{@{}l}{\emph{All LLM calls}} \\",
        line("First output p50 (s)", lambda x: n(x["first_content_p50_s_all_calls"])),
        line("Decode p50 (tok/s)", lambda x: n(x["decode_tok_s_p50_all_calls"], 1)),
        r"\bottomrule",
        r"\end{tabular}",
    ]
    return "\n".join(out) + "\n"


def failure_table(rows):
    r = {x["setup"]: x for x in rows}
    s = [k for k in ["D", "E", "F"] if k in r]
    cats = [("citation_id", "Unknown citation ID"), ("application_owned_activity", "Urgent activity altered"),
            ("application_owned_provenance", "Urgent provenance altered"), ("schema_or_provenance", "Schema / provenance")]

    def line(label, fn):
        return label + " & " + " & ".join(fn(r[k]) for k in s) + r" \\"

    out = [r"\begin{tabular}{@{}lrrr@{}}", r"\toprule", "Qwen3-8B setup & " + " & ".join(s) + r" \\", r"\midrule",
           line("Failed generations (/100)", lambda x: str(x["failed_generations"])),
           r"\multicolumn{4}{@{}l}{\emph{Validator rejection events in failed cases}} \\"]
    out += [line(lbl, lambda x, c=c: str(x["rejection_categories"].get(c, 0))) for c, lbl in cats]
    out += [line("Unusable interview turns", lambda x: str(x["interview_unusable_turns"])),
            line("\\quad in cases", lambda x: str(x["interview_unusable_cases"])),
            r"\bottomrule", r"\end{tabular}"]
    return "\n".join(out) + "\n"


def insurance_table(rows):
    names = {"Qwen3.6-27B": "Qwen3.6-27B", "Gemma-4-26B-A4B": "Gemma-4-26B-A4B", "Qwen3-8B": "Qwen3-8B"}

    def line(label, fn):
        return label + " & " + " & ".join(fn(x) for x in rows) + r" \\"

    out = [
        r"\begin{tabular}{@{}lrrr@{}}",
        r"\toprule",
        "Metric & " + " & ".join(names.get(x["model"], x["model"]) for x in rows) + r" \\",
        r"\midrule",
        line("Parallel workers", lambda x: str(x["workers"])),
        line("Returned a verdict", lambda x: f"{x['returned_verdict']}/{x['cases']}"),
        line(r"\textbf{Verdict correct}", lambda x: rf"\textbf{{{x['verdict_accuracy'] * 100:.1f}\%}}"),
        line(r"Amount within 1\%", lambda x: f"{x['amount_within_1pct'] * 100:.1f}\\%"),
        line("Amount exact", lambda x: f"{x['amount_exact'] * 100:.1f}\\%"),
        line("Verdict correct, of returned", lambda x: f"{x['verdict_correct'] / x['returned_verdict'] * 100:.1f}\\%"),
        line("Latency p50 (s)", lambda x: n(x["latency_median_s"], 1)),
        line("Latency p95 (s)", lambda x: n(x["latency_p95_s"], 1)),
        line("Input tokens/case", lambda x: n(x["input_tokens_per_case"], 0)),
        line("Output tokens/case", lambda x: n(x["output_tokens_per_case"], 0)),
        line("Run wall-clock (s)", lambda x: n(x["wall_clock_s"], 0)),
        line("Cost per case (INR)", lambda x: n(x["cost_per_case"])),
        line("Cost per correct verdict (INR)", lambda x: n(x["cost_per_correct_verdict"])),
        r"\bottomrule",
        r"\end{tabular}",
    ]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    s = json.loads(a.summary.read_text())
    (a.out / "healthcare_results.tex").write_text(healthcare_table(s["healthcare"]))
    (a.out / "insurance_results.tex").write_text(insurance_table(s["insurance"]))
    (a.out / "serving_metrics.tex").write_text(serving_table(s["healthcare"]))
    (a.out / "failures.tex").write_text(failure_table(s["healthcare"]))
    print("wrote", sorted(p.name for p in a.out.glob("*.tex")))


if __name__ == "__main__":
    main()
