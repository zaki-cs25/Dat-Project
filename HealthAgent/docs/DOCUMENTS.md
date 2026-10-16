# ICMR Markdown context library

Run the following commands from the project root. Preparation and classification are maintenance operations; an already prepared and indexed workspace does not need to repeat them to start the app.

The sole care-plan source library is the five user-supplied Markdown files in `md_care_documents/`. The [Markdown manifest](../src/python/central_park/data/icmr_markdown_manifest.json) records filenames, document identities, source format, publisher, official catalogue link and source notice. Publication dates and versions remain `unknown` unless verified; they are not inferred from filenames. The source checksum is calculated when preparing a review.

| File | Document ID | Active showcase passages (2026-10-08) |
| --- | --- | ---: |
| `stw_manual_v1_stw_i.md` | `icmr-md-volume-1` | 254 |
| `stw_v2.md` | `icmr-md-volume-2` | 19 |
| `stw_v3.md` | `icmr-md-volume-3` | 131 |
| `stw_v4.md` | `icmr-md-volume-4` | 103 |
| `hypertension.md` | `icmr-md-hypertension` | 5 |
| **Total** | | **512** |

These counts describe the local imported snapshot, not a fresh checkout or measured clinical/workflow coverage. Private `.preparation/` files are needed to reproduce that exact reviewed import; source Markdown alone needs preparation and classification first. The corpus is not bundled with the repository. Keep downloaded/copied manuals in the private directory; the importer never modifies them.

The former eight PDFs, their extracted local passages and their manifest have been removed. New imports accept only Markdown passages from the five configured sources, and every care search excludes the old library, including requests without a library parameter. Existing database rows are retained for historical citations, and saved patient records and plans are not deleted. Saved plans reopen using their persisted citation excerpts.

Git and Docker build contexts exclude the private Markdown directory. Docker mounts it read-only at `/app/md_care_documents`; preparation writes review files on the host. No corpus is included in an image or published to Git. The Markdown sources are never modified by the importer.

Workflow discovery now inventories all five manuals, including split, plain and bold STW banners and explicitly printed ICD-10 codes. ICD-11 notation is retained for mapping review without inventing a FHIR coding-system mapping. Ambiguous titles and missing codes are flagged. Source titles/codes are candidates, not new patient diagnoses. The care collection has no eight-condition limit. Runtime matching loads the baseline catalogue plus reviewed/enabled entries from `CP_CARE_CATALOGUE_PATH`: default `md_care_documents/.preparation/catalogue.json` on the host and `/app/md_care_documents/.preparation/catalogue.json` in Docker.

Preparation and classification do not activate new workflows. The original curation path reviews workflow boundaries, population, aliases/codes and selected recommendations individually. The user has also authorized a showcase bulk path: all non-rejected `include`, `supporting-context` and `needs-review` candidates become context-only passages, preserving their original classification and uncertainty. Explicit rejections and classifier exclusions remain excluded. Candidate FHIR codes are not silently approved; existing names/aliases can enable matching. Pediatric-only workflows remain labelled pediatric and are excluded from the adult generator's retrieval. Unknown population is retained as uncertain context, not relabelled adult. Complete tables, nested branches and footnotes must remain intact. Oversized sections without safe boundaries stay blocked and are reported.

For a new, unprepared source workspace, these host commands read the manuals; they never run automatically during application startup or synthetic tests. The classification step below expects existing agent decisions and does not invoke an agent itself. Do not reclassify the current approved workspace; preserve it and use an archived/new revision when preparing changed sources:

```bash
# Discover workflows and prepare unreviewed sections and bounded tasks.
PYTHONPATH=src/python .venv/bin/python -m central_park.import_care_documents prepare
PYTHONPATH=src/python .venv/bin/python -m central_park.import_care_documents catalogue
# Apply the private GPT-6 Luna agent decisions without endpoint calls.
PYTHONPATH=src/python .venv/bin/python -m central_park.import_care_documents classify \
  --decisions-dir md_care_documents/.preparation/agent-decisions
PYTHONPATH=src/python .venv/bin/python -m central_park.import_care_documents report
# Review .preparation/review-summary.md, catalogue.json, boundary-notes/ and reviews/.
# Approval, validation and publication are separate steps below.
```

When agent-produced decisions are unavailable, replace the `classify --decisions-dir` step with an explicit bounded call to the configured chat provider on the unreviewed workspace:

```bash
PYTHONPATH=src/python .venv/bin/python -m central_park.import_care_documents classify \
  --use-llm --limit 20
```

Repeat bounded classification to resume checkpointed work. Then generate the report and choose individual curation or the authorized showcase bulk policy before validation/publication. Do not rerun classification against already approved artifacts.

