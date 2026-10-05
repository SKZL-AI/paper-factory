# Deep Research Delta — Post v1.2

Date: 2026-10-05 · Branch: `v1.3/reproducibility-interchange` · Audience: public repo
Status: **planning delta document** — classifies the recommendations of the external
deep-research masterplan (a historical planning artifact, kept unchanged) against the
repository reality after the v1.2.0 release, and records which external factual claims
were verified against primary sources.

**Research is not a source of truth.** Priority of truth (unchanged):
repository reality > VeriHarness integration > research recommendations. Nothing is
planned just because a report says so; every entry below is grounded in shipped code,
a tracked DEFER decision, or an explicit rejection. PF-internal provenance remains the
canonical scientific truth; RO-Crate, W3C-PROV and any other standard format enter as
**pure exporters**, never as a second provenance engine.

## 1. Baseline: what v1.2.0 already delivered

v1.2.0 is released and immutable (annotated tag `v1.2.0` on `02f722d`). Verified facts:

- **Verification Plane**: versioned contract (`schema_version=1`: `WorkPackage` /
  `VerificationResult` / `BackendIdentity`), in-process backend registry, capability
  negotiation reusing the existing doctor/inventory probes, generalised VeriHarness
  adapter (two façades, one run flow).
- **Shadow / differential mode**: `DifferentialReceipt` with MATCH / SEMANTIC_MATCH /
  MISMATCH / PROVIDER_UNAVAILABLE / INCOMPARABLE; observational only, never changes a
  verdict.
- **Real positive end-to-end proof**: PF WorkPackage → real VeriHarness/HoH run
  `PF-938286ae-P05` → real receipts (8, SHA-256 registered) → `VerificationResult`
  → **Differential MATCH**. Full evidence: `docs/reports/V1_2_REAL_VERIHARNESS_INTEGRATION_PROOF.md`
  and `docs/reports/v1_2_integration_proof.json`; reproducible entry point
  `scripts/run_integration_proof_v12.py`.
- **Test suite**: 769 passed + 2 honest environment skips; adversarial dual review
  A/B = JA/JA; 0 open CRITICAL, 0 open MAJOR.
- **Honest limitations** (documented, not hidden): the real proof ran via
  `HarnessDispatcher --no-herdr` because herdr's hard-coded 5 s stall window deadlocks
  newer CLI TUI panes (live field-measured 2026-10-05); the MATCH binding is by
  construction identical on both sides (caller-declared package manifest, no
  independent re-hash); pane-provenance evidence (A01/A02/A12) is absent on the
  `--no-herdr` path. Tracked in `docs/reports/DEFERRED_HARDENING.md`.
- **P37**: NOT EXECUTED. No external scientific submission, ever, autonomously.

Architecture roles are fixed: **Paper Factory = Scientific Control Plane** (owns
P00–P37, U1–U16, evidence authority, protected prose, P36/P37), **VeriHarness/HoH =
Verification Plane**, **Herdr = Runtime Plane**.

## 2. Recommendations superseded by v1.2 / VeriHarness reality

The earlier research report pre-dates the Verification Plane. The following
recommendations are **SUPERSEDED** — the need they describe is already covered:

| Original recommendation | Status | Why |
|---|---|---|
| Versioned verification contract | IMPLEMENTED (v1.2) | `schema_version=1`, strict Pydantic models, round-trip tested, unknown versions fail visibly. |
| Capability negotiation / backend registry | IMPLEMENTED (v1.2) | `registry.py` + `capabilities.py` reuse existing doctor probes; no parallel discovery stack. |
| Independent verification kernel (reviewer orchestration, isolation, receipts) | IMPLEMENTED_VIA_VERIHARNESS | VeriHarness/HoH core competence; PF contributes one small harness-neutral adapter. Real receipts, real run, real MATCH. |
| Shadow / differential verification | IMPLEMENTED (v1.2) | `shadow.py`; real MATCH proof recorded 2026-10-05. |
| AI peer review (LLM reviewers as independent checkers) | IMPLEMENTED_VIA_VERIHARNESS | PF-native P23–P26 review exists; further reviewers enter as VeriHarness ensembles behind the same contract. Review is a gate, never an approval — P36 stays human. |
| DeltaSci / sourcecheck-style external checkers | IMPLEMENTED_VIA_VERIHARNESS | Independent checking is the Verification Plane's job; any such tool plugs into the `VerificationBackend` protocol. No dedicated adapter without a real consumer. |
| Manubot / showyourwork / Science Skills | SUPERSEDED | PF's deterministic compose (P13–P20), citation-identity audit (P21) and clean-rebuild (P34) cover the intent without external framework dependencies. |

