# Structured semantic review correction

Implemented 2026-10-25 after the uninterrupted run produced 90 completed plans and ten validation failures. This supersedes the earlier medication regex correction; the original run and grading artifacts remain historical results.

## Responsibility split

The application's existing reviewer uses the configured application LLM. It now owns interpretation of medication intent, coordinated negation, factual references versus treatment recommendations, patient-fact consistency, clinical timing and evidence applicability. Removing the regex veto does not automatically approve those statements: a draft must still pass semantic review.

Deterministic checks retain schema and required fields, exact source identifiers, provenance, application-owned urgent activities, supplemental-input hashes and input budgets. Adult eligibility remains deterministic. Benchmark score calculation and report accounting are unchanged.

The external benchmark judge is separate. It is optional for infrastructure measurements and generation-completion checks, but output-quality claims require evaluation against the rubric (an external judge or human review). Application approval alone is not independent quality evaluation. External judging was deferred for this fix and disabled in the development pilot.

## Changes

- Review JSON requires four checks: medication scope, patient facts, urgency and evidence applicability. Each rejection identifies a rule, an exact draft field, a verbatim excerpt from that field and an explanation. Code verifies evidence location and decision consistency, not the truth of the clinical interpretation.
- A malformed or unsupported review receives at most one contract-correction attempt on the same draft. A second invalid review fails closed. A valid semantic rejection permits the existing single generation repair. Reviewer text is never appended as unchecked plan content.
- Generation and review share an effective urgency: the higher of the assessment urgency and supplied clinician disposition. Both see the actual application-inserted urgent activities. Routine supplied disposition cannot reduce an urgent assessment.
- Models receive short citation labels such as S1. The application resolves them to exact stored IDs before persistence. Exact stored IDs remain accepted for compatibility; unknown IDs are rejected, never fuzzy-matched.
- Both review modes now have a 4096-token output budget, reflected in the serving profile. Review corrections are separately traced. New performance results must be measured under this profile rather than pooled with previous runs.

## Verification

- 95 targeted tests passed across `test_care_validation.py`, `test_careplan.py` and `test_enriched_careplan.py`. Tests cover evidence-backed rejection, inconsistent review decisions, fabricated quotations, bounded corrections, semantic routing, citation resolution and urgency floors. Mocked reviewer responses verify software contracts, not clinical model accuracy.
- 20 serving-observability tests passed. Additional profile/job/fixture checks produced 25 passed, one skipped and two failures in legacy fixture expectations (invented birth date and empty coding array). Those fixture tests and their implementation are byte-identical to the saved pre-fix source; they were not changed here.
- Luna monitored the real API pilot at `benchmarks/runs/20261025T132023Z-e85613c8/`: CHR-001 and CHR-006 both completed. Input, serving-profile and trace checks passed for both; protocol validity was true. No request/trace errors, ambiguous submissions, review rejections or repairs were recorded. The urgent case retained its application-owned urgent activity. Benchmark judge status was `not_run`.
- Pilot CSVs include `cases.csv`, `summary.csv`, `case_stage_metrics.csv` and `llm_attempts.csv`. Quality scores remain ungraded. Two development cases establish integration only; they do not establish a new 100-case completion rate or clinical quality.

Pre-change source is preserved in `benchmarks/runs/pre-semantic-review-source-20261025.zip` with a companion metadata JSON. Its source digest matches the fresh 100-case measurement source.

## Next validation

Run the unchanged 100-case dataset in enriched + ICMR mode under the new source/profile, with Luna monitoring and a fresh output directory. Benchmark judging can remain disabled while investigating completion failures. Evaluate quality separately before reporting quality improvements; retain both successes and failures in the denominator.
