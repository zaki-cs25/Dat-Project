# CarePlan100 run record

Updated 2026-10-25. The obsolete 30-case folder was cleared at the user’s request; its small summary archive remains in [history](history/benchmark-v1-summary-20261024.zip).

## Fresh uninterrupted run after validation correction

The latest run is `benchmarks/runs/20261025T101108Z-5f28651a/`. It was run after the medication/provenance validation correction in [BENCHMARK_VALIDATION_FIX.md](BENCHMARK_VALIDATION_FIX.md), using the unchanged 100-case dataset, criteria, weights and pass threshold. This is a single uninterrupted measurement; it is distinct from the two-segment combined run documented below.

| Cohort | Cases | Completed | Failed validation |
| --- | ---: | ---: | ---: |
| Everyday OPD | 50 | 46 | 4 |
| Chronic | 30 | 26 | 4 |
| Minor injury | 20 | 18 | 2 |
| Total | 100 | 90 | 10 |

The 10 terminal validation failures were CHR-008, CHR-011, CHR-026, CHR-030, INJ-004, INJ-008, OPD-016, OPD-017, OPD-029 and OPD-050. Each retained its draft attempts and failed after one repair. All 100 selected inputs, serving profiles and traces verified; all 100 cases have exactly four recorded interview responses (400 total). The run recorded 8,062 app API requests, no app API request errors, 819 LLM attempts with native timing and token fields present, and 2,690 infrastructure samples. Elapsed measurement time was 5,713.63 seconds (about 1 hour 35 minutes). No source, prompt, dataset or rubric changes were made during measurement.

The configured Gemma API judge was invoked for all 90 completed plans, but all 90 requests failed with `ConnectError` before receiving an HTTP response. Therefore **completed-plan grade coverage is 0/90**; all 90 completed-plan scores and critical status are unknown, and no quality pass claim can be made. The 10 valid generation failures are retained as zero scores under the scoring rule. No automatic retries were configured. The raw requests, errors and ungraded rows remain in `grades/20261025T114701Z-780e1600/`.

Run and grade integrity checks are recorded in [`benchmarks/runs/luna-fresh-verification.json`](../benchmarks/runs/luna-fresh-verification.json); live/final progress is in [`benchmarks/runs/luna-fresh-progress.json`](../benchmarks/runs/luna-fresh-progress.json). All 27 measurement artifact hashes and all five grade artifact hashes verified. The frozen config, dataset, source and profile fingerprints are recorded in the run manifest and verification file.

## Earlier combined run

The report below describes the earlier run captured across two segments. It is retained for historical comparison; the fresh uninterrupted run above is the latest measurement.

## Selected 100-case results

The combined report is `benchmarks/runs/careplan100-combined-20261024T210139Z/`.

| Cohort | Cases | Completed | Failed validation |
| --- | ---: | ---: | ---: |
| Everyday OPD | 50 | 47 | 3 |
| Chronic | 30 | 28 | 2 |
| Minor injury | 20 | 18 | 2 |
| Total | 100 | 93 | 7 |

All 100 selected results have verified full clinical packets, stable serving profile and ready traces. Development: 20 completed / 20. Evaluation: 73 completed / 80. There are exactly 400 selected interview API requests and no interview API errors. Interview quality and triage quality are not scored. All care jobs used enriched mode and ICMR enabled; retrieval availability is retained per case.

The local API judge has now evaluated all 93 completed plans. **83 have valid grades**, averaging **90.15/100**; **70 meet the predefined pass rule**, and one valid judgment contains a critical flag. **Ten remain ungraded** because returned evidence was missing or was not an exact excerpt. The seven valid generation failures retain zero scores. Judge coverage is 83/93 completed plans (89.25%). An all-100 quality average remains unavailable because ten scores are unknown. These are automated judge results. No Astra grading batch was launched.

## Earlier combined-run CSV files

- `cases.csv`: 100 case outcomes, plan JSON, timings, input/profile flags and source segment.
- `case_stage_metrics.csv`: per-case/per-stage timing, rate and token distributions, with units and coverage.
- `llm_attempts.csv`: 820 distinct HTTP attempts; native TTFT, mean inter-token latency, token rate and prompt/completion counts are available for all 820.
- `summary.csv`: pooled performance distributions and completion counts.
- `failures.csv`: 21 cases with terminal failures, repaired/rejected attempts or upstream conflicts. Filter `status != completed` for the seven terminal failures.
- `infra_samples.csv`: 2,608 periodic infrastructure snapshots with their collection scope and availability. These are segment aggregates, not per-case GPU measurements.
- `grades/20261025T074202Z-3eaddd15/cases.csv`: latest performance/quality join, with 83 valid grades, ten ungraded results and seven generation failures.
- `grades/20261025T074202Z-3eaddd15/rubric_results.csv`: 681 criterion/global-check or not-judged rows. Its `summary.csv` has overall/split/group/condition results.
- The initial unconfigured revision `grades/20261024T210151Z-25e86b1e/` remains preserved.

Raw JSONL and artifact hashes remain alongside the CSVs. Export checks are saved in `benchmarks/runs/full-verification.json`.

