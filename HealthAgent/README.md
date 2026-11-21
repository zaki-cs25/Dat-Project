# ICMR Care Plans

A local college showcase with patient registration, an adaptive English interview, and read-only care-plan drafts for clinicians. InterSystems IRIS stores the FHIR R4 records and vector collections; FastAPI runs the interview and one durable generation worker; React provides the patient and clinician interfaces.

The LLM can use its own knowledge to propose recommendations. Retrieved ICMR passages enrich its context; recommendations are not restricted to those excerpts or automatically attributed to ICMR. The clinician panel groups sources under **Retrieved ICMR context**, without citation dropdowns or model provenance labels under individual activities. Provenance and source snapshots remain stored with each draft.

## Start the project

Use Python 3.12+, Node.js and Docker Compose. Keep the workspace's permanent `.venv` and existing `.env` when returning to the project. On a fresh checkout, create them and install development dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install -r src/python/requirements.txt
npm ci --prefix ui
# First setup only; do not overwrite an existing configured .env.
cp .env.example .env
```

Configure the chat and embedding endpoints in `.env` and start those services before the application. The current local setup uses chat on **8001**, BGE-M3 embeddings on **8081** with **1024 dimensions**, and the agent on **8002**:

```dotenv
CP_AGENT_PORT=8002
CP_LLM_PROVIDER=openai
CP_OPENAI_BASE_URL=http://host.docker.internal:8001/v1
CP_OPENAI_MODEL=unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q8_K_XL
CP_LLM_API_KEY=local-placeholder
CP_OPENAI_TOKEN_LIMIT_PARAM=max_tokens
CP_OPENAI_JSON_MODE=true
CP_OPENAI_CHAT_TEMPLATE_KWARGS={"enable_thinking":false}
CP_EMBEDDING_PROVIDER=openai_compatible
CP_EMBEDDING_BASE_URL=http://host.docker.internal:8081/v1
CP_EMBEDDING_MODEL=gpustack/bge-m3-GGUF:Q8_0
CP_EMBEDDING_API_KEY=local-placeholder
CP_EMBEDDING_DIMENSIONS=1024
CP_EMBEDDING_SEND_DIMENSIONS=false
CP_CARE_GENERATION_MODE=enriched
CP_CARE_CONTEXT_MAX_CHARS=24000
```

Use actual provider keys if your endpoints require authentication. `host.docker.internal` reaches services on the host from Docker. See [configuration](docs/CONFIGURATION.md) for other providers, BGE-M3 launch arguments, ports and reindexing.

```bash
docker compose up -d --build --wait --wait-timeout 300
```

| Service | Address in the current local setup |
| --- | --- |
| Clinician Care Plans | [http://localhost:8501](http://localhost:8501) |
| Patient registration and interview | [http://localhost:8501/intake](http://localhost:8501/intake) |
| Agent health | [http://localhost:8002/health](http://localhost:8002/health) |
| Agent API documentation | [http://localhost:8002/docs](http://localhost:8002/docs) |
| IRIS portal | [http://localhost:52773](http://localhost:52773) |

The template's agent port defaults to 8001; set `CP_AGENT_PORT=8002` when chat already occupies 8001. The UI reaches the agent through Docker, independently of this host-port setting. Run **one agent process/replica**: the worker and registration locking use that deployment contract.

## Use the application

1. Open **Patient intake**. The interview is in English.
2. Select **New patient**, enter full name, date of birth and gender (or prefer not to say), then click **Register and start interview**. Keep the assigned patient ID for later visits.
3. Returning patients select **Existing patient** and enter their saved ID. Seeded synthetic IDs are `demo-patient-1` through `demo-patient-7`; `synthetic-hypertension` is available for a separate routine hypertension demonstration.
4. Complete the interview. The completion screen shows the assessment's guidance while a FHIR Task queues the care-plan draft in the background.
5. Open **Care Plans**, select the completed interview, and inspect the draft, patient record, interview transcript and assessment. Pending jobs update automatically; failed or unqueued cases offer retry.

New patients receive an independent FHIR Patient record with no inherited demo diagnoses, medications, allergies or observations. Missing history remains unrecorded. A registration request retains its UUID across retries; the same request reuses the patient record, and changed details under the same UUID return a conflict. Separate registrations are not automatically deduplicated by name or birth date.

Draft activities cover monitoring, investigations, referrals, lifestyle, follow-up and generic medication review. The assessment's urgent instruction appears first and must not be delayed by routine activities. The generator does not establish new diagnoses, recommend specific drugs/classes/doses, or advise medication changes. Editing, approval and prescribing are outside this version. Routine care generation currently requires adult eligibility; registration and interview access do not establish that eligibility or a diagnosis.

## ICMR context library

Only the five user-supplied Markdown files in `md_care_documents/` are used for new care retrieval. PDFs and conversion tools are not part of the pipeline. The expandable workflow catalogue matches established FHIR conditions using approved names/aliases and verified codes; interview symptoms do not create diagnoses. Interview retrieval remains in its separate collection.

The local showcase has **512 active context passages** across the five files. Bulk approval includes non-rejected recommendation, supporting-context and uncertain candidates, with their original classifications and non-clinical approval metadata preserved. Explicit rejections and classifier exclusions remain out. One broad hypertension candidate remains blocked because it overlaps previously excluded material; approved complete cells remain indexed. See [document ingestion](docs/DOCUMENTS.md) for the source inventory, preparation, approval and versioning rules.

For an already prepared workspace, importing or refreshing the selected passages is:

```bash
docker compose exec -T agent python -m central_park.import_care_documents publish \
  --directory /app/md_care_documents
