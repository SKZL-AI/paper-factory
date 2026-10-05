# ARCHITECTURE — PAPER FACTORY

## The four layers

```
Human Policy Authority        (final sign-off, credentials, external actions)
        │
        ▼
PAPER FACTORY CORE            deterministic orchestration + persisted state
        │                     (this repo; NOT an LLM session)
        ├───────────────────────┐
        ▼                       ▼
Research DAG (P00–P37)     Provider Router (harness ≠ backend)
        │                       │
        ▼                       ▼
VeriHarness/HoH adapter      Harness adapters (claude/codex/kimi/pi/opencode/litellm)
        │                       │
        ▼                       ▼
Herdr runtime (sessions, panes, worktrees, restore)
        │
        ▼
Evidence → Claims → Stats → Figures/Tables → Manuscript → Reviews → Release
```

v1.3 added the **Reproduction Plane** (capsule contract, differential,
local/Snakemake runners, P10 gate) — owned by the PF core, same control-
plane role — and a pure **export layer** (RO-Crate / W3C-PROV / Workflow
Card) that projects canonical evidence without ever feeding gates. v1.4
extended the reproduction plane with a **Nextflow backend** behind the
same capsule contract, and the export layer with **CWL v1.2** (export
only). Since v2.0 every contract is inventoried and carries an explicit
stability guarantee (see *Contract stability* below and
[CONTRACTS.md](CONTRACTS.md)). The
role split is unchanged: **PF = Scientific Control Plane** (incl.
reproduction and exports), **VeriHarness/HoH = Verification Plane**,
**Herdr = Runtime Plane**.

## Where things live

- **Deterministic core**: `core/` (config, results, util, issue ledger,
  double-down), `dag/` (nodes P00–P37, executor), `state/` (workspace +
  SQLite run store, machine inventory), `cli/`.
- **Adapters**: `adapters/` — `base.py` defines the harness contract
  (doctor/version/capabilities/invoke/identities). `veriharness/` and
  `herdr/` are first-class adapters with hard policies (below). The
  verification wiring lives one layer up, in `dag/handlers.py` (see
  *Verification Plane* below).
- **Pipeline**: `context/` (intake, chat mining), `evidence/`, `claims/`,
  `literature/` (discovery, DOI verification, novelty attack),
  `statistics/` (metrics, integrity audit, reproducibility, numbers audit),
  `figures/`, `tables/`, `manuscript/` (scaffold + deterministic compose),
  `reviews/` (framework, runners, remediation, verification-finding
  ingest), `paperpal/` (manual bridge),
  `venue/`, `release/` (secret scan, export, rebuild, closure U1–U16).
- **Reproduction plane (v1.3, Nextflow added v1.4)**: `reproduction/` —
  versioned, content-addressed Reproduction Capsule, six-class
  Reproduction Differential, native local runner, the optional Snakemake
  backend (capability-probed; `UNAVAILABLE` instead of a fake when
  absent), and the Nextflow backend (binary launcher, deliberately not a
  pip extra).
- **Export layer (v1.3, CWL added v1.4)**: `export/` — pure exporters
  (RO-Crate 1.3 / Process Run Crate 0.6, W3C-PROV, CWL v1.2 Tool,
  derived Workflow Card) over the canonical model. Exports never feed
  gates; PF provenance stays canonical.

## Hard boundaries (code-enforced)

1. **HoH never runs against a foreign or shared repository.** The adapter
   materializes a PF-owned git snapshot (`<target>/.paper-factory/hoh-repo/`)
   and runs HoH there, with its own runs root (`hoh-runs/`), PF-prefixed
   run-ids, a per-workspace serialization lock, and pane cleanup afterwards.
   Reason: VeriHarness O177 — two HoH runs over one repo block each other
   (capability witness cannot distinguish foreign commits). See
   `state/concurrency_audit.json`.
2. **Final-prose path guard**: `provenance/firewall.decide_write` must pass
   before any protected path is written; every write leaves an origin receipt.
3. **Honest states**: PASS/FAIL/DEGRADED/HUMAN_REQUIRED/UNAVAILABLE/NOT_RUN/
   UNSUPPORTED_ENVIRONMENT are distinct; nothing is rounded up to PASS.
