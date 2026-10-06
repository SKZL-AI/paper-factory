# ROADMAP — PAPER FACTORY

Status: canonical roadmap as of **v2.0.0** · Language: English · Audience: public repo
(SKZL-AI/paper-factory)

Project status: **PROJECT_COMPLETE / MAINTENANCE MODE** — this roadmap is
frozen backlog, not an active plan
(see `docs/reports/PROJECT_COMPLETION_2026-10-06.md`).

This document is a **roadmap overlay**, not a plan from scratch. It classifies the
recommendations of an earlier external deep-research report (a historical planning
artifact, kept unchanged) against the current repository reality, and fixes what is
`IMPLEMENTED`, what is `POST_V2` backlog, and what we deliberately do **not**
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
| **v1.3.0** | **Reproducibility & Scientific Interchange**: versioned, content-addressed **Reproduction Capsule** (`schema_version=1`, `capsule_digest`) with a six-class **Reproduction Differential** (`REPRODUCED_EXACT` / `REPRODUCED_SEMANTIC` / `MISMATCH` / `NONDETERMINISTIC_DECLARED` / `UNAVAILABLE` / `INCOMPARABLE`); native local runner plus **optional** Snakemake backend (`pip install .[snakemake]`, capability-probed, honest `UNAVAILABLE`) — real three-way proof: identical output hashes across local runner, Snakemake and the P10 DAG gate (`REPRODUCED_EXACT`, `docs/reports/V1_3_WP7_SNAKEMAKE_PROOF.md`). **P10 capsule integration** with honest self-attestation scope. Verification-contract hardening: semantic, gate-wired receipt freshness, run_id provenance validation. SQLite schema versioning via `PRAGMA user_version` + migration registry. `findings_map` production wiring: provider findings → `VF-<node>` review reports → U5 blocking, PF keeps disposition ownership. Pure export layer: **RO-Crate 1.3 / Process Run Crate 0.6**, **W3C-PROV**, derived **Workflow Card** (never gate inputs). Failure-injection pilots and regression differential: `docs/reports/V1_3_PILOT_MATRIX.md`. 968 tests (+2 environment skips). **Known limitations (unchanged, tracked):** herdr 5 s dispatch-stall window hard-coded upstream (`docs/reports/V1_3_WP1_HERDR_RUNTIME_HARDENING.md`); 2026-10-05 live field test: Claude folder-trust dialog blocked the HoH developer pane (tracked in `docs/reports/DEFERRED_HARDENING.md`). |
| **v1.4.0** | **Multi-backend & attestation**: backend conformance suite (12 semantic cases × every reproduction backend, honest skips without binaries); **Nextflow backend** behind the capsule contract with a real 3-way reproduction proof (local + Snakemake + Nextflow → `REPRODUCED_EXACT`); **CWL v1.2 export** (interchange only, capsule stays canonical); GitHub **release artifact attestations** for sdist/wheel on every `v*` tag (no SLSA claim; historical tags stay unsigned). ReproZip: DEFER. 1050 tests (+4 honest skips). |
| **v2.0.0** | **Contract stabilization & production freeze**: Contract Inventory — 10 contracts with real consumers, **all `schema_version=1`**, with an explicit stability guarantee (`docs/CONTRACTS.md`); schema-v2 decision — v1 stays, written empirical trigger criteria (`docs/reports/V2_0_SCHEMA_DECISION.md`); honest cross-platform matrix + packaging asset fix (`pfword.ps1`, `paper.mplstyle`) (`docs/reports/V2_0_PLATFORM_PACKAGING.md`); full conformance matrix (48 cells: 38 green / 1 locally verified / 2 pinned limits / 7 honestly open) incl. failure injection with two production fixes (receipt Digest-Guard collect→gate, export coverage guard) (`docs/reports/V2_0_CONFORMANCE_MATRIX.md`); historical state migration — 5 real pilot states (v1.0–v1.3) migrated 0→1, originals byte-identical (`docs/reports/V2_0_STATE_MIGRATION.md`). 1070 tests (+4 honest skips). |