```

Publishing requires the configured embedding service. It does not happen automatically at startup. Repeat imports do not duplicate passages, and failed replacements retain the previous active document version. Source manuals and preparation artifacts stay outside Git and Docker build contexts; Docker mounts them read-only. Saved drafts retain frozen excerpts and are not regenerated when the library changes.

## Maintenance and verification

Inspect startup failures with `docker compose logs --tail=100 iris agent ui`. Apply application changes with `docker compose up -d --build --no-deps --wait agent ui`. Stop with `docker compose down` to retain the database volume; adding `-v` deletes it. Keep the IRIS login and FHIR credentials in `.env` matched. See [troubleshooting](docs/CONFIGURATION.md#troubleshooting) before changing authentication or data volumes.

```bash
PYTHONPATH=src/python .venv/bin/python -m pytest src/python/tests -q
npm run build --prefix ui
PYTHONPATH=src/python .venv/bin/python -m central_park.evaluate_careplans \
  --protocol --compare-context --output docs/evaluation-protocol.json
```

Verified on **2026-10-09**: **204 Python tests, 24 isolated IRIS integration tests, and the frontend production build passed**. The integration suite includes new registration through interview, assessment and persisted draft generation. Tests and model-review calls do not establish clinical accuracy. See the [evaluation report](docs/EVALUATION.md) for measured software behavior, live comparison results and unscored clinical measures.

## Documentation

- [Configuration and troubleshooting](docs/CONFIGURATION.md): chat, embeddings, local addresses, reindexing and startup.
- [Markdown ingestion](docs/DOCUMENTS.md): the five sources, preparation, bulk approval, exclusions and frozen versions.
- [API and persistence](docs/API.md): registration, interview and job contracts, errors and retries.
- [IRIS integration checks](docs/INTEGRATION.md): isolated database setup and reproducible tests.
- [Evaluation](docs/EVALUATION.md): current results and historical runs.
- [Project overview](docs/ARTICLE.md) and [demo walkthrough](docs/VIDEO_STORYBOARD.md).

This project uses synthetic data for a local college demonstration. The former analytics, copilot, Explore, standalone summary/lab, risk, care-gap and follow-up interfaces are removed. ICMR source notices still apply; conversion fidelity and clinical applicability have not been independently validated, and the corpus is not publicly redistributed.
