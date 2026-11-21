> Historical V1 record: the old benchmark artifacts were cleared on 2026-10-24 at the user's request. Summary evidence is preserved in `docs/history/benchmark-v1-summary-20261024.zip`. The active benchmark is CarePlan100.

# Step 5 live pilot

Date: 2026-10-15. Status: engineering pilot complete, with model-output failures retained. The user approved Astra grading of the one accepted plan; its judgments were validated and imported.

## Workspace files

The 30 original cases are in `benchmarks/custom/`, inside this project workspace:

| File | Case count |
| --- | ---: |
| `cases_metabolic.json` | 12: hypertension and type 2 diabetes |
| `cases_respiratory.json` | 12: asthma and COPD |
| `cases_renal.json` | 6: chronic kidney disease |

Separate `rubrics_*.json` files hold grading criteria. `prepared/` contains all 30 canonical generation packets, interview scripts, grader inputs and the hash manifest. Case/rubric content is unchanged by the pilot. Engineering validation does not establish clinical validation of the draft rubrics.

## Deployment and protocol

- Docker context: `desktop-linux`; Compose project: `cp-benchmark`.
- Separate volume: `central-park-benchmark-iris-data`. Main application/database retained.
- API: `http://localhost:8003`; FHIR: `http://localhost:52776`.
- Chat: Qwen3.6-27B through vLLM 0.28.0, streaming enabled, thinking disabled, declared context 200000 tokens.
- Embeddings: `gpustack/bge-m3-GGUF:Q8_0`, 1024 dimensions, host port 8081.
- Indexed 512 locally validated ICMR passages across five source files before measurement.
- HTN-01 only: four recorded transcript prefixes, one shared assessment, two fresh ICMR-on/off jobs, enriched mode, concurrency 1, one repetition, no warmup, metrics interval 2 seconds. The fixed seed places ICMR-off first.
- Cache state is uncontrolled. Server-default sampling remains unspecified in the saved profile. This is an engineering pilot, not a model comparison or capacity estimate.

Docker's initial 32 GB disk filled during image build and then volume initialization. Approved unused-cache cleanup restored sufficient space. The incomplete new benchmark volume was removed and recreated; existing containers, images and database volumes were preserved. The final deployment used the successfully built images without rebuilding.

## Retained attempts and fixes

| Directory under `benchmarks/api_benchmark/runs/` | Outcome |
| --- | --- |
| `pilot-01` | Fixture creation returned HTTP 502 before model calls. FHIR MedicationStatement used `patient` instead of required `subject`. Corrected the fixture mapping and strengthened its existing check. |
| `pilot-02` | Four interview calls and shared assessment succeeded. Both care jobs failed after their bounded repair with `Invalid missing-information activity`. Packet/profile checks passed; model usage/native timings, repairs and failure traces were captured; workload drained. |
| `pilot-03` | Clarification formatting passed, but both care jobs failed the existing named-drug/class guard after repair. Input/profile checks and failure capture passed. |
| `pilot-04` | After explicitly requiring generic medication wording in every output field, ICMR-off completed. ICMR-on failed when review was truncated at 2048 tokens. Both variants retained matching packet/assessment/context/profile hashes, all 13 unique model attempts had usage/native timing, and the run drained. Clean pair coverage was 0/1. |
| `pilot-05` | Final engineering run: ICMR-on completed with five verified context sources; ICMR-off failed validation after repair. Full input/profile/span/source checks passed and work drained. Astra graded the accepted plan after user approval; no clean paired comparison is available. |

The clarification correction requires `category=clarification`, `provenance=missing-information`, `source_ids=[]`, and `timing=null`; scheduling belongs in a separate allowed activity. Medication wording instructions now explicitly match the existing guard on every narrative field, including review notes and missing information. Review instructions request concise JSON without copied inputs or rewritten plans. Validation restrictions, clinical scope and output token budgets are unchanged. Failed attempts remain recorded and are not replaced with successful results. Application-safe failure reasons are now retained in runner results.

`careplan.context.prepared` records selected passage IDs, versions and text/model-source hashes before model execution. This permits source identity verification even for failed care jobs. No source or patient prose is added to telemetry. `pilot-source-index-manifest.json` pins all 512 indexed passage text hashes and document versions; final source snapshots are checked against those pins.

Focused checks: 67 passed after the fixture correction; 140 passed after each subsequent correction. Application Python source snapshots for `pilot-03` through `pilot-05`, their file hashes and initial source/setup hashes are saved beside the run directories. Only the development case was used for these corrections; the twenty evaluation cases were not run or used for tuning.

## Verification and limitations

Final checks passed for complete clinical input at generation and review, call/attempt/span lineage, identical paired frozen context and assessment, actual ICMR retrieval, source snapshot hashes, distinct fresh generation identities, queue timing, trace completeness and valid/drained run artifacts. All five selected text hashes, document versions and serialized model-source hashes matched the pinned source/review files. Post-measurement replays reused the same assessment and both job UUIDs without new model calls or changes to their model traces. These diagnostic requests are archived separately from measured requests. Grading remains offline and requires explicit user approval before launching an Astra batch.

### Final run measurements

