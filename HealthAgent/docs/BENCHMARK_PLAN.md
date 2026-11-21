# CarePlan100 implementation plan and status

Updated 2026-10-25. This replaces the obsolete 30-case benchmark. Historical summaries and lessons are preserved in [the V1 archive](history/benchmark-v1-summary-20261024.zip); its raw benchmark folder was cleared at the user's request.

## Agreed scope

- 100 fresh adult English cases: 50 everyday OPD, 30 chronic conditions, 20 minor physical injuries.
- Enriched generation only, ICMR retrieval enabled. Missing relevant passages remain an explicit context limitation.
- Score care plans only. Four recorded interview prefixes/case measure performance; interview/triage quality is outside scoring.
- Retain established diagnoses and read-only clinician-facing monitoring, investigation, referral, lifestyle, follow-up and generic medication review. Factual existing medicine history is allowed. No new diagnoses, specific new prescriptions/doses or medication changes.
- Single script starts only the isolated app/database; the existing Qwen3.6-27B server on localhost:9000 and BGE-M3 Q8_0 embedding server on localhost:8081 (1024 dimensions) stay external.
- Judge endpoint/model are supplied later via an OpenAI-compatible API. No configured judge means ungraded, not zero. Later grading reuses saved measurements.

## Dataset: authored and frozen

Astra authored two cohorts and a separate Astra reviewer inspected/corrected the combined dataset. There are 100 self-contained clinical packets, 100 four-turn interview scripts, 500 atomic case criteria and verified-source registries. The split is 20 development / 80 evaluation. Three supplied urgent-disposition cases were assigned to development before measurement, keeping group and condition coverage, so urgent-path plumbing is exercised before evaluation. The total disposition mix is 87 routine, 12 urgent and 1 emergency.

Files: `benchmarks/careplan100/data/`. `manifest.json` records hashes, scope, authoring provenance and frozen scoring rules. This is public synthetic material with overlapping condition scaffolds, not a hidden or independently clinically validated test. Source-check and dataset-review limitations are in its README/review record.

## Lessons incorporated

1. Shared deterministic age/as-of facts for interview and care models. Fixtures store age without fabricating a birth date.
2. Field-aware medication validation permits accurate history while rejecting prescribing actions; lab concentrations are not doses. Local heuristics supplement the semantic reviewer and remain incomplete.
3. Normalize demographic discrepancies in the model-facing assessment view; retain the original FHIR assessment and export upstream-conflict diagnostics.
4. Supplied clinician disposition sets a minimum urgency constraint; it cannot downgrade an existing assessment. Routine follow-up must not delay active urgent care.
5. Enforce source ID/provenance validity, and add conservative text aliases only for existing ICMR workflows. No guessed clinical codes or automatic clinical approval of source material.
6. Preserve rejected attempts, field/category/feedback and upstream conflicts in the benchmark-only diagnostic export. Never promote rejected model output to accepted care plans.

## Runner and outputs

Entry point: `.venv/bin/python benchmarks/run_benchmark.py`.

The runner checks disk/context/model readiness, starts the benchmark compose project, verifies/publishes the approved ICMR index, provisions all selected FHIR fixtures before measured model calls, replays interviews, completes assessment without implicit care enqueue, and submits a fresh care generation through the app API. It audits full packets/profile/call-span lineage and saves failures without hidden POST retries. Ambiguous committed work or unfinished jobs blocks clinical grading.

Performance stops before judge calls. Each run has a fresh directory under `benchmarks/runs/` with immutable measurement artifacts, CSVs, configuration, model profile and dataset/source/code hashes. Native metrics retain units/origin/scope. Aggregate infrastructure snapshots are not attributed to cases. Grade-only operations create a new `grades/<revision>/` with separate hashes and CSVs.

Scoring: completed, input-verified output with score >=80/100 and no critical flags passes. Failed generation is zero where the measurement is valid; judge errors/missing judge are ungraded. Show completed-only quality, overall quality, completion rate, critical flags, grading coverage and split/group/condition breakdowns separately.

## Execution status

