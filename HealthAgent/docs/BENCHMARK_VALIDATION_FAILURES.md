> Historical V1 record: the old benchmark artifacts were cleared on 2026-10-24 at the user's request. Summary evidence is preserved in `docs/history/benchmark-v1-summary-20261024.zip`. The active benchmark is CarePlan100.

# Full-run validation failure analysis

Run: `full-enriched-02`. Read-only post-run diagnosis; no measurement or clinical logic changes.

Each case generated a draft, received one repair opportunity, and was blocked again by a local guard or the application LLM reviewer. The API persisted a generic reason; server exception logs retain the final blocker. Astra graded only accepted outputs and did not cause these failures.

## Final blockers

| Blocker | Count | Cases |
| --- | ---: | --- |
| age-review-rejection | 6 | AST-02, HTN-01, HTN-02, HTN-03, T2D-01, T2D-03 |
| urgent-disposition-review-rejection | 2 | AST-03, T2D-06 |
| dose-guard | 5 | CKD-03, CKD-06, T2D-02, T2D-04, T2D-05 |
| citation-guard | 1 | CKD-04 |
| medication-content-review-rejection | 1 | CKD-05 |
| drug-name-or-class-guard | 2 | COPD-04, HTN-05 |

Eight cases involved medication-name/class/dose rules (five dose-guard, two drug-name guards, one reviewer). These prohibit even recorded medicine names/doses in notes and information requests. Dose matching scans all prose and is not restricted to prescribing context. Without rejected drafts, the exact matches and whether each was a clinically inappropriate recommendation cannot be established.

## Age findings

The six age-rejected cases all have incorrect ages in the frozen upstream assessment HPI. Snapshots were fetched after the run; their canonical context hashes match the measured frozen hashes.

| Case | Original packet age | Assessment HPI age |
| --- | ---: | ---: |
| AST-02 | 41 | 38 |
| HTN-01 | 52 | 50 |
| HTN-02 | 46 | 43 |
| HTN-03 | 61 | 58 |
| T2D-01 | 54 | 51 |
| T2D-03 | 50 | 48 |

The assessment path supplies a trimmed birth date without an explicit computed current age/as-of date. Care generation/review receives explicit age and as-of date plus the conflicting assessment. Care repair regenerates the draft, not the saved upstream assessment. This permits an unchanged upstream error to keep triggering review.

The reviewer is also unreliable in these examples: HTN-01 treats age 50 as correct while packet/birthDate establish 52. HTN-02 claims birthDate 1980 implies 45 on 2026-10-15; the actual stored birthDate is 1980-10-15, which gives 46 and agrees with the packet. These are errors in the reported rejection reasons; rejected drafts are unavailable for a full independent adjudication.

## Exact terminal reasons

### AST-02

Review rejected: The assessment narrative states the patient is 38 years old, contradicting the patient record (age 41) and supplemental context.

Source log line: 826.

### AST-03

Review rejected: The draft recommends follow-up in 4-12 weeks, which contradicts the assessment's directive for urgent in-person clinical assessment today.

Source log line: 1293.

### CKD-03

Prohibited dose recommendation: remove medication doses from every output field, including notes and information requests, even if present in the record

Source log line: 3448.

### CKD-04

Unknown or missing evidence citation

Source log line: 4080.

### CKD-05

Review rejected: The review notes contain specific drug names (lisinopril) and doses (10 mEq) from the patient record, violating the restriction to refer to medicines generically in notes.; The review notes restate input facts (patient demographics, lab values, medication history) instead of focusing solely on unresolved uncertainties relevant to the draft.

Source log line: 4561.

### CKD-06

Prohibited dose recommendation: remove medication doses from every output field, including notes and information requests, even if present in the record

Source log line: 4966.

### COPD-04

Prohibited specific drug or class recommendation: remove drug and class names from every output field, including review_notes and missing_information, even if they describe recorded treatment; use generic current medication instead

Source log line: 6538.

### HTN-01

Review rejected: The draft review_notes explicitly contradict the patient record by stating the patient is 52, whereas the FHIR birth date and clinical input confirm age 50.

Source log line: 7574.

### HTN-02

Review rejected: Draft review notes contradict patient_facts by claiming a birth date of 1980 indicates age 46 on 2026-10-15, whereas the authoritative patient_facts and supplemental context state the age is 46 and the birth date in FHIR (1980) conflicts with this calculated age (which would be 45).

Source log line: 8017.

### HTN-03

Review rejected: Draft HPI states patient age as 58, contradicting patient_facts and supplemental context which specify age 61.

Source log line: 8458.

### HTN-05

Prohibited specific drug or class recommendation: remove drug and class names from every output field, including review_notes and missing_information, even if they describe recorded treatment; use generic current medication instead

Source log line: 9242.

### T2D-01

Review rejected: Draft states patient is 51 years old, but patient facts and context specify age 54.

Source log line: 10095.

### T2D-02

Prohibited dose recommendation: remove medication doses from every output field, including notes and information requests, even if present in the record

Source log line: 10698.

### T2D-03

Review rejected: Draft HPI incorrectly states patient is 48 years old, contradicting patient_facts and birthDate which confirm age is 50.

Source log line: 11262.

### T2D-04

Prohibited dose recommendation: remove medication doses from every output field, including notes and information requests, even if present in the record

Source log line: 11806.

### T2D-05

Prohibited dose recommendation: remove medication doses from every output field, including notes and information requests, even if present in the record

Source log line: 12237.

### T2D-06

Review rejected: Draft provides outpatient follow-up and monitoring advice, contradicting the context which mandates immediate emergency transfer and prohibits delaying for other care.; Draft suggests reviewing and adjusting diabetes medication, violating the prohibition against specific medication changes or recommendations.; Draft assumes a post-discharge scenario, ignoring the active acute emergency status where inpatient management is the only appropriate next step.

Source log line: 12704.

## Evidence and limits

- [Parsed errors, source hash and age snapshot findings](../benchmarks/api_benchmark/runs/full-enriched-02-validation-failures.json).
- [Saved application logs](../benchmarks/api_benchmark/runs/full-enriched-02-validation-logs.txt).

These are final blocking reasons, not an exhaustive adjudication of clinical quality. No benchmark outputs were replaced or rescored.
