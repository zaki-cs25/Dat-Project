"""Harness runner — executes cases, scores, computes cost, writes output."""

from __future__ import annotations

import asyncio
import csv
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from harness.adapters.base import AgentAdapter
from harness.cost import (
    compute_self_hosted_cost_per_solved_task,
    compute_self_hosted_cost_per_task,
    compute_task_cost,
    load_price_table,
)
from harness.dataset import load_dataset
from harness.scorers.base import Scorer
from harness.types import (
    CaseResult, PriceEntry, RunConfig, TargetConfig,
)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    i, j = int(k), min(int(k) + 1, len(s) - 1)
    return s[i] + (s[j] - s[i]) * (k - i)


def _mask_key(key: str) -> str:
    return key[:8] + "..." if len(key) > 12 else "***"


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _is_resolved(score: float, details: dict) -> bool:
    """A task is 'resolved' if score is 1.0 or fully_correct flag is set.
    
    coding-agent-plan.md: "Resolved rate — fraction of tasks where the
    agent's patch makes the tests pass."
    """
    return score >= 1.0 or details.get("fully_correct", False)


def _is_empty_patch(final_output) -> bool:
    """Empty-patch rate: agent gave up or produced nothing."""
    if final_output is None:
        return True
    if isinstance(final_output, str) and not final_output.strip():
        return True
    if isinstance(final_output, dict):
        output_str = str(final_output.get("patch", final_output.get("output", "")))
        return not output_str.strip()
    return False


# ---------------------------------------------------------------------------
# Main harness
# ---------------------------------------------------------------------------