- Old benchmark folder cleared; small historical summary archive saved.
- 100-case Astra authoring, independent critique and offline packet/schema validation completed.
- Single-script runner, API judge, CSV exports and targeted application changes implemented.
- Both configured model servers advertise the expected models.
- Four-case development pilot completed: CHR-007, INJ-011, OPD-001, OPD-045 all completed with valid packet/profile audits, 16 interview requests and all CSV exports. Measurement duration 237.13 seconds. Original pilot artifacts are preserved in `benchmarks/runs/20261024T151805Z-09639e8b/`.
- A narrow factual-adherence verification guard correction was made after the development pilot, before evaluation. Dataset and rubric hashes were unchanged.
- All 100 cases now have selected terminal results: 93 completed and 7 validation failures. Inputs, serving profile and traces verify for every selected result. The first process ended after 88 results; 12 cases ran in a continuation after the external LLM restarted. One unfinished OPD-039 attempt from the original segment is excluded from combined statistics and preserved in its original capture.
- Combined report: `benchmarks/runs/careplan100-combined-20261024T210139Z/`. This pools two segments; uninterrupted-run throughput is unavailable. There are 400 selected interview requests, 820 distinct LLM attempts and 2,608 infrastructure samples.
- Docker build-cache cleanup recovered 9.15 GB after the internal 32 GB disk filled. Startup now probes external models before expensive Docker work and includes the build error tail on failure. The database image copies only its own classes/configuration so app/docs changes no longer force a database rebuild. These startup changes occurred after measurement; the archived measurement source remains unchanged. The final startup function was verified successfully, including both model probes and index publication.
- Local API judge configured at `http://localhost:8001/v1`, using the advertised Gemma model. New grading revision: 83 valid grades (mean 90.15), 70 passes, ten unknown judge results and seven generation failures. No Astra grading batch was launched.
- API judging is complete with 89.25% coverage of completed plans. Exact-evidence errors remain ungraded, so the all-100 quality mean is unknown. These are automated judge scores. Further clinical changes must be evaluated in a fresh run.
- After the validation correction below, a fresh uninterrupted 100-case run completed at `benchmarks/runs/20261025T101108Z-5f28651a/`: 90 completed plans, ten validation failures, 400 interview responses, 819 timed/token-measured LLM attempts, and verified packet/profile/trace lineage for all 100 cases. The configured API judge was called for each completed plan, but all 90 calls failed with `ConnectError`; completed-plan grade coverage is zero and quality remains unknown. No tuning occurred during the run. See the [fresh run record](BENCHMARK_FULL_RUN.md#fresh-uninterrupted-run-after-validation-correction) and [verification artifact](../benchmarks/runs/luna-fresh-verification.json).

See [benchmark usage](../benchmarks/README.md) and [pilot/run record](BENCHMARK_FULL_RUN.md).

## Earlier validation correction (superseded)

Implemented explicit medication-history/allergy/safety-query exceptions at clause scope; prospective named treatment and regimen changes remain blocked. Unrecorded-use/allergy claims and unrecorded doses remain prohibited. Reserved assessment provenance now produces a field-specific error and repair instruction. Generation/review prompts and future API judging guidance agree on this scope (judge version 1.2).

Validation: 167 targeted tests passed; all 14 rejected candidates were replayed offline. All six medication-related final candidates pass the updated medication check. CHR-022 still requires correcting the reserved provenance label; a mocked generation/repair/review test verifies that path. Saved measurement and grading hashes are unchanged. See [fix evidence](BENCHMARK_VALIDATION_FIX.md). A fresh generation run is needed to measure the new completion rate.

## Current validation correction

Free-text medication/factual interpretation now belongs to the application's structured semantic reviewer; schema, citations, provenance, urgency ownership and input integrity remain deterministic. Reviewer rejections require exact field/quote evidence. Invalid reviews get one correction without regenerating the plan; valid clinical rejections retain one generation repair. Generation and review share effective urgency and short citation aliases.

Verification: 95 targeted care-plan tests and 20 serving-observability tests passed. Luna monitored the two-case development API pilot at `benchmarks/runs/20261025T132023Z-e85613c8/`: both cases completed with valid input/profile/trace checks, no rejections or repairs, and no external benchmark judging. See [implementation, verification and limitations](BENCHMARK_SEMANTIC_REVIEW_FIX.md).

Next: a fresh enriched + ICMR 100-case measurement, monitored by Luna. Defer external quality judging while fixing generation; completion metrics alone must not be reported as clinical quality. Preserve previous run artifacts and use the new source/profile for new measurements.
