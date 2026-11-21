# Architecture Decision Records

CS5903 Distributed AI Training — Project 24, Group 25 — Zaki Kazi (CS25MTECH11021).
Project: *Workload-Driven Evaluation of Self-Hosted LLM Serving*. Report: [`docs/Final_Project_Report.pdf`](Final_Project_Report.pdf).

One record per material design or methodology decision. Superseded records are kept. **All records were written on 2026-11-21**; each decision date comes from the dated project artifact cited under *Evidence* (nothing is backdated). Setup letters A–F follow the report (A: Qwen3.6-27B BF16 vLLM; B: 27B Q8_0 llama.cpp; C: B + q8_0 KV; D: Qwen3-8B BF16 vLLM; E: 8B Q8_0 llama.cpp; F: E + q8_0 KV).

| ID | Title | Decision date | Status |
|---|---|---|---|
| ADR-H01 | Reuse an existing care-plan agent as the healthcare workload | by 2026-10-08 | Accepted |
| ADR-H02 | **Methodology record (9 October 2026):** grounded → enriched care-plan generation | 2026-10-09 | Accepted (changed) |
| ADR-H03 | Replace the 30-case benchmark with CarePlan100 | 2026-10-25 | Accepted; supersedes V1 benchmark |
| ADR-H04 | Semantic reviewer instead of regex vetoes for care-plan validation | 2026-10-25 | Accepted |
| ADR-H05 | Rubric-based LLM judge with separate safety flags | 2026-10-25 | Accepted |
| ADR-H06 | Fixed sampling and isolated harness for serving comparisons | 2026-10-25 | Accepted |
| ADR-H07 | Serve BF16 on vLLM and GGUF quantization on llama.cpp | 2026-11-21 | Accepted; instructor-approved |
| ADR-H08 | Measure the full serving matrix on the healthcare workload | 2026-11-21 | Accepted; instructor-approved |
| ADR-H09 | GPU-time cost model instead of token pricing | by 2026-10-21 | Accepted; instructor-approved |
| ADR-I01 | 120-case balanced golden set for insurance runs | by 2026-10-21 | Accepted; instructor-approved |
| ADR-I02 | Insurance amount scored within 1% and exact | by 2026-10-21 | Accepted; instructor-approved |

Changes relative to the approved mid-semester plan (H03, H07, H08, H09, I01, I02) were made in consultation with, and approved by, the course instructor.

---

## ADR-H01 — Reuse an existing care-plan agent as the healthcare workload

- **Date, status & scope:** in use by 2026-10-08 (first verified build recorded in `HealthAgent/docs/history/GROUNDED_EVALUATION.md`); added to the shared repository on 2026-10-16. Accepted. Scope: healthcare domain, all serving runs.
- **Context & decision drivers:** The project measures serving choices, not agent design. The second domain needs a realistic multi-step agent that calls an OpenAI-compatible endpoint, so serving configurations can be swapped by changing an address.
- **Options considered:**
  1. Build a new healthcare agent — high effort, diverts time from measurement.
  2. Reuse `central-park` (MIT, © 2026 Eungi Hong): React UI, FastAPI agent, InterSystems IRIS for Health (FHIR R4 + vector search), configurable OpenAI-compatible LLM. *(selected)*
- **Decision & rationale:** Option 2. It already performs an adaptive patient interview, triage assessment and background care-plan generation with retrieval — a multi-call workload (about 8 LLM calls and 23k input tokens per case). Its LLM client is endpoint-configurable.
- **Consequences & trade-offs:** Inherits IRIS and the FHIR Task worker. Added in this project: ICMR Standard Treatment Workflow context library, enriched generation, semantic reviewer contract, serving profiles and per-attempt tracing, CarePlan100 dataset and harness, English-only intake. MIT licence and copyright notice retained.
- **Evidence & validation:** `HealthAgent/LICENSE`; `HealthAgent/src/python/central_park/`; `HealthAgent/benchmarks/careplan100/`.
- **Revisit trigger:** A serving setup cannot be selected without changing agent code (i.e. the endpoint/sampling configuration no longer suffices).

## ADR-H02 — Methodology record (9 October 2026): grounded → enriched care-plan generation

