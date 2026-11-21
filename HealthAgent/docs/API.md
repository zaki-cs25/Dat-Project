# API and persistence

The UI calls same-origin `/api/*`, proxied to FastAPI, and `/fhir/*`, proxied to IRIS with server-side credentials. The API paths below omit `/api`. Direct access uses `http://localhost:<CP_AGENT_PORT>`; the current workspace uses **8002**, while `.env.example` defaults to 8001. FastAPI exposes the current OpenAPI schema at `/openapi.json` and interactive documentation at `/docs`.

## Patient registration

`POST /patients` accepts:

```json
{
  "registration_id": "15a4699b-d562-4f5b-b7b4-18fb15100cb3",
  "full_name": "Synthetic New Patient",
  "birth_date": "1980-04-01",
  "gender": "unknown"
}
```

Use a new UUID for each intended registration and retain it across network retries. Full name is trimmed and must contain 1–200 characters. Birth date must be valid and not in the future. Gender accepts `female`, `male`, `other` or `unknown`, and defaults to `unknown`. Extra fields are rejected; this endpoint does not accept conditions or clinical history.

A successful request returns HTTP 200:

```json
{
  "patient_id": "patient-15a4699bd5624f5bb7b418fb15100cb3",
  "full_name": "Synthetic New Patient"
}
```

The FHIR Patient uses a deterministic UUID-derived ID and a registration identifier. Full name is stored in `Patient.name.text` without guessing name components. Repeating identical registration details returns the same patient, including after a lost successful write response or service restart. Reusing that UUID with different saved demographics returns HTTP 409 with the existing patient ID; it does not overwrite them. Different registration UUIDs can create separate records for the same person; demographic matching and merging are outside this version. The browser retains the UUID during that setup session, not across a fresh page load.

Registration creates no Conditions, medications, allergies or observations. Its patient ID can immediately be used for interview requests. Existing patients do not need to register again.

## Interview

| Endpoint | Request | Result |
| --- | --- | --- |
| `POST /interview/next` | `patient_id`, `answers: [{link_id, question, answer}]`, optional `language` | `{done, question, stop_reason}` for the next adaptive step |
| `POST /interview` | `patient_id`, `questionnaire_response_id` | Persisted assessment handoff, plus optional care-plan job ID/status |

The UI first writes a completed FHIR `QuestionnaireResponse` with `subject.reference = Patient/{patient_id}`, question text, answers and authored time. `/interview` assesses it and persists an encounter, observations, assessment ServiceRequest and safety findings as applicable. The handoff retains the existing fields: `triage_level`, `chief_complaint`, `hpi`, `red_flags`, `recommended_actions`, `citations`, `detected_issues`, questionnaire, encounter, ServiceRequest, observation and DetectedIssue IDs. `service_request_id` is the assessment ID used by care-plan requests.

Symptom observations are written only for affirmed keyword mentions in interview answers. The bounded English rules evaluate each answer independently, preserve denials across comma/and/or symptom lists, recognize local postfix absence, and distinguish a new affirmative clause after a denial. Explicit historical, uncertain and other-person mentions are omitted from positive booleans; their original wording remains in the questionnaire. Omitted observations do not establish absence. This heuristic is not a complete clinical language parser and does not resolve contradictory answers.

After assessment, `/interview` queues generation and adds `care_plan_job_id` and `care_plan_status`. Enqueue failures do not fail the completed assessment or patient guidance. The worklist exposes the unqueued case for explicit retry. Assessment failure itself is not a completed interview handoff.

## Care-plan jobs

| Endpoint | Behavior |
| --- | --- |
| `POST /careplan` | Accept `patient_id`, `questionnaire_response_id`, `assessment_id`; validate linkage and idempotently enqueue |
| `GET /careplans?offset=0&limit=25` | Paginated worklist with patient name, interview date, urgency and generation status; limit 1–100 |
| `GET /careplans/{job_id}` | Persisted status, reason, structured draft and supporting patient/questionnaire/assessment context |
| `POST /careplans/{job_id}/retry` | Queue a failed or insufficient-evidence attempt, or enqueue an unqueued completed assessment |

The queue request is:

```json
{
  "patient_id": "patient-15a4699bd5624f5bb7b418fb15100cb3",
  "questionnaire_response_id": "YOUR_QUESTIONNAIRE_ID",
  "assessment_id": "YOUR_SERVICE_REQUEST_ID"
}
```

The questionnaire must be completed, both resources must belong to this patient, and the assessment must reference that exact questionnaire. Submissions with the same patient/questionnaire reuse the deterministic `cp-...` job and CarePlan ID. Retrying a completed job returns its current status; it does not regenerate a saved draft. Retry failed jobs after resolving the reported provider, FHIR, validation or indexing problem.

