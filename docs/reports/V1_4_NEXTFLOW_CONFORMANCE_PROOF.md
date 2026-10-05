# v1.4 WP-A/WP-B — Backend Conformance Suite + Nextflow: proof

Generated: 2026-10-05T14:38:28.600623+00:00

## Gate

The same capsule (`repro-pilot-01`, digest
`3cb31773760b30b793aa9738b38a102fbf4c4a1c0ec44d2614106b40eacc2dfc`) run via the PF native local runner,
the Snakemake backend and the Nextflow backend must produce identical
output hashes — pairwise `REPRODUCED_EXACT`. This run:
**REPRODUCED_EXACT** on all three pairs.

## Environment

- Python 3.13.5, Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Java 21.0.12.1
- Snakemake 9.27.0 (optional extra, not a core dependency)
- Nextflow 26.04.6 (binary launcher, deliberately NOT a
  pip extra — install: `curl -s https://get.nextflow.io -o nextflow`,
  then place the launcher on PATH, in PF's venv bin dir, or in
  `<repo>/tools/`; the backend probes exactly those locations, PATH first)

## Method

- Capsule: deterministic synthetic pilot `tests/fixtures/repro_pilot`,
  executed once per backend on separate copies (staged run directories for
  the external backends, outside the caller's capsule root).
- Interpreters/consoles: real local CPU only — no LLM, no HoH.
- Classification: `compare_executions` (WP6 differential).
- Conformance: `tests/conformance` (parametrized per backend), verdict
  matrix below.

## Output hashes (SHA-256)

| output (rel. to capsule root) | local runner | snakemake backend | nextflow backend |
|---|---|---|---|
| `summary.json` | `8f76c7d9d07d070ba3aa3fffa058a4d65212fc9a97915596587531ce1d4ec5b2` | `8f76c7d9d07d070ba3aa3fffa058a4d65212fc9a97915596587531ce1d4ec5b2` | `8f76c7d9d07d070ba3aa3fffa058a4d65212fc9a97915596587531ce1d4ec5b2` |
| `table.txt` | `01e71442cf89bf465d78c3c972f8c969825b2dd62db8546e5e7e972d98a483de` | `01e71442cf89bf465d78c3c972f8c969825b2dd62db8546e5e7e972d98a483de` | `01e71442cf89bf465d78c3c972f8c969825b2dd62db8546e5e7e972d98a483de` |

Pairwise classifications:

- `local_runner` vs `nextflow_backend`: **REPRODUCED_EXACT** (differing: —, missing: —)
- `local_runner` vs `snakemake_backend`: **REPRODUCED_EXACT** (differing: —, missing: —)
- `nextflow_backend` vs `snakemake_backend`: **REPRODUCED_EXACT** (differing: —, missing: —)

## Conformance matrix (WP-A suite, this run)

| case | local | snakemake | nextflow |
|---|---|---|---|
| `test_cleanup_caller_root_never_polluted` | PASS | PASS | PASS |
| `test_cleanup_no_scratch_leak_with_private_run_dir` | SKIP | PASS | PASS |
| `test_duplicate_execution_reproduced_exact` | PASS | PASS | PASS |
| `test_failed_job_recorded_in_receipt_not_raised` | PASS | PASS | PASS |
| `test_input_binding_hash_mismatch_fails_before_execution` | PASS | PASS | PASS |
| `test_nondeterminism_declaration_classified_honestly` | PASS | PASS | PASS |
| `test_output_binding_collects_declared_outputs` | PASS | PASS | PASS |
| `test_partial_outputs_recorded_and_differenced` | PASS | PASS | PASS |
| `test_receipt_carries_honest_backend_identity` | PASS | PASS | PASS |
| `test_receipt_mandatory_fields_and_digest` | PASS | PASS | PASS |
| `test_three_way_reproduced_exact` | — | — | — |
| `test_timeout_recorded_not_raised` | PASS | PASS | PASS |
| `test_unavailable_fails_visible_when_binary_missing` | SKIP | PASS | PASS |
| `test_undeclared_output_fails_visible` | PASS | PASS | PASS |

Verdict legend: PASS = case passed for this backend; SKIP = case not
applicable to this backend (local runner has no external binary and creates
no backend scratch) or its binary is missing (then ALL cases of that backend
skip). pytest exit code: 0.

## Honest limits

- One rule / one process per capsule: the adapters map the capsule contract
  onto Snakemake/Nextflow, they do not orchestrate workflows; neither engine
  is ever PF's orchestrator.
- The Nextflow process deliberately declares no outputs: output evidence is
  PF's own post-hoc hash collection (identical semantics to the local
  runner). Consequence, pinned by the `partial_outputs` conformance case:
  a job that omits an expected output is recorded with fewer outputs and
  classified MISMATCH by the differential, while Snakemake's generated rule
  fails the job at the wrapper. Both behaviours are conformance-clean.
- The receipt's `exit_code` for the external backends is the wrapper's exit
  code (WP7 review B-MINOR-4 applies unchanged to WP-B).
- Same hard limits as the local runner: not a sandbox; writes outside the
  workdir subtree are not detected by the snapshot diff.

## Reproduce

    python -m scripts.proof_v14_nextflow_conformance --out-dir docs/reports

Machine-readable twin: `V1_4_NEXTFLOW_CONFORMANCE_PROOF.json` (same
directory; relative paths and hashes only).
