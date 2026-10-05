# V2.0 WP-IV — Full Conformance Matrix + Failure Injection

Datum: 2026-10-05 · Worktree `.worktrees/v2-conformance` (Branch `v2.0/wp-iv-v`,
Basis 756c692) · Suite: **1071 Tests** (Baseline 1050 passed / 4 skipped + 21
neue WP-IV/WP-V-Tests), keine echten LLM/HoH/Netz-Zugriffe in der Suite
(`tests/e2e-config/paper-factory.yaml`: `hoh_nodes: []`).

Legende: **getestet** = grün in dieser Suite (Referenz) · **offen** =
ehrlich nicht von der Suite abgedeckt, mit Grund · **Limit** = gepinntes,
dokumentiertes Verhalten (Test verhindert stilles Wegwandern).

## 1. Scientific Core (P00–P37 DAG, U1–U16 Closure-Invarianten)

| Grenze / Fall | Status | Referenz |
|---|---|---|
| P00–P37 Node-Semantik, Claim–Evidence-Graph, Number-Provenance, Authority-Order T0–T4 | getestet (448) | `tests/test_real_pilot_gaps.py` |
| E2E-Synthetik (20 Szenarien inkl. False-Citation, Altered-Number, Secret-Leak, Forbidden-Prose-Origin) | getestet (20) | `tests/test_e2e_synthetic.py` (HoH-frei) |
| U5/U6/U8 Freeze/Scan-Invarianten, Bundle-Manifest, Hash-Pins, Symlink-Angriffe | getestet (67) | `tests/test_release_hardening.py` |
| P10-Capsule-Pfad statt Legacy-Heuristik | getestet (7) | `tests/test_p10_capsule.py` |
| Findings-Wiring P20-Chain, Review-Remediation | getestet (20) | `tests/test_findings_wiring.py` |
| Manuskript-/Figur-/Tabellen-Architektur | getestet (6) | `tests/test_figures_tables_manuscript.py` |
| Live-HoH-E2E | offen (Quota-Disziplin) | Suite startet nie echte HoH-Runs; echte Runs nur lokal via `scripts/run_live_hoh.py` |

## 2. Verification Plane (Contract / Freshness / Replay / Shadow)

| Grenze / Fall | Status | Referenz |
|---|---|---|
| Contract-Modelle, Strictness, Extra-Fields verboten, Statement-Hash | getestet (28) | `tests/test_verification_contract.py` |
| Shadow-Differential, INCOMPARABLE bei Lügen-Backend, LyingBackend | getestet (29) | `tests/test_verification_shadow.py` |
| Adversarial: korrupte Receipts, Stale/Freshness-Dimensionen, Replay via Store, Namespace-Falle, Lock-Serialisierung, Capability-Status | getestet (49) | `tests/test_verification_adversarial.py` |
| Findings-Map | getestet (19) | `tests/test_verification_findings_map.py` |
| Receipt-Digest zwischen Collect und Gate (Tamper) | getestet (neu) | `tests/test_failure_injection.py` + Guard in `paper_factory/dag/handlers.py` |
| VeriHarness-Adapter (41), Harness-Adapter (24), Provider-Router inkl. Forbidden-Family/Final-Prose | getestet | `tests/test_veriharness_adapter.py`, `tests/test_adapters.py`, `tests/test_router.py` |

## 3. Runtime Plane (Herdr)

| Grenze / Fall | Status | Referenz |
|---|---|---|
| Herdr-Hardening (Pane-Cleanup, Run-State-Disziplin) | getestet | `tests/test_verification_adversarial.py` §Cleanup (gemockt, fremde Tabs nie geschlossen) |
| Echte Herdr-Laufzeit unter Last | offen | Binary-abhängig; dokumentiert in `docs/reports/V1_3_WP1_HERDR_RUNTIME_HARDENING.md`, ehrlich NICHT in der Suite reproduzierbar |
| 1 Job/GPU, fremde Prozesse | offen (Betriebsregel) | Hausregeln, kein automatisierter Test sinnvoll |

## 4. Reproduction (3 Backends × 12 Fälle + 3-Way)

| Grenze / Fall | Status | Referenz |
|---|---|---|
| Input-Binding-Hash-Mismatch fail-visible | getestet ×3 Backends | `tests/conformance/test_reproduction_backends.py` |
| Output-Binding / Undeclared-Output / Backend-Identity / Failure / Timeout / Duplikat-Exaktheit / Partielle Outputs / Cleanup / Nondeterminismus-Deklaration / Receipt-Pflichtfelder / Metacharacter-Verbatim | getestet ×3 Backends | selbe Suite (12 Semantik-Fälle) |
| Native-Backend-N/A-Zeilen (kein externes Binary, kein Scratch) | ehrlich geskippt (2) | dieselbe Suite, Skip mit Grund |
| 3-Way-Reproduktion | getestet | `test_three_way_reproduced_exact` |
| Capsule-Digest (Kanonisierung, Order-Invarianz, Identity-Exklusion) | getestet (40) | `tests/test_reproduction_capsule.py` |
| Differential-Klassifikation (EXACT/SEMANTIC/NONDET/MISMATCH/UNAVAILABLE/INCOMPARABLE) | getestet (21) | `tests/test_reproduction_differential.py` |
| Native Runner (Pre-flight-Hashing, Undeclared/Deletion-Detection, Timeout) | getestet (14) | `tests/test_reproduction_runner.py` |
| expected_outputs-Tamper: Digest-Grenze by design, Export-Guard fängt Folge | getestet (neu) | `tests/test_failure_injection.py` |
| ReproZip/System-Level-Capture | offen (DEFER) | `docs/reports/V1_4_REPROZIP_DECISION.md` — Gate entschieden DEFER |

