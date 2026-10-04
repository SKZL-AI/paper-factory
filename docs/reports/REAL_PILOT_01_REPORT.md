# REAL PILOT 01 — REPORT

Datum: 2026-09-22 · PF-HEAD beim Pilot: `5f7dc75` (+2 Gap-Fixes, siehe unten) ·
Pilot-Workspace: `pilots/real-pilot-01/project/.paper-factory/` ·
Quelle (read-only, unangetastet): `~/wt-massinv/paper_arxiv/ARXIV_SUBMISSION_PAPER_A_v1.2.5/`
+ Overlay `r_analysis_013/`

## PROJECT

**MassInv Paper A — „Beyond Matched FFN Exposure"** (arXiv-Submission-Bundle v1.2.5),
ein abgeschlossenes, submission-reifes Paper über konditionales FFN-Training,
Checkpoint-Gate-Kompatibilität und die forensische Korrektur eines Optimizer-Labels.
Gewählt wegen: benotbarer Ground Truth (CLAIM_INVENTORY_v1.csv, 230 Claims, 42 davon
retrahiert — blind zurückgehalten), vollständiger Paper-Form, hash-gepinnter Evidenz.

## INPUT MODE

**MIXED_EVIDENCE** (auto-detektiert; Code + Daten + Draft + Historie + Bib).
56 Dateien in der Arbeitskopie; Ground Truth (`CLAIM_INVENTORY_v1.csv`) bewusst
NICHT im Input (externe Bewertung).

## SOURCE INVENTORY

- `pilots/real-pilot-01/source_inventory.json`: alle Quelldateien sha256-gehasht
  (Bundle 19 Dateien/1,3 MB; Overlay-Auswahl 21 Dateien), Git-State der Quelle
  (`wt-massinv` HEAD `e5558bf`, 9 uncommitted) erfasst. Quelle nie beschrieben.
- Draft als T4, Historie (JSONL-Journal, Entscheidungsdokumente, Preregs) als T3,
  Analyse-Artefakte als T0/T1 behandelt.

## RESEARCH RECONSTRUCTION

P03 lief: Chronologie aus `R_JOB_STATE_JOURNAL.jsonl` (50 Einträge), 3 Hypothesen,
2 fehlgeschlagene Experimente erkannt. **Einschränkung:** alle Storyline-Previews leer
(GAP-006) — Chronologie ja, Inhaltsextraktion nein. Hypothesen/Entscheidungen waren
für die Claim-Matrix nur teilweise maschinell nutzbar; die Matrix unten wurde vom
Orchestrator aus PF-Artefakten + Ground Truth gebaut und ist als solche markiert.

## CLAIM STATUS

Orchestrator-Matrix (Draft-Kernclaims → PF-Evidenzlage → Ground Truth):

| Draft-Claim | PF-Evidenz | GT (CLAIM_INVENTORY) | Status |
|---|---|---|---|
| Matched scalar exposure ≢ strukturelle Austauschbarkeit | K4-CSVs, BLOCK1-Kontraste (140 Metriken abgeleitet) | K4-*/CS-01..05 claim_safe | **VERIFIED** |
| „muon"-Label = Hybrid-Konfiguration (forensische Korrektur) | Routing-Audit im Draft; Overlay evidencelos in Kopie | EX-19 HELD, EX-03b HELD | **VERIFIED** (als Korrektur-Narrativ; Lesart HELD respektiert) |
| Ordering rekurrent über 3 Item-Züge; Masken-Rangstabilität verworfen | R39/R40-Artefakte **nicht** in der Pilot-Kopie | EX-07→EX-07b korrigiert (399x) | **PARTIAL** (Evidenz außerhalb Scope) |
| 18/18 Zellen, 0 INVALID; A-vs-B/C gebündelter Konfig-Kontrast (~2.9×) | K4_FACTORIAL_* CSVs + PAPER_SAFE_REPORT | K4-Reihe (teils retrahiert: K4-08/09/16/34/38 — im Draft korrekt als gebündelt gezähmt) | **VERIFIED** |
| R22/R28 Hilfsproben (scope-korrigiert) | R22R28-B1/B2-JSONs | B1/B2-Serien (mehrere retrahiert) | **VERIFIED** (deskriptiv begrenzt) |

