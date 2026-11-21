#!/usr/bin/env python3
"""Regenerate every results table in the report from raw run files.

Standard library only. Usage (from the repository root):

    python evaluation/summarize_results.py \
        --healthcare-runs evaluation/healthcare/runs \
        --insurance-runs evaluation/insurance \
        --gpu-rate-per-hour 180

Cost model (self-hosted, one GPU): cost = run wall-clock hours x GPU rate.
Cost per useful answer = run cost / number of useful answers
(healthcare: passed plans; insurance: correct verdicts).
"""
import argparse, csv, json, statistics as st
from pathlib import Path

# Setup label -> healthcare run directory name.
HEALTHCARE_SETUPS = [
    ("A", "Qwen3.6-27B", "BF16", "default", "vLLM 0.28.0", "20261025T132635Z-9124c8d8"),
    ("B", "Qwen3.6-27B", "Q8_0", "default (f16)", "llama.cpp b11429", "20261121T080107Z-5a3ebbe5"),
    ("C", "Qwen3.6-27B", "Q8_0", "q8_0", "llama.cpp b11429", "20261121T100928Z-ae372aae"),
    ("D", "Qwen3-8B", "BF16", "default", "vLLM 0.28.0", "20261121T134403Z-850b2ef2"),
    ("E", "Qwen3-8B", "Q8_0", "default (f16)", "llama.cpp b11429", "20261121T121100Z-8b82aeb9"),
    ("F", "Qwen3-8B", "Q8_0", "q8_0", "llama.cpp b11429", "20261121T125430Z-3d533fc1"),
]

INSURANCE_RUNS = [
    ("Qwen3.6-27B", "full_eval_20261021_173855_Qwen-27B"),
    ("Gemma-4-26B-A4B", "full_eval_20261021_154324_gemma-4-26B-A4B-it-GGUF"),
    ("Qwen3-8B", "full_eval_20261021_092646_Qwen3-8B"),
]


def pct(values, p):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * p
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def latest_judged_grade(run_dir):
    """Most recent grade revision that was produced with a judge configured."""
    grades = run_dir / "grades"
    best = None
    for rev in sorted(grades.iterdir()) if grades.is_dir() else []:
        man = rev / "report-manifest.json"
        if man.is_file() and json.loads(man.read_text()).get("judge_endpoint_configured"):
            best = rev
    return best


def healthcare(root, rate):
    out = []
    for setup, model, weights, kv, engine, name in HEALTHCARE_SETUPS:
        run = root / name
        if not (run / "manifest.json").is_file():
            out.append({"setup": setup, "model": model, "status": "not present"})
            continue
        manifest = json.loads((run / "manifest.json").read_text())
        if manifest.get("status") != "completed":
            out.append({"setup": setup, "model": model, "status": manifest.get("status")})
            continue
        cases = list(csv.DictReader(open(run / "cases.csv")))
        attempts = list(csv.DictReader(open(run / "llm_attempts.csv")))
        completed = [c for c in cases if c["status"] == "completed"]
        e2e = [float(c["case_operation_seconds"]) for c in completed]
        job = [float(c["careplan_duration_seconds"]) for c in completed]
        wall = float(manifest["measured_elapsed_seconds"])
        n = len(cases)
        row = {
            "setup": setup, "model": model, "weights": weights, "kv_cache": kv, "engine": engine,
            "run_dir": name, "cases": n, "completed": len(completed),
            "protocol_valid": manifest.get("protocol_valid"),
            "case_latency_median_s": st.median(e2e), "case_latency_mean_s": st.mean(e2e),
            "case_latency_p95_s": pct(e2e, 0.95), "careplan_job_median_s": st.median(job),
            "input_tokens_per_case": sum(int(a["prompt_tokens"] or 0) for a in attempts) / n,
            "output_tokens_per_case": sum(int(a["completion_tokens"] or 0) for a in attempts) / n,
            "llm_calls": len(attempts), "truncated_calls": sum(a["truncated"] == "True" for a in attempts),
            "wall_clock_s": wall, "run_cost": wall / 3600 * rate, "cost_per_case": wall / 3600 * rate / n,
        }
        # Per-call serving metrics, measured by the agent's client for every LLM attempt:
        # first streamed content (includes network/app overhead) and decode rate =
        # output tokens / (call duration - first content), for calls with >= 20 output tokens.
        def fl(a, c):
            try:
                return float(a[c])
            except (TypeError, ValueError, KeyError):
                return None

        def per_call(sel):
            fs = [fl(a, "first_streamed_content_seconds") for a in sel
                  if fl(a, "first_streamed_content_seconds") is not None]
            dec = [int(a["completion_tokens"]) / (fl(a, "duration_seconds") - fl(a, "first_streamed_content_seconds"))
                   for a in sel if fl(a, "first_streamed_content_seconds") is not None and a["completion_tokens"]
                   and int(a["completion_tokens"]) >= 20 and fl(a, "duration_seconds")
                   and fl(a, "duration_seconds") > fl(a, "first_streamed_content_seconds") + 0.05]
            return (st.median(fs) if fs else None, st.median(dec) if dec else None)

        gen = [a for a in attempts if a.get("parent_stage") == "careplan.generation"]
        row["first_content_p50_s_all_calls"], row["decode_tok_s_p50_all_calls"] = per_call(attempts)
        row["first_content_p50_s_careplan"], row["decode_tok_s_p50_careplan"] = per_call(gen)
        # Failure analysis: validator rejection categories of terminally failed plans, and
        # interview turns whose model output the agent rejected (HTTP 502 = ModelOutputError).
        cats, failed = {}, 0
        fpath = run / "failures.csv"
        if fpath.is_file():
            for f in csv.DictReader(open(fpath)):
                if f.get("status") != "failed":
                    continue
                failed += 1
                for d in json.loads(f.get("attempt_diagnostics") or "[]"):
                    c = d.get("category") or "other"
                    cats[c] = cats.get(c, 0) + 1
        bad_turns, bad_cases = 0, set()
        for line in open(run / "requests.jsonl"):
            q = json.loads(line)
            if q.get("kind") == "interview" and q.get("http_status") == 502:
                bad_turns += 1
                bad_cases.add(q.get("case_id"))
        row.update({"failed_generations": failed, "rejection_categories": dict(sorted(cats.items())),
                    "interview_unusable_turns": bad_turns, "interview_unusable_cases": len(bad_cases)})
        grade = latest_judged_grade(run)
        if grade:
            g = list(csv.DictReader(open(grade / "cases.csv")))
            graded = [r for r in g if r["rubric_status"] == "graded"]
            passes = sum(r["pass"] == "True" for r in g)
            row.update({
                "grade_revision": grade.name, "graded": len(graded), "passes": passes,
                "fails": sum(r["pass"] == "False" for r in g),
                "mean_score_graded": st.mean(float(r["score"]) for r in graded) if graded else None,
                "critical_failures": sum(r["critical_failure"] == "True" for r in g),
                "cost_per_pass": row["run_cost"] / passes if passes else None,
            })
            disp = {}
            for line in open(run / "input_packets.jsonl"):
                p = json.loads(line)
                disp[p["case_id"]] = (p["clinical_input"].get("clinician_disposition") or {}).get("level") \
                    if isinstance(p["clinical_input"].get("clinician_disposition"), dict) \
                    else p["clinical_input"].get("clinician_disposition")
            by = {}
            for r in g:
                d = disp.get(r["case_id"]) or "unknown"
                t = by.setdefault(d, [0, 0])
                t[1] += 1
                t[0] += r["pass"] == "True"
            row["pass_by_disposition"] = {k: f"{v[0]}/{v[1]}" for k, v in sorted(by.items())}
        out.append(row)
    return out