4. **Audit → review → remediation → closure**: detection nodes record
   findings (PASS = the audit ran), reviews fold findings into structured
   reports, remediation resolves them (never by copying reviewer prose),
   closure re-checks the post-remediation artifacts.

## Verification Plane (v1.2)

- **Contract modules** (`paper_factory/verification/`):
  `contract.py` (strict, versioned models — `WorkPackage`,
  `VerificationResult`, `BackendIdentity`; `schema_version=1`),
  `registry.py` (`VerificationBackend` protocol + `register`/`BACKENDS`),
  `capabilities.py` (`CapabilityStatus`: SUPPORTED / SUPPORTED_DEGRADED /
  UNAVAILABLE / UNSUPPORTED / REQUIRES_NETWORK / REQUIRES_HUMAN;
  declarations reuse the existing doctor/inventory probes),
  `shadow.py` (differential comparison + receipts),
  `findings_map.py`.
- **Adapter wiring** (`dag/handlers.py::build_handlers`): at handler-build
  time, the base handlers of `hoh_nodes ∪ shadow_nodes` (intersected with
  `VERIHARNESS_CAPABLE = {P04, P05, P07, P09, P10, P16, P17, P18, P20}`)
  are wrapped. `hoh_nodes` defaults to `["P05"]`. The wrapper runs the
  deterministic/agentic base handler, then — unless offline — drives the
  VeriHarness adapter and folds the verification verdict into the node
  outcome (a HoH FAIL fails the node; an incomplete verification degrades
  it, never hidden).
- **Shadow / differential mode**: nodes listed in `shadow_nodes` (also
  intersected with `VERIHARNESS_CAPABLE`) additionally get a
  `DifferentialReceipt` (kind="shadow") comparing the PF-native verdict
  with the backend verdict (`MATCH` / `SEMANTIC_MATCH` / `MISMATCH` /
  `PROVIDER_UNAVAILABLE` / `INCOMPARABLE`). Shadow never changes the node
  verdict. A node in both lists causes exactly one adapter run that feeds
  both planes.
- **Closure gate U7** (`release/closure.py`) counts only `kind="hoh"`
  receipts for configured `hoh_nodes`; shadow receipts are observational
  and would false-close the gate if counted.
- **v1.3 hardening** — semantic, gate-wired receipt freshness
  (`contract.py::check_receipt_freshness`: a receipt is fresh iff its
  bindings — run_id, store key, artifact hash — still hold at
  consumption time, not by wall-clock age; a receipt that fails can
  never satisfy a gate) and run_id provenance validation. Backend
  findings on the hoh/shadow paths are ingested via
  `reviews/verification_ingest.py` into PF-owned `VF-<node>` review
  reports that block closure gate U5 like native CRITICAL/MAJOR
  findings — disposition and closure stay with PF.

## Reproduction Plane (v1.3)

Owned by the PF control plane (the capsule contract is PF's own, not a
backend concern); workflow engines enter only as capability-probed
backends, the same adapter pattern as the provider router:

- **Capsule contract** (`reproduction/capsule.py`): versioned
  (`schema_version=1`), strict models — commands, environment identity,
  declared code/input refs with SHA-256, expected outputs, parameters,
  declared non-determinism, semantic match rules. Content-addressed
  identity via `capsule_digest`; control-character and path-traversal
  guards at parse time.
- **Differential** (`reproduction/differential.py`): compares two
  ExecutionReceipts into `ReproductionComparison` with one of six
  classes — `REPRODUCED_EXACT`, `REPRODUCED_SEMANTIC`, `MISMATCH`,
  `NONDETERMINISTIC_DECLARED`, `UNAVAILABLE`, `INCOMPARABLE`. Declared
  non-determinism matches honestly; anything uncomparable is a visible
  class, never a rounded-up PASS.
