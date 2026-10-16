# Full enriched benchmark run

Status: measurement completed for `full-enriched-02`; all 30 cases attempted. Astra grading of all 13 completed plans is complete and imported. All results are saved inside the project workspace.

## Requested workload

| Setting | Value |
| --- | --- |
| Dataset | All 30 original synthetic cases: 10 development, 20 evaluation |
| Care generation mode | `enriched` |
| ICMR context | Enabled only (`icmr-on`) |
| Measured care jobs | 30 |
| Interview workload | Four recorded transcript prefixes per case, 120 requests |
| Repetitions / session concurrency | 1 / 1 |
| Warmup sessions / metrics interval | 0 / 2 seconds |
| API | Isolated benchmark app, `http://localhost:8003` |
| Serving models | Qwen3.6-27B via vLLM; BGE-M3 GGUF Q8_0, 1024 embedding dimensions |
| Quality judge | Astra in Codex; a new grading batch needs user approval |

No grounded or ICMR-off generations are included. This is a single baseline run; it does not establish run-to-run variation or serving capacity under concurrent load. Clinical packets and criteria remain draft pending independent clinical review. The development and evaluation split stays visible in reports.

## Preflight and freeze

The negation persistence fix was exercised through a fresh HTN-01 enriched/ICMR-on run before starting the full set. Care generation completed. Its full clinical packet and frozen context hash matched, and no positive symptom observations were written from the denial.

- [Preflight verification](../benchmarks/api_benchmark/runs/preflight-06-verification.json).
- [Saved preflight job snapshot](../benchmarks/api_benchmark/runs/preflight-06-job-snapshot.json).
- [Full-run setup and application hashes](../benchmarks/api_benchmark/runs/full-enriched-02-setup.json), with a Python source archive beside it.

The full run follows that separate preflight; caches were not reset. Explicit sampling settings, weights identity and serving-host hardware remain undeclared in the current profile, so server defaults and uncontrolled background activity limit formal comparisons. The existing indexed source versions and source/review file hashes were checked before measurement. Application prompts/code and model configuration are frozen during the run. Failures will be retained rather than replaced with successful reruns.

## Interrupted first attempt

`full-enriched-01` was stopped after six recorded outcomes when two fixtures were rejected before model inference. Text-only conditions incorrectly included an empty `coding` array, which FHIR rejects. Its queued care job was allowed to finish, and the manifest is marked aborted, incomplete and unsuitable for clinical review. Original raw files remain preserved; the interruption manifest, drain snapshot/trace and audit are beside the folder.

The only application change for `full-enriched-02` omits that empty array and retains the original condition text. All 30 fixtures (178 resources) passed FHIR `$validate` without persistence or model calls. The new run has fresh identities and a new source archive. No clinical prompts, cases, rubrics or serving settings changed. Cache state includes the earlier partial run; no cache reset was performed.

- [FHIR validation](../benchmarks/api_benchmark/runs/full-enriched-02-fixture-validation.json).
- [First-attempt interruption audit](../benchmarks/api_benchmark/runs/full-enriched-01-abort.json).

## Saved result files

All files are under `benchmarks/api_benchmark/runs/` inside the workspace. Run folders are ignored by Git but exist on disk.

- `full-enriched-02/results.jsonl`: one incremental outcome per case, including draft or failure, input/profile/source identities and care timings.
- `full-enriched-02/requests.jsonl`: client durations/statuses for interviews, assessment, enqueue, polling, metrics and trace fetches.
- `full-enriched-02/interviews.jsonl`: returned interview questions and stop reasons; no interview quality score.
- `full-enriched-02/traces.jsonl`: model attempts, application spans, retries/repairs and packet/source audits.
- `full-enriched-02/metrics.jsonl`: raw timestamped backend/host snapshots and component availability.
- `full-enriched-02/manifest.json`: selected identities, configuration and eventual measurement hashes.
- `full-enriched-02/report.json` and `report.md`: final performance/quality coverage summaries, regenerated after any approved grading.
- `full-enriched-02-progress.json`: separate progress record; not part of measured request traffic.
- `full-enriched-02-verification.json`: engineering checks after completion.

Serving metrics are available. Embedding metrics return HTTP 501, and serving-host GPU utilization/VRAM needs an exporter; container-local host readings are labeled separately. Missing metrics stay unknown. Failed generations score zero in the all-attempt quality mean; completed outputs remain ungraded until valid Astra judgments are imported. No new Astra agent is authorized by the earlier one-plan pilot approval.

## Measurement results

Measured run ID: `70d0352f-1719-48a3-883b-f1b3af1e556f`. Elapsed time: 3,042.62 seconds (50.71 minutes). All 30 care jobs reached a terminal state and finished tracing, with no outstanding jobs, ambiguous submissions or trace capture errors. The measurement manifest reports protocol validity. Artifact hashes, clinical packet hashes, profile identity, source pins and care-job lineage checks passed.

