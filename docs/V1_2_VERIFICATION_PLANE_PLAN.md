# PAPER FACTORY v1.2 — Verification Plane & Modular Provider Architecture

Status: **PLAN (implementiert auf Branch `v1.2/verification-plane`, kein Release)**
Erstellt: 2026-10-04 · Baseline: HEAD `e1ccaac` (v1.1.0), Suite 622 passed + 2 env-skips

Dieser Plan evaluiert den externen v1.2-Vorschlag gegen den tatsächlich
inventarisierten Code (2026-10-04, zwei unabhängige Read-only-Inventuren von
`/home/sai/paper-factory` und `/home/sai/veriharness`). Jede Empfehlung ist als
**REUSE / ADAPT / GENERALIZE / DEFER / REJECT** eingestuft. Nichts wird
implementiert, nur weil es in einem Bericht steht.

## 0. Baseline (empirisch)

| Punkt | Wert | Beleg |
|---|---|---|
| CURRENT_HEAD | `e1ccaac` (Tag v1.1.0) | git |
| CURRENT_VERSION | 1.1.0 → Branch trägt `1.2.0.dev0` (PEP-440-Dev, kein Release) | pyproject.toml |
| CURRENT_TEST_RESULT | 622 passed, 2 skipped (46.8s) | pytest-Log |
| CURRENT_VH_VERSION | hoh 0.1.0, `v0.1.0-18-g5d576bd`, main clean | /home/sai/veriharness |
| PF↔VH-Integration | `adapters/veriharness/adapter.py` (263 Z.), einziger Einhängepunkt: `dag/handlers.py:120-181` Wrapper | Inventur |
| HoH-fähige Nodes | `VERIHARNESS_CAPABLE = {P04,P05,P07,P09,P10,P16,P17,P18,P20}` (handlers.py:117), Config `hoh_nodes`, Default `["P05"]` | handlers.py:117, core/config.py:60-68 |
| VeriharnessAdapter Unit-Tests | **keine** (nur E2E-Receipt-Lesetest, gemockte allgemeine Adapter-Tests) | tests/ |
| paperqa im Code | **nirgends importiert** — nur pyproject-Extra, unbenutzter `LiteratureCfg.paperqa2`-Schalter, Inventory-Probing | Inventur |
| State-Schema | SQLite (`runs.sqlite`), **keine Schema-Versionierung** | state/store.py:16-51 |
| Modellierungsstil | Pydantic v2 (Main-Dependency) für Config/Findings/Claims/Receipts | pyproject.toml:10 |
| VH-Contracts | Pydantic v2, `schema_version = 1` an RunState/SpecAmendment/DispatchRecord/ProjectState; CLI-first (`hoh start`/`hoh run`) ist der supported Integrationspfad, `hoh/__init__.py` leer | /home/sai/veriharness Inventur |

Doku-Drift-Befund: README nennt 574 Tests (Stand v1.0); aktuell 622.
Wird in WP9 korrigiert.

## 1. Architektur-Leitplanken (unverhandelbar)

- PF bleibt alleiniger Owner von P00–P37, U1–U16, T0–T4-Evidence-Authority,
  Protected-Prose-Firewall, P36/P37. VeriHarness setzt niemals U-Invarianten
  und schreibt niemals Finalprosa.
- VeriHarness/HoH = Verification Plane: verifiziert übergebene Work Packages
  gegen ihren Contract. Herdr = Runtime Plane (unverändert).
- Kein optionaler Provider wird Core-Hard-Dependency. Fehlt VH/PaperQA/Herdr,
  läuft PF weiter (ehrlich DEGRADED/UNAVAILABLE, nie False-PASS).
- PF-native Verifikation wird in v1.2 **nicht entfernt**. Shadow-Mode sammelt
  Evidenz, verändert keine wissenschaftliche Wahrheit.
- Tests starten nie echte HoH-/LLM-/Netzwerk-Aufrufe.

## 2. Capability-Matrix (P00–P37)

Legende: **N** = PF_NATIVE, **V** = VH_CAPABLE (handlers.py:117),
**U** = VH_CURRENTLY_USED (Default hoh_nodes), **H** = HUMAN_ONLY,
**X** = NOT_APPROPRIATE_FOR_DELEGATION.