PF-interner Claim-Graph: 7 Claims, alle EVIDENCE_FOUND — aber Extraktion schwach
(LaTeX-Fragmente, Placeholder-Evidence) → GAP-005. Zählung: VERIFIED 4 · PARTIAL 1 ·
CONTRADICTED 0 · UNSUPPORTED 0 (Orchestrator-Matrix, nicht P08).

**Ground-Truth-Abgleich (extern):** 42 retrahierte Claims im GT; keiner der
retrahierten unsafe Phrasings kommt im Draft vor (0/0 grep-Treffer). PF fand
**keinen** Widerspruch, der dem GT widerspräche — und **keine** der 44
Zahlen-Findings ist ein echter GT-Treffer (Stichprobe 20/44 verifiziert als
Heuristik-False-Positives → GAP-003).

## EVIDENCE COVERAGE

- Intake: 56 Dateien; U7: 31 Artefakte hash-identisch zu Intake (0 Drift).
- Evidenz-Lücken (ehrlich): R39/R40-Rohartefakte und GPU-Trainingslogs nicht im
  Pilot-Scope → Claims daraus nur PARTIAL abgedeckt; P10 DEGRADED (keine
  Reproduktions-Kommandos ableitbar — GPU-Runs sind nicht im Repo).

## LITERATURE / PRIOR ART

- Online-Verifikation: **0 false_citation**; 20 bib-Einträge geprüft;
  16× MINOR `no_doi` (bib trägt keine DOIs; Companion-Selbstzitation per Definition
  nicht auflösbar) → GAP-007. Keine halluzinierte Quelle.
- P07 Prior-Art-Attack lief (deterministischer Pool; begrenzt ohne PaperQA2).

## STATISTICS

- 140 Metriken aus 5 Ergebnis-CSV abgeleitet (nach GAP-001-Fix); `paper_metrics.json`
  → `generated/numbers.tex` (Makros); 0 Handeinträge; small_samples: 0.
- Integrity-Audit: 44 `number_mismatch` MAJOR — Stichprobe mehrheitlich False
  Positives (GAP-003); der Audit fand **keinen** echten Zahlenbruch, der GT bekannt
  wäre, übersah aber per Range-Gate die tragenden Zahlen außerhalb des Fensters
  (ADV-05 → letztlich der Closure-blockende Befund).

## REPRODUCIBILITY

- P34 Clean Rebuild: **PASS** (pdflatex, echtes PDF, post-freeze, dieser Run).
- P10: DEGRADED (keine Run-Kommandos im Projekt auffindbar — korrekt ehrlich).
- Figuren reproduzierbar aus CSVs (13 Figuren, Manifest mit Input-Hashes).

## PAPER OUTPUT

- `paper/`: main.tex + 5 Sections + generated/{numbers,tables}.tex, 13 Figuren
  (PDF/SVG/PNG), 5 Tabellen (booktabs), references.bib (verifiziert, 0 false).
- Provenance: 6 geschützte Dateien, alle mit Origin-Receipts (deterministic);
  U11–U14 PASS. Kein Anthropic-Prosa (Policy strikt eingehalten).
- Der PF-Kandidat ist bewusst **konservativ-dürr** (Template-Prosa aus Metriken);
  der adversariale Reviewer attestiert Underclaim (Kern-JSONs ungenutzt) statt
  Overclaim — sichere Richtung.

## REVIEW FINDINGS

- Deterministische Rollen P23–P26 + P29: 132 Findings (44 distinct ×3 Fanout —
  GAP-010), 0 aus P26/P29.
- **Adversarial Reviewer 2 (kimi-Familie, unabhängiger Pfad): 13 Findings**
  — 3 CRITICAL (PF-Manuskript ohne Korrektur-Kontext des Drafts; Review-Gates
  replizieren Audit-Boilerplate mit Vakuum-Disposition; Claim-Graph-Qualität),
  6 MAJOR (u.a. ADV-05 Range-Gate-Blindheit — verifiziert), 4 MINOR.