- **Date, status & scope:** Decision 2026-10-09; **changed**. Documentation date of this record: 2026-11-21 (not backdated). Scope: healthcare care-plan generation and its evaluation.
- **Project-level methodology:** Reaffirmed — hold the agent and dataset fixed, change the serving configuration, and report quality alongside performance and cost.
- **Old approach:** *Grounded* generation — every recommendation had to be supported by retrieved ICMR passages; missing evidence produced "insufficient evidence".
- **New evidence:** Before 2026-10-09 only a small reviewed subset of ICMR passages was indexed, so grounded mode returned insufficient-evidence outcomes for many eligible patients and could not produce a usable workload (archived history, below).
- **Alternatives:** (a) keep grounded mode and wait for a larger reviewed corpus; (b) *enriched* mode — the model uses its own knowledge with retrieved ICMR passages as optional context, plus validation and semantic review *(selected)*; grounded mode retained as a comparison mode.
- **Impact on milestones/tests:** Evaluation protocol regenerated for enriched mode; CarePlan100 (ADR-H03) runs in enriched mode with ICMR retrieval enabled; ICMR passages are context, not proof of each recommendation.
- **Revised plan:** (1) build a scored benchmark for enriched mode (→ ADR-H03, H05); (2) run the serving setups on it with fixed sampling (→ ADR-H06, H07, H08); (3) report pass rate, latency and cost per passed plan per setup.
- **Evidence & validation:** `HealthAgent/docs/history/GROUNDED_EVALUATION.md` (archived 2026-10-09); `HealthAgent/docs/EVALUATION.md`; `CP_CARE_GENERATION_MODE=enriched`.
- **Revisit trigger:** A clinically reviewed corpus covers at least the benchmark's chronic conditions, making grounded generation feasible for ≥ 90% of eligible cases.

## ADR-H03 — Replace the 30-case benchmark with CarePlan100

- **Date, status & scope:** 2026-10-25; Accepted; supersedes the V1 30-case benchmark (run 2026-10-15). Scope: healthcare evaluation. Instructor-approved.
- **Context & decision drivers:** The V1 benchmark (30 chronic cases) completed 13/30 plans, lacked per-case serving metrics and covered only chronic disease.
- **Options considered:** (1) keep and extend V1; (2) adopt an external benchmark (AMEGA was considered); (3) a new 100-case dataset matching the agent's scope *(selected)*.
- **Decision & rationale:** CarePlan100 — 100 synthetic adult English cases (50 outpatient, 30 chronic, 20 minor injury; 20 development / 80 evaluation), four interview turns per case, 500 weighted rubric criteria including 14 critical, frozen with recorded hashes (dataset SHA-256 `59f35edf…0b21fb`). Test cases were generated with Astra and checked by the dataset validator. One script starts only the isolated app/database, replays the interview through the API, records every LLM attempt and writes CSVs.
- **Consequences & trade-offs:** Generated, not sampled from real practice; not clinically validated. V1 results are not comparable (different dataset, code and judge).
- **Evidence & validation:** `HealthAgent/benchmarks/careplan100/data/`, `HealthAgent/docs/BENCHMARK_PLAN.md`, `HealthAgent/docs/history/benchmark-v1-summary-20261024.zip`.
- **Revisit trigger:** Clinician review flags rubric errors in ≥ 5% of criteria, or a validated public dataset matching the scope appears.

## ADR-H04 — Semantic reviewer instead of regex vetoes for care-plan validation

- **Date, status & scope:** 2026-10-25; Accepted. Scope: care-plan generation pipeline.
- **Context & decision drivers:** A 100-case run produced 90 plans and 10 validation failures; several were false rejections by free-text regex checks (e.g. medication negations, factual medication history).
- **Options considered:** (1) keep regex vetoes; (2) delete safety checks; (3) move meaning interpretation to the model reviewer with a strict output contract, keeping deterministic checks for machine-verifiable rules *(selected)*.
- **Decision & rationale:** The reviewer returns four Boolean checks (medication scope, patient facts, urgency, evidence applicability); any rejection must cite a verbatim quote from a named field, which code verifies. Deterministic validation keeps schema, citation identity, provenance, urgent-action insertion and input hashes. One repair attempt is allowed.
- **Consequences & trade-offs:** Fewer false rejections; relies on the reviewer model's judgement (a software safeguard, not clinical approval).
- **Evidence & validation:** `HealthAgent/docs/BENCHMARK_SEMANTIC_REVIEW_FIX.md`; `HealthAgent/src/python/central_park/careplan.py`, `care_validation.py`; setup A run: 100/100 plans generated.
- **Revisit trigger:** The judge flags critical failures in ≥ 3% of reviewer-approved plans.