## 5. Workflow Backends

| Grenze / Fall | Status | Referenz |
|---|---|---|
| Snakemake-Backend | getestet (19) | `tests/test_snakemake_backend.py` |
| Nextflow-Backend | getestet (23) | `tests/test_nextflow_backend.py` |
| CWL-Export (Parameter-Referenz-Escaping, Staging, Hash-Pins, Identifier-Kollision fail-visible) | getestet (17) | `tests/test_export_cwl.py` |
| Docker/Container-Hints, Konfig-Metadaten | getestet | selbe Suite |

## 6. Provenance-Exporte (RO-Crate / PROV / CWL / Workflow Card)

| Grenze / Fall | Status | Referenz |
|---|---|---|
| RO-Crate 1.3 / Process Run Crate 0.6 (Struktur, Invarianten, Roundload) | getestet (16) | `tests/test_export_rocrate.py` |
| PROV-O (content-adressierte Entities, Aktivitäten, Assoziationen) | getestet (14) | `tests/test_export_prov.py` |
| Workflow Card (Disclaimer, keine Verdicts, Limitationen ehrlich) | getestet (12) | `tests/test_workflow_card.py` |
| Fehlende Pflichtdaten (completed ohne Outputs, fremde capsule_id/digest, keine Receipts) | getestet | ExportBundle-Validierung (`paper_factory/export/_shared.py`) + Export-Suites |
| Partielle Output-Abdeckung (deklariert, nicht geliefert) | getestet (neu) | Export-Guard + `tests/test_failure_injection.py` |

## 7. Release Hardening + Attestation

| Grenze / Fall | Status | Referenz |
|---|---|---|
| H1–H4/R2–R5 (Secrets inkl. UTF-16/32, Freeze-Tamper, Scan-Manipulation, Symlink-Angriffe) | getestet (67) | `tests/test_release_hardening.py` |
| Release-Attestation-Workflow (tags-only Trigger, minimale Permissions, actions/attest-Pflicht, kein Publish/Release) | getestet (neu, 6) | `tests/test_release_attestation_workflow.py` inkl. 5 Tamper-Simulationen |
| Historische Tags v1.2.0/v1.3.0 unsigned | Limit (by design) | Workflow-Kommentar, immutable history |

## 8. State Store + Migration

| Grenze / Fall | Status | Referenz |
|---|---|---|
| Schema-Versionierung, Legacy-v0-Migration, Backup-vor-Mutation, Idempotenz | getestet (6) | `tests/test_state_store_versioning.py` |
| Unbekanntes neueres Schema → SchemaVersionError, keine Mutation | getestet | selbe Suite + `tests/test_historical_state_migration.py` |
| Historische Pilot-States (v0 → 1, echte Kopien) | getestet lokal | `docs/reports/V2_0_STATE_MIGRATION.md` (nicht committed, keine Pilot-DBs im Repo) |
| Concurrent Writers (Serialisierung, Lock-Timeout fail-visible) | getestet (neu) | `tests/test_failure_injection.py` |
| `_node_artifact_refs` DB-Row-Trust | Limit (gepinnt) | selbe Datei — kein Re-Hash auf diesem Lesepfad, dokumentiert |

## 9. Optional Providers / Evidence Intelligence (v1.5-Gates)

| Grenze / Fall | Status | Referenz |
|---|---|---|
| PaperQA2 Literature Provider | offen (DEFER, Benefit-Gate definiert, Benchmark NOT_RUN) | `docs/reports/V1_5_DECISIONS.md` Gate A; Import-Block-Test grün mit/ohne Paket |
| Zusätzlicher Citation-Provider | offen (REJECT_NO_CURRENT_NEED) | Gate B |
| Provider-SDK | offen (REJECT_NO_CURRENT_NEED) | Gate C |
| Reviewer-Ensemble via VeriHarness | offen (VALUE ALREADY MEASURED, kein Code) | Gate D |
| arXiv-Policy-Compliance | getestet (48) | `tests/test_arxiv_compliance.py` |

## Zusammenfassung

48 Matrix-Zellen insgesamt:

- **38** vollständig grün in der Suite (davon 8 durch WP-IV neu abgesichert:
  Receipt-Digest-Guard, Export-Coverage-Guard, Capsule-Tamper-Kette,
  Attestation-Guard, Concurrent-Writers, Historical-Migration-Fixtures).
- **1** lokal verifiziert statt committed (Historische-Pilot-Migration —
  echte Pilot-DBs werden nicht ins Repo genommen, siehe
  `V2_0_STATE_MIGRATION.md`).
- **2** gepinnte Limits (unsigned historische Tags by design; DB-Row-Trust
  auf einem Lesepfad) — als Test verankert, damit sie nicht still zu
  "Verifikation" aufblühen.
- **7** ehrlich offen (Live-HoH-E2E, Herdr-Laufzeit unter Last,
  ReproZip-System-Capture, PaperQA2 + 3 weitere v1.5-Provider-Gates) —
  alle mit dokumentiertem Grund, keines still.
- Suite-Gesamt: 1071 Tests, davon 1067 erwartet grün / 4 ehrlich geskippt
  (2 Conformance-N/A-Zeilen native Backend, 2 binary-abhängig).

> Correction addendum (2026-10-05, review A MINOR): after merging WP-I..III
> the final v2.0 suite measures **1074 collected = 1070 passed + 4 skipped**
> (the 3 packaging-asset tests arrived with the merge). The 1071/1067 figures
> above are the pre-merge worktree measurement; kept for provenance, the
> merged numbers are authoritative (README/CHANGELOG).