## 3. New delta points (v1.3 → v1.4), with external-claim verification

Each external factual claim from the masterplan was verified against primary sources
on 2026-10-05. Full source list in §5.

### 3.1 Reproduction Capsule with content-addressed identity — v1.3, ADOPT

The capsule is a versioned, harness-neutral contract (commands, environment, inputs,
outputs, hashes, exit codes) for P10 — plus a **stable content-addressed
`capsule_digest`** over exactly those inputs that semantically determine the
scientific computation (code/config/input hashes, declared parameters,
dependency/environment identity, relevant platform identity). mtimes and random
runtime fields (timestamps) are excluded from the deterministic digest.
`execution_id` (one concrete run) stays separate from `capsule_digest` (semantic
reproduction identity). Round-trip tests; unknown schema versions fail visibly.

- The report's OxyMake reference is treated as **non-binding inspiration only**
  (principle adopted, tool not integrated; OxyMake itself UNVERIFIED, see §5).
- This matches PF's existing content-addressed evidence philosophy and does not make
  P10's historical DEGRADED state a fake PASS — it gives *new* projects a way to
  declare and prove reproducible commands.
- *Korrektur-Provenance (2026-10-05, v1.3-Fixloop nach dem Dual-Review des
  v1.3-Diffs): Präzisierung, nicht Widerruf.* „Does not make P10's historical
  DEGRADED state a fake PASS" galt im Kontext des Übergangs (kein
  Rückwirkendes Umwerten historischer DEGRADED-Befunde). Es darf aber nicht
  so gelesen werden, als wäre *jeder* P10-PASS ein „Paper reproduziert".
  Nach dem Fixloop ist P10-PASS definiert als: **die deklarierte Kapsel
  reproduziert sich selbst** (Detail-Feld `scope: "declared capsule
  reproduces itself"`, statistics/reproducibility.py) — verifiziert gegen
  die deklarierten code/input-Refs mit sha256-Bindung; eine Kapsel ohne
  code_refs UND input_refs ist Self-Attestation und wird DEGRADED statt
  PASS. Die Bindung des P10-Ergebnisses an die Claims/Evidenz des Papers
  (P04/P08) bleibt ausdrücklich ein v1.4+-Thema; P10-PASS allein ist nie
  Claim-Beweis.

### 3.2 Snakemake as the first workflow consumer — v1.3, ADOPT (gated)

CONFIRMED: Snakemake officially supports reproducible software environments via
Conda environment files and containers (integrated package management; Conda +
Apptainer/Singularity/Docker combinable).

Architecture (unchanged from the masterplan):

```text
Reproduction Capsule
        |
        +-- PF Local Runner   (first, native consumer)
        |
        +-- Snakemake Backend (thin adapter, only after the capsule contract is stable)
```

Snakemake never becomes PF's orchestrator; no Snakemake semantics leak into the core
contract. Real proof gate: same capsule → local and Snakemake → identical output
hashes (or honestly justified semantic equality). Backend-conformance tests start here.

### 3.3 RO-Crate 1.3 / Workflow Run RO-Crate / Provenance Run Crate — v1.3, ADOPT as export layer

All three external claims CONFIRMED against primary sources (§5, rows 1–3):

- **RO-Crate 1.3** is published (2026-06-22, status: Recommendation).
- **Workflow Run RO-Crate 0.6** exists (profiles 0.6.0, released 2026-09-07, with
  explicit "Profile updates for RO-Crate 1.3") and models the provenance of
  computational workflow executions.
- **Provenance Run Crate 0.6** extends Workflow Run Crate 0.6 and models individual
  step executions (ControlAction/HowToStep) and intermediate outputs, on RO-Crate 1.3
  terminology.

This is the strongest delta addition: a Paper Factory release is logically a Research
Object (manuscript, code, inputs, outputs, environment, run evidence), and the WRROC
profiles model exactly the run/step/artifact granularity PF already records. Plan:

```text
               PF canonical provenance
                        |
             Reproduction Capsule
                        |
              +---------+---------+
              |                   |
       RO-Crate / WRROC      W3C PROV
       research object       interchange
```

