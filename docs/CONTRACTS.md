# PAPER FACTORY — Contract Inventory (v2.0 WP-I)

Stand: 2026-10-05 · Basis: 756c692 (main nach v1.5-Entscheidungen) · Scope: ausschließlich
Contracts mit **echtem Consumer im Code** (keine hypothetischen, keine abgestorbenen
Schnittstellen).

Konventionen: „Producer" erzeugt Instanzen/Payloads des Contracts, „Consumer" liest oder
validiert sie. `schema_version` ist überall `Literal[N]` im Pydantic-Modell — streng
(`extra="forbid"`), d.h. unbekannte Felder und unbekannte Versionsnummern scheitern
sichtbar am Laden. Alle Contracts sind v1; Begründung siehe
`docs/reports/V2_0_SCHEMA_DECISION.md`.

## 1. Verification Contract (WorkPackage / VerificationResult / VerificationFinding)

- **Ort:** `paper_factory/verification/contract.py`, `SCHEMA_VERSION = 1`
- **Modelle:** `WorkPackage` (Eingabe), `VerificationResult` (Ausgabe),
  `VerificationFinding`, `ArtifactRef`, `EvidenceRef`, `BackendIdentity`,
  `artifact_binding()` (Digest-Funktion)
- **Producer:** PF-Orchestrierung baut `WorkPackage`
  (`paper_factory/dag/handlers.py`, `adapters/veriharness/adapter.py`);
  Backends produzieren `VerificationResult` (`registry.VerificationBackend.verify`,
  pf-native Pfad in `dag/handlers.py`, `adapters/veriharness/adapter.py`).
- **Consumer:** Gates/Runner (`dag/handlers.py` — u.a.
  `VerificationResult.check_receipt_freshness`), Shadow/Differential
  (`verification/shadow.py`), Findings-Mapping (`verification/findings_map.py`,
  `reviews/verification_ingest.py`), Adapter-Legacy-Shim (`adapter.py`).
- **Stabilitätsgarantie:** streng (`Strict`: `extra="forbid"`). Der
  Freshness-Konsum (`ReceiptExpectation`, Konsumzeitpunkt statt Ladezeitpunkt)
  ist Teil des Contracts seit v1.3.
- **Deprecation-Pfad:** keine Altlasten. Eine Feldsänderung wäre eine
  schema_version=2 (Kollisionsregel siehe Schema-Decision-Report).

## 2. Verification Receipt (`verification.contract.ExecutionReceipt`)

- **Ort:** `paper_factory/verification/contract.py` (gleiche Datei, eigener Contract)
- **Producer:** `adapters/veriharness/adapter.py` (parst HoH-Receipt-Dateien zu
  strengen Objekten), pf-native Stubs in `dag/handlers.py`.
- **Consumer:** Gates via `VerificationResult.check_receipt_freshness` →
  `ExecutionReceipt.check_freshness` (Konsumzeitpunkt-Prüfung: Binding, Backend,
  Run/Replay über den State-Store, Zeitstempel).
- **Stabilitätsgarantie:** streng; Laden ist zu v1.2-Zeitstempel-losen Receipts
  kompatibel (lenient load), die harten Checks laufen am Konsum.
- **Inventar-Befund (Namenskollision):** es gibt **zwei** `ExecutionReceipt`-Klassen:
  - `paper_factory/verification/contract.py:236` (VerificationReceipt)
  - `paper_factory/reproduction/capsule.py:226` (ReproductionReceipt)
  Beide heißen `ExecutionReceipt`, exportiert über jeweils `verification/__init__.py`
  und `reproduction/__init__.py`. **Keine** Datei importiert beide gleichzeitig
  (Inventar-Durchgang 2026-10-05: jede Verwendungsstelle importiert genau eine), daher
  ist heute kein Defekt belegt. Der Name ist aber im Paket doppelt belegt und ein
  gemeinsamer Import (z. B. in zukünftigem Code, der beide Ebenen zusammenführt —
  die Export-Ebene tut das bereits über `_shared.ExportBundle`) bricht oder greift
  still auf die falsche Klasse zu. **TODO (schema v2):** beim ersten echten
  Contract-Bruch beide umbenennen (`VerificationExecutionReceipt` /
  `ReproductionExecutionReceipt`) als Teil von schema_version=2, nicht vorher —
  ein Breaking-Rename ohne Grund ist teurer als die dokumentierte Kollision.

