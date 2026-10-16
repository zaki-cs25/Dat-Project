# Custom care-plan and serving benchmark plan

Agreed scope: 2026-10-15. This document records the implementation plan and its progress.

## Objectives

Build a separate benchmark program that drives the application's APIs. Measure:

| Target | Evaluation |
| --- | --- |
| Care-plan output quality | 30 original synthetic cases across five established conditions, using the complete clinical input |
| Interview performance | API latency, model-call latency, usage, errors and context growth across multiple turns |
| Assessment and care-plan performance | Generation, review, repair, queueing, retrieval and persistence costs |
| Serving infrastructure | Available backend and host metrics for interchangeable models and serving engines |

Interview and triage quality are outside the scoring scope. Their software failures must still be recorded. Model generation must pass through the application's production functions and APIs. The benchmark program must not import and call the care-plan generator directly.

The care-plan generator continues to use established conditions and excludes new diagnoses, specific drug names/classes/doses, and medication changes. This is a project-specific synthetic benchmark, not a validated clinical instrument or an AMEGA-comparable score. ICMR context is supplementary to model knowledge in enriched mode; a source ID is not proof of clinical support.

## Step 1: Create and freeze the custom dataset

Status: dataset drafted; independent clinical review pending. See [dataset and scoring contract](../benchmarks/custom/README.md).

Create 30 original adult English-language cases: six each for hypertension, type 2 diabetes, asthma, COPD and chronic kidney disease. Each condition covers routine follow-up, missing information, adherence/access barriers, multimorbidity, a safety constraint and acute escalation. Acute cases supply a clinician disposition and measure care-plan consistency with that disposition; they do not grade triage decisions.

- Store clinical packets and four-turn interview scripts separately from scoring rubrics. A packet includes demographics, established diagnoses, medication/allergy history, dated or relative observations, narrative, explicit unknowns and the care-plan request.
- Deliver the entire clinical packet to generation and review regardless of interview completion. Unknown information remains unknown. No rubric, expected response or grading metadata enters model inputs.
- Use ten development cases (two per condition) and twenty evaluation cases (four per condition). Freeze this allocation before outputs are generated. Evaluation cases are visible in this repository, so this is an evaluation split, not a secret held-out test. Do not tune prompts on its scores; create a new independently reviewed set if it becomes tuning data.
- Keep criterion-level source references and distinguish clinical guidance, supplied case facts and application scope. ICMR sources inform the rubric, but source links alone do not establish that a recommendation is supported. Independent clinical review must confirm source interpretation, patient applicability and the rubric before clinical-quality claims.
- Score only the application's supported care-planning activities. No criterion rewards new diagnoses, specific drug/class/dose recommendations or medication changes.
- Freeze file hashes, canonical input hashes, rubric version, source references and split membership before a run. Changes require a new dataset version and invalidate direct score comparisons with older versions.
- Use the same rubric with ICMR enabled and disabled. Report this as an ICMR-informed project evaluation, including the advantage of access to the same guidance underlying the rubric.

The earlier AMEGA exploration remains in `benchmarks/amega/` as historical work; its preparation tool is incomplete and is not part of this benchmark. No upstream AMEGA examples are reused in the custom cases.

## Step 2: Application context, correctness and APIs