def insurance(root, rate):
    out = []
    for model, name in INSURANCE_RUNS:
        d = root / name
        cfg = json.loads((d / "run_config.json").read_text())
        summ = json.loads((d / "summary.json").read_text())
        # Skip trailer lines without a case id (two files end with one).
        rows = [r for r in csv.DictReader(open(d / "per_case.csv")) if (r.get("id") or "").strip()]
        n = len(rows)
        returned = sum(1 for r in rows if (r.get("pred_verdict") or "").strip())
        verdict = sum(r.get("verdict_match") == "True" for r in rows)
        within = sum(r.get("amount_within_1pct") == "True" for r in rows)
        exact = sum(r.get("amount_exact") == "True" for r in rows)
        lat = [float(r["latency_seconds"]) for r in rows if r.get("latency_seconds")]
        wall = float(summ["latency"]["batch_wall_clock_seconds"])
        cost = wall / 3600 * rate
        by_gold = {}
        for r in rows:
            t = by_gold.setdefault(r.get("gold_verdict") or "unknown", [0, 0])
            t[1] += 1
            t[0] += r.get("verdict_match") == "True"
        out.append({
            "model": model, "configured_model": cfg.get("model"), "endpoint": cfg.get("endpoint"),
            "workers": cfg.get("workers"), "cases": n, "returned_verdict": returned,
            "verdict_correct": verdict, "verdict_accuracy": verdict / n,
            "amount_within_1pct": within / n, "amount_exact": exact / n,
            "latency_median_s": st.median(lat), "latency_p95_s": pct(lat, 0.95),
            "input_tokens_per_case": summ["tokens"]["total_input"] / n,
            "output_tokens_per_case": summ["tokens"]["total_output"] / n,
            "wall_clock_s": wall, "run_cost": cost, "cost_per_case": cost / n,
            "cost_per_correct_verdict": cost / verdict if verdict else None,
            "verdict_correct_by_gold": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by_gold.items())},
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--healthcare-runs", type=Path, required=True)
    ap.add_argument("--insurance-runs", type=Path, required=True)
    ap.add_argument("--gpu-rate-per-hour", type=float, default=180.0, help="GPU rental rate (INR/hour)")
    ap.add_argument("--json-out", type=Path)
    a = ap.parse_args()
    result = {"gpu_rate_per_hour_inr": a.gpu_rate_per_hour,
              "healthcare": healthcare(a.healthcare_runs, a.gpu_rate_per_hour),
              "insurance": insurance(a.insurance_runs, a.gpu_rate_per_hour)}
    text = json.dumps(result, indent=2, default=str)
    if a.json_out:
        a.json_out.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