## 3. Verification Shadow/Differential Receipt (`DifferentialReceipt`)

- **Ort:** `paper_factory/verification/shadow.py`, `schema_version: Literal[1]`
- **Producer:** `shadow.run_shadow` / `shadow.compare`.
- **Consumer:** `dag/handlers.py` (schattenpfad), Reports/Review (JSON auf Disk,
  menschenlesbar).
- **Stabilitätsgarantie:** streng; Outcome-Enum (`MATCH`/`SEMANTIC_MATCH`/`MISMATCH`/
  `PROVIDER_UNAVAILABLE`/`INCOMPARABLE`) ist semantisch spezifiziert im Modul-Docstring.
- **Deprecation-Pfad:** keine.

## 4. Reproduction Capsule (`ReproductionCapsule`)

- **Ort:** `paper_factory/reproduction/capsule.py`, `SCHEMA_VERSION = 1`
- **Modelle:** `ReproductionCapsule`, `FileRef`, `EnvironmentIdentity`,
  `ParameterDecl`, `NondeterminismDecl`, `SemanticRule`,
  `capsule_digest` (content-addressed Identität, Feldliste im Modul-Docstring).
- **Producer:** Capsule-Erzeuger (DAG/pilotseitig, Beispiel:
  `tests/test_p10_capsule.py`, Pilot-Skripte).
- **Consumer:** Alle Reproduction-Backends — `runner.LocalReproductionRunner`
  (pf-native), `nextflow_backend.NextflowBackend`, `snakemake_backend.SnakemakeBackend`
  — sowie alle Provenance-Exporter (`export/_shared.py` konsumiert Capsule + Receipts).
- **Stabilitätsgarantie:** streng; `capsule_digest` ist über die Feldliste stabil
  definiert — jede semantische Feldänderung ist zwangsläufig schema v2 (das
  schema_version-Feld liegt bewusst IM Digest).
- **Deprecation-Pfad:** keine Altlasten.

## 5. Reproduction Receipt (`reproduction.capsule.ExecutionReceipt`)

- **Ort:** `paper_factory/reproduction/capsule.py:226`
- **Producer:** `LocalReproductionRunner.run`, `NextflowBackend`,
  `SnakemakeBackend` (alle produzieren dieselbe Receipt-Form).
- **Consumer:** `reproduction/differential.py` (`compare_executions` →
  `ReproductionComparison`), `export/*` (RO-Crate/PROV/CWL/Card), `statistics/
  reproducibility.py`.
- **Stabilitätsgarantie:** streng. `capsule_digest` im Receipt koppelt jede
  Ausführung an die Capsule-Identität.
- **Inventar-Befund:** Namenskollision mit §2 (siehe dort).

## 6. Execution Backend — Verification (`VerificationBackend` Protocol)

- **Ort:** `paper_factory/verification/registry.py` (`Protocol`, runtime-checkable)
- **Methoden:** `identity() -> BackendIdentity`, `verify(WorkPackage, **options) ->
  VerificationResult`
- **Producer/Implementierungen:** pf-native (in `dag/handlers.py`),
  VeriHarness-Adapter (`adapters/veriharness/adapter.py`), externe.
- **Consumer:** `shadow.run_shadow`, Registry-Lookups, DAG-Runner.
- **Stabilitätsgarantie:** Protokoll-Contract; Ausnahmen der Backend-Implementierung
  werden vom Consumer nicht propagiert (PROVIDER_UNAVAILABLE statt Crash).
- **Deprecation-Pfad:** keine.

## 7. Execution Backend — Reproduction

- **Ort:** `paper_factory/reproduction/__init__.py` + `runner.py` /
  `nextflow_backend.py` / `snakemake_backend.py` (konventioneller als explizites
  Protocol: alle Backends exponieren `run(capsule, capsule_root, timeout, ...) ->
  ExecutionReceipt`)
