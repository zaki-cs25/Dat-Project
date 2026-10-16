# Serving profiles and observability

Step 3 instruments the production API path. The external workload runner and offline quality grader remain Step 4. No benchmark generation has been run by this implementation.

## Current endpoints

Read-only probes confirmed Qwen3.6-27B on localhost:9000, vLLM version 0.28.0, advertised context 200000 tokens, and a working `/metrics` endpoint. The parser recognized 96 metric families and 497 samples in one snapshot. This count is an observation, not a fixed capability contract.

The BGE-M3 Q8_0 endpoint on localhost:8081 advertises 1024 dimensions. Its `/metrics` currently returns HTTP 501, which the collector records as unavailable. It does not substitute zero values. Local Docker configuration uses `host.docker.internal` for these endpoints. Containers must be able to reach the host listeners.

## Profiles and configuration

`GET /benchmark/serving/profile` returns a local configuration snapshot and canonical SHA-256 `profile_id`. It performs no model or monitoring requests. The profile identifies endpoint/model/backend, declared revision/weights/quantization/tokenizer/template/context limit, sampling, stage token budgets, streaming, retry/timeout policy, embedding configuration and monitoring endpoints. Missing metadata remains null. Unspecified sampling means the server default is unknown. Arbitrary template settings are represented by a hash; known `enable_thinking` is recorded separately. Credentials are excluded and endpoint user-info/query/fragment are stripped.

New care jobs freeze the full profile. A changed profile causes an explicit failure before inference; restore the queued configuration to retry or use a fresh generation UUID for a deliberate comparison. Older Step 2 jobs retain their smaller identity check. A declared model ID is not a weights checksum: replacing weights behind the same name cannot be detected without updating the declared weights/revision identity. Record those identities before formal comparisons.

| Setting | Meaning |
| --- | --- |
| `CP_LLM_BACKEND` | `vllm`, `llamacpp`, or `generic` compatible serving |
| `CP_LLM_TIMEOUT_SECONDS` | SDK request timeout, default 60; retries can extend total operation time |
| `CP_LLM_MAX_RETRIES` | Additional HTTP attempts, default 1, maximum 5 |
| `CP_LLM_RETRY_BACKOFF_SECONDS` | Initial exponential backoff, default 0.5; delays capped at 30 seconds |
| `CP_LLM_STREAM` | Internal OpenAI-compatible streaming, default false; local workspace configuration enables it |
| `CP_LLM_TEMPERATURE`, `CP_LLM_TOP_P`, `CP_LLM_SEED` | Optional explicit sampling; empty leaves server defaults |
| `CP_LLM_MAX_OUTPUT_TOKENS` | Default output reservation, 2048; care generation overrides to 4096, review to 2048 enriched / 1024 grounded |
| `CP_SERVING_METADATA` | Strict JSON object of declared serving identity metadata; scalar values only |
| `CP_SERVING_METRICS_URL` | Optional explicit chat metrics endpoint; known local backends default to server-root `/metrics` |
| `CP_EMBEDDING_METRICS_URL` | Optional separate embedding metrics endpoint |
| `CP_HOST_METRICS_URL` | Optional Prometheus host/GPU exporter on the serving machine |

`CP_SERVING_METADATA` accepts `model_revision`, `weights_identity`, `quantization`, `tokenizer`, `chat_template`, `context_limit_tokens`, `server_version`, `parallelism`, `cache_policy`, `hardware`, `collector_location`, optional embedding metadata and context-limit aliases `n_ctx`/`max_model_len`. Actual `CP_EMBEDDING_*` configuration takes precedence for embedding identity. This is declared metadata; `/capabilities` is a separate observed probe. Update declared metadata when changing the server/model. In-process API keys, FHIR credentials and embedding credentials do not enter snapshots.

OpenAI-compatible endpoints support the streaming/sampling settings above. Anthropic and Ollama adapters retain available usage/native timings and explicit retries; unsupported streaming or seed options fail before sending rather than silently ignoring them. Embedding traffic remains owned by IRIS, with retrieval spans recording its application cost.

## LLM trace records

The existing request, submission and care-job trace APIs export correlated events. Logical stages are `interview.question`, `assessment`, `assessment.review`, `careplan.generation` and `careplan.review`.

