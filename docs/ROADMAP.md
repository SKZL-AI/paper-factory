# ROADMAP — PAPER FACTORY

Status: canonical roadmap as of **v1.2.0** · Language: English · Audience: public repo
(SKZL-AI/paper-factory)

This document is a **roadmap overlay**, not a plan from scratch. It classifies the
recommendations of an earlier external deep-research report (a historical planning
artifact, kept unchanged) against the current repository reality, and fixes what is
`IMPLEMENTED`, what is `PLANNED` (v1.3 / v1.4+), and what we deliberately do **not**
build.

**Priority of truth:** repository reality > VeriHarness integration > research
recommendations. Nothing is planned just because a report says so; every entry below
is grounded in shipped code, a tracked DEFER decision, or an explicit rejection.

## Status: what has shipped

| Release | Delivered |
|---|---|
| **v1.0.0** | Scientific core frozen after a real pilot (a mass-invariance paper): P00–P37 DAG, claim–evidence graph with content-addressed artifacts, 16 closure invariants U1–U16 (pilot: P21–P36 PASS, U1–U16 16/16 PASS), provenance firewall, human gates P36/P37, 574 tests. |
| **v1.1.0** | arXiv compliance layer (P32): AI-use disclosure with structured `ai_disclosure.yaml`, no-LLM-authorship gate, chatbot meta-comment scan, license/format rules — verified against primary sources. 622 tests. |
| **v1.2.0** | **Verification Plane**: versioned contract (`paper_factory/verification/`, `schema_version=1`: `WorkPackage` / `VerificationResult` / `BackendIdentity`), in-process backend registry, capability negotiation reusing the existing doctor/inventory probes (`CapabilityStatus`), generalised VeriHarness adapter (two façades, one run flow), and **shadow / differential mode** (`DifferentialReceipt`: MATCH / SEMANTIC_MATCH / MISMATCH / PROVIDER_UNAVAILABLE / INCOMPARABLE; observational only, never changes a verdict). Real positive end-to-end proof: PF WorkPackage → real VeriHarness/HoH run → real receipts → `VerificationResult` → **Differential MATCH** (see `docs/reports/V1_2_REAL_VERIHARNESS_INTEGRATION_PROOF.md`). 769 tests (+2 environment skips). |

Architecture roles are fixed: **Paper Factory = Scientific Control Plane**
(owns P00–P37, U1–U16, evidence authority, protected prose), **VeriHarness/HoH =
Verification Plane**, **Herdr = Runtime Plane**. This separation is what moved most
third-system recommendations from "build it" to "reuse it" or "defer it".

## Classification of research-report recommendations

Legend: **IMPLEMENTED** = built in v1.0–v1.2 · **IMPLEMENTED_VIA_VERIHARNESS** =
covered by the VeriHarness integration · **SUPERSEDED** = replaced by a different
in-repo solution · **V1_3** / **V1_4_PLUS** = planned · **OPTIONAL_PROVIDER** = only
with a real consumer · **REJECTED_NO_CURRENT_NEED** = deliberately not built.

### Verification, review, provenance

| Recommendation | Classification | Rationale |
|---|---|---|
| Versioned verification contract | IMPLEMENTED | Shipped in v1.2 (`schema_version=1`, strict Pydantic models, round-trip tested, unknown versions fail visibly). |
| Capability negotiation / registry | IMPLEMENTED | v1.2 `registry.py` + `capabilities.py` reuse the existing doctor probes; no parallel discovery stack. |
| Independent verification kernel (reviewer/verifier orchestration, isolation, receipts) | IMPLEMENTED_VIA_VERIHARNESS | This is VeriHarness/HoH's core competence. PF contributes one small harness-neutral adapter, not a re-implementation. |
| Shadow / differential verification | IMPLEMENTED | v1.2 `shadow.py`; observational by design, real MATCH proof recorded 2026-10-05. |
| AI Peer Review (LLM reviewers as independent checkers) | IMPLEMENTED_VIA_VERIHARNESS | PF-native review pipeline P23–P26 exists; additional independent reviewers can enter as VeriHarness ensembles behind the same contract. Hard rule: reviewers are a **gate, never an approval** — P36 stays human. |
| W3C-PROV provenance standard | V1_3 (export only) | Suitable as an interchange/export format, never as a replacement for PF's canonical provenance (firewall, origin receipts). Deferred: no consumer exists today (`docs/reports/DEFERRED_HARDENING.md`). |
| DeltaSci / sourcecheck-style external checkers | IMPLEMENTED_VIA_VERIHARNESS | Independent checking is exactly the Verification Plane's job; any such tool would plug in via the `VerificationBackend` protocol. No dedicated adapter is built without a real consumer. |
| Cryptographic attestation / external provenance anchor | V1_4_PLUS | Receipts are SHA-256-bound today; tamper/replay-proof signatures need a stable contract and a consumer first. |

### Literature, citations, workflow execution

