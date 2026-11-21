# Medication and provenance validation correction

Historical correction: the regex approach below has since been superseded by the [structured semantic review fix](BENCHMARK_SEMANTIC_REVIEW_FIX.md). Its recorded tests and replay results describe the earlier implementation.

Implemented 2026-10-25 after the recorded 100-case run and API judging.

## Application changes

- Check medication mentions per clause, allowing explicit current/prior history questions, allergy clarification, uncertain medication-risk review, negative treatment recommendations and medication questions in missing-information lists.
- Preserve checks against unrecorded use/allergy claims, unrecorded/misattributed doses and named treatment/regimen instructions, including instructions appended to a history question. Extend prescribing-target detection to antacid/alginate proposals and direct broad-class treatment instructions.
- Keep the independent semantic model reviewer. The deterministic checks have a finite vocabulary and bounded language rules; they are not complete clinical intent recognition.
- Explain the actual reserved field when a generated activity uses `assessment` provenance or the `urgent` category. The application retains ownership of these activities. No silent relabelling or automatic acceptance was added.
- Align generation and review prompts with those exceptions. Future judge version 1.2 clarifies that naming a drug in a history/allergy question is distinct from recommending it. Dataset cases, criteria, weights and pass threshold are unchanged.

## Verification

Command: `PYTHONPATH=src/python .venv/bin/python -m pytest -q src/python/tests/test_care_validation.py src/python/tests/test_careplan.py src/python/tests/test_enriched_careplan.py`.

Result: **167 passed**. Includes positive history/allergy examples, contradictory prescribing clauses, unrecorded patient claims, known-drug changes, dose transfer, laboratory concentrations, reserved provenance and the bounded repair pipeline. Model calls in these tests are mocked.

Offline replay artifacts: `benchmarks/runs/validation-fix-20261025/saved-draft-replay.csv` and `summary.json`. All 14 originally rejected drafts were checked. All six final medication-related candidates now pass the local medication check. CHR-022 also passes medication checks, but its original `assessment` provenance remains prohibited; the repair test separately verifies that accurate feedback can lead to an allowed routine model referral.

Three earlier candidates still fail medication checks: CHR-026 attempt 0 includes named avoidance advice; OPD-017 attempt 0 proposes antacid/alginate use; OPD-042 attempt 0 introduces hypothetical antibiotic therapy in a clarification rationale. The replay checks local medication scope only, not complete source applicability, factual consistency, semantic approval or clinical quality.

Original measurement and grading artifact hashes were verified unchanged. There were no new LLM calls and no new benchmark completion or quality score. A fresh run is required to measure the effect of the code changes. The normal benchmark script reloads the current application code on startup.
