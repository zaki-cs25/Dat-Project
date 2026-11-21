# Workload-Driven Evaluation of Self-Hosted LLM Serving

CS5903 Distributed AI Training, IIT Hyderabad · Project ID 24 · Group 25 · Zaki Kazi (CS25MTECH11021)

**Question.** For a real agentic workload, which self-hosted serving choices pay off, and what do they cost in answer quality? Two agents and their datasets are held fixed while one serving decision changes at a time: model size, weight precision, KV-cache precision and serving engine. Quality is always reported next to latency and cost.

**Status (final).** Six healthcare serving setups (600 agent cases) and three insurance runs are measured and graded. Every reported number can be regenerated from the raw outputs in `evaluation/`; re-running the healthcare measurements needs an A100-class GPU and the private ICMR corpus.

| Document | Location |
|---|---|
| Final report | [`docs/Final_Project_Report.pdf`](docs/Final_Project_Report.pdf) (LaTeX source in [`docs/report/`](docs/report/)) |
| Architecture Decision Records | [`docs/Architecture_Decision_Records.md`](docs/Architecture_Decision_Records.md) |
| Raw results and scripts | [`evaluation/`](evaluation/) |
| Serving launch scripts (Slurm) | [`serving/`](serving/) |
| Mid-semester report and slides | `DAT Project Report.pdf`, `MidSem_DAT_Presentation.pdf` |

## Headline results (healthcare, CarePlan100, 100 cases per setup)

| Setup | Model | Weights / KV | Engine | Passed | Median case latency | Cost per passed plan |
|---|---|---|---|---|---|---|
| A | Qwen3.6-27B | BF16 / default | vLLM 0.28.0 | **86** | 48.9 s | INR 2.97 |
| B | Qwen3.6-27B | Q8_0 / default (f16) | llama.cpp b11429 | 77 | 69.6 s | INR 4.59 |
| C | Qwen3.6-27B | Q8_0 / q8_0 | llama.cpp b11429 | 80 | 68.5 s | INR 4.51 |
| D | Qwen3-8B | BF16 / default | vLLM 0.28.0 | 53 | 24.4 s | INR 2.54 |
| E | Qwen3-8B | Q8_0 / default (f16) | llama.cpp b11429 | 48 | 23.5 s | INR 2.63 |
| F | Qwen3-8B | Q8_0 / q8_0 | llama.cpp b11429 | 44 | 25.3 s | INR 3.03 |

Cost = run wall-clock hours × INR 180 per A100 GPU-hour, divided by passed plans. Full metrics, analysis and the insurance results are in the report.

## Repository layout

```
HealthAgent/        healthcare agent (React UI, FastAPI agent, IRIS for Health) and the CarePlan100 benchmark
  benchmarks/       CarePlan100 dataset (benchmarks/careplan100/data), harness, grader, per-setup configs
  docker-compose.benchmark*.yml   isolated benchmark deployment + per-engine overrides
insurance_agent/    health-insurance claim adjudication agent (FastAPI + Next.js)
harness/            agent benchmark harness used for the insurance runs
serving/            Slurm sbatch scripts for every serving setup (A–F) and the judge
evaluation/         raw run outputs and the scripts that regenerate every table and figure
docs/               final report, report source, ADR log
```

## Prerequisites

- Python 3.12, Node.js 18+, Docker with Docker Compose.
- An OpenAI-compatible model server per setup (scripts in `serving/`; one NVIDIA A100 80 GB was used), and an OpenAI-compatible embedding server for BGE-M3 (1024 dimensions).
- For grading: an OpenAI-compatible judge endpoint serving `unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q8_K_XL`.
- Python: minimum versions in `HealthAgent/src/python/requirements.txt`; exact versions used for all runs in `HealthAgent/src/python/requirements.lock.txt`. UI: `HealthAgent/ui/package-lock.json`.

## Setup (healthcare agent)

```bash
cd HealthAgent
python3 -m venv .venv && .venv/bin/pip install -r src/python/requirements.txt
npm ci --prefix ui
cp .env.example .env          # then set model/embedding endpoints; never commit .env
docker compose up -d --build --wait
```

Key environment variables (see `HealthAgent/.env.example` and `HealthAgent/docs/CONFIGURATION.md`): `CP_OPENAI_BASE_URL`, `CP_OPENAI_MODEL`, `CP_LLM_BACKEND` (`vllm` | `llamacpp` | `generic`), `CP_EMBEDDING_BASE_URL`, `CP_EMBEDDING_MODEL`, `CP_EMBEDDING_DIMENSIONS`, `CP_CARE_GENERATION_MODE=enriched`. The IRIS database is created and seeded with synthetic demo patients by the container on first start. The ICMR guideline documents used for retrieval are private and not included; without them the agent still runs in enriched mode with no retrieved context.