- **Producer/Implementierungen:** Local (pf-native), Snakemake, Nextflow.
- **Consumer:** Differential (`compare_executions`), Pilot-/Exportskripte.
- **Stabilitätsgarantie:** implizit über die gemeinsame Receipt-Form (§5); die
  Snakemake-/Nextflow-Backends sind dokumentiert dünne Adapter („the workflow
  engines map the contract, they never become PF's orchestrator").
- **Deprecation-Pfad:** keine.

## 8. Provenance-Export-Formate

Alle vier Exporter konsumieren `ExportBundle` (`export/_shared.py`: Capsule +
Reproduction-Receipts). Echte Consumer im Code: `scripts/pilot_exports_v13.py`
und die Test-Suite; ein CLI-Subcommand existiert **nicht** (`cli/main.py` hat
keinen Export-Befehl) — ehrlicher Inventar-Befund.

| Format | Ort | Version/Profil | Ziel |
|---|---|---|---|
| Workflow Card (JSON+Markdown) | `export/workflow_card.py` | `CARD_SCHEMA_VERSION = 1` | menschenlesbare Run-Karte, `schema_version` im JSON |
| RO-Crate | `export/rocrate.py` | RO-Crate 1.3, Process-Run-Crate-Profil `…/wfrun/process/0.6` | Archiv/Austausch |
| W3C PROV | `export/prov.py` | PROV-JSON | Provenance-Graphen |
| CWL Tool | `export/cwl.py` | CWL v1.2 (Tool-Dokument) | Workflow-Austausch |

- **Stabilitätsgarantie:** die externen Profile (RO-Crate/PROV/CWL) sind
  drittseitig versioniert; PFs eigener Anteil ist nur die Card (`CARD_SCHEMA_VERSION`).
  Exporter erzeugen, sie importieren nie zurück („never a source of truth").
- **Deprecation-Pfad:** keine.

## 9. State-DB-Schema (`runs.sqlite`)

- **Ort:** `paper_factory/state/store.py`, `SCHEMA_VERSION = 1` (PRAGMA
  `user_version`), `MIGRATIONS`-Registry (`0 -> 1` für v1.2-er Legacy-DBs).
- **Producer:** `Workspace.connect()` legt/migriert die DB; alle Schreibpfade
  (runs/nodes/receipts/events-Tabellen).
- **Consumer:** Jeder PF-Lauf über `Workspace`; CLI (`status`/`report`/`audit`).
- **Stabilitätsgarantie:** Migrationen sind registriert, idempotent und kopieren
  die DB vor jeder Mutation (nie move/delete); neuere DBs scheitern sichtbar
  (`SchemaVersionError`).
- **Deprecation-Pfad:** Migrations-Kette ist der Pfad; ein v2-Schema käme als
  `MIGRATIONS[1]` mit Copy-Before-Mutate.

## 10. Finding-Identity (Review-Ebene)

- **Ort:** `paper_factory/reviews/framework.py` (`dedupe_key`,
  `legacy_dedupe_key`, `_stmt_hash`)
- **Producer/Consumer:** Review-Framework selbst (`reviews/decisions.py` bindet
  durable Entscheidungen an den kanonischen `dedupe_key`; `release/closure.py`
  zählt blocking Findings über denselben Key); Findings-Map
  (`verification/findings_map.py`) bildet externe VerificationFindings auf
  PF-Findings ab und erhält die Identitätslogik.
- **Stabilitätsgarantie:** Identität = (kind/category, affected_section/draft,
  starkes Bindeglied [value | doi/key | span | bound_metrics] oder
  Statement-Hash-Fallback). `legacy_dedupe_key` existiert nur für
  Pre-Hardening-Entscheidungen (Migrationszwecke, niemals für neue).
- **Deprecation-Pfad:** `legacy_dedupe_key` ist der dokumentierte
  Kompatibilitätsanker; neues Material ausschließlich über `dedupe_key`.

## Inventar-Zusammenfassung

- 10 reale Contracts, **alle v1**, keine Altlast, keine toten Schnittstellen
  (Provenance-Exporter ohne CLI-Subcommand sind bewusst Skript-Ebene, nicht tot).
- Einziger benannter Inventar-Befund: `ExecutionReceipt`-Namenskollision (§2/§5) —
  dokumentiert, kein belegter Defekt, TODO an schema v2 gebunden.