| Node | Art | Klasse | Begründung / Side-Effects |
|---|---|---|---|
| P00 Doctor | det. | N, X | Maschinen-Inventur, kein Delegationssinn |
| P01 Intake | det. | N, X | Datei-Ownership |
| P02 Context Mining | agent | N | LLM-Agent über ProviderRouter |
| P03 Research Reconstr. | agent | N | LLM-Agent |
| P04 Evidence Inventory | verif. | N+V | Kandidat Shadow (det. + VH) |
| P05 Result Integrity | verif. | N+V+U | einziger Default-HoH-Node |
| P06 Literature Discovery | det. | N | Netz (OpenAlex/Crossref); VH nicht sinnvoll |
| P07 Novelty Attack | verif. | N+V | Kandidat Shadow |
| P08 Claim Graph | agent | N | Ownership Claim-Semantik |
| P09 Statistics | verif. | N+V | Kandidat Shadow |
| P10 Reproducibility | verif. | N+V | aktuell häufig DEGRADED; Capsule → v1.3 |
| P11/P12 Figure/Table Plan | agent | N | LLM-Agent |
| P13/P14 Figure/Table Gen | det. | N, X | erzeugt Artefakte (side effects) |
| P15 Manuscript Arch. | agent | N | Ownership |
| P16–P18, P20 Prose-Nodes | agent | N+V | VH verifiziert nur, schreibt nicht (U15) |
| P19 Discussion | agent | N | final prose, kein VH-Flag |
| P21 Citation Audit | det. | N | kanonisch, Netz; externe Resolver nur ergänzend |
| P22 Numbers/Units | det. | N | kanonisch |
| P23–P26 Reviews | agent | N | Findings-Ownership PF; VH-Findings nur normalisiert |
| P27 Remediation | agent | N, X | schreibt Finalprose (Firewall) |
| P28 Freeze | det. | N, X | Closure-Vorstufe |
| P29/P30 Language/SemDiff | agent | N | |
| P31 Paperpal | det. | N, X | Windows-UI-Automation, nicht VH-delegierbar |
| P32 Venue Compliance | det. | N | kanonisch (v1.1) |
| P33/P34 Export/Rebuild | det. | N, X | Build-Side-Effects |
| P35 Global Closure | det. | N, X | **nie delegierbar** (U1–U16) |
| P36 Sign-Off | human | H | |
| P37 Submission | human | H | **wird nie automatisch ausgeführt** |

Pro Capability relevante Metadaten (Inputs/Outputs/Evidence/Failure-Semantik)
sind bereits im Code verankert: `Node`-Dataclass (dag/nodes.py:17-26),
`NodeOutcome(verdict, detail)` (dag/executor.py), `Verdict`-Enum mit
`blocks_closure` (core/results.py:7-65). Der v1.2-Contract referenziert diese,
statt ein Parallelmodell zu bauen.

## 3. Einstufung der Berater-Phasen

| Phase | Votum | Begründung |
|---|---|---|
| 0 Baseline | REUSE (erledigt) | s. §0 |
| 1 Capability Matrix | ADAPT (dieses Dok) | maschinenlesbarer Teil folgt als `verification/registry.py`-Daten |
| 2 Versionierter Contract | **GENERALIZE** | Neues Modul `paper_factory/verification/contract.py`, Pydantic v2, `schema_version`; VH-Receipt-Mapping im Adapter |
| 3 Capability Negotiation | ADAPT | bestehende doctor-Logik (`adapters/base.py`, `state/inventory.py`) wiederverwenden, Status-Enum darüber |
| 4 VH-Adapter generalisieren | **GENERALIZE** | Adapter konsumiert `WorkPackage`, liefert `VerificationResult`; alle Sicherheitsregeln (PF-owned clone, HOH_RUNS, Run-IDs, flock, blocked_kind, Pane-Cleanup) bleiben; erste Unit-Tests überhaupt für diesen Adapter (gemockt) |
| 5 Shadow/Differential | **GENERALIZE** | Config `verification.shadow_nodes`; Differential-Receipt MATCH/SEMANTIC_MATCH/MISMATCH/PROVIDER_UNAVAILABLE/INCOMPARABLE; ändert kein Verdict |
| 6 Reviewer/Verifier-Ensemble | ADAPT (minimal) | Mapping VH-Findings → `reviews/framework.py:Finding`; Finding-Identity/Severity/Closure bleibt PF; kein Protected-Prose-Eingriff |
| 7 Literature Provider | **DEFER (PaperQA), REJECT (Nachbau)** | paperqa wird nirgends verwendet → Abstraktion hätte keinen zweiten realen Consumer (verletzt eigene Regel). PF-native bleibt einziger Pfad; Entscheidung dokumentiert; Extra bleibt optional |
| 8 Citation/Provenance | REUSE (keine Änderung) | DOI/arXiv/authoritative-URL-Verifikation und Firewall bleiben kanonisch; W3C-PROV-Exporter → DEFER v1.3 (kein Consumer) |
| 9 Reproduction Capsule | **DEFER v1.3** | kein zwingender aktueller Use Case; P10-DEGRADED wird transparent dokumentiert, keine Framework-Factory |
| 10 Compliance-Migration | REUSE (nur Doku) | Unterscheidung HISTORICAL_V1_FREEZE / CURRENT_V1_1_COMPLIANCE / V1_2_REGRESSION_PILOT; Freeze unantastbar; keine erfundene Disclosure |
| 11 Adversarial Tests | GENERALIZE | neue `tests/test_verification_*.py`, alles gemockt/offline |
| 12 Pilot Replays | ADAPT | Differential aus **gespeicherten** Pilot-States/Receipts + Offline-Shadow (PROVIDER_UNAVAILABLE-Pfad); keine echten HoH-Replays (Quota) — ehrlich als Limitation deklariert |
| 13 Dual Review | REUSE | etablierter A/B-Prozess |
| 14 Dokumentation | ADAPT | README-Testzahl 574→aktuell; Diagramme mit IMPLEMENTED/OPTIONAL/PLANNED; Position Paper nur falls materiell veraltet |
| 15 Commit-Disziplin | REUSE | kleine Commits, grüne Suite, kein Push/Release/Tag |