- Zählung gesamt (dedupliziert sinnvoll): CRITICAL 3 · MAJOR 50 · MINOR 20 ·
  NIT 0. Nach Remediation: 1 unresolved (ADV-05) → blockiert Closure.

## PIPELINE

Finaler Lauf (`complete-20260922T111606Z`): P01–P09 PASS · P00/P10 DEGRADED ·
P11–P26 PASS · P27 DEGRADED (1 deferred) · P28–P32 PASS · P33/P34 PASS ·
**P35 FAIL (U5)** · P36 SKIPPED (hängt von P35) · P37 NOT-RUN-by-design.
Run 1 (pre-Fix): FAIL ab P11/P12, 25 Knoten SKIPPED.

> **Korrektur (Post-Pilot-Audit 2026-09-22):** P31 war im Snapshot als PASS
> verbucht — korrigiert zu **DEGRADED** (manueller Operator-Check, keine externe
> Paperpal-Evidenz; Details im Abschnitt POST-PILOT INTEGRITY AUDIT unten).
> P36/P37 kanonisch **SKIPPED_DEPENDENCY** (P36: hängt an P35; P37: externe
> Submission läuft per Design nie automatisch, hängt an P36) — die frühere
> Zeile „P37 NOT-RUN-by-design" war eine zweite, abweichende Bezeichnung für
> denselben Maschinenzustand und ist damit vereinheitlicht.

## GLOBAL CLOSURE

U1–U4 PASS · **U5 FAIL** (1 unresolved MAJOR) · U6–U16 PASS.
Gesamt: **FAILED** — und das ist der korrekte, ehrliche Endzustand: das System
reicht ein Paper mit einem offenen verifizierten MAJOR-Befund NICHT durch.

> **Korrektur (Post-Pilot-Audit 2026-09-22):** U9/U16 waren im Snapshot PASS —
> korrigiert zu **U9 DEGRADED** (nur Operator-Check, keine externe
> Paperpal-Evidenz) und **U16 NOT_RUN** (`external_edits: false` — es gab keine
> externen Edits, also nichts zu reconcilen). Gesamt bleibt **FAILED** (U5).

## REAL-WORLD PF GAPS

Siehe `REAL_PILOT_01_GAP_REPORT.md` (GAP-001..010). Kern: zwei blockierende
Core-Bugs gefixt (GAP-001/002); GAP-003 (Audit-Heuristik-FP), GAP-004
(Vakuum-Disposition), GAP-005 (Claim-Extraktion) sind die substanziellen
offenen Core-Themen — alle nur im realen Lauf sichtbar geworden.

## PROJECT-SPECIFIC ISSUES

- bib ohne DOI-Felder (A); GPU-Rohdaten/R39-R40-Artefakte außerhalb Repo (A);
  Ground-Truth-Inventory existiert nur außerhalb (bewusst).

## PAPER FACTORY GENERIC ISSUES

GAP-001..006, GAP-010 (alle Klasse B); je mit Reproduktion im Gap-Report.

## VERIHARNESS/HERDR ISSUES

Keine — `hoh_nodes: []` per Pilot-Design (HoH-Live-Beweis existiert bereits,
PF-e05758a3-P05). Herdr wurde im Pilot nicht benötigt (deterministischer Lauf).

## HUMAN_REQUIRED

