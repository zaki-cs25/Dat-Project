# Model and service configuration

Settings are read from environment variables. Docker Compose reads the workspace `.env`; Python commands run directly on the host do not. Keep the existing `.env` when updating this workspace.

## Chat endpoints

Use any endpoint implementing OpenAI-style `POST /chat/completions` and returning text in `choices[0].message.content`. Configure the API root and exact model name provided by that service:

```dotenv
CP_LLM_PROVIDER=openai
CP_OPENAI_BASE_URL=http://host.docker.internal:9000/v1
CP_OPENAI_MODEL=Qwen3.6-27B
CP_LLM_API_KEY=local-placeholder
CP_OPENAI_TOKEN_LIMIT_PARAM=max_tokens
CP_OPENAI_JSON_MODE=true
```

`CP_LLM_API_KEY` overrides `OPENAI_API_KEY` for chat only. For an unauthenticated local server, use `local-placeholder`. The base URL is the API root, not the complete `/chat/completions` URL. Outside Docker, `OPENAI_BASE_URL` also works; `CP_OPENAI_BASE_URL` takes precedence. Set `CP_OPENAI_JSON_MODE=false` if the endpoint rejects `response_format`; prompts and application JSON/schema/citation validation remain in force. [Official OpenAI JSON-mode documentation](https://developers.openai.com/api/docs/guides/structured-outputs) explains that JSON mode alone does not guarantee schema conformance. `CP_OPENAI_TOKEN_LIMIT_PARAM` accepts `max_tokens` or `max_completion_tokens` (the default for the existing OpenAI configuration). Endpoint failures do not fall back to another provider.

Apply Docker environment changes with `docker compose up -d --build agent`. For a server running on the host, use a host address reachable from Docker; `localhost` inside the agent refers to its own container.

For llama.cpp models whose thinking consumes the output budget, set `CP_OPENAI_CHAT_TEMPLATE_KWARGS={"enable_thinking":false}`. This optional JSON object is sent only when configured; its keys depend on the endpoint's chat template. See the [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#post-v1chatcompletions-openai-compatible-chat-completions-api). Responses ending at the token limit are rejected explicitly, even when the partial content happens to parse as JSON.

For Anthropic chat, set `CP_LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY` and `CP_ANTHROPIC_MODEL`. For an installed Ollama chat model, set `CP_LLM_PROVIDER=ollama`, `CP_OLLAMA_BASE_URL` and `CP_OLLAMA_MODEL`. The bundled Ollama service is enabled with Compose's `ollama` profile, whose init service pulls `llama3.2:3b`; install any different selected model separately. Neither choice changes the independent embedding provider. See [.env.example](../.env.example) for the shipped defaults.

**Embeddings are required for retrieval; a reranker model is not required.** The custom chat URL/key is never passed to the embedding provider. No reranker API is called: retrieval uses condition-filtered cosine search, and the configured chat LLM performs the separate draft-review call.

Care generation itself can proceed without applicable passages in enriched mode. A retrieval outage is disclosed in the saved draft; failed FHIR requests still fail the job rather than being treated as an empty patient record.

```dotenv
CP_CARE_GENERATION_MODE=enriched
CP_CARE_CONTEXT_MAX_CHARS=24000
```

The context budget retains whole passages and shares space across matched conditions. `grounded` enables the earlier source-support requirement for comparison, using individually curated passages rather than the bulk context-only library. Both modes retain citation-ID validation, patient-fact and prescribing restrictions, urgent instructions and a separate model-review call with one repair attempt.

## Embedding model

Serve your model through an OpenAI-compatible embedding API and configure `.env`:

```dotenv
CP_EMBEDDING_PROVIDER=openai_compatible
CP_EMBEDDING_BASE_URL=http://your-embedding-server:8080/v1
CP_EMBEDDING_MODEL=your-embedding-model
CP_EMBEDDING_API_KEY=local-placeholder
CP_EMBEDDING_DIMENSIONS=768
CP_EMBEDDING_SEND_DIMENSIONS=false
CP_EMBEDDING_REVISION=
```

Use the model's actual output dimension. The endpoint must return a numeric float array in `data[0].embedding` with `index=0` for `POST /embeddings`. `CP_EMBEDDING_SEND_DIMENSIONS=true` adds the optional `dimensions` request field only for models/endpoints that support selecting output size. Vectors are never padded or truncated; wrong dimensions, non-numeric and zero vectors are rejected.

The current local chat endpoint is `http://host.docker.internal:9000/v1` with model ID `Qwen3.6-27B`. The embedding endpoint is `http://host.docker.internal:8081/v1` with model ID `gpustack/bge-m3-GGUF:Q8_0` and **1024 dimensions**. The `.env.example` values describe this setup. These `host.docker.internal` addresses are for containers to reach services on the host; host-run Python tools should use `http://localhost:9000/v1` and `http://localhost:8081/v1`.

Complete source passages also require sufficient input capacity. For the user's llama server, increasing context alone did not raise its physical batch limit; use:

```bash
llama serve -hf gpustack/bge-m3-GGUF:Q8_0 \
  --embedding --pooling mean --host 0.0.0.0 --port 8081 \
  -c 8192 --batch-size 8192 --ubatch-size 8192
```

For Ollama, use `CP_EMBEDDING_PROVIDER=ollama`, `CP_EMBEDDING_BASE_URL=http://ollama:11434`, the name of an installed embedding model, and its output size. The adapter calls `/api/embed` with truncation disabled. It does not install models. A server on the host must use an address reachable from the IRIS container, rather than `localhost` inside the container.

`CP_EMBEDDING_API_KEY` is independent of the chat key; when empty it falls back to `OPENAI_API_KEY` for OpenAI-compatible requests. Ollama does not use that fallback. With your own chat and embedding services, an OpenAI API key is unnecessary.

Apply settings and reindex after changing the provider, endpoint, model, dimensions or revision:

```bash
# Existing deployments: load the new ObjectScript classes once before this step.
# See the upgrade instructions below; preserve the existing data volume.
docker compose up -d --build iris agent
# Force a refresh even when Compose hasn't recreated the unchanged agent service.
docker compose restart agent
# Agent startup refreshes embedding configuration and reseeds interview guidelines.
# Import inside the agent so Compose supplies the configured URLs/credentials.
docker compose exec -T agent python -m central_park.import_care_documents publish \
  --directory /app/md_care_documents
```

Both evidence collections use the same model for documents and queries. Each stored vector records a fingerprint of its provider, endpoint, model, output size and revision. Search fails with a reindexing reason while active passages belong to another fingerprint. Republish unchanged reviewed care documents to replace their vectors atomically without changing passage IDs, source text or saved plan citations. Rotating an API key does not require reindexing. If model weights change under the same URL/name, bump `CP_EMBEDDING_REVISION` to trigger reindexing. Changing from a prior embedding model or vector length can leave existing indexed rows incompatible with the configured 1024-dimensional model; re-embed the care passages and reseed interview guidelines using the documented procedure before relying on retrieval. Configuration alone does not rewrite stored vectors.

The vector columns accept different lengths, with dimension checks in the shared embedding service and model isolation during search. Existing vector rows without a fingerprint also require reindexing. For an existing IRIS installation, compile the new classes without deleting data:

```bash
docker compose exec -T iris iris session IRIS -U CENTRALPARK <<'EOF'
do $system.OBJ.LoadDir("/home/irisowner/central-park/src/cls","ck",,1)
halt
EOF
```

## Service addresses and credentials

| Setting/service | Docker address in this workspace | Host address |
| --- | --- | --- |
| Chat API root | `http://host.docker.internal:9000/v1` | `http://localhost:9000/v1` |
| Embedding API root | `http://host.docker.internal:8081/v1` | `http://localhost:8081/v1` |
| Agent | `http://agent:8000` | `http://localhost:8002` with `CP_AGENT_PORT=8002` |
| FHIR | `http://iris:52773/csp/healthshare/centralpark/fhir/r4` | `http://localhost:52773/csp/healthshare/centralpark/fhir/r4` |
| IRIS care REST | `http://iris:52773/centralpark` | `http://localhost:52773/centralpark` |
| UI | `http://ui:80` | `http://localhost:8501` |

These are the current local values; `.env.example` defaults the agent to port 8001. Configure `CP_AGENT_PORT=8002` to keep the chat server's 8001 separate. The UI uses `/api/*` and `/fhir/*` proxies and does not expose IRIS credentials to the browser. Run one agent process/replica.

Keep `IRIS_USERNAME` / `IRIS_PASSWORD` matched to `CP_FHIR_USER` / `CP_FHIR_PASSWORD`. Startup applies the configured IRIS account and clears its forced-password-change flag, then waits for authenticated FHIR readiness. Default template credentials are only for the local demonstration.

Docker mounts `CP_CARE_DOCUMENT_DIR` (default `./md_care_documents`) read-only. The in-container catalogue path is `/app/md_care_documents/.preparation/catalogue.json`; host Python uses `md_care_documents/.preparation/catalogue.json`. Change `CP_CARE_CATALOGUE_PATH` accordingly when switching execution environments.

For host Python maintenance/evaluation, export the selected provider and credential settings yourself. Set FHIR and IRIS REST to the localhost addresses above, chat to `http://localhost:9000/v1`, embeddings to `http://localhost:8081/v1`, and the catalogue to its host path. Do not use Compose's `iris` hostname or `/app/...` paths from the host. Source preparation, validation and protocol evaluation do not require a live chat endpoint; `classify --use-llm` and `--live` evaluation do.

## Troubleshooting

| Symptom | Check or action |
| --- | --- |
| Agent cannot bind to port 8001 | Chat already uses that port in this workspace; set `CP_AGENT_PORT=8002` and recreate the agent/UI |
| FHIR appears to return 404 for valid resources | Check matching IRIS/FHIR credentials and startup logs; authentication or forced-password-change can masquerade as a missing endpoint |
| Patient ID not found | Use **New patient** to register, or **Existing patient** with the assigned ID; demo IDs use `demo-patient-*` |
| Registration conflict (409) | The same request UUID already saved different details; use **Existing patient** with the ID in the error rather than overwriting the record |
| BGE-M3 import returns HTTP 500 for a longer passage | Check physical batch capacity; this workspace required both `--batch-size 8192` and `--ubatch-size 8192` while retaining 1024 output dimensions |
| Wrong embedding dimensions or model-changed reason | Correct `CP_EMBEDDING_*`, apply configuration, refresh interview embeddings and republish care passages; do not pad or truncate vectors |
| Model output is truncated | Confirm token parameter support and template settings; the Gemma endpoint used `enable_thinking=false`; truncated JSON is rejected |
| Context is absent in a valid enriched draft | Check established conditions, enabled catalogue mappings, active sources and recorded retrieval notes; the model can still generate from its knowledge |
| Draft is failed/unqueued | Open the case's reason, fix the underlying provider/FHIR/indexing issue and select **Retry generation** |
| Saved plan still shows older recommendations | Expected: saved drafts are frozen and do not regenerate on reopen; a new completed interview creates a separate job |
| UI shows an older layout | Rebuild the UI and refresh the browser; Python source mounts do not rebuild frontend assets |

```bash
docker compose ps
docker compose logs --tail=100 iris agent ui
docker compose up -d --build --no-deps --wait agent ui
```

Use `docker compose down` to stop while retaining the database volume. Do not add `-v` when preserving patients, Tasks and saved plans. See [IRIS integration checks](INTEGRATION.md) for tests in a separate database, and [the API guide](API.md) for job states and retry behavior.


## Benchmark preparation

The workspace endpoints were checked with `GET /v1/models`: localhost:9000 advertises `Qwen3.6-27B` through vLLM with `max_model_len=200000`; localhost:8081 advertises `gpustack/bge-m3-GGUF:Q8_0` through llama.cpp with `n_embd=1024`. Model-list metadata is not a generation or embedding smoke test. Docker configuration uses `host.docker.internal` and Linux host-gateway mappings; the services must accept connections from the Docker bridge, not only bind the host loopback interface.

`CP_MODEL_INPUT_MAX_CHARS=120000` rejects oversized full generation/review messages without truncation. It is a character guard, not tokenization. The server separately enforces its token window, including 4096 reserved generation tokens and 2048 enriched-review (1024 grounded-review) tokens.

`CP_BENCHMARK_API_ENABLED=false` disables fixture and trace APIs by default. The isolated override enables them and uses a separate `central-park-benchmark-iris-data` volume:

```bash
docker compose -p cp-benchmark -f docker-compose.yml -f docker-compose.benchmark.yml up --build -d
```

The override uses API port 8003, FHIR port 52776 and UI port 8503. Its port replacement syntax requires Compose supporting `!override` (the installed version passes configuration validation). Step 5 started the isolated IRIS and agent services with Docker context `desktop-linux`; its UI is optional and was not started. Use `docker --context desktop-linux compose -p cp-benchmark -f docker-compose.yml -f docker-compose.benchmark.yml ...` for this deployment. Prepare the separate database's ICMR indexes with this embedding profile before measured ICMR-on runs; existing embeddings from another profile are not reused. The [pilot log](BENCHMARK_PILOT.md) records indexing, retained attempts and findings. Full serving profiles and collectors are implemented; see [serving observability](SERVING_BENCHMARK.md).

Step 3 adds `CP_LLM_BACKEND`, explicit timeout/retry/sampling/output/streaming settings, `CP_SERVING_METADATA`, and separate chat/embedding/host metrics URLs. The workspace identifies vLLM 0.28.0, enables internal streaming, and points collectors at the existing local servers. These are configuration-file changes; running containers have not been restarted. Native embedding metrics currently return HTTP 501. To measure serving-host GPU/CPU/RAM from the application container, configure a host exporter with `CP_HOST_METRICS_URL`; collector-local readings are labeled separately. Detailed settings and measurement definitions are in [SERVING_BENCHMARK.md](SERVING_BENCHMARK.md).