## ADR-H05 — Rubric-based LLM judge with separate safety flags

- **Date, status & scope:** 2026-10-25; Accepted. Scope: quality measurement for all healthcare setups.
- **Context & decision drivers:** Care plans are free text without a single correct answer; grading must be automatic to compare several serving setups.
- **Options considered:** (1) human grading only — not feasible for six 100-case runs; (2) reference-text similarity — does not capture requirements; (3) LLM judge applying per-case weighted rubrics with exact-quote evidence *(selected)*.
- **Decision & rationale:** The judge receives the clinical packet, rubric and plan (model identity and retrieved passages removed), marks each criterion and must quote the plan; code validates quotes and computes `score = 100 × Σ(weight × satisfied) / Σ weight`. Critical safety flags are reported beside the score. Pass = completed, input-verified, score ≥ 80, no critical failure. Judge: `unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q8_K_XL` on llama.cpp b11429, temperature 0, 4096 output tokens, thinking disabled. One correction pass for structurally invalid judgments. Grades are versioned revisions; measurements are never modified.
- **Consequences & trade-offs:** Judge not calibrated against clinicians; 1–5 completed plans per setup stay ungraded after the correction pass and count as not passed. Setup A was graded on 2026-10-25 and B–F on 2026-11-21 with the same model file, prompt, grading code and rubrics; the settings hash differs only by the endpoint port (recomputing B–F's settings with A's port reproduces A's hash `3dc5ff7c…`).
- **Evidence & validation:** `HealthAgent/benchmarks/careplan100/grading.py`; `config.judge-gemma.json`; each run's `grades/<revision>/report-manifest.json`.
- **Revisit trigger:** Judge–clinician agreement below 80% on a 20-case calibration sample.

## ADR-H06 — Fixed sampling and isolated harness for serving comparisons

- **Date, status & scope:** 2026-10-25; Accepted. Scope: all healthcare serving runs.
- **Context & decision drivers:** Differences between runs must come from the serving setup, not sampling noise or shared state.
- **Options considered:** (1) server-default sampling (as in V1); (2) explicit per-request sampling with an isolated database and one agent image *(selected)*.
- **Decision & rationale:** Temperature 0, top_p 1, seed 42, thinking disabled, sent with every request (overriding server defaults); concurrency 1; 900 s job timeout; 180 s LLM timeout. Isolated compose project `cp-benchmark` with its own IRIS volume; the same agent image (built 2026-10-25) for every run; each run writes a new immutable directory; dataset hash checked per run.
- **Consequences & trade-offs:** One repetition per setup; concurrency 1 measures single-agent latency, not throughput under load.
- **Evidence & validation:** `HealthAgent/docker-compose.benchmark.yml`; per-run `manifest.json` / `profile.json` in `evaluation/healthcare/runs/`.
- **Revisit trigger:** Throughput under concurrent agents becomes the evaluation target.

## ADR-H07 — Serve BF16 on vLLM and GGUF quantization on llama.cpp

- **Date, status & scope:** 2026-11-21; Accepted; approved by the course instructor. Scope: all six healthcare setups (both models).
- **Context & decision drivers:** BF16 safetensors serve directly on vLLM (setups A, D). Q8_0 weights and a q8_0 KV cache are both available in llama.cpp from one GGUF file per model (setups B, C, E, F). Shared GPU time limited the number of runs.
- **Options considered:**
  1. All setups on vLLM — KV-cache FP8 is a one-flag change, but 8-bit weight quantization would require separate quantized checkpoints in another format, adding conversion and validation work per model.
  2. All setups on llama.cpp — would replace the existing vLLM baseline (A).
  3. BF16 on vLLM, GGUF quantization on llama.cpp *(selected)*.
- **Decision & rationale:** Option 3 measures weight and KV-cache quantization for both models with the least conversion work, and keeps the baseline. Within llama.cpp, B→C and E→F isolate the KV cache. A's vLLM deployment used MTP speculative decoding (one draft token) and max-model-len 200k; D used max-model-len 40,960 (Qwen3-8B's limit; no MTP layers).
- **Consequences & trade-offs:** vLLM ↔ llama.cpp comparisons (A↔B, D↔E) change engine and precision together and are reported as whole-deployment comparisons; per-call prefill/decode metrics show where the time goes. The agent sends identical sampling settings to both engines.
- **Evidence & validation:** per-run `profile.json` (`backend`, `server_version`); `serving/*.sbatch`; `HealthAgent/docker-compose.benchmark-llamacpp*.yml`, `docker-compose.benchmark-vllm-8b.yml`.
- **Revisit trigger:** A single-engine BF16 vs Q8_0 comparison differs from the cross-engine comparison by more than 5 passed plans or 10% median latency.