1. P36 Final Sign-off (per Design, bleibt menschlich).
2. Systempakete (`texlive-latex-extra graphviz qpdf poppler-utils`) — sudo.
3. Paperpal bleibt manuelle Bridge (im Pilot ehrlich als Operator-Check gefahren,
   kein API); U9/U16 PASS über Bridge + Semantic Diff.

   > **Korrektur (Post-Pilot-Audit 2026-09-22):** Der Inbox-Eintrag wurde vom
   > Orchestrierungs-Agenten als Operator verfasst (Selbstdeklaration im
   > Artefakt: „not a Paperpal product") — er ist **kein** Paperpal-Ergebnis.
   > U9/U16 waren fälschlich PASS; korrigiert: U9 DEGRADED, U16 NOT_RUN.
   > Ein echter Paperpal-Report des Nutzers steht weiterhin aus.

## POST-PILOT INTEGRITY AUDIT (2026-09-22, auf Basis des eingefrorenen Snapshots `96b1a9c`)

Vier Befunde, alle mit Regressionstests und Fix; Snapshot `96b1a9c` unverändert,
Korrekturen in einem Folge-Commit (Korrektur-Provenienz: Alter Claim oben
sichtbar, Neuer mit Datum/Grund):

1. **Paperpal-Provenienz (POST-AUDIT-1):** Inbox-Artefakt `language_check_report.txt`
   (sha256 `20696911…89eab`) ist ein interner Operator-Check, verfasst vom
   Orchestrierungs-Agenten — keine externe Paperpal-Evidence. Fixes:
   `paperpal/bridge.py` klassifiziert Inbox-Provenienz fail-closed
   (`external_paperpal_declared` nur mit explizitem `source: paperpal`-Header
   oder Sidecar), `_u9`/`_u16` lesen die Klasse ehrlich aus. Empirisch gegen
   eine unveränderte **Kopie** des Pilot-Workspace verifiziert:
   P31→DEGRADED, U9→DEGRADED, U16→NOT_RUN, U2/U5/U7 unverändert, P35 bleibt FAIL.
2. **GAP-002-Rest: False-Green bis P35 (POST-AUDIT-2):** U2 prüfte nur rohe
   Dezimalzahlen — ein quantitativer Claim ohne `paper_metrics.json` konnte
   P35 PASS erreichen. Fix: Closure-Provenienz-Gate (quantitativer Inhalt oder
   `\pfget`-Nutzung ohne Metrik-Artefakt → FAIL; ungebundene Makros → FAIL;
   kaputtes `paper_metrics.json` → FAIL). P11–P14 bleiben DEGRADED (nicht pauschal
   FAIL) — der Block sitzt präzise in der Closure.
3. **Overall-State (POST-AUDIT-3):** Dashboard nutzte eine zweite Wahrheit
   (`FAILED if fail else PASS`). Jetzt eine kanonische Funktion
   `run_status_overall` (executor.py) für CLI **und** Dashboard:
   FAILED > HUMAN_REQUIRED > INCOMPLETE > DEGRADED > CLOSED; DEGRADED wird nie
   mehr blind zu CLOSED gerundet; unbekannte States/Knoten → INCOMPLETE.
4. **Status-Konsistenz:** P36/P37 kanonisch SKIPPED_DEPENDENCY mit getrennter
   Erklärung (`status_notes` in `real_pilot_01_summary.json`, im Dashboard
   gerendert); Maschinenstate und Erklärung sind jetzt getrennte Felder.

Regressionstests: `tests/test_real_pilot_gaps.py` (+75, Suite 132 → **207**),
dazu eine adversariale Review-Kampagne gegen die Audit-Fixe selbst: 2
unabhängige Reviewer mit Widerlegungsauftrag, A 4 Runden bis JA (GAP-001),
B 10 Runden bis JA (GAP-002/False-Green) — ~80 verifizierte Angriffsrepros,
alle final blockiert; Details als POST-AUDIT-4 im Gap-Report. Dokumentierte
Restgrenzen: siehe Gap-Report (u.a. Empfehlung PDF-Text-Scan als
architektonischer Endpunkt).
Offen bleiben unverändert: GAP-003/004/005/006/010 (ausdrücklich NICHT Teil
dieses Audits).
4. ADV-05 muss menschlich disponiert werden (AUTHOR_DECISION oder Fix der
   Audit-Heuristik) — erst dann kann eine erneute Closure PASS erreichen.

## RECOMMENDED NEXT ACTION

Aus Pilotbefunden, nicht aus Prinzip:
1. **GAP-004 zuerst** (Vakuum-Disposition unterminiert die Ehrlichkeitszusage) —
   eigenes Fix-Paket mit Dual-Review-Gate.
2. GAP-003 (Kontextbindung Zahl↔Metrik) als Design-Paket.
3. GAP-005/006 (Claim-Extraktion LaTeX, Journal-Parser) als Qualitätspaket.
4. Danach Pilot 2 (Kandidat VeriHarness-Positionspapier oder Wiederholung
   MassInv mit erweitertem Evidenz-Umfang) gegen die gehärteten Checks.
