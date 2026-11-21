# CarePlan100 API benchmark

`careplan100` runs the fixed 100-case workload against the app API, writes raw append-only records and CSV views, and can grade saved runs separately. The harness uses Python standard-library modules and the repository's existing `httpx` dependency. It does not import the application generator.

From the repository root:

```sh
python benchmarks/run_benchmark.py validate
python benchmarks/run_benchmark.py run --dry-run --split development
python benchmarks/run_benchmark.py run --split development
python benchmarks/run_benchmark.py grade --run-dir benchmarks/runs/<run-id>
```

`run` defaults to all cases. `--cases CASE_ID ...` and `--limit N` narrow a pilot. `--skip-startup` attaches to a running app. `--dry-run` performs offline validation and prints the planned workload without contacting Docker, model endpoints, or the application. A normal run checks disk space and the configured Docker context, starts only `iris` and `agent` with the benchmark compose override, restarts the agent, waits for app/profile readiness, publishes the accepted care-document index, and probes already-running model endpoints. It never starts model servers, deletes volumes, or clears caches.

Copy `careplan100/config.example.json` to a private config and set paths, app URL, timeouts, and optional independent judge endpoint. Secrets are read only from named environment variables and are excluded from manifests. The judge is disabled when no endpoint/model are set. Generation completes before optional grading starts. Grade revisions are stored in a new `grades/<revision>/` directory, leaving the measurement record immutable.

Each run records `manifest.json`, packet and profile fingerprints, fixture provisioning, every app request/status/duration/request ID, request and care-job traces, interview responses, care-plan results, periodic resource metrics, and errors. CSV views include `cases.csv`, `case_stage_metrics.csv`, `llm_attempts.csv`, `rubric_results.csv`, `failures.csv`, `summary.csv`, and `infra_samples.csv`. Native LLM measurements remain attributed to recorded attempt spans; host resource snapshots are run-level observations and are not allocated to individual cases.

The runner provisions and verifies all selected deterministic FHIR fixtures before the first interview/model call. A result is not quality-gradeable unless the frozen packet and job trace hash verify and serving profile identity remains stable. HTTP POSTs are never retried. A timeout/ambiguous POST is captured and blocks a valid protocol result. Generation failures receive score zero only when graded; a missing judge means quality is ungraded, not zero.

## Default full run

From the repository root, using the existing virtual environment:

```sh
.venv/bin/python benchmarks/run_benchmark.py
```

This selects all 100 cases (400 recorded interview prefixes and 100 fresh care jobs) in enriched mode with ICMR enabled. The dataset comprises 50 ordinary OPD cases, 30 chronic cases and 20 injury cases. The 20/80 split is reported separately. See [dataset review](careplan100/data/README.md) and [active implementation plan](../docs/BENCHMARK_PLAN.md). Astra authored and independently critiqued the dataset; it is not clinically validated.

Docker Desktop must be running. Only the app/database are started by the script. The default model endpoints are localhost:9000/v1 (Qwen3.6-27B) and localhost:8081/v1 (BGE-M3 Q8_0, 1024 dimensions). Container endpoints are specified separately using host.docker.internal. Existing benchmark database/index/cache state is retained; fresh patient/operation UUIDs isolate runs. Main application data is not mounted into the benchmark deployment.

For a small development run:

```sh
.venv/bin/python benchmarks/run_benchmark.py --split development --cases CHR-007 INJ-011 OPD-001 OPD-045
```

## Configure a judge later

Copy `benchmarks/careplan100/config.example.json` beside it as `config.local.json`. Set `judge.base_url` (including the `/v1` API prefix), `judge.model`, and `judge.api_key_env` to the name of an environment variable containing your key. Do not put the key itself in the config. `json_mode`, `token_limit_param`, output budget, temperature, timeout, retries and concurrency are configurable for compatible endpoints. Missing provider timing/token fields remain unavailable; unsupported JSON request mode can be disabled in configuration.

```sh
.venv/bin/python benchmarks/run_benchmark.py --config benchmarks/careplan100/config.local.json
.venv/bin/python benchmarks/run_benchmark.py grade --config benchmarks/careplan100/config.local.json --run-dir benchmarks/runs/<run-id>
```

Provider-specific parameters can be supplied in `judge.extra_body`; they cannot override the configured model, messages or grading parameters. For the local Gemma judge, `{"chat_template_kwargs": {"enable_thinking": false}}` avoids spending the response budget on hidden reasoning. Use this option only with servers that support it. The local configuration uses a 4,096-token output budget. The required rubric response format is explicit, and exact plan evidence is validated. Completed judge calls are saved as the grading batch progresses.

The first command measures and then grades; the second grades existing outputs without restarting the app or repeating generation. With no judge configured, completed plans are ungraded and receive no pass claim. Each grade revision contains joined `cases.csv`, criterion/global-check `rubric_results.csv`, split/group/condition `summary.csv`, raw judgments/traffic and a report hash manifest. Performance CSVs stay at the measurement directory root. Regrading with a different judge creates a new revision rather than overwriting existing grades.

Pass requires a completed, input-verified plan scoring at least 80/100 with no critical flags. Overall quality includes valid generation failures as zero; missing or invalid judgments remain unknown. This is a predefined project threshold, not a clinical safety certification.

All native times are seconds; vLLM's recorded token rate has scope `prefill_and_decode`, not decode-only throughput. Native first-token timing is distinct from first streamed content observed by the app. CSV metric sample counts show coverage; percentiles use linear interpolation. `failures.csv` retains repaired/rejected attempts as well as terminal failures, so use `status` to distinguish them.

## Latest saved 100-case report

The latest fresh, uninterrupted run is [`runs/20261025T101108Z-5f28651a/`](runs/20261025T101108Z-5f28651a/). It has 90 completed plans and ten validation failures, with all 100 packet/profile/trace checks verified and exactly 400 interview responses. The API judge attempted all 90 completed plans, but every request failed with `ConnectError`; score coverage is 0/90 and quality remains unknown. The failed generation outputs retain their prescribed zero scores. See [the fresh run record](../docs/BENCHMARK_FULL_RUN.md#fresh-uninterrupted-run-after-validation-correction) and [verification artifact](runs/luna-fresh-verification.json).

The earlier two-segment combined report remains at [`runs/careplan100-combined-20261024T210139Z/`](runs/careplan100-combined-20261024T210139Z/). It contains 93 completed plans and seven validation failures, with 83 valid API judge grades averaging 90.15/100 and 70 passes. Its measurement spans two segments separated by an LLM restart, so it is not a continuous-run throughput result. See [the run record](../docs/BENCHMARK_FULL_RUN.md) for provenance and comparisons.

The default script checks the external model endpoints before Docker startup. If Docker builds report “No space left on device”, the Docker Desktop disk can be full even when the workspace drive has space; build failures include the relevant output tail. The script does not automatically delete Docker data.