- Mapping/exporter only. **No RO-Crate model in the scientific core semantics.**
- Preferred first real consumer: Reproduction Capsule / Release Bundle export.
- Conformance tested against the current profiles where practical.
- PF-internal provenance (firewall, origin receipts) remains authoritative.

### 3.4 W3C-PROV export — v1.3, ADOPT as export only

Unchanged from the existing roadmap: PF canonical provenance → W3C-PROV-compatible
representation. If the RO-Crate path offers a suitable PROV mapping, reuse it instead
of building a second mapping engine. Round-trip is not forced to be identity where
the target format abstracts; defined exported invariants are tested instead. The
v1.2 DEFER reason (no consumer) is lifted by the Reproduction Capsule / Release
Bundle consumer in §3.3.

### 3.5 Workflow Cards — v1.3, ADOPT as derived summary

CONFIRMED (§5, row 9): "Workflow Cards: Structured Summaries of Workflow Executions
Using Provenance Data" (arXiv 2608.11022, 2026) — compact, human- and LLM-readable
summaries derived from machine-readable provenance, evaluated to improve workflow
question answering over direct schema querying.

PF adoption is deliberately small: the card is **derived exclusively from canonical
machine evidence** (receipts, capsule, provenance) and is never a source of truth or
gate input. Very little code, potential high reviewer/human value.

### 3.6 SLSA 1.2 / GitHub Artifact Attestations — v1.4 inspiration, ADOPT with strict honesty

All external claims CONFIRMED (§5, rows 4–5):

- GitHub Artifact Attestations are available for **public repositories** on Free/Pro/
  Team plans, generated in **GitHub Actions** via `actions/attest`, and verified with
  `gh attestation verify`.
- SLSA v1.2's build-provenance predicate defines builder identity (`builder.id`),
  build type (`buildType`), external parameters (`externalParameters`), and
  subject digests (in-toto Statement / ResourceDescriptor). The verified property
  **`SLSA_BUILD_REPRODUCED`** exists in the SLSA v1.2 verified-properties
  specification: issuable only when the artifact has provenance from **two or more
  independently operated Build Platforms trusted by the VSA issuer**.

Rules adopted verbatim from the masterplan:

- The published v1.2.0 tag is annotated but unsigned — **do not touch it
  retroactively** (verified=false / reason=unsigned is a documented fact, not a
  defect to repair by rewriting history).
- For future releases actually built in GitHub Actions: generate artifact
  attestations, verify them in CI with `gh attestation verify`.
- **No invented SLSA levels.** Structures may be reused and compatible claims
  exported, but a formal level or a `SLSA_BUILD_REPRODUCED` claim may only be made
  when its prerequisites are demonstrably met (two *independent* build platforms, not
  two runs on the same runtime).
- Scientific provenance and software-build provenance stay strictly separated:
  "this wheel came from this GitHub workflow" ≠ "this number came from this evidence
  artifact".

### 3.7 Nextflow — v1.4, DEFER behind stable contract

Second backend only after the capsule contract is stabilised and a backend-conformance
suite exists (input/output binding, environment, failure, timeout, resume, hashing,
duplicate execution, partial outputs, cleanup, nondeterminism declarations, receipts).
No Nextflow semantics in the core. The report's motivation (containers, HPC/cloud,
resume, intermediate results) is plausible but is a consumer argument, not a checklist
argument.

### 3.8 CWL — v1.4+, primarily INTERCHANGE, not a third runtime

CONFIRMED (§5, row 7): CWL v1.2.x self-describes as a vendor-neutral standard for
representing analysis tasks, aimed at portable execution across platforms. Plan:
evaluate whether a meaningful subset of the Reproduction Capsule exports losslessly to
CWL CommandLineTool/Workflow; if yes, build exporter + import validation. A full
third runtime backend only with a real consumer — no runner built for feature lists.

### 3.9 PaperQA2 — v1.5, CONDITIONAL (benefit gate)

CONFIRMED (§5, row 8): PaperQA2 is an agentic scientific RAG system with LLM-based
re-ranking and contextual summarization, evidence gathering, and in-text citations,
supporting multiple LLMs via LiteLLM. This matches the repo's long-standing
assessment of quality — but the v1.2 inventory still holds: `paperqa` is imported
nowhere in the code, so a `LiteratureProvider` interface has zero real consumers and
violates our own "no abstraction without a second consumer" rule.