| Application status | Meaning |
| --- | --- |
| `queued` / `running` | Waiting for or executing background generation |
| `completed` | A validated generation result is persisted |
| `failed` | Generation or persistence failed; an urgent assessment-only draft may still exist |
| `insufficient-evidence` | Grounded mode lacks applicable evidence, or adult eligibility for routine generation is not established |
| `unqueued` | A completed questionnaire has an assessment but generation was not queued |
| `assessment-missing` | A saved questionnaire has no associated assessment; reassessment is required |
| `legacy-draft` | A pre-existing unattributed plan remains readable |

In default `enriched` mode, lack of ICMR context does not itself fail generation. Draft `context_status` is `available`, `no-matching-passages`, `unavailable` or `disabled`; the last is used in evaluation comparisons. FHIR context failures remain errors. Routine generation currently applies to adults; registering a child does not enable adult care recommendations.

## Saved drafts and sources

The structured result contains title, activities, missing information, uncovered conditions and review notes, plus mode, context status and enabled flag. Each activity records category, description, optional timing, provenance and source IDs. Routine enriched activities are `model` or `context-informed`; clarifications use `missing-information`; urgent instructions are application-owned `assessment` activities. Grounded and older drafts can retain `icmr` provenance. Citation identifiers must resolve to the actual supplied passages.

`evidence_sources` holds referenced passage snapshots. `related_icmr_context` holds all supplied enriched context, even when uncited. Snapshots include document identity/version, source filename, section, line and optional character references, exact excerpt, applicability, exceptions, publisher and official link. Source versions can legitimately be `unknown`; Markdown citations do not invent PDF page numbers. Bulk-approved passages retain their context-only and unvalidated status.

The clinician panel hides per-activity citations and model attribution labels. **Retrieved ICMR context** displays the deduplicated union of these saved source lists, including sources attached to older drafts. Removing a UI label does not change the stored provenance.

FHIR Task stores durable queue state. Newly generated CarePlans are always `status=draft`, `intent=proposal`, with activities `not-started`. They link the patient, completed questionnaire, assessment, encounter and matched established conditions when present. The application extension `https://centralpark.example/fhir/StructureDefinition/care-plan-data` stores structured output, source snapshots, mode, model identifier, generation timestamp and attempt metadata. Historical resources are retained without rewriting their original fields.

One worker polls Tasks in the FastAPI process. On restart it resumes unfinished tasks and checks for a saved plan from the current attempt before repeating generation. Completed drafts reopen from FHIR without another model call. Generation and separate bounded review allow one repair; invalid model content is not saved. An urgent instruction can survive routine generation failure as an assessment-only draft.

## Internal care collection

Authenticated IRIS endpoints use the IRIS REST base URL, independently of FastAPI:

| Endpoint | Behavior |
| --- | --- |
| `POST /centralpark/care-guidelines/import` | Import the reviewed Markdown passage payload produced by the importer; index successfully before activating a replacement version |
| `POST /centralpark/care-guidelines/search` | Condition-scoped active/reviewed cosine search; up to five passages; only the five configured Markdown document identities |

Use the [document importer](DOCUMENTS.md) rather than composing raw import metadata manually. Interview guidelines use their own collection and are never a fallback for care context.

## Errors

Registration and care API validation return 422; registration conflicts return 409. Unknown patients/jobs and FHIR 404 responses map to 404. Other FHIR HTTP failures map to 502 and network failures to 503. Model generation runs asynchronously: its failures appear in job state and the clinician worklist rather than turning the completed patient handoff into an error.

## Benchmark submission API

`POST /interview/complete` accepts `submission_id` (UUID), `patient_id`, `transcript: [{link_id, question, answer}]`, optional `supplemental_clinical_context`, `care_options`, `correlation` and `enqueue_care_plan` (boolean, default `true`). The clinical packet has exactly the `clinical_input` structure in `benchmarks/custom/cases_*.json`: patient age/sex, established conditions, medicines, allergies, observations, narrative, explicit unknowns and request. Age/sex must agree with the FHIR patient.

The original packet is stored on the questionnaire, frozen with the job, and supplied to generation and review. The response includes `submission_id` and `clinical_input_sha256`. Retain the same UUID, transcript, packet and options across retries. Successful assessments are durably cached before enqueue, so a lost enqueue response can be retried without repeating assessment inference. Changed input/options return 409. Correlation changes are allowed. Busy or unfinished submissions return 409 for inspection; a process crash before saving the assessment is not an exactly-once inference guarantee.

For controlled benchmarks, `enqueue_care_plan=false` persists the questionnaire and assessment without queueing care generation. The response has `care_plan_job_id=null` and `care_plan_status="not-requested"`. Repeating the same submission reuses that assessment; changing the enqueue option under the same UUID returns 409. Use the returned questionnaire and assessment IDs with fresh `/careplan` generation UUIDs for paired runs. The default `true` behavior continues to enqueue after assessment.

`care_options` is `{mode: "enriched" | "grounded", use_icmr_context: boolean}`. Omitted mode resolves to the configured default and is frozen. `correlation` accepts optional `run_id`, `case_id`, `task_id`, `turn_id` strings. Every response includes a generated `X-Request-ID`. Interview stop reasons are `model_complete` or `max_questions`. Provider/parse errors return HTTP 503/502; the UI preserves answers and offers Retry.

