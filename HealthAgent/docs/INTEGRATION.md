# Isolated IRIS integration checks

These tests use synthetic cosine vectors, a local embedding HTTP fixture and a scripted model to exercise real IRIS tables, REST routes and FHIR persistence. They do not measure embedding relevance or clinical accuracy. They do not mount the application's existing patient-data volume.

Build this project's IRIS image as `icmr-care-iris:integration` first. Alternatively, override `CP_TEST_IRIS_IMAGE` with an IRIS for Health image containing the `CENTRALPARK` namespace. The integration overlay starts `/iris-main` directly in `/home/irisowner` to avoid an incompatible image-specific database initialization wrapper. Test ObjectScript code and the private Markdown manuals are excluded from Docker build contexts.

```bash
docker build -t icmr-care-iris:integration .
docker compose -p icmr-eval -f docker-compose.integration.yml up -d
# Wait until the IRIS container is healthy.
docker compose -p icmr-eval -f docker-compose.integration.yml exec -T iris \
  iris session IRIS -U CENTRALPARK < tests/integration/setup.script
CP_RUN_IRIS_TESTS=1 PYTHONPATH=src/python .venv/bin/python -m pytest tests/integration -q
# Stop without deleting any application's data.
docker compose -p icmr-eval -f docker-compose.integration.yml stop
```

The setup compiles the application classes and the integration-only `CareTest.Embedding`. It configures that synthetic embedding class only inside the isolated database, creates a separate `/care-test/fhir/r4` endpoint, and creates a dedicated synthetic test account without changing existing users. Both REST applications use password authentication. Artificial evidence is explicitly labelled synthetic. A failure text triggers an intentional embedding error to verify that a failed replacement does not switch active versions.

Checks use synthetic Markdown passages under the five configured document identities. They cover rejection of former PDF imports and invalid Markdown references, exclusion of archived PDF evidence even when search omits a library, idempotent reviewed imports, rollback/activation, imports beyond the original eight names with invalid-tag rejection, condition isolation, original interview collection isolation, completed interview → automatic durable Task → cited FHIR draft, urgent instruction ordering, repeated submissions, saved-plan reopening, service lifespan restart after a partial Task write, insufficient-evidence drafts and explicit retry. The Python unit suite additionally injects FHIR/network failures, cross-patient references, malformed/rejected model responses and partial CarePlan writes. These tests never read the private Markdown manuals.

The Unicode import check verifies exact round trips for document titles, source text, applicability and exceptions containing `≥`, `²`, bullets, an em dash and Hindi text. It repeats the same import to verify immutable IDs remain idempotent after UTF-8 decoding.

The showcase checks verify bulk context imports preserve the non-clinical approval label and reject excluded candidates. Enriched drafts persist model-generated activities and uncited retrieved context; reopening reads the frozen draft without another model call. New-patient coverage registers a synthetic patient twice with one UUID, confirms one FHIR record with no inherited clinical history, asks an adaptive question, submits the interview and verifies the automatic persisted draft and clinician worklist name. These use synthetic passages and do not validate the bulk corpus clinically.

The latest run on 2026-10-09 passed all **24 integration tests**, alongside **204 Python unit tests** and the frontend production build.

The additional embedding checks use the integration-only `embedding-fixture` service on localhost port 52775. IRIS calls it over the isolated Compose network. They exercise configurable endpoint paths, model names, separate keys, 384/768 dimensions, native dimension validation, equal-size model changes, reindexing unchanged passage IDs, legacy rows without fingerprints, key rotation, optional output-size requests, Ollama's API, invalid configuration and malformed/zero/wrong-size responses. A model-change failure also verifies that an urgent instruction can still be saved as a FHIR draft while the Task records the reindexing reason. Configuration snapshots are restored after each embedding test.

For a real-provider run, use the normal Docker Compose stack, configure the embedding/chat provider, publish the reviewed local corpus and execute the live evaluation from README.md. Never install `CareTest.Embedding` in that stack.