**Demo path.** Open `http://localhost:8501/intake`, choose *Existing patient* `demo-patient-1`, complete the interview, then open `http://localhost:8501` (clinician *Care Plans*) to see the urgency and the generated read-only draft.

## Run the benchmark (one setup)

1. Start a model server, e.g. `sbatch serving/C_llamacpp_qwen36-27b_q8_kvq8.sbatch`, and forward its port to `localhost`.
2. Run the 100 cases (starts only the isolated benchmark database and agent):

```bash
cd HealthAgent
.venv/bin/python benchmarks/run_benchmark.py validate --config benchmarks/careplan100/config.example.json
.venv/bin/python benchmarks/run_benchmark.py run --config benchmarks/careplan100/config.llamacpp-q8-kvq8.json --split all
```

Per-setup configs: `config.example.json` (A), `config.llamacpp-q8.json` (B), `config.llamacpp-q8-kvq8.json` (C), `config.vllm-8b-bf16.json` (D), `config.llamacpp-8b-q8.json` (E), `config.llamacpp-8b-q8kv.json` (F); judge: `config.judge-gemma.json` with `serving/judge_llamacpp_gemma4_26b.sbatch`. Each run writes a new immutable directory under `benchmarks/runs/`.

3. Grade with the shared judge, then retry structurally invalid judgments once:

```bash
.venv/bin/python benchmarks/run_benchmark.py grade --config benchmarks/careplan100/config.judge-gemma.json --run-dir benchmarks/runs/<run>
.venv/bin/python benchmarks/run_benchmark.py grade --config benchmarks/careplan100/config.judge-gemma.json --run-dir benchmarks/runs/<run> --retry-invalid-from benchmarks/runs/<run>/grades/<first-revision>
```

**Expected output.** `run` prints a JSON summary (`status: completed`, `protocol_valid: true`); the run directory contains `cases.csv`, `llm_attempts.csv`, `summary.csv`, `manifest.json`. `grade` writes `grades/<revision>/cases.csv` with a score and pass flag per case.

## Regenerate every number in the report

```bash
python evaluation/summarize_results.py --healthcare-runs evaluation/healthcare/runs \
  --insurance-runs evaluation/insurance --gpu-rate-per-hour 180 --json-out evaluation/results_summary.json
python evaluation/make_tables.py  --summary evaluation/results_summary.json --out docs/report/tables
python evaluation/make_figures.py --summary evaluation/results_summary.json --out docs/report/figures   # needs matplotlib
```

`summarize_results.py` uses only the Python standard library. The healthcare run folders keep the per-case results, generated plans, request logs, attempt metrics, manifests and all grade revisions; large raw trace files are omitted.

## Tests

```bash
cd HealthAgent
PYTHONPATH=src/python .venv/bin/python -m pytest src/python/tests -q   # 325 passed, 1 skipped (log: evaluation/tests/pytest.log)
npm run build --prefix ui
```

## Insurance agent

See [`insurance_agent/readme.md`](insurance_agent/readme.md) (`./run.sh` starts backend :8000 and frontend :3000; set `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`) and [`harness/README.md`](harness/README.md). The insurance run outputs and the evaluation script are in `evaluation/insurance/` (copied unmodified from the development repository at commit `1015498b`; `run_evaluation.sh` keeps that machine's absolute paths, and the insurance case documents and dataset generator stay in the development repository).

## Operations

- Start / stop the healthcare app: `docker compose up -d --wait` / `docker compose down` (add `-v` only to delete the database volume).
- Benchmark deployment: compose project `cp-benchmark` with its own volume; it never touches the main database.
- Logs: `docker compose logs --tail=100 iris agent ui`; Slurm server logs in `job_<id>.out` (vLLM) and `job_<id>.err` (llama.cpp).
- Troubleshooting: [`HealthAgent/docs/CONFIGURATION.md#troubleshooting`](HealthAgent/docs/CONFIGURATION.md#troubleshooting).
- External services: a GPU model server per setup and an embedding server; no paid API is required.

## Limitations

One run per setup; concurrency 1 (single-agent latency); synthetic, LLM-generated cases graded by an LLM judge without clinician calibration. See Section 8 of the report.

## Attribution

Healthcare agent based on `central-park` (MIT, © 2026 Eungi Hong); insurance agent based on the Ema project (public GitHub repository without a licence file; used for academic evaluation). AI assistance: Astra generated the benchmark test cases; Claude Code and Codex were used as coding assistants (details in the report, Section 10). No credentials or private data are included; `.env` files are ignored.