`POST /careplan` also accepts `care_options`, `supplemental_clinical_context`, `correlation`, and optional `generation_id` UUID. A fresh generation UUID creates a new measured job from the same questionnaire and assessment, permitting paired ICMR-on/off runs with identical assessment input. Retain the generation UUID across retries. Existing jobs reject changed options/packets. Without a generation UUID the existing one-job-per-questionnaire behavior applies. Fetch explicit benchmark generation jobs by their returned ID; the clinician worklist is organized around questionnaires.

New jobs freeze complete FHIR context, context/packet hashes, effective options and model endpoint/name/chat settings. A worker rejects changed serving configuration. Restore that configuration to retry, or submit a fresh generation UUID for an intentional comparison. Older tasks without snapshots retain live-context behavior. `CP_MODEL_INPUT_MAX_CHARS` bounds the complete generation/review input, including the review draft. Oversized input and server context-window errors fail explicitly without patient-data truncation. This character bound is not an exact token count; the serving endpoint enforces total token capacity and each call reserves its output budget.

## Isolated fixture and trace APIs

These endpoints return 404 unless `CP_BENCHMARK_API_ENABLED=true`. Use [docker-compose.benchmark.yml](../docker-compose.benchmark.yml), which has a separate named IRIS volume and API port 8003. Enable fixture creation only against a synthetic database.

| Endpoint | Behavior |
| --- | --- |
| `POST /benchmark/fixtures` | `{fixture_id: UUID, clinical_input: complete packet}` → patient ID, packet hash, resource IDs |
| `GET /benchmark/submissions/{submission_id}/trace` | Persisted submission state, correlation and input hash |
| `GET /benchmark/careplans/{job_id}/trace` | Frozen hashes/options/model identity and generation/review boundary audit |
| `GET /benchmark/requests/{request_id}/trace` | Basic HTTP events; latest 1000 requests in this process, lost on restart |

Fixtures create only deterministic synthetic patient/resource IDs. Explicit established diagnoses become Conditions; patient-reported medicines become MedicationStatements with unknown status; positive reported allergies become AllergyIntolerances. Unknown/no-known statements remain in the packet. Observations retain relative dates as text; no timestamp is invented. Fixture age uses a pinned reference date. Same UUID and packet reuse resources, including after partial writes; conflicting packet or clinical content returns 409. No diagnoses are inferred from symptoms.

Boundary audits verify the full packet at generation/review and export payload digests without raw prompts. Audit events and logical LLM calls share their generation/review parent span; each HTTP attempt links to its logical call. This permits the runner to verify which packet audit belongs to each model call. Per-call token usage, available native serving timings and host collectors are implemented in [serving observability](SERVING_BENCHMARK.md). See [the external runner](../benchmarks/api_benchmark/README.md) for workload and offline grading commands.

## Serving observability APIs

With `CP_BENCHMARK_API_ENABLED=true`, `GET /benchmark/serving/profile` returns the effective secret-free profile and hash; `/benchmark/serving/capabilities` probes the configured model list; `/benchmark/serving/metrics` collects chat, embedding and host snapshots. Capabilities and metrics use read-only requests and perform no inference. See [the measurement contract](SERVING_BENCHMARK.md) for configuration, origins, units, unknowns and limitations.

Request/job/submission traces now include nested application spans and per-HTTP-attempt LLM events. Use `llm.attempt.finished` for token accounting, `llm.call.finished` for logical latency including retries, and `llm.retry.finished` for backoff. Care repairs are identified separately by `generation_attempt`. Count each usage record once; parent/child spans overlap. Job trace export includes queue/start/finish times and `trace_ready`. Poll until that flag is true before archiving a completed job's final trace.

## CarePlan100 additions (2026-10-24)

Supplemental clinical packets may include `as_of_date` (ISO date) and `clinician_disposition` (`routine`, `urgent`, `emergency`). The latter is a supplied clinician instruction, not a benchmark triage label to predict; it can raise the care-planning urgency floor and cannot downgrade an existing urgent assessment.

Synthetic benchmark Patients now retain reported age and reference-date extensions without inventing an exact birth date. The same deterministic age facts reach assessment and care models. Existing recorded birth dates remain usable for real Patients. A model-facing assessment view corrects conflicting demographic age statements while retaining the original frozen FHIR context and recording upstream conflicts.

Accurate factual mention of supplied medication history is allowed. New drug/class/dose recommendations and medication start/stop/change instructions remain prohibited. Laboratory concentrations are not medication doses. The local field-aware guard is a bounded heuristic supplemented by model review, not a complete prescribing detector.

When the benchmark API is enabled, `/benchmark/careplans/{job_id}/trace` also returns `attempt_diagnostics` and `upstream_fact_conflicts`. Diagnostics can contain rejected candidate prose and raw synthetic model/reviewer output. They are excluded from ordinary job views and normal telemetry. Enable these routes only on the isolated local benchmark deployment.
