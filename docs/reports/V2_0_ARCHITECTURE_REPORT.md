# V2 Architecture Report — Paper Factory 2.0.0 (Production Freeze)

Date: 2026-10-05 · Release commit: see V2_FREEZE_MANIFEST.json

## Plane architecture (invariant since v1.2, now frozen)

- **Paper Factory = Scientific Control Plane** — sole owner of P00–P37,
  U1–U16, claim semantics, evidence authority (T0–T4), protected prose,
  finding disposition, scientific closure, P36 (human sign-off), P37 policy
  (never executed autonomously).
- **VeriHarness/HoH = Verification Plane** — verifies work packages behind the
  versioned verification contract; can never set or override PF closure.
- **Herdr = Runtime Plane** — sessions/panes/processes/worktrees; known
  upstream stall limitation documented (WP1 report).

## Contracts (all schema_version=1, frozen)

Full inventory with producers/consumers/stability guarantees:
`docs/CONTRACTS.md`. Schema v2 decision: not needed, triggers documented
(`docs/reports/V2_0_SCHEMA_DECISION.md`). The `ExecutionReceipt` naming
collision (verification vs reproduction) is documented and bound to a future
schema v2.

## Planes built across v1.0–v2.0

Scientific DAG core (v1.0) · arXiv compliance (v1.1) · Verification Plane with
real VeriHarness MATCH proof (v1.2) · Reproduction Plane with capsule +
3-backend conformance (v1.3/v1.4) · Export layer: RO-Crate 1.3 / Process Run
Crate 0.6, W3C-PROV, CWL 1.2, Workflow Cards — all EXPORT ONLY (v1.3/v1.4) ·
Release attestation via GitHub Artifact Attestations (v1.4) · Contract
stabilization, failure injection, historical state migration (v2.0).

## Evidence index

Conformance: `docs/reports/V2_0_CONFORMANCE_MATRIX.md` (48 cells) ·
Migration: `docs/reports/V2_0_STATE_MIGRATION.md` ·
Attestation: `docs/reports/V2_0_RELEASE_ATTESTATION_REPORT.md` ·
Interchange: `docs/reports/V2_0_PROVENANCE_INTERCHANGE_REPORT.md` ·
Deferred: `docs/reports/DEFERRED_HARDENING.md` ·
Roadmap: `docs/ROADMAP.md`.