Architecture roles are fixed: **Paper Factory = Scientific Control Plane**
(owns P00–P37, U1–U16, evidence authority, protected prose), **VeriHarness/HoH =
Verification Plane**, **Herdr = Runtime Plane**. This separation is what moved most
third-system recommendations from "build it" to "reuse it" or "defer it".

## Classification of research-report recommendations

Legend: **IMPLEMENTED** = built in v1.0–v2.0 · **IMPLEMENTED_VIA_VERIHARNESS** =
covered by the VeriHarness integration · **SUPERSEDED** = replaced by a different
in-repo solution · **POST_V2** = ungated backlog · **OPTIONAL_PROVIDER** = only
with a real consumer · **REJECTED_NO_CURRENT_NEED** = deliberately not built.

### Verification, review, provenance

| Recommendation | Classification | Rationale |
|---|---|---|
| Versioned verification contract | IMPLEMENTED | Shipped in v1.2 (`schema_version=1`, strict Pydantic models, round-trip tested, unknown versions fail visibly). |
| Capability negotiation / registry | IMPLEMENTED | v1.2 `registry.py` + `capabilities.py` reuse the existing doctor probes; no parallel discovery stack. |
| Independent verification kernel (reviewer/verifier orchestration, isolation, receipts) | IMPLEMENTED_VIA_VERIHARNESS | This is VeriHarness/HoH's core competence. PF contributes one small harness-neutral adapter, not a re-implementation. |
| Shadow / differential verification | IMPLEMENTED | v1.2 `shadow.py`; observational by design, real MATCH proof recorded 2026-10-05. |
| AI Peer Review (LLM reviewers as independent checkers) | IMPLEMENTED_VIA_VERIHARNESS | PF-native review pipeline P23–P26 exists; additional independent reviewers can enter as VeriHarness ensembles behind the same contract. Hard rule: reviewers are a **gate, never an approval** — P36 stays human. |
| W3C-PROV provenance standard | IMPLEMENTED (v1.3, export only) | Shipped as `export/prov.py` — a pure projection over the canonical PF provenance model, exactly as scoped here; never a replacement for firewall/origin receipts. No consumer yet, so it stays export-only. |
| DeltaSci / sourcecheck-style external checkers | IMPLEMENTED_VIA_VERIHARNESS | Independent checking is exactly the Verification Plane's job; any such tool would plug in via the `VerificationBackend` protocol. No dedicated adapter is built without a real consumer. |
| Cryptographic attestation / external provenance anchor | IMPLEMENTED (v1.4, release artifacts) | GitHub Artifact Attestations ship for sdist/wheel on every `v*` tag since v1.4.0 (Free/Pro/Team public repos, `actions/attest` in GitHub Actions, `gh attestation verify`; first attested release v1.4.0; historical tags stay unsigned). Receipts are SHA-256-bound; attestation of receipts *beyond* the build path stays POST_V2 until receipts are consumed outside this repo. `SLSA_BUILD_REPRODUCED` requires provenance from two or more independently operated build platforms — a high bar we do not claim (`docs/reports/DEEP_RESEARCH_DELTA_POST_V1_2.md` §3.6). |

### Literature, citations, workflow execution

