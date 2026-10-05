# Changelog

## [1.3.0] — 2026-10-05

Reproducibility & Scientific Interchange:

- **Reproduction Capsule** (`paper_factory/reproduction/`): versioned,
  harness-neutral contract with content-addressed `capsule_digest`
  (code/config/input hashes, deterministic parameters, environment identity —
  never timestamps or mtimes); `execution_id` strictly separate
- **Native local runner** with declared-input pre-flight, undeclared-output
  detection (create/modify/delete), honest failure/timeout receipts
- **Reproduction differential** with six classifications
  (REPRODUCED_EXACT / REPRODUCED_SEMANTIC / MISMATCH /
  NONDETERMINISTIC_DECLARED / UNAVAILABLE / INCOMPARABLE); semantic match only
  via declared domain rules
- **Snakemake backend** (optional extra `snakemake`): same capsule → local and
  Snakemake → real REPRODUCED_EXACT proof
- **P10 integration**: a project declaring
  `.paper-factory/reproduction/capsule.json` gets a real PASS/FAIL gate instead
  of honest DEGRADED (scope honestly labelled: the declared capsule reproduces
  itself; capsules without code+input refs degrade as self-attestation-only)
- **Semantic receipt freshness**, gate-wired: receipts bound to artifact
  binding / backend / run / contract version; replay and cross-run detection
  via store namespace; receipt-internal run_id validation in the VeriHarness
  adapter
- **SQLite state versioning**: `PRAGMA user_version`, migration registry,
  backup before migration, unknown-newer fail-visible
- **findings_map production wiring**: external provider findings enter the PF
  review pipeline as `VF-<node>` reports (U5-blocking); PF remains finding and
  closure owner — provider findings never overwrite an AUTHOR_DECISION
- **Export layer (EXPORT ONLY)**: RO-Crate 1.3 / Process Run Crate 0.6,
  W3C-PROV (PROV-JSON), Workflow Cards (derived, never a gate input)
- v1.3 pilot matrix: synthetic end-to-end reproduction pilot (P10 PASS,
  REPRODUCED_EXACT), unchanged-pilot regression (bit-identical), failure
  injection — `docs/reports/V1_3_PILOT_MATRIX.md`
- 968 tests passing (+2 honest environment skips); dual adversarial review
  A/B = JA/JA; 0 open CRITICAL/MAJOR

## [1.2.0] — 2026-10-05

Verification Plane:

- Versioned verification contract (`paper_factory/verification/`,
  `schema_version=1`): WorkPackage / VerificationResult / VerificationFinding /
  ArtifactRef / EvidenceRef / BackendIdentity / ExecutionReceipt as strict
  Pydantic models; unknown schema versions fail visibly
- Capability negotiation (`CapabilityStatus`) reusing doctor/inventory probes
- Generalised VeriHarness/HoH adapter: one run flow, two façades
  (generic `verify(WorkPackage)` + legacy DAG shim)
- Shadow / differential verification (`DifferentialReceipt`: MATCH /
  SEMANTIC_MATCH / MISMATCH / PROVIDER_UNAVAILABLE / INCOMPARABLE) —
  observational, never changes a node verdict
- Real integration proof: run `PF-938286ae-P05`, hoh 0.1.0 @ `5d576bd`,
  PF-native PASS + VeriHarness PASS → differential MATCH
  (`docs/reports/V1_2_REAL_VERIHARNESS_INTEGRATION_PROOF.md`)
- 769 tests passing (+2 environment skips); dual review A/B = JA/JA

## [1.1.0] — 2026-10-04

arXiv compliance layer (P32 extension), verified against primary arXiv
sources on 2026-10-04:

- New checks for venue `arxiv`: structured AI-use disclosure
  (`ai_disclosure.yaml`, GAIDeT vocabulary, fail-closed), no-LLM-authorship
  scan, chatbot meta-comment scan, English-language check, license allowlist
  (6 arXiv options), filename/figure rules, self-overlap detection,
  cs review/position-paper journal-reference rule
- Advisory `arxiv_submission_preflight.json` (rate limits 2/month + 3 active
  since 2026-10-01, endorsement, license irrevocability)
- New CLI command: `paper-factory compliance --target arxiv`
- `paper` config gains `license`, `type`, `category`, `journal_ref`
- Docs: `docs/ARXIV_COMPLIANCE.md` with the verified policy mapping
- 44 adversarial tests

## [1.0.1] — 2026-10-04

Repository professionalization (no pipeline-semantics change):

- GitHub CI green on Python 3.11/3.12 (TeX/pandoc toolchain in the workflow,
  honest skips for machine-dependent adapter tests)
- MIT LICENSE file, CITATION.cff, professional README, position paper
  (`docs/paper/`), reports moved to `docs/reports/`, machine paths
  desensitized

## [1.0.0] — 2026-10-02 (v1.0 Freeze)

First public release. Evidence-first, harness-neutral research-paper
production core, validated end-to-end on a real pilot paper.

- Deterministic P00–P37 research DAG with persistent state and receipts
- Global closure invariants U1–U16 (claim support, citation identity,
  number-to-metric binding, remediation integrity, external-edit reconciliation)
- VeriHarness/HoH verification-kernel adapter; provider router with
  Claude/Kimi/Codex/Pi/OpenCode/GLM/LiteLLM worker adapters
- Microsoft Word + Paperpal integration (ownership-scoped, capture-only)
- Citation verification incl. authoritative-URL path for no-DOI sources
- Durable human decisions with collision-hardened finding identity
- arXiv-ready release packaging; P36 human sign-off; P37 never automatic
- 574 tests (+2 Windows-only environment skips); 245 unique writing-assistant suggestions
  processed capture-only, 100 % dispositioned (75 applied, 124 rejected,
  46 not applicable)

Evidence: `V1_FREEZE_REPORT.md`, `docs/reports/FINAL_ACCEPTANCE_2026-10-02.md`.
