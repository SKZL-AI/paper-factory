# v1.3 WP12 — Pilot Matrix

Generated: 2026-10-05 · Branch: `v1.3/reproducibility-interchange` ·
HEAD: `d5145c5` (WP1–11 + P10-Integration) ·
Machine-readable twin: `V1_3_PILOT_MATRIX.json` (same directory).

Three pilot lanes over the v1.3 reproduction/interchange plane, plus one
honestly-marked live field test. Real local execution only in A–C: no
network, no LLM, no HoH. The live lane (Herdr) spent claude quota exactly
once and is reported separately. Pilot workspaces under `pilots/` are
gitignored local evidence; this report carries the durable results and
hash cores. Suite after this WP: **948 passed, 2 skipped** (104 s).

## A. Synthetic deterministic end-to-end repro pilot over the real PF DAG

**Setup.** New minimal target project `pilots/v1-3-repro-synth/project/`
(pilot workspace, not committed): the deterministic fixture compute
(`tests/fixtures/repro_pilot/pilot_compute.py` + `input.csv`, copied
verbatim) and a versioned Reproduction Capsule at
`.paper-factory/reproduction/capsule.json`
(`schema_version: 1`, `capsule_id: v1-3-repro-synth-01`,
command `python3 pilot_compute.py`, declared code/input hashes,
`expected_outputs: [summary.json, table.txt]`).

**Run.** The real PF DAG via the canonical CLI, HoH disabled through the
offline e2e config (`tests/e2e-config/paper-factory.yaml`,
`hoh_nodes: []`), run id `v13-synth-a`:

```
python -m paper_factory.cli.main --root pilots/v1-3-repro-synth/project \
    --config-dir tests/e2e-config complete --offline --run-id v13-synth-a
```

**Result — the v1.3 core proof.**

- **P10 = PASS, classification `REPRODUCED_EXACT`.** P10 went from the
  historical honest DEGRADED ("no reproduction commands discovered") to a
  real PASS gate on a declared capsule — via the capsule path in
  `paper_factory/statistics/reproducibility.py`.
- Both capsule executions completed, exit 0, **identical output hashes**:

| output | SHA-256 (both executions) |
|---|---|
| `summary.json` | `8f76c7d9d07d070ba3aa3fffa058a4d65212fc9a97915596587531ce1d4ec5b2` |
| `table.txt` | `01e71442cf89bf465d78c3c972f8c969825b2dd62db8546e5e7e972d98a483de` |

  These are exactly the hashes of the WP7 proof (local runner *and*
  Snakemake backend) — three-way consistency over one declared
  computation.
- Capsule digest `6b1efffda4f6f85ffbfb09dfeb3677440d45972862012af0f51fab145251eee3`.

**Evidence.**

- `pilots/v1-3-repro-synth/project/.paper-factory/reports/reproducibility.json`
  (sha256 `6fc07be20f476c77ebc4a60576f457719ee2628b3633ac3ccaf7b3bf211c1d6f`) —
  mode `capsule`, two receipts, `differing_outputs: []`,
  `missing_outputs: []`.
- `pilots/v1-3-repro-synth/run-v13-synth-a.stdout.json`
  (sha256 `ab2c11fc2611645e32bd267ce6d6bc36c3f3d38edb17c87965958201e43a870c`)
  — full per-node status map.
- Node record: `P10 | PASS | {"capsule_digest": "6b1efffd…",
  "classification": "REPRODUCED_EXACT"}` in the pilot `runs.sqlite`.

**Honest context.** The run's overall state is `FAILED`, and that is
downstream of P10 and fully explained: P09 DEGRADED (minimal project, no
data sources discovered — an OK state for P10's dependency per the DAG
contract), P31 HUMAN_REQUIRED (paperpal manual bridge), P32 FAIL
(`bib_exists` — the minimal project ships no `literature/references.bib`).
None of these touches the P10 claim; a minimal repro pilot is not a
paper project.

## B. Existing pilot, unchanged — regression differential

**Method.** `scripts/pilot_differential.py` re-run read-only (sqlite
`mode=ro`) over stored v1.2 pilot state; historical reports in
`docs/reports/` untouched, new output in `docs/reports/v1_3/`. No live
HoH replay (quota discipline), no network, no LLM.

**Result — no regression.** Verdict distributions are bit-identical to
the v1.2 reports:

| pilot | run | nodes | v1.2 native verdicts | v1.3 native verdicts | mismatches |
|---|---|---|---|---|---|
| pilot-03-massinv-paper1 | complete-20261002T143931Z | 38 | PASS 33 / DEGRADED 4 / NOT_RUN 1 | PASS 33 / DEGRADED 4 / NOT_RUN 1 | 0 |
| real-pilot-01-rerun | complete-20260925T162928Z | 38 | PASS 31 / DEGRADED 5 / HUMAN_REQUIRED 1 / SKIPPED 1 | PASS 31 / DEGRADED 5 / HUMAN_REQUIRED 1 / SKIPPED 1 | 0 |

Every row is `PROVIDER_UNAVAILABLE` on the VH side (no HoH receipts were
persisted historically) — a documented gap in both v1.2 and v1.3, not a
PASS. v1.3 changed nothing about existing pilot behavior.

**Evidence.** `docs/reports/v1_3/V1_2_PILOT_DIFFERENTIAL_*.md|.json`,
`docs/reports/v1_3/V1_2_PILOT_DIFFERENTIAL_SUMMARY.md`.