| Recommendation | Classification | Rationale |
|---|---|---|
| PaperQA2 (literature RAG) | OPTIONAL_PROVIDER | High-quality retrieval, but `paperqa` is imported nowhere in the code. A `LiteratureProvider` interface with zero real consumers violates our own "no abstraction without a second consumer" rule. Revisit **only if a real consumer appears**; the pyproject extra stays optional. |
| Snakemake (first workflow backend) | IMPLEMENTED (v1.3, optional extra) | Shipped behind the capsule contract as `reproduction/snakemake_backend.py` (`pip install .[snakemake]`, capability-probed with honest `UNAVAILABLE`). Real proof: `REPRODUCED_EXACT` with identical output hashes across local runner, Snakemake backend and the P10 DAG gate (`docs/reports/V1_3_WP7_SNAKEMAKE_PROOF.md`). |
| Nextflow | IMPLEMENTED (v1.4, binary-launcher backend) | Shipped as `reproduction/nextflow_backend.py` behind the same capsule contract, with the 12-case backend conformance suite and a real 3-way reproduction proof (local + Snakemake + Nextflow → `REPRODUCED_EXACT`, `docs/reports/V1_4_NEXTFLOW_CONFORMANCE_PROOF.md`). Deliberately not a pip extra (binary launcher). |
| CWL | IMPLEMENTED (v1.4, export only) | Shipped as `export/cwl.py`: capsule → CWL v1.2 CommandLineTool, interchange only, no third runtime engine (`docs/reports/V1_4_CWL_DECISION.md`); capsule stays canonical. |
| ReproZip-style reproduction capsules | POST_V2 | DECIDED DEFER (`docs/reports/V1_4_REPROZIP_DECISION.md`): the v1.3 Reproduction Capsule (shipped, content-addressed) is PF's own minimal, contract-bound format; heavier system-capture tooling only if a real interchange consumer emerges. |
| Manubot (manuscript/citation pipeline) | SUPERSEDED | PF's deterministic compose (P13–P20) and canonical citation-identity audit (P21: DOI/arXiv/authoritative-URL match) cover the intent; no LLM-authored-manuscript pipeline needed. |
| showyourwork (reproducible-paper builds) | SUPERSEDED | The intent — every figure/number traceable to code — is PF's core design (deterministic P13/P14 generation, P34 independent clean rebuild), without a Snakemake/LaTeX-framework dependency. |
| Science Skills (agentic research skill packs) | SUPERSEDED | Thin frontend skills already exist (`frontends/`, `/complete-paper` wrappers around the same deterministic core); the core, not prompt packs, is the product. |
| Flowcept (agent telemetry/interception) | REJECTED_NO_CURRENT_NEED | PF already records receipts, provenance and run state deterministically; adding a telemetry-interception layer solves a problem the repo does not have. |
| AI Scientist (end-to-end autonomous paper generation) | REJECTED_NO_CURRENT_NEED | Contradicts the design: no mass production without a novelty gate, no self-approving loops, P36/P37 stay human. Documented as a non-goal in `docs/reports/ROADMAP_AUTONOMY.md`. |

### v1.2 leftovers deferred to v1.3 — disposition after v1.3 shipped

| Item | Classification | Rationale |
|---|---|---|
| `findings_map` full DAG/review-pipeline wiring | IMPLEMENTED (v1.3) | Production wiring shipped as `reviews/verification_ingest.py`: provider findings become `VF-<node>` review reports (same dedupe identity as native findings) and block U5 like native CRITICAL/MAJOR. PF remains closure owner; decisions.jsonl stays append-only and PF-written. |
| Reproduction Capsule (P10) | IMPLEMENTED (v1.3) | Versioned (`schema_version=1`), content-addressed (`capsule_digest`); commands/env/inputs/outputs/hashes/exit codes. P10 runs the declared capsule twice and gates on the six-class differential. Prerequisite for any workflow backend — satisfied by the Snakemake adapter shipping in the same release. |
| Stale-receipt freshness check | IMPLEMENTED (v1.3) | Shipped semantically, gate-wired: freshness is binding-based (run_id, store key, artifact hash at consumption time), not wall-clock age; a receipt that fails freshness can never satisfy a gate (`verification/contract.py::check_receipt_freshness`, wired through `dag/handlers.py`). The v1.2 red test has its green counterpart in `tests/test_verification_adversarial.py::test_stale_execution_receipt_still_loads_but_fails_freshness_at_consumption`. |
| SQLite schema versioning / state migration | IMPLEMENTED (v1.3) | `PRAGMA user_version` + migration registry in `state/store.py`; unknown newer schemas fail visibly. |
| Herdr / CLI-TUI hardening (dispatch stall window, `--no-herdr` DAG plumbing, receipt-internal validation) | V1_4 | **Still open.** Field-measured 2026-10-05: herdr's 5 s stall window is hard-coded upstream; the adapter workaround exists with honest evidence trade-off. The live field test additionally surfaced Claude's folder-trust dialog blocking the HoH developer pane (VH FAIL, differential MISMATCH). Tracked as MINOR/NIT in `docs/reports/DEFERRED_HARDENING.md`; subprocess-path verification evidence remains binding. |

