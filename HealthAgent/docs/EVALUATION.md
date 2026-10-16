# Evaluation status

Last software verification: **2026-10-09**. The project is a synthetic local showcase with enriched generation, optional ICMR context, new-patient registration and read-only clinician drafts. Software safeguards, retrieval/citation counts and clinical accuracy are separate measures.

## Software checks

| Check | Verified result |
| --- | --- |
| Python suite | **204 passed** |
| Isolated Docker/IRIS integration suite | **24 passed** |
| Frontend TypeScript/Vite production build | Passed |
| Deployed intake and registration route | UI bundle and API proxy verified |

The newest integration case registers a synthetic patient twice with one UUID and confirms one saved FHIR record, Unicode full-name handling and no inherited conditions, medications, allergies or observations. It asks an adaptive question, completes assessment, waits for automatic enriched draft generation, and verifies the clinician worklist uses the new patient's name. Registration unit checks also cover lost successful write responses, changed-details conflicts, invalid/future birth dates and FHIR failures. These checks use a scripted model and do not add clinical accuracy evidence.

Other checks cover interview contracts and safety floors, FHIR linkage/failure handling, mode/provenance/citation validation, bounded review and repair, context budgets, no-evidence and retrieval-outage behavior, bulk approval guards, Unicode source references, version activation and rollback, idempotent imports, persistence, restart recovery and retry. Integration tests use a separate IRIS database, artificial evidence and synthetic embeddings. They do not mount the application's patient database or read the private manuals. See [reproduction instructions](INTEGRATION.md).

## Imported context coverage

The sole library is five user-supplied Markdown files described by the [manifest](../src/python/central_park/data/icmr_markdown_manifest.json). The user authorized bulk context approval of non-rejected candidates on 2026-10-08. Source files were not modified; their conversion fidelity and clinical applicability have not been independently validated.

| Document | Active passages verified on 2026-10-08 |
| --- | ---: |
| `stw_manual_v1_stw_i.md` | 254 |
| `stw_v2.md` | 19 |
| `stw_v3.md` | 131 |
| `stw_v4.md` | 103 |
| `hypertension.md` | 5 |
| **Total** | **512** |

Bulk processing preserved **388 classifier exclusions and 11 explicit passage rejections**, added seven safely split parts, and left one broad hypertension candidate blocked because it overlaps excluded material. Separately approved complete cells were retained. Original classification, population uncertainty and context-only approval remain stored; 137 unverified candidate code entries were not silently promoted to verified mappings. The private report is `md_care_documents/.preparation/bulk-approval-report.json`.

The first import failed because BGE-M3 rejected a 612-token input against a 512-token physical batch limit. Increasing the same server's batch and physical batch limits to 8192 resolved the error while retaining its 1024 output dimensions and complete passages. Repeat publish returned identical document versions; direct IRIS checks confirmed 512 active rows, zero invalid context-only approval labels, and 518 total current/historical rows before and after the second import. The six older hypertension rows remain for historical citations. These are indexing measurements, not evidence that every workflow or patient condition has relevant recommendations.

## Generation and UI behavior

Default `enriched` mode allows model knowledge even without applicable passages. Stored activities distinguish `model` and `context-informed` provenance; valid related source IDs do not prove clinical support. The UI hides per-activity citation dropdowns and model attribution labels and groups all supplied sources under **Retrieved ICMR context**. Persistence retains these sources, versions, model and generation time. Older saved drafts remain unchanged.

New diagnoses, specific drugs/classes/doses, medication changes, invented patient facts and fabricated citations remain outside the intended scope. A separate bounded reviewer call and deterministic guards check the output with one repair attempt. They cannot guarantee every unsafe or inaccurate statement will be detected. Adult eligibility remains required for routine generation. Urgent instructions come from the persisted interview assessment and appear first, even when routine generation fails.

## Scripted evaluation

The [19-case synthetic fixture](../src/python/tests/fixtures/care-evaluation.json) includes each original baseline condition, two multimorbidity combinations, missing observations, urgent/emergency cases without evidence, unsupported conditions, FHIR failure, malformed output, fabricated citation, prohibited prescribing and conflicting recommendations. It is a regression set, not an exhaustive evaluation of the expanded manual catalogue.