async def run_harness(
    adapter: AgentAdapter,
    scorer: Scorer,
    cases: list,
    config: TargetConfig,
    price_table: dict[str, PriceEntry],
    out_dir: str,
    tag: str | None = None,
    workers: int = 1,
    gpu_cost_per_hour: float | None = None,
) -> dict:
    """Run all cases and write outputs.

    Args:
        gpu_cost_per_hour: GPU cost rate for self-hosted models.
                          If set, cost is computed from batch wall-clock.
                          If not set, uses token-based pricing.

    Returns the summary dict.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    total = len(cases)
    batch_start = time.time()

    is_self_hosted = gpu_cost_per_hour is not None

    async def _run_one(case):
        adapter_result = await adapter.run(case, config)
        score, details = scorer.score(adapter_result.final_output, case.ground_truth)

        # Cost: token-based for frontier/gateway, 0.0 for self-hosted (computed at batch level)
        if is_self_hosted:
            cost = 0.0
        else:
            cost = compute_task_cost(adapter_result.calls, price_table)

        all_tokens_in = sum(c.input_tokens for c in adapter_result.calls)
        all_tokens_out = sum(c.output_tokens for c in adapter_result.calls)
        models = list(dict.fromkeys(c.model_used for c in adapter_result.calls))

        return CaseResult(
            case_id=case.id,
            score=round(score, 4),
            score_details=details,
            input_tokens=all_tokens_in,
            output_tokens=all_tokens_out,
            total_tokens=all_tokens_in + all_tokens_out,
            computed_cost=round(cost, 6),
            latency_seconds=round(adapter_result.timing.wall_clock_seconds, 2),
            steps=len(adapter_result.calls),
            models_used=";".join(models),
            tag=tag or "",
            final_output=adapter_result.final_output,
        )

    # Run with optional concurrency
    results: list[CaseResult] = []
    if workers > 1:
        sem = asyncio.Semaphore(workers)
        async def _limited(case):
            async with sem:
                return await _run_one(case)
        results = await asyncio.gather(*[_limited(c) for c in cases])
    else:
        for i, case in enumerate(cases):
            print(f"  [{i+1:>4}/{total}] {case.id}", end=" ... ")
            r = await _run_one(case)
            print(f"score={r.score:.2f}  cost=${r.computed_cost:.4f}  {r.latency_seconds:.1f}s")
            results.append(r)

    batch_wall_clock = time.time() - batch_start

    # Self-hosted cost: compute from batch wall-clock
    if is_self_hosted and gpu_cost_per_hour is not None:
        tasks_solved = sum(1 for r in results if _is_resolved(r.score, r.score_details))
        cost_per_solved = compute_self_hosted_cost_per_solved_task(
            batch_wall_clock, gpu_cost_per_hour, tasks_solved
        )
        cost_per_task = compute_self_hosted_cost_per_task(
            batch_wall_clock, gpu_cost_per_hour, len(results)
        )
        # Distribute the batch cost to per-case rows (for CSV)
        per_case_cost = batch_wall_clock * gpu_cost_per_hour / 3600 / len(results) if results else 0
        for r in results:
            r.computed_cost = round(per_case_cost, 4)
    else:
        cost_per_solved = None
        cost_per_task = None

    # Write outputs
    _write_per_case_csv(results, out / "per_case.csv")
    summary = _write_summary(
        results, out / "summary.json",
        is_self_hosted=is_self_hosted,
        batch_wall_clock=batch_wall_clock,
        workers=workers,
        gpu_cost_per_hour=gpu_cost_per_hour,
        cost_per_solved=cost_per_solved,
        cost_per_task=cost_per_task,
    )
    _write_run_config(
        config, price_table, out / "run_config.json",
        tag=tag, workers=workers,
        gpu_cost_per_hour=gpu_cost_per_hour,
    )

    print(f"\n  Batch wall-clock: {batch_wall_clock:.1f}s")
    print(f"  Output written to {out}/")
    return summary


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _write_per_case_csv(results: list[CaseResult], path: Path):
    fieldnames = [
        "id", "score", "input_tokens", "output_tokens", "total_tokens",
        "computed_cost", "latency_seconds", "steps", "models_used", "tag",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            w.writerow({
                "id": r.case_id,
                "score": r.score,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "total_tokens": r.total_tokens,
                "computed_cost": r.computed_cost,
                "latency_seconds": r.latency_seconds,
                "steps": r.steps,
                "models_used": r.models_used,
                "tag": r.tag,
            })


def _write_summary(
    results: list[CaseResult], path: Path,
    *, is_self_hosted: bool = False,
    batch_wall_clock: float = 0.0,
    workers: int = 1,
    gpu_cost_per_hour: float | None = None,
    cost_per_solved: float | None = None,
    cost_per_task: float | None = None,
) -> dict:
    """Write summary.json with aggregated metrics.
    
    Headline metrics (coding-agent-plan.md):
    - Resolved rate (accuracy)
    - Cost per task
    - Cost per solved task (the one that matters)
    - Wall-clock per task
    
    Secondary signals:
    - Patch-apply rate
    - Empty-patch rate
    - Step counts
    """
    scores = [r.score for r in results]
    costs = [r.computed_cost for r in results]
    latencies = [r.latency_seconds for r in results]
    tokens_in = [r.input_tokens for r in results]
    tokens_out = [r.output_tokens for r in results]
    steps_list = [r.steps for r in results]

    resolved = sum(1 for i, r in enumerate(results)
                   if _is_resolved(scores[i], r.score_details))

    # Secondary signals
    empty_patches = sum(1 for r in results if _is_empty_patch(r.final_output))
    # Patch-apply rate: from score_details if available, else estimate
    apply_rates = [r.score_details.get("patch_apply", None) for r in results]
    patch_apply_count = sum(1 for a in apply_rates if a is True)
    patch_apply_rate = patch_apply_count / len(results) if patch_apply_count > 0 else None

    # Model mix
    model_counter: Counter = Counter()
    for r in results:
        for m in r.models_used.split(";"):
            if m.strip():
                model_counter[m.strip()] += 1

    # Cost per solved task
    solved_costs = [r.computed_cost for i, r in enumerate(results)
                    if _is_resolved(scores[i], r.score_details)]

    # Collect numeric sub-metrics
    sub_metrics: dict[str, list] = {}
    for r in results:
        for k, v in r.score_details.items():
            if isinstance(v, (int, float)):
                sub_metrics.setdefault(k, []).append(v)

    summary = {
        "n_cases": len(results),
        "workers": workers,
        "resolved_rate": round(resolved / len(results), 4) if results else 0,
        "resolved_count": resolved,
        "cost": {
            "per_task": {
                "mean": round(sum(costs) / len(costs), 6) if costs else 0,
                "median": round(_percentile(costs, 50), 6),
                "p95": round(_percentile(costs, 95), 6),
            },
            "per_solved_task": {
                "mean": round(sum(solved_costs) / len(solved_costs), 6) if solved_costs else None,
            },
        },
        "latency": {
            "per_task": {
                "mean": round(sum(latencies) / len(latencies), 2) if latencies else 0,
                "median": round(_percentile(latencies, 50), 2),
                "p95": round(_percentile(latencies, 95), 2),
            },
            "batch_wall_clock_seconds": round(batch_wall_clock, 2),
        },
        "tokens": {
            "total_input": sum(tokens_in),
            "total_output": sum(tokens_out),
        },
        "steps": {
            "mean": round(sum(steps_list) / len(steps_list), 1) if steps_list else 0,
            "median": round(_percentile(steps_list, 50), 1),
        },
        "secondary_signals": {
            "empty_patch_rate": round(empty_patches / len(results), 4) if results else 0,
            "patch_apply_rate": round(patch_apply_rate, 4) if patch_apply_rate else None,
        },
        "model_mix": dict(model_counter.most_common()),
        "sub_metrics": {
            k: round(sum(v) / len(v), 4) for k, v in sub_metrics.items()
        },
    }

    # Self-hosted specific
    if is_self_hosted and gpu_cost_per_hour is not None:
        summary["self_hosted"] = {
            "gpu_cost_per_hour": gpu_cost_per_hour,
            "batch_wall_clock_seconds": round(batch_wall_clock, 2),
            "workers": workers,
            "cost_per_task_serial": round(cost_per_task, 4) if cost_per_task else None,
            "cost_per_solved_task": round(cost_per_solved, 4) if cost_per_solved else None,
        }

    with open(path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    return summary


def _write_run_config(
    config: TargetConfig, price_table: dict, path: Path,
    *, tag: str | None = None, workers: int = 1,
    gpu_cost_per_hour: float | None = None,
):
    """Write run_config.json — everything needed to reproduce the run."""
    pt_serializable = {
        model: {"input": e.price_per_1m_input, "output": e.price_per_1m_output}
        for model, e in price_table.items()
    }
    cfg = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target": config.target if hasattr(config, "target") else "unknown",
        "endpoint": config.endpoint,
        "model": config.model,
        "api_key_masked": _mask_key(config.api_key),
        "system_prompt": config.system_prompt or "(agent default)",
        "tag": tag,
        "workers": workers,
        "price_table": pt_serializable,
    }
    if gpu_cost_per_hour is not None:
        cfg["gpu_cost_per_hour"] = gpu_cost_per_hour

    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