## 4. Contract-Design (Phase 2, verbindlich)

Modul `paper_factory/verification/` (neu):

- `contract.py` — Pydantic v2, `extra="forbid"` (Stil wie VH `Strict`):
  - `ArtifactRef`: path (relativ), sha256, kind
  - `EvidenceRef`: evidence_id, tier (T0–T4), artifact (ArtifactRef)
  - `WorkPackage`: schema_version=1, package_id, node_id, spec (Markdown-Text
    oder Pfad), artifacts[], acceptance_criteria[], provenance{}
  - `BackendIdentity`: kind (`pf_native|veriharness|external`), name, version,
    executable_sha256 soweit sinnvoll
  - `VerificationFinding`: kind, severity, statement, claim_refs[], evidence_refs[],
    statement_hash (SHA-256 über normalisiertes Statement — schließt an die
    durable-decision-Härtung aus v1.0 an)
  - `VerificationResult`: schema_version=1, package_id, backend (BackendIdentity),
    verdict (Verdict-Enum), findings[], receipts[], artifact_sha256 (Bindung!),
    started_at/finished_at, failure_reason, raw_receipt_refs[]
  - `ExecutionReceipt`: receipt_id, backend, artifact_sha256, sha256 (Receipt),
    created_at, stale-Flag-Ableitung
  - Round-trip-Test serialize→deserialize→semantic equality; unbekannte
    schema_version → fail-visible (ValidationError, kein stilles Ignorieren).
- `capabilities.py` — `CapabilityStatus`-Enum: SUPPORTED, SUPPORTED_DEGRADED,
  UNAVAILABLE, UNSUPPORTED, REQUIRES_NETWORK, REQUIRES_HUMAN.
  `declare_capabilities(backend)` nutzt bestehende doctor-Probes; kein
  paralleler Discovery-Stack.
- `registry.py` — `VerificationBackend`-Protokoll (`capabilities()`,
  `verify(WorkPackage) -> VerificationResult`) + Registry mit `pf_native`
  (Wrap um bestehende deterministische Handler) und `veriharness`.
- `shadow.py` — `DifferentialOutcome`-Enum (MATCH, SEMANTIC_MATCH, MISMATCH,
  PROVIDER_UNAVAILABLE, INCOMPARABLE), `run_shadow(node, …) -> DifferentialReceipt`
  (JSON im `receipts/`-Tree), MISMATCH nie still auflösen.

Kein Leaken von HoH-/Provider-Semantik in den Core-Contract: `blocked_kind`,
Herdr-Pane-IDs etc. bleiben im Adapter-internen `raw_receipt_refs`-Detail.

## 5. Abweichungen vom Berater-Vorschlag (bewusst, begründet)

1. **Kein LiteratureProvider-Interface in v1.2.** Der Berater selbst verlangt
   "keine Abstraktion ohne realen Consumer" — paperqa hat keinen einzigen
   Aufruf im Code. Ein Interface mit genau einer Implementierung wäre
   Spekulation. Stattdessen: dokumentierte DEFER-Entscheidung + der unbenutzte
   `LiteratureCfg.paperqa2`-Schalter wird als `DEFERRED_HARDENING`-Eintrag
   markiert (nicht entfernt — keine stille Mutation).
2. **Pilot-Replays ohne echte HoH-Runs.** Quota-Disziplin (AGENTS.md) +
   "Tests dürfen keine echten Kosten verursachen". Differential wird aus
   gespeicherten Receipts der existierenden Pilot-States und dem
   Offline-/UNAVAILABLE-Pfad gespeist. Ein echter Live-Replay bleibt dem
   expliziten Live-Pfad (`scripts/run_live_hoh.py`) vorbehalten und ist **nicht**
   Teil des Acceptance-Gates.