The current [protocol report](evaluation-protocol.json) runs each case with context enabled and disabled using a scripted provider:

| Measure | Result |
| --- | --- |
| Paired runs | 38 |
| Completed results | 28 |
| Deliberately failed results | 10 |
| Insufficient-evidence results in enriched protocol | 0 |
| Fabricated citation IDs accepted | 0 |
| Injected prohibited prescribing accepted | 0 |
| Urgent/emergency assessment instructions | Retained in both context settings |
| Clinical recommendation support/accuracy | Unscored |

The ten failures exercise the five injected error cases in both settings. Enriched generation does not treat missing ICMR passages as a reason to suppress otherwise valid adult suggestions. The report's `evidence_coverage` field counts referenced condition sources; `retrieved_context_count` and `retrieved_context_conditions` describe supplied context. None measures whether a recommendation is medically appropriate or truly supported by a source.

## Limited live model checks

The configured model for these runs was `unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q8_K_XL` through the user's compatible endpoint, with BGE-M3 embeddings.

A live interview-to-draft check on 2026-10-08 used `synthetic-hypertension`, QuestionnaireResponse `125` and job `cp-dc8653b0b47c085db077143c60233d91f0eee902`. Assessment was `see-gp`. The saved draft contained five activities (one model-generated and four context-informed), five supplied passages and three referenced passages. FHIR status was `draft`, activities were `not-started`, reopening returned identical content and repeated enqueue returned the same job.

A separate paired generation comparison used the same synthetic hypertension fixture with retrieval enabled and disabled:

| Measure | Context enabled | Context disabled |
| --- | ---: | ---: |
| Completed | Yes | Yes |
| Supplied passages | 5 | 0 |
| Model-generated activities | 2 | 6 |
| Context-informed activities | 3 | 0 |
| Fabricated citation IDs accepted | 0 | 0 |
| Deterministically prohibited content accepted | 0 | 0 |

The private report is `md_care_documents/.preparation/evaluation-live-enriched-comparison.json`. These runs verify live protocol behavior and frozen context; they do not establish that either plan is clinically correct or better. Earlier grounded tests exposed age, conditional-timing, historical symptom provenance and Unicode problems despite passing model review. Their fixes and original results remain in the [grounded evaluation history](history/GROUNDED_EVALUATION.md); those saved drafts were not overwritten.

## Reproduce the evaluation

Run from the project root with the permanent `.venv`. Protocol runs require no live providers:

```bash
PYTHONPATH=src/python .venv/bin/python -m central_park.evaluate_careplans \
  --protocol --compare-context --output docs/evaluation-protocol.json
```

For a bounded live comparison, start the chat/embedding services, publish the prepared library and export the [host-side configuration](CONFIGURATION.md#service-addresses-and-credentials). Python does not automatically load `.env`. Then run:

```bash
PYTHONPATH=src/python .venv/bin/python -m central_park.evaluate_careplans \
  --live --compare-context --case-id hypertension \
  --output md_care_documents/.preparation/evaluation-live-enriched-comparison.json
```

Omitting `--case-id` runs the full fixture set; fault injection remains a protocol-mode check. Add `--generation-mode grounded` for source-constrained comparisons, which exclude the bulk context-only passages. The evaluator passes synthetic fixture contexts directly to generation; it does not register patients or execute the full interview. The integration suite separately verifies FHIR registration, assessment, queueing and persistence.

The full live-model evaluation across the expanded five-manual catalogue has not run. Score condition context coverage, recommendation applicability, unmet prerequisites/exceptions, proposed timing, invented patient facts, prohibited drugs/doses/new diagnoses, multimorbidity conflicts, urgent instruction retention and failure behavior separately. Record the model, reviewer, source versions, test date and individual judgments. Missing citations in enriched mode do not by themselves make a model recommendation inappropriate. Clinical accuracy and unsupported-recommendation rates remain unscored until independent review.