Condition (unchanged): PF-native P06 stays canonical until a real pilot benchmark
shows measurable PaperQA2 benefit (coverage, precision, citation identity, source
traceability, contradiction detection, runtime/cost, failure behaviour) without
diluting evidence authority. No benefit → documented REJECT_NO_CURRENT_NEED; PF-native
remains.

### 3.10 ReproZip — v1.4 decision gate, CONDITIONAL

Not implemented automatically. Only if real capsule pilots demonstrate a system-level
dependency-capture gap the PF capsule cannot cover, and a real consumer exists, an
isolated ReproZip adapter/exporter pilot may be built. Never a core dependency.

## 4. Explicitly NOT adopted

| Proposal | Decision | Reason |
|---|---|---|
| Retroactively signing/replacing the v1.2.0 tag | REJECT | Published tags are immutable; attestation starts with future releases. |
| Claiming a formal SLSA level or `SLSA_BUILD_REPRODUCED` now | REJECT | Prerequisites (independent build platforms, VSA issuer trust model) not met; claims only when demonstrably true. |
| OxyMake integration | REJECT (principle reused) | Content-addressed reuse-decision principle adopted for capsule identity; the tool itself is not integrated (also UNVERIFIED, §5). |
| Nextflow/CWL as immediate v1.3 backends | DEFER | No stable capsule contract, no conformance suite, no real consumer yet. |
| PaperQA2 as default literature path | DEFER (benefit gate) | Zero current consumers in-repo; PF-native P06 canonical. |
| Broad provider/plugin SDK now | REJECT | No abstraction with zero or one consumer; SDK only after ≥2 independent provider implementations of the same contract class. |
| Flowcept (agent telemetry interception) | REJECTED_NO_CURRENT_NEED | PF records receipts/provenance/run state deterministically; telemetry interception solves a problem the repo does not have. |
| AI Scientist (end-to-end autonomous paper generation) | REJECTED_NO_CURRENT_NEED | Contradicts the design: no novelty-gate-free mass production, no self-approving loops, P36/P37 stay human. |
| ReproZip-class heavy capture capsules | CONDITIONAL | Decision gate (§3.10); PF capsule is the primary, contract-bound format. |
| Second reviewer-orchestration stack inside PF | REJECTED | VeriHarness is reused; review is never self-approval. |

## 5. Verification of external claims (checked 2026-10-05)

Status legend: CONFIRMED = primary source verifies the claim · PARTIALLY = core of the
claim confirmed, material nuance or sub-claim differs/missing · UNVERIFIED = not
checked against a primary source (treated as non-binding).

| # | Claim (as stated in the masterplan) | Status | Primary source(s) |
|---|---|---|---|
| 1 | RO-Crate 1.3 was released in 2026 (specification status) | CONFIRMED | Spec page: "Published: 2026-06-22", "Status: Recommendation" — https://www.researchobject.org/ro-crate/specification/1.3/index.html · Announcement: https://www.researchobject.org/ro-crate/blog/2026-06-23/announcing-ro-crate-1-3 |
| 2 | Workflow Run RO-Crate 0.6 exists, is adapted to RO-Crate 1.3, and models workflow executions | CONFIRMED | Profiles 0.6.0 released 2026-09-07, changelog explicitly lists "Profile updates for RO-Crate 1.3 (#104)" — https://github.com/ResearchObject/workflow-run-crate/releases · "capture the provenance of the execution of computational workflows" — https://www.researchobject.org/workflow-run-crate/ |
| 3 | Provenance Run Crate models individual step executions and intermediate outputs | CONFIRMED | Profile v0.6, extends Workflow Run Crate 0.6, "describe internal details of the workflow run, such as step executions and intermediate outputs"; uses RO-Crate 1.3 terminology — https://www.researchobject.org/workflow-run-crate/profiles/provenance_run_crate/ |
| 4 | GitHub Artifact Attestations are available for public repositories via GitHub Actions; verification via `gh attestation verify` | CONFIRMED | "On GitHub Free, Pro, or Team plans, artifact attestations are only available for public repositories"; generation via `actions/attest` step; `gh attestation verify <artifact> -R <org>/<repo>` — https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds |
| 5 | SLSA 1.2 defines builder identity, subject digest, build type, external parameters; the property `SLSA_BUILD_REPRODUCED` exists | CONFIRMED (nuance) | v1.2 provenance predicate: `builder.id`, `buildType`, `externalParameters`, subject digests via in-toto Statement/ResourceDescriptor — https://slsa.dev/spec/v1.2/build-provenance · `SLSA_BUILD_REPRODUCED`: "reproduced by two or more independently operated Build Platforms trusted by the VSA issuer" — https://slsa.dev/spec/v1.2/verified-properties · Nuance: it is a **VSA verified property** (verification summary), not a field inside the provenance predicate; the masterplan's description matches the spec's intent. |
| 6 | Snakemake supports reproducible environments via Conda + containers | CONFIRMED | Official docs "Distribution and Reproducibility" / integrated package management: per-rule Conda environments, combination of Conda with (Apptainer/Singularity/Docker) containers — https://snakemake.readthedocs.io/en/stable/snakefiles/deployment.html |
| 7 | CWL v1.2.x is a vendor-neutral workflow standard | CONFIRMED | "a vendor-neutral standard for representing analysis tasks where a sequence of steps …", portability across platforms — https://www.commonwl.org/v1.2/Workflow.html (v1.2.1 errata documented at https://www.commonwl.org/v1.2/CommandLineTool.html) |
| 8 | PaperQA2: agentic literature RAG with re-ranking, evidence, citations | CONFIRMED | "engineered to be the best agentic RAG model for working with scientific papers"; "LLM-based re-ranking and contextual summarization (RCS)"; "grounded responses containing in-text citations"; agentic evidence gathering; multiple LLMs via LiteLLM — https://github.com/Future-House/paper-qa · Paper: Skarlinski et al. 2024, https://arxiv.org/abs/2409.13740 |
| 9 | (Context) Workflow Cards: 2026 work, provenance-derived human/LLM-readable run summaries that improve question answering over schema querying | CONFIRMED | Marchioro 2026, "Workflow Cards: Structured Summaries of Workflow Executions Using Provenance Data" — https://arxiv.org/abs/2608.11022 |
| 10 | (Context) OxyMake: content-addressed reuse-decision keys over rule source/input/parameters/environment | UNVERIFIED | No primary source checked; used only as non-binding inspiration for the capsule-digest principle (§3.1). Not load-bearing for any decision. |