Status: implemented; unit/API checks complete and live input/telemetry verification exercised in Step 5. See [API contracts](API.md#benchmark-submission-api) and [configuration](CONFIGURATION.md#benchmark-preparation).

- Accept supplemental clinical context through the API, persist a frozen copy with the operation, and pass the complete packet to both care-plan generation and review. Map suitable facts to FHIR while retaining the authoritative narrative.
- Record the packet hash and audit the actual model input against it. A context-window failure is explicit; required patient input is not silently shortened. Account for output and reviewer budgets as well as input length.
- Add idempotent interview completion accepting patient ID, transcript, supplemental context and a submission UUID. Retry successful submissions without repeating assessment/model work.
- Add run, case, task, turn, request, job and attempt correlation identifiers.
- Expose validated care-generation options for mode and ICMR context enabled/disabled. Persist effective options with queued jobs.
- Provide a read-only trace export API in the isolated benchmark deployment.
- Apply the small triage/interview correctness fixes: strict output schemas and urgency labels; emergency checks before model work; consistent urgency/actions; bounded improvements to negation and historical-event handling; explicit provider/parse failures; meaningful interview stop reasons; questionnaire ownership/completion validation; and explicit unavailable FHIR history.
- Update the frontend to handle interview failures as errors/retry states rather than successful completion.
- Provision synthetic benchmark patient histories through FHIR in a separate database. Registration itself remains demographic registration.

## Step 3: Serving profiles and observability

Status: implemented. See [serving profiles and observability](SERVING_BENCHMARK.md). Read-only server/metrics probes and the isolated Step 5 live telemetry pilot are complete.

Use configuration profiles supporting vLLM, llama.cpp and generic compatible endpoints. Each profile records the API endpoint, served model name, model revision/weights identity, quantization, tokenizer/chat template where known, context limit, sampling settings, output budgets, thinking settings, timeout/retry policy, server version, parallelism, cache policy, hardware and monitoring configuration. Credentials are configured separately and excluded from reports.

Use the compatible generation API and small backend-specific adapters for capabilities, extra request options and native metrics. Verify capabilities against the installed server version. Freeze and identify the effective profile for each run/job; pending work must not silently move to another model when configuration changes.

Capture each LLM call, including unsuccessful attempts:

- Stage: interview question, assessment, assessment review, care-plan generation or care-plan review.
- Request/run/case/task/turn/job/attempt IDs and parent relationships.
- Request duration, finish reason, truncation, provider failures, timeouts, retries and backoff.
- Provider-reported prompt, completion and cached-token usage; unknown usage stays unknown.
- First streamed content arrival when available, retaining its distinction from native server first-token timing. Assemble and validate JSON before returning product responses.
- Repair and review calls as part of the accepted output's total latency and token cost.

Capture application spans for FHIR reads/writes, retrieval, model calls, parsing/validation, queue wait and complete operation duration. Record enqueue/start/finish timestamps. The existing care-plan worker is serial and polls every three seconds; report this queueing behavior explicitly. Increasing worker/process concurrency is a separate architectural change.

Collectors may read backend metrics endpoints and serving-host resource data. Generation traffic still goes through the application. Native metrics can include queue/prefill/decode timing, token throughput, cache reuse, active/waiting requests and cache occupancy. Host metrics can include GPU utilization, VRAM, CPU and RAM.

Normalize units, retain raw values/definitions and label measurement origin. Do not attribute aggregate server histograms to individual requests. Do not infer true decoding speed or GPU utilization from application wall time. Missing capabilities remain unavailable.

## Step 4: External API runner and quality grader

Status: implemented and exercised by the Step 5 pilot. See [runner usage and artifacts](../benchmarks/api_benchmark/README.md). Automatic quality grading uses an Astra agent in Codex, launched only after explicit user approval for the grading batch. The user approved one pilot-plan review; its Astra judgments were imported. Further batches still require approval.

- Controlled performance workload: replay recorded transcript prefixes through the interview API, sequentially within a session, so input histories are repeatable across models/backends.
- The selected protocol uses recorded transcript prefixes. An adaptive interview simulator is an optional future extension; it is not part of this implementation.
- Care-plan quality workload: submit the full canonical clinical packet independently of interview completeness. Retain the application's generator, validation, reviewer and repair behavior.
- Run with ICMR context enabled and disabled, using identical clinical packets, assessments, generation mode and other settings for paired comparisons.
- Persist one assessment with `enqueue_care_plan=false`, then submit both care variants through the same enqueue API with fresh generation UUIDs. Check API support before creating fixtures or invoking interviews.
- Compare models under a common input protocol and backends serving the same model where practical. Record tokenizer differences and response length alongside tokens/s and completed operations/s.
- Use fresh benchmark resource/operation identities for measured repetitions. Record idempotent saved-result reads separately from fresh generation.
- Export blinded review packets offline; ask the user before launching Astra in Codex. Import its structured, evidence-backed judgments against pinned case/rubric/prompt/run hashes. The runner never launches an agent or calls a judge endpoint. Clinician spot checks and independent rubric review remain necessary before clinical claims.
- Keep simulator and grader execution outside the measured serving workload, or explicitly account for their contention.
- Use fixed case-specific weighted criteria, global scope/fact-consistency checks and critical-failure flags. Report macro-average per-case quality, condition/scenario breakdowns, completion rate and critical failures separately. Failed or invalid outputs receive zero in the all-attempt quality score; also report quality among completed outputs. No combined quality/performance score.
- Keep completed outputs ungraded until valid judgments arrive. Invalid judge output is rejected rather than scored as a generation failure. Record unknown critical-failure status separately.
- Verify full clinical packets at the model boundary through packet-audit/call/attempt span relationships. Pin serving identity and frozen FHIR context; reject saved-result reuse and invalid on/off pairs.
- Archive request/trace/metric/result files in new run directories, deduplicate overlapping attempt exports, distinguish warmups and monitoring overhead, and retain native timing origins. Preserve the measurement manifest when regenerating reports after grading.
- Record outstanding jobs and ambiguous enqueue/completion outcomes without hidden POST retries. Block review until work is drained and input/profile integrity is valid; do not silently resume a failed run.

## Step 5: Pilot and input/telemetry verification

Status: engineering pilot and approved one-plan Astra grading complete, with failures explicitly retained. All 30 cases and prepared packets are inside the workspace under `benchmarks/custom/`; dataset hashes pass. The isolated `cp-benchmark` database/API is running with 512 indexed ICMR passages. Final run `pilot-05` completed four interview calls, one shared assessment and two fresh care jobs: ICMR-on completed; ICMR-off failed validation after repair. Input/profile/source/span and saved-result checks passed; 12 unique model attempts have usage/native timing. The accepted plan scored 57.1429/100 with a patient-facts critical flag; the all-attempt mean is 28.57145/100 including the failed output's zero. The fact inconsistency originates in application-created observations, so this is not an isolated care-generator quality estimate. No clean paired comparison is available. See [the pilot findings and artifacts](BENCHMARK_PILOT.md).

First milestone: one development case through the application API with complete source input verified at the model boundary and a trace covering every model call and application stage.

Validate input preservation, rubric isolation and transcript-to-packet consistency, packet/profile/source hashes, per-attempt accounting, explicit failures, queue timing, job correlation, saved-result detection and backend capability reporting. Start with a small pilot before scoring the selected set.

## Step 6: Repeated comparisons and concurrency runs

Status: first full baseline measurement and approved Astra grading completed. The user selected enriched mode with ICMR enabled only: all 30 cases, one repetition, session concurrency 1, four recorded interview prefixes per case, no grounded or ICMR-off jobs. Results are saved under `benchmarks/api_benchmark/runs/full-enriched-02/`; see [full-run record](BENCHMARK_FULL_RUN.md). Repeated/concurrency comparisons remain future work. The user approved Astra grading for the 13 completed full-run plans; all judgments were imported and reports saved. Future batches still require separate approval.

Run repeated quality comparisons and serving-load scenarios. Specify concurrency/arrival policy, warm-up, warm/cold model state, cache conditions, repetition counts and polling policy. Use comparable workloads and record variation. Report latency distributions, throughput, failures, resource use, and quality together rather than presenting a single combined score.

Before formal comparisons, review the development pilot's validation failure rate, freeze application prompts/code and explicit sampling/weights identity, and configure serving-host exporters if GPU utilization/VRAM is required. The pilot proves input preservation and measurement, not clinical quality or reliable completion across the full set. Do not combine successful variants from different prompt revisions into a clean pair. Ask the user before launching any Astra grading batch.

The approved grading exposed a concrete input-consistency defect in `create_observations`: keyword matching wrote denied symptoms as positive FHIR observations. The negation-aware persistence fix is implemented and loaded into the isolated benchmark API. A fresh HTN-01 enriched/ICMR-on preflight completed successfully and its frozen context contains zero positive symptom observations; the full packet and context hash were verified before starting the full run. The earlier pilot's contradictory application-derived facts remain in its frozen records and grades; those artifacts were not rewritten or rescored.

## Source references

- [ICMR Standard Treatment Workflows](https://www.icmr.gov.in/standard-treatment-workflows-stws?q=order)
- Criterion-level sources are recorded in `benchmarks/custom/rubrics_*.json`.
- [vLLM production metrics](https://docs.vllm.ai/en/latest/usage/metrics/)
- [vLLM per-request metrics](https://docs.vllm.ai/en/latest/features/per_request_metrics/)
- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)

## Progress log

- 2026-10-15: Saved the agreed plan. Started source pinning, input inspection and eligibility preparation. Application logic, serving configuration and model execution have not been changed by this preparation step.

- 2026-10-15: Replaced the active AMEGA subset plan with an original 30-case custom dataset at the user’s request. Added separate clinical packets, interview workload scripts, source-linked draft rubrics and dataset integrity preparation. Steps 2–6 remain planned; no live benchmark has run.

- 2026-10-15: Implemented Step 2 API/context preparation: frozen clinical packets and FHIR job snapshots, hash audits at generation/review, durable interview completion, effective options and distinct generation UUIDs for paired runs, correlation/trace export, bounded interview/triage correctness fixes, UI retry behavior, and synthetic fixture provisioning. Added an isolated Compose override without starting it. Configured Qwen3.6-27B at host port 9000 and BGE-M3 Q8_0 (1024 dimensions) at 8081; both model-list endpoints verified. Serving token/native/host telemetry remains Step 3, and the external runner remains Step 4.

- 2026-10-15: Implemented Step 3: full hashed serving profiles (including embedding identity), explicit SDK-attempt telemetry and retry/backoff accounting, assembled streaming with usage and first-content timing, optional native llama.cpp/vLLM timings, application/FHIR/retrieval/validation spans, persisted queue timing, and gated capability/metrics APIs. vLLM 0.28.0 metrics endpoint verified; embedding metrics returns HTTP 501 and is recorded unavailable. No generation benchmark, service restart or workload runner has run; Step 4 is next.

- Step 3 verification: 332 mocked backend/unit/HTTP tests passed; Python compilation and base/isolated Compose configuration checks passed. Live checks were read-only model/version/metrics requests.

- 2026-10-15: Implemented Step 4 in `benchmarks/api_benchmark/`: hash-validated dataset loading; API-only four-turn workloads; assessment-only completion and fresh paired care jobs; packet/profile/span integrity checks; warmup/concurrency/polling/metrics controls; performance and quality reports; blinded Astra review export and validated offline judgment import. The user's approval requirement is recorded in code, review artifacts and these instructions. No live benchmark or Astra grading batch has run.

- Step 4 development checks: 29 runner/dataset/grading/reporting/review tests passed, plus 89 focused application tests passed (one HTTP test deselected). These checks used mock services; live input/telemetry verification remains Step 5. The dataset and rubrics remain draft pending independent clinical review.

- Step 4 final preparation: regenerated and validated all 30 packets and 151 criteria after documentation updates; Python compilation, CLI help/list/one-case planning and isolated Compose configuration checks passed. Added an assessment-only API preflight check and conservative handling of ambiguous server-error/invalid-success enqueue outcomes. No live workload was started.

- 2026-10-15: Executed Step 5 in Docker Desktop's isolated deployment. Reclaimed unused build cache and recreated only the incomplete new benchmark volume after disk-full setup failures; existing application/database retained. Verified all 30 cases are in the workspace, validated/indexed 512 passages, and retained five development pilot attempts. Fixed MedicationStatement's FHIR subject mapping, clarified existing output/repair/review instructions, and added selected-source identity telemetry for failed jobs without relaxing validation or increasing token budgets. Focused checks: 140 passed.

- Step 5 final run `pilot-05`: 174.316 seconds, four successful interview API calls (mean 3.700 seconds), ICMR-off failed after repair, ICMR-on completed with five verified sources. All 12 unique model attempts have prompt/completion usage and native TTFT; 82 serving-metrics snapshots captured. Packet/assessment/context/profile identity matches within the pair; all generation/review calls link to packet audits. No outstanding jobs, ambiguous POSTs or trace-capture errors. Live idempotent submission/job replays made no new model calls. One blinded review packet awaits user approval; Astra has not launched, and the completed-output quality score remains unknown.

- 2026-10-15: After explicit user approval, launched one blinded `gpt-6-astra` review. Imported valid judgments for the accepted plan: C2/C4/C5 passed, C1/C3 failed, weighted score 57.1429/100, patient-facts global check failed. Failed generation scored zero; all-attempt mean 28.57145/100. Confirmed all frozen measurement hashes stayed unchanged. Recorded the application-origin symptom-observation inconsistency separately from the independent judge's attribution. No application/rubric changes or further model runs were performed during grading.

- 2026-10-15: At the user's request, fixed symptom Observation persistence: answer/clause-aware affirmative matching replaces raw substring matching; coordinated denials, postfix absence and explicit historical/uncertain wording do not become positive booleans. Added no new clinical mappings. Python compilation and independent static review completed; tests and fresh benchmark runs were not performed for this fix. Restarted only the isolated benchmark agent to load it. Existing pilot resources, frozen inputs, grades and reports remain unchanged. The next measurement must use fresh patient/submission/generation identities, with separate approval for any new Astra grading batch.

- 2026-10-15: User requested the full benchmark and selected enriched + ICMR enabled only (30 care jobs). Ran a separate fresh HTN-01 preflight: care completed, packet/context hashes passed, no positive symptoms were persisted from the denial. Saved its job snapshot and verification. Pinned current application Python source and existing source-index hashes, then started `full-enriched-01` with all 30 cases, 120 interview requests, one repetition and concurrency 1. No prompt/code/config tuning during this full run; no new Astra batch launched.

- 2026-10-15: Stopped and preserved `full-enriched-01` after a FHIR fixture schema defect rejected text-only conditions with empty `coding` arrays. Drained its in-flight care job and marked the manifest aborted/incomplete. Applied only the schema serialization fix; all 30 fixture packets (178 resources) passed FHIR `$validate`. Pinned a fresh source archive/setup and restarted all 30 cases as `full-enriched-02`, enriched + ICMR enabled only, with fresh identities. Clinical prompts/rubrics and model configuration remain fixed; no new Astra grading launched.

- 2026-10-15: `full-enriched-02` measurement completed: 30 enriched/ICMR-on care jobs, 13 completed and 17 failed validation after repair; 50.71 minutes, 120 interview requests (119 successful responses), 259 model attempts, 1,401 metric snapshots. Artifact/packet/profile/source/lineage/drain checks passed; AST-06 interview turn 2 returned 502, and CKD-02 had no matching ICMR passages. Exported blinded 13-plan review bundle. User explicitly approved Astra grading; launched `/root/astra_full02_grade`, import pending.

- 2026-10-15: Astra reviewed all 13 accepted full-run plans after explicit approval. Imported 13 validated judgments plus 17 deterministic failed-generation zero records; completed-plan mean 71.53/100, all-attempt mean 31.00/100, critical rubric flags 7/13 completed plans. Reports, approval provenance and summary saved; original measurement hashes unchanged. Draft rubric and synthetic fixture metadata limitations documented, including DOB/medication-status mismatches without model-origin attribution.
