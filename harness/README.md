# Agent Benchmark Harness

One harness to run a domain agent over its dataset and report **quality, cost, and latency** across three targets: frontier (paid API), self-hosted (vLLM), and gateway (LiteLLM routing).

See [agent-benchmark-harness-spec.md](../agent-benchmark-harness-spec.md) for the spec and [coding-agent-plan.md](../coding-agent-plan.md) for the coding agent cost model.

## Quick start

```bash
# Self-hosted (GPU cost, no price table needed)
python -m harness \
    --agent coding \
    --dataset ./datasets/coding/cases.jsonl \
    --target self-hosted \
    --endpoint http://localhost:9000/v1 \
    --model Qwen3.6-27B \
    --api-key not-needed \
    --gpu-cost-per-hour 500 \
    --out-dir ./results/coding-selfhosted

# Frontier / Gateway (price table required)
python -m harness \
    --agent finance \
    --dataset ./datasets/finance/cases.jsonl \
    --target frontier \
    --endpoint https://api.openai.com/v1 \
    --model gpt-4o \
    --api-key $OPENAI_KEY \
    --price-table ./harness/price_table.json \
    --out-dir ./results/finance-frontier
```

## Arguments

| Argument | Required | Description |
|---|---|---|
| `--agent` | yes | `insurance`, `finance`, or `coding` |
| `--dataset` | yes | Path to JSONL dataset file |
| `--target` | yes | `frontier`, `self-hosted`, or `gateway` |
| `--endpoint` | yes | Base URL for model calls |
| `--model` | yes | Model name to request |
| `--api-key` | yes | API key for the endpoint |
| `--price-table` | frontier/gateway | Path to price table JSON |
| `--gpu-cost-per-hour` | self-hosted | GPU rental cost per hour (e.g. rupees/hr) |
| `--out-dir` | yes | Where results are written |
| `--workers` | no | Concurrent cases (default: 1) |
| `--limit` | no | Run only first N cases |
| `--system-prompt` | no | Override agent's default prompt |
| `--tag` | no | Label on every result row |

## Cost model

### Frontier / Gateway — Token-based
```
cost = input_tokens / 1e6 × price_in + output_tokens / 1e6 × price_out
```
Prices come from `--price-table`. Same formula for all calls the agent makes per task.

### Self-hosted — GPU wall-clock
Per [coding-agent-plan.md](../coding-agent-plan.md):
```
cost per solved task = (batch wall-clock seconds) × (GPU cost/hr ÷ 3600) ÷ (tasks solved)
```
The GPU was rented for the entire batch window — that's the true cost, divided by tasks actually solved. No token accounting needed.

## Concurrency sweep (self-hosted)

A single agent leaves the GPU mostly idle. To find the real production cost:

```bash
for w in 1 4 8 16; do
    python -m harness \
        --agent coding \
        --dataset ./datasets/coding/cases.jsonl \
        --target self-hosted \
        --endpoint http://localhost:9000/v1 \
        --model Qwen3.6-27B \
        --api-key not-needed \
        --gpu-cost-per-hour 500 \
        --workers $w \
        --out-dir ./results/coding-w${w}
done
# Compare summary.json → self_hosted.cost_per_solved_task across workers
```

Expect a U-shaped curve: too few workers = idle GPU, too many = contention. The minimum is the honest production cost.

## Headline metrics

| Metric | Description |
|---|---|
| **Resolved rate** | Fraction of tasks where the agent succeeds (patch passes tests) |
| **Cost per task** | Average cost across all attempted tasks |
| **Cost per solved task** | Cost ÷ tasks actually solved — the number that matters |
| **Wall-clock per task** | End-to-end time per task |

Secondary signals:
- **Empty-patch rate** — agent gave up or produced nothing
- **Patch-apply rate** — patch applied cleanly (separate from passing tests)
- **Step counts** — average think-act turns per task

## Architecture

```
harness/
├── main.py               # CLI entry point
├── runner.py             # Core loop: cases → adapter → scorer → cost → output
├── types.py              # Shared dataclasses
├── cost.py               # Token cost (frontier/gateway) + GPU cost (self-hosted)
├── dataset.py            # JSONL loader → universal Case format
├── price_table.json      # Per-model prices for frontier/gateway
├── adapters/
│   ├── base.py           # Abstract AgentAdapter
│   ├── insurance.py      # Wraps existing benchmark_adapter.py
│   ├── finance.py        # Wraps finance pipeline
│   └── coding.py         # Spawns mini-swe-agent as subprocess
└── scorers/
    ├── base.py           # Abstract Scorer
    ├── insurance.py      # verdict + amount + clause F1
    ├── finance.py        # TBD — depends on dataset format
    └── coding.py         # SWE-bench test evaluation
```

One shared harness core + one adapter per agent + one scorer per dataset. The only thing that changes between targets is the endpoint.

## Dataset format

A JSONL file where each line is:

```json
{
  "id": "case-001",
  "input": "the content the agent works on",
  "ground_truth": { ... },
  "metadata": { ... }
}
```

- `id` — unique case identifier
- `input` — the content the agent works on
- `ground_truth` — expected answer/label, structure varies by domain
- `metadata` — extra fields the adapter needs (paths, tickers, etc.)

### Example metadata per agent

**Insurance:**
```json
{
  "base_dir": "./insurance_agent/dataset/public",
  "product_id": "health-individual",
  "wording_path": "wordings/health-individual.pdf",
  "documents": ["cases/case-001/policy_certificate.pdf", "cases/case-001/claim_form.pdf"],
  "agent_brief_text": "..."
}
```

**Finance:**
```json
{
  "ticker": "AAPL",
  "filing_path": "./data/10k/aapl-2024.pdf"
}
```

**Coding:**
```json
{
  "instruction": "Fix the off-by-one in sort.py line 42",
  "repo_path": "/tmp/test-repo",
  "timeout_seconds": 300
}
```

## Price table

Required for frontier/gateway only. Price per 1M tokens per model:

```json
{
  "gpt-4o": {"input": 2.50, "output": 10.00},
  "Qwen3.6-27B": {"input": 0.00, "output": 0.00}
}
```

## Outputs

Written to `--out-dir`:

| File | Content |
|---|---|
| `per_case.csv` | One row per case: id, score, tokens, cost, latency, steps, models, tag |
| `summary.json` | Aggregated metrics: resolved rate, cost (per task / per solved task), latency, model mix, secondary signals |
| `run_config.json` | Every argument and price table used — full reproducibility |

Self-hosted summary also includes `self_hosted` section: GPU rate, batch wall-clock, workers, cost-per-solved-task.

## Comparison patterns

**Evaluate model behind an agent** — keep agent + dataset fixed, vary target:
```bash
python -m harness --agent finance --dataset ... --target frontier --model gpt-4o --price-table ...
python -m harness --agent finance --dataset ... --target self-hosted --model Qwen3.6-27B --gpu-cost-per-hour 500
```

**Naive vs gateway cost** — keep everything same, change endpoint:
```bash
python -m harness --agent insurance --dataset ... --target self-hosted --endpoint http://vllm:9000/v1 ...
python -m harness --agent insurance --dataset ... --target gateway --endpoint http://litellm:4000/v1 --price-table ...
```

## Adding a new agent

1. Create `harness/adapters/<name>.py` implementing `AgentAdapter.run()` → returns `AdapterResult`
2. Create `harness/scorers/<name>.py` implementing `Scorer.score()` → returns `(score, details)`
3. Add the name to the `--agent` choices and registry in `main.py`