To reproduce the authorized bulk context approval after classification:

```bash
PYTHONPATH=src/python .venv/bin/python -m central_park.bulk_approve_care \
  --directory md_care_documents --actor user
PYTHONPATH=src/python .venv/bin/python -m central_park.import_care_documents validate
docker compose exec -T agent python -m central_park.import_care_documents publish \
  --directory /app/md_care_documents
```

The private `.preparation/bulk-approval-report.json` records approvals, preserved rejections, blocked selections and an archive of prior artifacts. The current import contains **512 context passages across all five files**. One broad hypertension candidate overlapping previously rejected lines remains blocked; the separately approved complete cells are retained. Repeating approval/import preserves document versions and does not duplicate passages. This bulk policy does not modify the source manuals or overwrite saved plans.

Individual source-curation requirements (distinct from bulk context approval and independent clinical validation):

- Workflow: verify boundaries and condition tag; record adult/mixed population, reviewed=true, reviewer and reviewed_at.
- Catalogue entry: verify aliases/codes (candidate_* fields are suggestions); record reviewed/enabled=true, population, reviewer and reviewed_at. No missing codes or code-family mappings are invented.
- Recommendation: select only decision=include with an allowed category, include/reviewed=true, applicability and exceptions. Preserve exact source text and explicitly selected context_spans; record document review metadata too.

Mixed tables can be curated by selecting a complete cell after explicit review. Keep the full cited line in the private passage's `original_text`; set `char_start` and `char_end` as zero-based Unicode character offsets with an exclusive end, and record `selection_review` (`reviewed=true`, `reviewer`, `reviewed_at`, `unit_type="complete-table-cell"`, and `rationale`). The importer verifies the original line and the entire selected cell, including its branches and exceptions. A partial bullet, cross-cell selection or rewritten excerpt is rejected. `text` must equal the exact selected substring followed by selected context spans joined with two newlines. Supporting context can use the same reviewed cell format. Classification does not automatically create these selections.

Published cell evidence contains only the selected excerpt, its line/character coordinates, review metadata and a checksum of the full audit line. The mixed full line stays in the private review file; excluded neighboring cells do not enter vectors, model inputs or saved citations. The clinician view displays character positions starting at one. User approval records source curation for this demonstration; it is not represented as independent clinical validation.

The IRIS REST dispatcher decodes JSON requests as UTF-8, preserving symbols such as `≥`, `²`, and non-English text. Index format version 2 creates a new immutable review revision when republishing previously misdecoded evidence. It preserves the unchanged source checksum, existing document versions and frozen citations in saved plans.

Classification alone leaves selections unselected/unreviewed. Individual curation embeds accepted recommendations; the authorized bulk path additionally embeds supporting and uncertain candidates as explicitly unvalidated context. Excluded and rejected material is never embedded. Exact duplicate qualified recommendations are consolidated with alternative source references; differing exceptions are retained. Candidate parent context and classifier diagnostics never enter searchable evidence. The clinician view displays workflow identity and main/supporting source lines. Existing saved plans retain frozen citation excerpts.

Version-2 artifacts live in `.preparation/`; older `.reviews/` artifacts are preserved. Preparation preserves existing revisions. Use a new `--workspace` or archive unreviewed preparation when refining boundaries/changing sources. The source files are never modified. No corpus or preparation artifacts enter Git or Docker images.

Optional future classification through your configured chat endpoint requires explicit `--use-llm`. Calls are bounded (default `--limit 20` per invocation), cached by exact source/context, prompt and model/endpoint identity, and checkpointed. Repeat to resume. Malformed responses remain unresolved; `--retry-errors` explicitly retries failed tasks after their issue is resolved. `--classification-model` overrides the chat model only for this offline task. This option is separate from the GPT-6 Luna agents used to prepare this workspace. No endpoint calls happen during preparation or synthetic tests; no manual is sent in a single request.

The importer validates the entire selected library before publishing. Publishing requires functioning configured embeddings and credentials only if that endpoint requires them. Only reviewed passages with enabled mappings are accepted. Immutable passage IDs and document versions are preserved; a replacement is activated only after indexing succeeds. Interview searches remain in their separate collection, with no silent fallback.

Source advisory/copyright notices still apply. The user-supplied conversion is not independently verified against the original publication. Educational purpose is not blanket reuse permission, and this project does not redistribute the ICMR corpus publicly.

The current [clinician view](API.md#saved-drafts-and-sources) consolidates all supplied source snapshots under **Retrieved ICMR context**; it does not place citations under activity cards. Stored excerpts and original classification/approval metadata remain available there. A source's presence supplies context and is not independent clinical support for every model recommendation. See [evaluation](EVALUATION.md) for measured counts and unscored relevance/applicability.