3. **SQLite-Schema-Versionierung DEFER.** Der Contract versioniert sich selbst
   (`schema_version`); eine `runs.sqlite`-Migration ist ein eigenes
   Risikopaket ohne v1.2-Consumer → v1.3-Backlog.
4. **Kein W3C-PROV-Exporter in v1.2.** Kein Consumer; PF-Provenance bleibt
   kanonisch.
5. **Dev-Version `1.2.0.dev0`** statt unverändertem 1.1.0 auf dem Branch —
   PEP-440-Standard, verhindert Verwechslung Branch-Artefakte ↔ v1.1.0-Release.
   Kein Tag, kein Release.

## 6. Work-Pakete & Acceptance

WP2 Contract+Capabilities → WP3 Adapter-Generalisierung → WP4 Shadow-Mode →
WP5 Reviewer-Mapping + DEFER-Dokumentation → WP6 Adversarial Tests →
WP7 Pilot-Differential → WP8 Dual-Review (A: Architektur/Scientific Integrity,
B: Failure/Release/Provenance) → WP9 Doku + Abschlussbericht.

Acceptance Gate = die 21 Punkte des Berater-Auftrags, mit den §5-Abweichungen
(dokumentiert statt still abgewichen). Open CRITICAL/MAJOR = 0, A/B = JA/JA,
kein Push, kein Release, P37 NOT EXECUTED.

## 5a. Runde-1-Review-Nachträge (2026-10-04, append — Originaltext oben unverändert)

Der Dual-Review (WP8) kam zu NEIN (4 MAJOR + MINOR/NIT). Die MAJOR-Fixes
F1–F4 und die billigen Fixes F5–F10 sind im Code gelandet (je mit
Regressionstest); die reine Dokumentationspunkte werden hier ehrlich
nachgetragen, ohne den Originaltext umzuschreiben:

- **Detail-Escape-Hatch (A-2/A-5):** `BackendIdentity.detail` ist bewusst
  untypisiertes Freifeld für Provider-Interna (run_id, blocked_kind,
  hoh_detail, clone_fingerprint) — reine Evidenz, kein maschineller Rückpfad
  in Verdicts.
- **findings_map/registry (A-6):** aktuell Bibliothek ohne
  Produktions-Verdrahtung; Verdrahtung frühestens v1.3. Disposition bleibt
  PF-owned (None), kein falscher Grün-Pfad.
- **MATCH im DAG-Pfad (A-7):** aktuell unerreichbar — PF-native bindet im
  Shadow-Pfad bewusst kein Artifact, daher höchstens SEMANTIC_MATCH oder
  INCOMPARABLE. Dokumentierte Lücke, kein PASS.
- **Shadow-/HoH-Nebenpfad-Crash (B-7):** Node FAIL (fail-visible, gewollt).
- **ensure_clone außerhalb flock (B-8):** Sequential-Design-Annahme
  (Analogon A-R3-TOCTOU; PF serialisiert eigene Runs pro Workspace).
- **Pane-Guard lange node_id (B-8-Anm.):** eigene Pane, die der Guard nicht
  eindeutig zuordnet, wird als `skipped_foreign` protokolliert, nie still
  geschlossen.
- **U7-Gate (A-1/F1):** nur `kind="hoh"`-Receipts schließen das HoH-Gate;
  Shadow-Receipts (`kind="shadow"`) sind Differential-Beobachtungen und
  sättigen es nie (False-Close behoben).
- **HoH ∩ Shadow (F7, Captain-Entscheidung):** ein `adapter.verify()`-Aufruf
  pro Node speist beide Ebenen; Receipts bleiben getrennt als
  `kind="hoh"` + `kind="shadow"` recorded.

## 5b. Fixloop-Nachtrag zu aa4de1f (2026-10-05, append — §5a unverändert)

„MATCH im DAG-Pfad unerreichbar" ist durch aa4de1f + Fixloop geschlossen:
der artefaktgebundene Shadow-Pfad bindet Node-Output-Receipts
(`_node_artifact_refs`, kind-Ausschluss von hoh/shadow, deterministisches
[:20]-Fenster), und `artifact_binding()` ist die beiderseits geteilte Regel.
Ehrliche Einschränkung (Reviewer A-8): die Bindung ist caller-deklariert
(Package-Manifest) und beiderseits per Konstruktion identisch — das Backend
hasht Artefakte nicht unabhängig neu. MATCH ist damit „Übereinstimmung auf
einer gemeinsamen Deklaration", kein unabhängiges Artefakt-Audit; die
Rationale des DifferentialReceipt sagt das wörtlich. Resume-Sicherheit
(Reviewer F-1): Verifikations-Receipts früherer Attempts (gleiche run_id)
kontaminieren die Bindung nie.