### Deviations / nuances relative to the masterplan's wording

1. **SLSA_BUILD_REPRODUCED scope** (row 5): the property lives in the *verification
   summary* layer (VSA `verifiedLevels`), issuable only by a VSA issuer, and requires
   build provenance from two or more *independently operated, issuer-trusted* build
   platforms. The masterplan's caution ("nicht behaupten, solange Voraussetzungen
   nicht erfüllt") is exactly right and is adopted verbatim.
2. **SLSA field attribution** (row 5): builder identity / build type / external
   parameters are fields of the provenance *predicate* (`builder.id`, `buildType`,
   `externalParameters`); the subject digest is part of the in-toto Statement's
   `subject` (ResourceDescriptor). The masterplan groups them loosely as "SLSA 1.2
   verification properties" — substance confirmed, terminology tightened here.
3. **CWL currency** (row 7): v1.2.x (with the v1.2.1 errata) is the current stable
   line; a v1.3 exists in draft. The plan targets the stable v1.2.x semantics.
4. **OxyMake** (row 10): deliberately not verified and not integrated; the
   content-addressing *principle* is retained because it matches PF's existing
   evidence philosophy.
5. All other factual claims (rows 1–4, 6, 8) verified as stated, with dates above.

## 6. Source of truth — restated

- Research ≠ Source of Truth. This delta document classifies recommendations; it does
  not create obligations. Repo evidence wins every conflict.
- **PF canonical provenance remains the single scientific truth** (P00–P37, U1–U16,
  evidence authority, protected prose, P36 human sign-off, P37 never executed
  automatically). RO-Crate / WRROC, W3C-PROV, Workflow Cards and any SLSA-aligned
  release metadata are **exporters or derived summaries** — they are never gate
  inputs unless the underlying receipts are verified, and they never replace PF
  closure ownership.
- VeriHarness/HoH remains the Verification Plane; Herdr the Runtime Plane. No
  ownership inversion.

## 7. References (repo-internal)

- `docs/ROADMAP.md` — canonical classification of research recommendations.
- `docs/reports/V1_2_REAL_VERIHARNESS_INTEGRATION_PROOF.md` + `v1_2_integration_proof.json` — v1.2 real MATCH proof.
- `docs/reports/DEFERRED_HARDENING.md` — v1.2 DEFER decisions, review addenda (2026-10-04/05), herdr stall-window findings.
- `docs/reports/ROADMAP_AUTONOMY.md` — autonomy boundaries (P37, no self-approval).