## ADR-H08 — Measure the full serving matrix on the healthcare workload

- **Date, status & scope:** 2026-11-21; Accepted; approved by the course instructor. Scope: which workload carries the serving matrix.
- **Context & decision drivers:** The mid-semester plan ran the matrix on insurance first. The insurance runs of 21 Oct showed 9–38 cases per run without a verdict and clause-level scoring with no matches, while the healthcare harness verifies input, profile and trace integrity per case and grades every plan with a validated rubric.
- **Options considered:** (1) run the matrix on insurance; (2) run it on healthcare and use insurance for the model comparison *(selected)*; (3) both — not possible in the available GPU time.
- **Decision & rationale:** Option 2 gives every setup a validated, graded 100-case result with integrity checks.
- **Consequences & trade-offs:** Insurance results cover model choice (Qwen3.6-27B, Gemma-4-26B-A4B, Qwen3-8B), not quantization.
- **Evidence & validation:** `evaluation/insurance/*/summary.json`; `evaluation/healthcare/runs/*/manifest.json`.
- **Revisit trigger:** The insurance harness returns a verdict for every case and scores clauses (report Sec. 9, task 5).

## ADR-H09 — GPU-time cost model instead of token pricing

- **Date, status & scope:** in use by 2026-10-21 (insurance run configs record `gpu_cost_per_hour: 180`); Accepted; approved by the course instructor. Scope: all cost figures.
- **Context & decision drivers:** The mid-semester report priced tokens (0.25 / 2.00 per million). For a self-hosted GPU, the real cost is GPU time, whether or not tokens flow.
- **Options considered:** (1) token pricing; (2) GPU time × hourly rate, divided by useful answers *(selected)*.
- **Decision & rationale:** cost per run = wall-clock hours × INR 180 per A100 GPU-hour (assumed rental rate); cost per passed plan (healthcare) or per correct verdict (insurance) = run cost / useful answers, so failures raise the price of every useful answer.
- **Consequences & trade-offs:** Costs scale with the assumed rate (`--gpu-rate-per-hour`); runs with different worker counts are not directly comparable.
- **Evidence & validation:** `evaluation/summarize_results.py`; `evaluation/insurance/*/run_config.json`.
- **Revisit trigger:** Results are deployed on metered API endpoints, where token pricing applies.

## ADR-I01 — 120-case balanced golden set for insurance runs

- **Date, status & scope:** in use by 2026-10-21; Accepted; approved by the course instructor. Scope: insurance evaluation.
- **Context & decision drivers:** A full 1,000-case run per model was not feasible in the GPU time available (one 120-case run took 0.98–5.5 h); verdict classes are unevenly distributed in the full set.
- **Options considered:** (1) full 1,000 cases; (2) random subset; (3) balanced 120-case golden set, 30 per verdict *(selected)*.
- **Decision & rationale:** Equal class sizes make per-verdict accuracy comparable (report Fig. 3).
- **Consequences & trade-offs:** Overall accuracy does not reflect the full set's class mix.
- **Evidence & validation:** `evaluation/insurance/run_evaluation.sh`; per-case `gold_verdict` in `evaluation/insurance/*/per_case.csv`.
- **Revisit trigger:** GPU time allows full-set runs.

## ADR-I02 — Insurance amount scored within 1% and exact

- **Date, status & scope:** in use by 2026-10-21; Accepted; approved by the course instructor. Scope: insurance scoring.
- **Context & decision drivers:** The mid-semester report used a 2% tolerance. The harness scorer reports exact match and a 1% band, which separates rounding from rule errors more strictly.
- **Options considered:** (1) 2% tolerance; (2) exact and 1% *(selected)*.
- **Decision & rationale:** Both strict measures are reported; no tolerance is tuned after seeing results.
- **Consequences & trade-offs:** Not directly comparable with the mid-semester 2% figures.
- **Evidence & validation:** `harness/scorers/insurance.py`; `amount_exact`, `amount_within_1pct` in `evaluation/insurance/*/per_case.csv`.
- **Revisit trigger:** Policy rounding rules require a different tolerance.