| Observation | Value |
| --- | --- |
| Run ID | `5a2f6ffe-e233-437d-827c-a61f8fca0645` |
| Measured workload duration | 174.316 seconds |
| Interview requests | 4/4 successful; mean client latency 3.700 seconds |
| ICMR-off | Failed after repair; queue 0.561 s, processing 68.686 s |
| ICMR-on | Completed; queue 2.739 s, processing 77.678 s |
| Unique model HTTP attempts / logical calls | 12 / 12; overlapping trace exports deduplicated |
| Stages | Interview 4; assessment 1; assessment review 1; care generation 4; care review 2 |
| Prompt/completion token totals | 49,758 / 6,039, including repairs and failed work |
| Usage, first-streamed-content and native TTFT coverage | 12/12 attempts |
| Serving metrics snapshots | 82 |
| Application HTTP requests | 254/254 returned 200; asynchronous care failure remains a failed result |
| Outstanding jobs / ambiguous POSTs / trace errors | 0 / 0 / 0 |
| Clean completed on/off pairs | 0/1; shared inputs match, but one output failed |
| Quality grading | Accepted output 57.1429/100; failed output 0; all-attempt mean 28.57145/100; accepted output failed patient-facts global check |

These are individual engineering observations, not latency/capacity estimates or clinical-quality findings. Both care variants required their existing bounded generation repair. A successfully validated output is not independent clinical approval. Successful variants from different pilot revisions must not be combined into a paired comparison.

### Approved Astra grading

The user approved one Astra review after the engineering pilot. `/root/astra_pilot05_grade` used `gpt-6-astra` with only the blinded packet and blank template. It did not receive variant/model metadata, generated FHIR context, retrieved excerpts or prior pilot results. All criterion IDs, boolean judgments, exact evidence excerpts and frozen run/data/prompt hashes passed import validation. Reports were regenerated; measurement artifacts and the run manifest stayed unchanged. Further Astra batches still require user approval.

| Criterion | Judgment |
| --- | --- |
| C1: ongoing BP measurement and defined follow-up | Failed: follow-up lacked a defined interval/date |
| C2: salt reduction and regular activity | Passed |
| C3: BP monitoring and consideration of annual laboratory evaluation | Failed: baseline testing was included, annual evaluation was not |
| C4: missing home BP trend and adherence/tolerance history | Passed |
| C5: generic clinician medication review within scope | Passed |

Weights yielded 4/7, or 57.1429/100. The patient-facts global check failed; medication scope and urgent disposition passed. The critical flag is reported separately and does not change the weighted score. The failed generation receives zero without a judge call; averaging the two attempts gives 28.57145/100. This is one synthetic development case under draft rubrics, not a clinical-performance estimate.

The patient-fact flag has an application-origin confound. The original case denies chest pain and neurologic symptoms, but the frozen context contains application-created positive `Chest pain` and `Unilateral weakness` observations. `create_observations` in `src/python/central_park/tools/fhir.py` writes `valueBoolean=true` whenever a keyword occurs in the answer, including denials. The care plan flagged these actual record conflicts. The blinded judge did not see those generated records, so its description of invented FHIR records does not establish a care-model hallucination. Its birth-year concern also references a fixture-derived field. Preserve the independent judgment, but interpret the score as affected by the application pipeline rather than an isolated care-generation score.

Before a full evaluation run, correct symptom-observation negation handling and repeat a fresh development pilot. This grading turn did not change application logic, existing outputs or rubric content.

### Subsequent persistence fix

The user subsequently requested the negation fix. `create_observations` now uses answer/clause-aware affirmative matching. Denials remain in scope across coordinated symptom lists; explicit new affirmative clauses start a new scope. Local postfix absence and explicit historical/uncertain mentions are excluded from positive booleans. The supplied HTN-01 denial no longer qualifies as an affirmative chest-pain or weakness mention by these rules. The original questionnaire wording is retained, and no negative observation is invented for an omitted match.

Python compilation and independent static review completed. Tests and a new benchmark run were not performed for this fix. The isolated benchmark agent was restarted to load it. The original pilot's frozen FHIR observations and grading results remain historical artifacts. Repeat a fresh development pilot before a full evaluation; further Astra grading requires a new approval.

### Saved artifacts

All paths below are inside the workspace:

- [Final measurement report](../benchmarks/api_benchmark/runs/pilot-05/report.json) and [immutable measurement manifest](../benchmarks/api_benchmark/runs/pilot-05/manifest.json).
- [Engineering verification](../benchmarks/api_benchmark/runs/pilot-05-engineering-verification.json).
- [Live saved-result/context/source verification](../benchmarks/api_benchmark/runs/pilot-05-verification/verification.json), with full frozen job snapshots beside it.
- [Exact model-source hash reproduction](../benchmarks/api_benchmark/runs/pilot-05-model-source-verification.json).
- [Pinned source index](../benchmarks/api_benchmark/runs/pilot-source-index-manifest.json) and [application source snapshot manifest](../benchmarks/api_benchmark/runs/pilot-05-application-source.json).
- [Blinded review manifest](../benchmarks/api_benchmark/runs/pilot-05/review/manifest.json), marked `judgments-imported`: one reviewed packet and one failed output excluded from judge calls.
- [Astra judgments](../benchmarks/api_benchmark/runs/pilot-05/review/astra-judgments.jsonl), [approval record](../benchmarks/api_benchmark/runs/pilot-05/review/approval.json), and [grading summary with application-origin attribution](../benchmarks/api_benchmark/runs/pilot-05/review/grading-summary.json).

The run folders are ignored by Git but exist on disk. Retain them for reproducibility. The 30 case JSON files and rubric files are separate workspace sources under `benchmarks/custom/`.

Serving Prometheus and vLLM per-request timings are available. The embedding metrics endpoint returns HTTP 501 and stays unavailable. Host snapshots describe the application container/process namespace; no serving-host exporter is configured, so they do not establish utilization or VRAM for the machine serving Qwen. Weights/revision identity and explicit sampling/hardware/cache declarations are still needed for formal repeated comparisons.