- `llm.call.finished`: one logical call, including retries/backoff, stage, profile ID, effective budget, attempt count and final outcome.
- `llm.attempt.finished`: one HTTP attempt. Use these records for usage accounting across successful and failed requests. They retain unique attempt/call IDs, parent span, generation repair attempt, duration, HTTP status/error type, finish reason/truncation, returned model/response ID and available usage/native metrics. Missing usage stays null.
- `llm.retry.finished`: measured backoff between HTTP attempts. SDK hidden retries are disabled. Connection/timeouts and HTTP 408/409/429/5xx have bounded retries; stream failures after receiving a chunk are not retried.

Application repair attempts are separate from HTTP retries. JSON syntax/schema/clinical-scope rejection can trigger the existing single care-plan repair. All resulting generation/review calls stay in the operation trace. Truncated or incomplete streamed responses fail explicitly; a complete content string is assembled before application parsing and validation.

`careplan.context.prepared` records context status and a manifest of the exact selected source IDs, versions, text hashes and serialized model-source hashes before generation. It remains available when no final draft is accepted. Traces contain source identity/digests, not source or patient prose. The external runner retains this context status and source manifest for failed results too.

`first_streamed_content_seconds` measures application-clock time until the first nonempty content delta. It includes client/network overhead and may include earlier reasoning output. It is not native server TTFT. No token throughput is inferred from this value or API wall time.

When returned by the backend, native fields retain an origin and raw units: llama.cpp `timings` values include prompt/decode milliseconds, token/cache counts and backend rates; vLLM response `metrics` can include TTFT, queue/decode/ITL milliseconds and throughput. The vLLM response throughput definition includes prefill plus decode; it is not pure decoding speed. Absent native fields remain unknown. Server flags/version determine availability; the implementation does not restart servers or enable flags.

## Application timing and persistence

Nested spans cover the complete API operation through ASGI body emission, interview/assessment, FHIR helpers, retrieval, care-plan processing, parsing and validation. Durations use monotonic clocks; UTC timestamps permit correlation. Do not sum parent and child spans as independent costs. API timing ends at application response emission; client-observed latency is collected by [the external runner](../benchmarks/api_benchmark/README.md).

Jobs retain `enqueued_at`, per-attempt `queued_at`, `started_at`, `finished_at`, `queue_wait_seconds` and `processing_seconds`. Queue wait uses persisted UTC times and can include process downtime. An invalid/negative interval becomes unknown. Processing uses a monotonic clock and includes claim/model/validation/result persistence through the completion transition; the final telemetry flush is additional overhead. The worker remains serial and polls every 3 seconds. Trace export exposes `trace_ready` so the runner can wait for the final flush.

Saved-job/assessment/plan reuse emits an explicit event and skips new inference. Request traces retain the latest 1000 requests in process memory; job and submission traces are persisted in FHIR. A hard process crash can lose events not yet flushed, including in-flight attempt data; this is not a durable billing ledger.

## Backend and host collection

With the isolated benchmark API enabled:

| Endpoint | Result |
| --- | --- |
| `GET /benchmark/serving/capabilities` | Read-only model-list probe, advertised model/context/dimensions where present; unavailable/error fields otherwise |
| `GET /benchmark/serving/metrics` | Timestamped chat, embedding and host snapshots with collection duration, availability and metric definitions |

Prometheus samples retain original names, HELP/TYPE definitions and an allowlist of safe labels. Known suffix units are labeled; histogram bucket/count values are counts and bucket bounds have their own unit. Unknown units are not guessed. Nonfinite sample values are omitted. Server metrics are aggregates; they are never assigned to an individual request. External host/embedding exporters do not receive chat credentials.

Without an external host exporter, the collector reads its own visible `/proc` CPU/memory counters and optionally bounded `nvidia-smi` data. CPU utilization requires interval deltas, so a single snapshot reports cumulative ticks. GPU percentages and MiB retain raw units and also normalize to ratios/bytes. CPU, memory and GPU availability are separate. Container visibility is not proof of serving-host visibility: record collector location and use a serving-host exporter when needed.

The application collects metrics only when requested. The external runner polls during measured sessions using its own sampling thread, archives profiles/capabilities/snapshots and records sampling frequency/overhead. Snapshot endpoints are disabled unless `CP_BENCHMARK_API_ENABLED=true`; use the isolated benchmark Compose override. Offline Astra grading is outside the measured workload and requires explicit user approval before launch.

## Primary references

- [vLLM production metrics](https://docs.vllm.ai/en/latest/usage/metrics/)
- [vLLM per-request metrics](https://docs.vllm.ai/en/latest/features/per_request_metrics/)
- [llama.cpp server timings and metrics](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
