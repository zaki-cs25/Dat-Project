# Care-plan demonstration

Before recording, start the configured chat endpoint (current local port 8001), the BGE-M3 embedding endpoint (8081, 1024 dimensions) and Docker Compose. Confirm the application is ready at `http://localhost:8501` and the approved Markdown library is indexed. Current agent access is port 8002. See [setup and configuration](../README.md).

1. Open `/intake` and select **New patient**. Enter an explicitly synthetic full name, an adult birth date and gender (or prefer not to say). Select **Register and start interview**.
2. Show the assigned patient ID and explain that it is used for returning visits. Complete the adaptive interview. New registration starts with no recorded diagnoses, medications, allergies or observations; it does not reuse a demo patient's history.
3. Show the assessment's final patient guidance. Explain that a separate care-plan Task runs in the background and does not add generated recommendations to the patient completion screen.
4. Open the clinician **Care Plans** worklist. Find the new patient by name and show the interview date, urgency and generation status. Pending work updates automatically; it may already be completed by this point.
5. Open the persisted draft. Show activity descriptions and proposed timing. For an urgent synthetic assessment, show its instruction first and explain that routine activities cannot delay it. The draft is read-only and offers no prescribing, editing or approval flow.
6. Expand a passage under **Retrieved ICMR context** to show publisher, document identity/version, Markdown filename, section, line references, excerpt and official link. Version may be recorded as unknown. Activity cards have no citation dropdowns or model provenance labels; provenance remains in stored metadata. Explain that the model can also use its own knowledge and the related passage is not proof of every recommendation.
7. Inspect the patient record, exact completed questionnaire and assessment tabs. Missing patient history is unrecorded information, not a confirmed absence of disease. Separately demonstrate **Existing patient** with a saved ID or `synthetic-hypertension`, which has an established condition for matching context.
8. Reopen the completed draft and show the same saved content. Do not expect older plans to change after UI or library updates; reopening does not regenerate them.

Optional technical segments:

- Use the [paired live evaluation](EVALUATION.md#reproduce-the-evaluation) to compare the same synthetic case with and without ICMR context. Do not describe a case with no matching passages as a generation failure in default enriched mode.
- Demonstrate failure and retry in the [isolated integration environment](INTEGRATION.md), without disrupting the running showcase's model services. Grounded mode can produce insufficient evidence; enriched mode also retains adult eligibility checks.
- Show restart recovery using the isolated worker tests, which resume unfinished Tasks and avoid repeating model generation for saved drafts.

Use synthetic records only. Clearly label scripted models and synthetic embeddings in test demonstrations. Report the current verified counts as dated results: **204 Python tests, 24 IRIS integration tests and a frontend build passed on 2026-10-09**. These results do not establish clinical accuracy. Do not publish the private document corpus as part of the video or repository.
