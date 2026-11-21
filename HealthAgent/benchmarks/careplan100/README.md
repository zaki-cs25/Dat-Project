# CarePlan100 harness

Entrypoint: `python benchmarks/run_benchmark.py [run|grade|validate]` from the repository root. The root launcher imports `careplan100.cli`.

The data folder is expected at `benchmarks/careplan100/data/` and contains `cases/*.jsonl`, `rubrics/*.jsonl`, and `sources-*.json`. Validation checks the 100-case split, 50/30/20 cohort counts, four transcript turns, age/date constraints, criteria shape and source references, family split isolation, and the canonical combined dataset fingerprint in `data/manifest.json` when present.

Run artifacts are created as a new output directory. JSONL records are authoritative; CSV files are convenience views. A grade revision is an independent subdirectory and includes its own report manifest. Judge calls occur after measurement and have their own endpoint/model metadata; do not compare scores from differing judge configurations without accounting for that revision.

### Retry invalid judgments only

Use `grade --retry-invalid-from <run-dir>/grades/<revision> --run-dir <run-dir> --config <config>` to create a new grading revision. The runner verifies the original measurement and prior grade hashes, retains all valid grades (including failures), and retries only rows marked `ungraded`. Each retry receives its previous invalid response and validation error, with instructions to copy exact plan evidence. There is one new judge call per selected result (plus any explicitly configured transport retries); invalid responses remain ungraded. The new reports cover all results and record the parent revision, retained count and retried result IDs. Existing measurement and grade files are untouched. This is a correction pass, not repeated sampling until a case passes.