| Condition | Completed care plans | Failed validation |
| --- | ---: | ---: |
| Asthma | 4 | 2 |
| CKD | 2 | 4 |
| COPD | 5 | 1 |
| Hypertension | 2 | 4 |
| Type 2 diabetes | 0 | 6 |
| **Total** | **13** | **17** |

Completion rate is 43.33%. All 17 failures report `Draft failed validation after one repair.` This describes application acceptance, not a clinical quality score. No failed case was replaced with a successful retry.

| Measurement | Samples | Mean | Median | p95 |
| --- | ---: | ---: | ---: | ---: |
| Interview API latency | 120 | 3.29 s | 3.55 s | 4.60 s |
| Care operation latency, all outcomes | 30 | 78.51 s | 78.27 s | 127.90 s |
| Care operation latency, completed only | 13 | 53.99 s | 58.16 s | 72.46 s |
| Care worker processing, all outcomes | 30 | 76.35 s | 75.73 s | 125.72 s |
| Application worker queue, all outcomes | 30 | 1.47 s | 1.51 s | 2.87 s |
| Native vLLM interview TTFT | 120 | 0.52 s | 0.49 s | 0.64 s |
| Native vLLM care-generation TTFT, including repair calls | 51 | 1.62 s | 1.96 s | 3.35 s |

Care operation timing starts at care enqueue and ends at the observed terminal/traced result; it excludes interview and assessment latency. Completed-only distributions in the standard report use 13 samples. The separate summary includes all 30 outcomes to expose failure/repair latency. TTFT is provider-native; first streamed content timing is separately recorded in `report.json`.

There were 259 unique model HTTP attempts and 259 logical calls, including 51 care-generation attempts (21 repair calls). All attempts expose prompt/completion usage and native vLLM timing; total known usage is 882,895 prompt tokens and 103,039 completion tokens. This counts repeated prompt processing and repairs, not unique clinical text. No HTTP model retries or truncation were recorded.

There are 1,401 infrastructure snapshots. Serving and container-host metrics are available for all snapshots; embedding metrics return 501 and GPU readings are unavailable. Twenty-nine jobs had available ICMR context; CKD-02 returned no matching passages. ICMR remained enabled for that case; it is not an ICMR-off variant. Source presence does not prove clinical support.

All 120 interview requests were attempted. AST-06 turn 2 returned HTTP 502, leaving 119 successful saved interview responses. This is retained as an API failure and a limitation on complete four-response interviews; the full original clinical packet still reached care generation. No interview quality score is produced.

- [Machine-readable result report](../benchmarks/api_benchmark/runs/full-enriched-02/report.json).
- [Standard report](../benchmarks/api_benchmark/runs/full-enriched-02/report.md).
- [All-outcome timing summary](../benchmarks/api_benchmark/runs/full-enriched-02-summary.json).
- [Integrity verification](../benchmarks/api_benchmark/runs/full-enriched-02-verification.json).
- [Grading approval record](../benchmarks/api_benchmark/runs/full-enriched-02/review/approval.json).

## Quality review

The user explicitly approved Astra grading of the 13 completed plans. All 13 judgments passed structural and exact-evidence validation and were imported; reports were regenerated. Measurement inputs, results, traces, metrics and manifest hashes remained unchanged. Seventeen failed generations receive deterministic zero in the all-attempt score, with critical safety status unknown.

| Quality result | Value |
| --- | ---: |
| Completed-plan mean, 13 graded outputs | 71.53 / 100 |
| All-attempt mean, 30 cases including failed generations as zero | 31.00 / 100 |
| Completed outputs with critical rubric flags | 7 / 13 (53.85%) |
| Completed grading coverage | 13 / 13 (100%) |

Weights apply to case-specific criteria. Global checks and critical criteria produce separate flags; they do not gate the numerical score. A plan can therefore score 100 while receiving a global critical flag. These scores and flags use draft rubrics and are not clinically validated safety estimates.

Recurring issues include incomplete compound requirements, missing follow-up conditions or urgent-care guidance, and assertions unsupported by the original packet. Some patient-facts flags concern metadata supplied through the fixture: medication resources are marked status `unknown`, and exact birth dates are synthesized from age. Those flags measure consistency with the original packet and cannot by themselves establish model-origin hallucination. This limitation is retained without modifying the frozen rubric or rescoring.

- [Saved Astra judgments](../benchmarks/api_benchmark/runs/full-enriched-02/review/astra-judgments.jsonl).
- [All 30 grade records](../benchmarks/api_benchmark/runs/full-enriched-02/grades.jsonl).
- [Grading summary](../benchmarks/api_benchmark/runs/full-enriched-02/review/grading-summary.json).

Rubrics remain draft and require independent clinical review.

## Subsequent failure diagnosis

[Detailed validation failure analysis](BENCHMARK_VALIDATION_FAILURES.md) maps all 17 terminal blockers from server logs. Eight involve blanket medication-name/dose restrictions, six involve age review rejections with conflicting upstream assessment ages, two involve urgent-disposition review, and one an invalid/missing citation. Reviewer age errors and unavailable rejected drafts limit attribution. Original measurement and grades remain preserved.
