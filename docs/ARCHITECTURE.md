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
  `reviews/` (framework, runners, remediation), `paperpal/` (manual bridge),
  `venue/`, `release/` (secret scan, export, rebuild, closure U1–U16).

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

## State model

- SQLite (`<target>/.paper-factory/runs.sqlite`): runs, node states, receipts,
  events. Mutable orchestration state.
- Immutable artifacts: evidence ledger (JSONL), claims (YAML), review reports
  (JSON), manifests, release bundle with SHA256SUMS.
- Resume: `paper-factory resume` re-executes only nodes not yet PASS/DEGRADED.
