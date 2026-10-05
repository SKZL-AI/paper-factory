# v1.3 WP7 — Snakemake as first workflow consumer: proof

Generated: 2026-10-05T12:23:07.911878+00:00

## Gate

From `docs/reports/DEEP_RESEARCH_DELTA_POST_V1_2.md` §3.2: the same capsule
run via the PF native local runner and via the Snakemake backend must
produce identical output hashes (`REPRODUCED_EXACT`), or honestly justified
semantic equality. This run: **REPRODUCED_EXACT**.

## Method

- Capsule: `repro-pilot-01` (digest
  `3cb31773760b30b793aa9738b38a102fbf4c4a1c0ec44d2614106b40eacc2dfc`), the deterministic synthetic
  pilot `tests/fixtures/repro_pilot`, executed twice on separate copies of
  the fixture root.
- Side A: `LocalReproductionRunner` (backend
  `pf_native/
  local-reproduction-runner`
  0.1.0).
- Side B: `SnakemakeBackend` (backend
  `external/
  snakemake`
  9.27.0), one generated rule
  per capsule, `--cores 1`, staged run directory outside the capsule root.
- Classification: `compare_executions` (WP6 differential). Real local CPU
  only — no network, no LLM, no HoH.

## Environment

- Snakemake 9.27.0 (optional extra, not a core
  dependency)
- Python 3.13.5, Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.39

## Output hashes (SHA-256)

| output (rel. to capsule root) | local runner | snakemake backend |
|---|---|---|
| `summary.json` | `8f76c7d9d07d070ba3aa3fffa058a4d65212fc9a97915596587531ce1d4ec5b2` | `8f76c7d9d07d070ba3aa3fffa058a4d65212fc9a97915596587531ce1d4ec5b2` |
| `table.txt` | `01e71442cf89bf465d78c3c972f8c969825b2dd62db8546e5e7e972d98a483de` | `01e71442cf89bf465d78c3c972f8c969825b2dd62db8546e5e7e972d98a483de` |

Both sides exit_code=0/
0, status
`completed`/`completed`.
Machine-readable twin: `V1_3_WP7_SNAKEMAKE_PROOF.json` (same directory).

## Honest limits

- One rule per capsule: the adapter maps the capsule contract onto
  Snakemake, it does not orchestrate workflows; Snakemake is never PF's
  orchestrator.
- The staged execution protects the caller's tree from `.snakemake`
  metadata; output hashes are unaffected (staged inputs are verified
  byte-identical before the run).
- Same hard limits as the local runner: not a sandbox; writes outside the
  workdir subtree are not detected by the snapshot diff.

## Reproduce

    python -m scripts.proof_wp7_snakemake --out-dir docs/reports