## v1.3 — Reproducibility & Scientific Interchange (shipped)

Everything scoped for v1.3 in this roadmap shipped in v1.3.0 (see the
release row above and `docs/reports/V1_3_PILOT_MATRIX.md`): Reproduction
Capsule, the Snakemake backend behind the capsule contract, `findings_map`
wiring, reproducibility hardening (semantic receipt freshness, SQLite
migrations), and the pure export layer (W3C-PROV, RO-Crate 1.3 / Process
Run Crate, Workflow Card). Deliberately **not** shipped in v1.3:
Herdr/CLI-TUI hardening (moved to v1.4, see above), the literature
provider (still no real consumer), and Nextflow/CWL (conformance gate
unchanged).

## v1.4 — Multi-backend & attestation (shipped)

- Backend conformance suite (12 semantic cases × every reproduction backend).
- Nextflow backend behind the capsule contract; real 3-way proof (local +
  Snakemake + Nextflow → REPRODUCED_EXACT).
- CWL v1.2 as interchange **export** (no third runtime engine).
- GitHub Artifact Attestations for release artifacts (sdist/wheel attested on
  every `v*` tag; first attested release: v1.4.0). No SLSA level claimed;
  `SLSA_BUILD_REPRODUCED` needs ≥2 independently operated build platforms,
  which we do not have. Historical unsigned tags stay untouched.
- ReproZip: DEFER (`docs/reports/V1_4_REPROZIP_DECISION.md`).

## v1.5 — Evidence Intelligence (evaluated, no release)

All four gates decided without a release (`docs/reports/V1_5_DECISIONS.md`):
PaperQA2 benefit benchmark DEFER (defined, needs authorized LLM budget),
additional citation provider REJECT (no gap), provider SDK REJECT (<2 external
providers; conformance suite covers internal backends), reviewer ensemble
REUSED (dual-review value already measured in-repo; VeriHarness remains the
ensemble path).

## v2.0 — Contract stabilization (shipped)

Scope: contract inventory, schema v2 only on proven need, honest
cross-platform matrix, full conformance + failure injection, historical
state migration (v1.0–v1.4), docs sync, dual adversarial acceptance,
freeze reports. All items shipped in **v2.0.0** (see the release row
above): `docs/CONTRACTS.md`, `docs/reports/V2_0_SCHEMA_DECISION.md`,
`docs/reports/V2_0_PLATFORM_PACKAGING.md`,
`docs/reports/V2_0_CONFORMANCE_MATRIX.md`,
`docs/reports/V2_0_STATE_MIGRATION.md`.

## Post-v2 candidates (ungated backlog)

- Herdr / CLI-TUI hardening — the 5 s dispatch-stall window (hard-coded
  upstream), the Claude folder-trust dialog finding, `--no-herdr` DAG
  plumbing (`docs/reports/DEFERRED_HARDENING.md`).
- PaperQA2 benefit benchmark (once an LLM budget is authorized).
- Reproducible builds (payload-identical today; zip/tar timestamps prevent
  bit-identity) and multi-platform reproduced-build evidence.
- `ExecutionReceipt` name collision (verification vs reproduction receipt) —
  rename is bound to `schema_version=2`, not before
  (`docs/CONTRACTS.md` §2/§5, `docs/reports/V2_0_SCHEMA_DECISION.md`).
- Cryptographic attestation of receipts beyond the GitHub build path, once
  receipts are consumed outside this repo.

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