- **Backends** (`reproduction/runner.py`, `reproduction/snakemake_backend.py`,
  `reproduction/nextflow_backend.py`):
  the native local runner enforces declared-input verification, output
  collection, and undeclared-output detection (deletion/tamper is caught
  by a pre/post subtree snapshot, not by trust). The Snakemake backend
  subclasses the same runner, renders a Snakefile from the capsule and
  runs it via a probed binary — an optional extra
  (`pip install .[snakemake]`), fail-visible `UNAVAILABLE` when absent.
- **P10 wiring** (`statistics/reproducibility.py` + the DAG): P10 loads a
  declared capsule, runs it twice and gates on the differential. Honest
  scope: this proves a *declared* capsule reproduces itself; it is not
  system-level environment capture (ReproZip-class tooling: DEFER,
  `docs/reports/V1_4_REPROZIP_DECISION.md`).

## Export layer (v1.3)

`export/` turns capsule + receipts into interchange documents. All three
exporters are **pure projections** of canonical PF evidence
(receipts, capsule, provenance) — never sources of truth:

- `rocrate.py` — RO-Crate 1.3 metadata conforming to the *Process Run
  Crate 0.6* profile (Workflow Run RO-Crate family).
- `prov.py` — W3C-PROV document (`prov.json`).
- `cwl.py` — CWL v1.2 CommandLineTool export; interchange only, no
  third runtime engine (v1.4).
- `workflow_card.py` — derived, human- and LLM-readable card (JSON +
  Markdown); explicitly never a gate input.

`export/_shared.py::ExportBundle` validates the evidence before any
exporter runs (receipts must belong to the capsule and match its
`capsule_digest`); inconsistency raises `ExportError` — exports are
all-or-nothing, never half-true.

## State model

- SQLite (`<target>/.paper-factory/runs.sqlite`): runs, node states,
  receipts, events. Mutable orchestration state, schema-versioned via
  `PRAGMA user_version` (v1.3): a migration registry in `state/store.py`
  brings fresh and legacy databases to `SCHEMA_VERSION`, and an unknown
  newer schema fails visibly instead of silently downgrading.
- Immutable artifacts: evidence ledger (JSONL), claims (YAML), review reports
  (JSON), manifests, release bundle with SHA256SUMS.
- Resume: `paper-factory resume` re-executes only nodes not yet PASS/DEGRADED.

## Contract stability (v2.0)

Every PF contract with a real consumer in the code is inventoried in
[CONTRACTS.md](CONTRACTS.md) — 10 contracts, **all `schema_version=1`**:
verification contract and receipts, shadow/differential receipt,
reproduction capsule and receipt, the two backend protocols (verification
+ reproduction), the provenance export formats, the state-DB schema, and
finding identity. The stability policy is:

- **Strict models, visible failure.** All contract payloads are strict
  Pydantic models (`extra="forbid"`); unknown fields and unknown schema
  versions fail visibly at load, never parse leniently into a gate.
- **No silent field changes.** Any semantic field change is a
  `schema_version=2` event. The empirical trigger criteria for a v2 are
  written down in `docs/reports/V2_0_SCHEMA_DECISION.md`; as of v2.0 no
  proven need exists, so every contract stays on v1 (incl. the state DB,
  whose `schema_version` field deliberately sits inside the
  `capsule_digest` payload).
- **Deprecation discipline.** Breaking renames without consumer benefit
  do not happen. The one documented example: two `ExecutionReceipt`
  classes (verification vs reproduction) share a name — inventoried, no
  proven defect (no file imports both), and the rename TODO is bound to
  schema v2, where it lands in the same version-bump transaction as any
  field change. Existing compatibility anchors (`legacy_dedupe_key`,
  lenient load of v1.2-era receipts without timestamps) are tested and
  are removed only through the same versioned path.
- **Migrations never rewrite history.** State-DB migrations are
  registered (`MIGRATIONS` chain), idempotent, and copy the database
  before any mutation; a future v2 would ship as `MIGRATIONS[1]` with
  the same copy-before-mutate contract, and old v1 payloads stay
  readable.
- **Conformance is measured, not asserted.** 48 matrix cells (38 green,
  1 locally verified, 2 pinned limits, 7 honestly open) in
  `docs/reports/V2_0_CONFORMANCE_MATRIX.md`.