| Recommendation | Classification | Rationale |
|---|---|---|
| PaperQA2 (literature RAG) | OPTIONAL_PROVIDER | High-quality retrieval, but `paperqa` is imported nowhere in the code. A `LiteratureProvider` interface with zero real consumers violates our own "no abstraction without a second consumer" rule. Revisit in v1.3 **only if a real consumer appears**; the pyproject extra stays optional. |
| Snakemake (first workflow backend) | V1_3 | Preferred candidate for the first reproduction-backend adapter, gated on the Reproduction Capsule. Only after the capsule contract is stable. |
| Nextflow | V1_4_PLUS | Additional backend behind the same capsule contract; needs a backend-conformance suite first. |
| CWL | V1_4_PLUS | Same reasoning as Nextflow; lowest priority of the three. |
| ReproZip-style reproduction capsules | V1_4_PLUS | The v1.3 Reproduction Capsule is PF's own minimal, contract-bound format; heavier system-capture tooling only if a real interchange consumer emerges. |
| Manubot (manuscript/citation pipeline) | SUPERSEDED | PF's deterministic compose (P13–P20) and canonical citation-identity audit (P21: DOI/arXiv/authoritative-URL match) cover the intent; no LLM-authored-manuscript pipeline needed. |
| showyourwork (reproducible-paper builds) | SUPERSEDED | The intent — every figure/number traceable to code — is PF's core design (deterministic P13/P14 generation, P34 independent clean rebuild), without a Snakemake/LaTeX-framework dependency. |
| Science Skills (agentic research skill packs) | SUPERSEDED | Thin frontend skills already exist (`frontends/`, `/complete-paper` wrappers around the same deterministic core); the core, not prompt packs, is the product. |
| Flowcept (agent telemetry/interception) | REJECTED_NO_CURRENT_NEED | PF already records receipts, provenance and run state deterministically; adding a telemetry-interception layer solves a problem the repo does not have. |
| AI Scientist (end-to-end autonomous paper generation) | REJECTED_NO_CURRENT_NEED | Contradicts the design: no mass production without a novelty gate, no self-approving loops, P36/P37 stay human. Documented as a non-goal in `docs/reports/ROADMAP_AUTONOMY.md`. |

### v1.2 leftovers explicitly deferred to v1.3

| Item | Classification | Rationale |
|---|---|---|
| `findings_map` full DAG/review-pipeline wiring | V1_3 | Library exists; production wiring (duplicate/conflict/stale finding tests) planned. PF remains closure owner. |
| Reproduction Capsule (P10) | V1_3 | Commands/env/input/output/hash/exit reproducibility; prerequisite for any workflow backend. |
| Stale-receipt freshness check | V1_3 | `created_at` is validated but unconsumed; the pinning test `test_stale_execution_receipt_loads_without_any_freshness_check` defines the red test a future check must turn green. |
| SQLite schema versioning / state migration | V1_3 | The contract versions itself; migrating `runs.sqlite` is a separate risk package with no current consumer. |
| Herdr / CLI-TUI hardening (dispatch stall window, `--no-herdr` DAG plumbing, receipt-internal validation) | V1_3 | Field-measured 2026-10-05: herdr's 5 s stall window is hard-coded upstream; adapter workaround exists with honest evidence trade-off. Tracked as MINOR/NIT in `docs/reports/DEFERRED_HARDENING.md`. |

## v1.3 — Reproducibility & Scientific Interchange (planned)

Scope, in priority order:

1. **Reproduction Capsule** — a versioned, contract-bound description of commands,
   environment, inputs, outputs, hashes and exit codes for P10, reproducible
   end-to-end.
2. **One workflow consumer first** — one backend adapter (Snakemake preferred)
   running the same capsule locally and on the backend with identical output.
   More backends (Nextflow, CWL) only after a conformance suite exists → v1.4+.
3. **`findings_map` wiring** — external findings fully integrated into the DAG /
   review pipeline (duplicate/conflict/stale handling), with PF retaining finding
   disposition and closure ownership.
4. **Reproducibility hardening** — stale-receipt freshness checks, SQLite schema
   versioning and migration, Herdr/CLI-TUI robustness.
5. **Exports** — W3C-PROV exporter as a pure export over the canonical PF
   provenance model; PF-internal semantics stay canonical.
6. **Literature provider** — `LiteratureProvider` + PaperQA2 **only if a real
   consumer materialises**; PF-native P06 remains the canonical path until then.

## v1.4+ — Multi-backend & ecosystem (planned, gated)

- Nextflow / CWL backends behind the stable capsule contract, with a
  backend-conformance suite.
- Broader provider/plugin SDK (multiple real consumers required before the
  abstraction is justified).
- ReproZip-class heavy capture capsules, only with a real interchange consumer.
- Cryptographic attestation / external provenance anchors, once receipts are
  consumed outside this repo.

## The "do not rebuild" principle

Paper Factory does not clone other systems internally.

- Repo reality beats VeriHarness integration beats research recommendations —
  in that order.
- VeriHarness/HoH already provides reviewer orchestration, work packages,
  isolation and receipts. We build adapters, not second copies.
- External systems (PaperQA2, Snakemake, Nextflow, CWL, W3C-PROV, ReproZip,
  Flowcept, Manubot, showyourwork, …) enter — if at all — as **adapters or
  interchange exports behind the versioned contract**, and only when a real
  consumer exists. An interface with zero consumers is rejected by rule.
- PF remains the sole owner of the scientific truth: P00–P37, U1–U16, evidence
  authority, protected-prose policy, P36 human sign-off, and P37 (never executed
  automatically).