## C. Failure injections (3 × honest failure)

All against fresh scratch copies of the Pilot A project (the pilot
itself is never modified); full detail and per-injection observations in
`docs/reports/v1_3/V1_3_PILOT_INJECTIONS.json`
(sha256 `d563f999199b4a6b1482426723c172e050546e99830cb795dfae906ccd750297`).
The runner script `scripts/pilot_injections_v13.py` exits non-zero unless
every injection produces its expected honest result.

| # | injection | expected | observed | verdict |
|---|---|---|---|---|
| C1 | broken capsule (`{not json`) | P10 FAIL, visible reason, no execution | P10 FAIL — `reproduction capsule invalid: … json_invalid`; no receipt run | as expected |
| C2 | output tampering (uuid nonce patched into `pilot_compute.py`, capsule code hash updated to match) | MISMATCH → P10 FAIL | classification `MISMATCH`, `differing_outputs: [summary.json, table.txt]`, both receipts' hash sets differ, P10 FAIL | as expected |
| C3 | Snakemake backend, PATH emptied, interpreter without snakemake beside it | honest UNAVAILABLE, no fake | `SnakemakeUnavailableError`, probe binary `None`; positive control via the PF venv completed (`status: completed`) | as expected |

C3 is a real negative, not a mock: the probe code is the production
`snakemake_binary()` capability check, and the environment genuinely has
no reachable binary (venv python invoked through a fresh scratch-dir
symlink, `PATH=""` — the venv bin dir is the designed fallback, so a
bare PATH emptying via the venv interpreter would not be a true
negative; documented in the script).

## Interchange exports (WP9–11 exporters over the pilot)

From the Pilot A capsule + the two persisted P10 receipts, via
`paper_factory/export/` (EXPORT ONLY — PF provenance stays authoritative;
the Workflow Card is a derived summary, never a gate input):

| file | sha256 |
|---|---|
| `docs/reports/v1_3/exports/v1-3-repro-synth/ro-crate-metadata.json` | `704137eea2b06f543b19b11ba8f86b0d96a66c088c00fc109ec11a1fd7f89ffc` |
| `docs/reports/v1_3/exports/v1-3-repro-synth/prov.json` | `ad05b9ec1fe07fe211cdee5ebdb6e2ee0eb2366851966df7d6be2fce1e33464c` |
| `docs/reports/v1_3/exports/v1-3-repro-synth/workflow_card.json` | `919084d52ef063351b67d3d4b18e7aebe0d79e196460c48ed7ee70bbb62ace69` |
| `docs/reports/v1_3/exports/v1-3-repro-synth/workflow_card.md` | `65b6f98d21eccc03b611de4f7509bcd4f8fbc20fd28d06e2b3eac07dcb1bf063` |
| `docs/reports/v1_3/exports/v1-3-repro-synth/export_manifest.json` | `cd256b39803727aac41a8f8a307f0d960d5ff7af286db083e072a777502f7f06` |

Reproduce: `python -m scripts.pilot_exports_v13`. Scope note: the Pilot
B workspaces declare no reproduction capsule, so there is no
capsule/receipt bundle to export for them — a documented gap, not a PASS.

## Herdr field test (live, one attempt — honest result)

Separately reported; addendum in `docs/reports/V1_3_WP1_HERDR_RUNTIME_HARDENING.md`,
evidence `docs/reports/v1_3_integration_proof_herdr_20261005T124256Z.json`.
Headline: herdr dispatch with claude roles worked (no stall), but
claude's folder-trust dialog blocked the developer pane (HoH does not
auto-confirm dialogs) → VH FAIL → differential MISMATCH. Not a v1.3
blocker; the subprocess-path v1.2 proof remains the binding evidence.

## Suite

`pytest tests -q` after this WP: **948 passed, 2 skipped** (104 s) —
unchanged from the pre-WP12 baseline. New WP12 verification lives in the
two executable scripts above (fail-visible, exit-non-zero-on-surprise),
not in mocked pytest tests.

## Reproduce

```
# A — build + run (capsule generation one-off, see report history)
python -m paper_factory.cli.main --root pilots/v1-3-repro-synth/project \
    --config-dir tests/e2e-config complete --offline --run-id <id>
# B — regression differential (new files under docs/reports/v1_3/)
python -m scripts.pilot_differential --pilots pilot-03-massinv-paper1 \
    real-pilot-01-rerun --out-dir docs/reports/v1_3
# C — failure injections
python -m scripts.pilot_injections_v13 --out-dir docs/reports/v1_3
# exports
python -m scripts.pilot_exports_v13
```

## DEFER / not run

- **Herdr + claude trust dialog** — new field finding, tracked in
  `DEFERRED_HARDENING.md`; options (pre-trusted workdir in claude config,
  upstream trusted-workdir declaration) not executed (quota discipline,
  one-attempt rule).
- **Exports for Pilot B** — no capsule declared in the v1.2 pilots; no
  export bundle exists. Documented gap.
- **Nextflow/CWL backends, ReproZip** — unchanged v1.4 decision gates
  (`DEEP_RESEARCH_DELTA_POST_V1_2.md` §3.7/3.8/3.10).
- The blocked HoH run `PF-4ca0e67c-P05` was left blocked for a human
  (`hoh unblock`); no silent continuation.