## Earlier combined-run performance interpretation

| Metric | Mean | Median | p95 |
| --- | ---: | ---: | ---: |
| Interview API latency | 3.21 s | 3.38 s | 4.30 s |
| Care job latency, enqueue through final trace | 37.34 s | 31.78 s | 57.92 s |
| Whole case operation | 58.54 s | 53.15 s | 81.30 s |
| Native first-token latency, all LLM stages | 0.784 s | 0.539 s | 2.210 s |
| Native mean inter-token latency | 21.27 ms | 20.74 ms | 23.83 ms |

Statistics include both successful and failed selected cases. Native token rate averages 35.35 tokens/s with server scope `prefill_and_decode`; it is not decode-only throughput. Judge calls are outside performance measurement.

This is a combined report from **two measurement segments**, not one uninterrupted run. The first runner stopped after 88 saved results and started one additional OPD-039 case without saving a final result. The LLM was restarted before a 12-case continuation. The unfinished original OPD-039 records are excluded from combined case/request/attempt statistics and remain preserved in the original directory. Original aggregate samples are truncated at the start of that excluded case. Server caches were not controlled across the restart, so pooled distributions describe these two segments. Overall wall-clock throughput is intentionally unavailable because the first segment’s final elapsed timer was not saved.

Preserved segments:

1. `benchmarks/runs/20261024T152741Z-beac6444/`: 88 selected results, plus excluded unfinished OPD-039 traces. Its original manifest still records the abrupt process’s last status, `running`.
2. `benchmarks/runs/20261024T205027Z-08964375/`: 12 results, completed with valid protocol checks.

Dataset, application/harness source and serving profile fingerprints match between segments. The combined manifest retains each source run ID and manifest hash. The measured source snapshot is `benchmarks/runs/careplan100-full-source-20261024.zip`; its audit file stores the archive hash. Startup diagnostics and build-copy changes made after measurement are not part of that frozen source.

## Failures retained

CHR-022 failed twice because a routine referral was incorrectly labelled `provenance=assessment`, which is reserved for application-inserted activities. The old error text misleadingly described this as an urgent-instruction error. CHR-026, INJ-008, INJ-014, OPD-017, OPD-042 and OPD-050 failed twice on the unrecorded medication/class guard. These are application validation outcomes; the guard can also reject safety-review wording. They do not independently establish that each rejected plan was clinically harmful. Candidates, fields and exact rejection feedback are retained for later analysis. No guard or prompt tuning was performed on these evaluation failures.

## Startup recovery and development pilot

Docker’s internal 32 GB disk filled during a later startup rebuild. Clearing unused build cache reclaimed 9.15 GB; database volumes were retained. External model probes now fail early and Compose errors include their output tail. The IRIS image copies only `src/cls` and `iris-config`, preventing app/report/docs edits from forcing database rebuilds. The final startup function completed successfully with both model probes ready, a 1024-dimensional embedding and index publication confirmed. Its result is saved in `benchmarks/runs/startup-verification.json`. Startup recovery was checked separately from the completed benchmark measurements.

The original four-case development pilot used single-script startup and completed CHR-007, INJ-011, OPD-001 and OPD-045, with valid input/profile checks, 16 interview calls and CSV export. Measurement duration was 237.13 seconds. Its artifacts remain in `benchmarks/runs/20261024T151805Z-09639e8b/`. A narrow factual-adherence guard correction was made after this pilot and before evaluation, with no dataset/rubric changes.

## Earlier combined-run API judge

Endpoint: `http://localhost:8001/v1`. Advertised model: `unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q8_K_XL`. Private reusable configuration: `benchmarks/careplan100/config.local.json`, with credentials read from the named environment variable when needed. This local endpoint accepted requests without authentication. Grading used temperature 0, 4,096 output tokens, JSON object response mode, concurrency 1 and `chat_template_kwargs.enable_thinking=false`. The first compatibility request exhausted its 2,500-token budget on reasoning; the updated compatibility check returned a valid rubric response before the full batch began. Compatibility records are stored separately from final judge traffic.

Grading version 1.1 makes the JSON array/object contract explicit, supports provider options through `judge.extra_body` and journals completed judgments. Clinical packets, rubric criteria/weights and pass thresholds were unchanged. Exact evidence checks remain enforced. Raw model responses for all 93 API calls and usage are retained in the new grade revision. Usage totals: 192,309 prompt tokens, 57,732 completion tokens, 250,041 total. Judge usage and latency are outside the serving measurement.

The ten ungraded cases are CHR-007, CHR-008, CHR-029, INJ-004, INJ-009, INJ-019, OPD-018, OPD-019, OPD-033 and OPD-037. Their scores remain unknown. The judge configuration, coverage, error list and integrity verification are saved in `benchmarks/runs/judge-verification-20261025.json`.

## Validation correction applied before the fresh run

After the earlier combined run and its API judging, the application medication/provenance checks and future judge guidance were updated. The fresh run at the top of this record measured that corrected application. See [the fix record](BENCHMARK_VALIDATION_FIX.md). The correction does not revise any result from the earlier run.
