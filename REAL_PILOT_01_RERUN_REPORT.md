# REAL PILOT 01 — RE-RUN REPORT (nach semantischen Core-Fixes GAP-003/004/005/010/006)

Rerun-Workspace: `pilots/real-pilot-01-rerun/project/` (frische Kopie der Pilotquellen,
byte-identisch verifiziert; historischer Snapshot `96b1a9c` + Original-Workspace
`pilots/real-pilot-01/` unverändert). Config: `pilots/real-pilot-01/config` (hoh_nodes: []).
PF-HEAD beim Lauf: `fb88174`. Läufe: `complete` → P31 HUMAN_REQUIRED → Operator-Check
(ehrlich als `operator_check`, kein externes Paperpal) → `resume`.

Ziel war NICHT „Pilot wird grün", sondern Ground-Truth-Discrimination. Ergebnis: die
Pipeline unterscheidet jetzt sauber zwischen PASS / FAIL / DEGRADED / HUMAN_REQUIRED.

---

## HEADLINE-VERGLEICH ALT vs. NEU

| Dimension | Original-Pilot (`96b1a9c`) | Re-Run (`fb88174`) |
|---|---|---|
| Claims gesamt | 7 (davon 2 `\hypertarget`-Fragmente, 2 Tabellen-Fragmente) | **3 (nur echte Sätze)** |
| Claim-Evidence | alle `["evidence_ledger"]` (Placeholder) | keine Placeholder; kein Binding → UNSUPPORTED |
| Claim-Status | 7× EVIDENCE_FOUND (unverdient) | 3× UNSUPPORTED → 3× RETIRED (gebunden verifiziert) |
| number_mismatch | 44 MAJOR (~20/44 FP in Stichprobe) | **0 MAJOR** |
| unverifiable_number | — (Klasse existierte nicht) | 5 MINOR (echte Kontrast-Zahlen ohne Metrik-Bindung) |
| Remediation-Einträge | 141 (140 RESOLVED via globaler Postcondition, `retired: []`) | **3 (alle `retire_bound_claims`, excerpt- + manuskript-verifiziert)** |
| Review-Findings gesamt | 148 (P23:44, P24:44, P25:60) | 29 (P23:8, P24:5, P25:21) |
| …davon vakuum-RESOLVED | 132 | **0** |
| …undisposed CRITICAL/MAJOR | 16 (inkl. ADV-05, blockierend) | **0** |
| P35 | FAIL (U5) | DEGRADED (U9 operator check; U16 NOT_RUN) |
| Overall / Exit | FAILED / 1 | HUMAN_REQUIRED / 3 (P36 by design) |

## CLAIM-QUALITÄT

Neu extrahiert (GAP-005): nur die drei echten wissenschaftlichen Sätze
(C001 Adam/weight-decay, C002 MMAV lower-loss, C003 corrected-experiment), alle mit
`source: draft/manuscript.tex`. Keiner konnte deterministisch an eine Metrik gebunden
werden (kein Field/Alias-Match) → ehrlich UNSUPPORTED statt Placeholder-EVIDENCE_FOUND.
Die GAP-004-Remediation hat alle drei mit voller Beweiskette retiriert:

- Excerpt↔Statement-Korrespondenz (G6) ✓
- Claim RETIRED in claims.yaml, **von Disk re-verifiziert** (B2) ✓
- Claim-Text fehlt in der geschützten Manuskript-Fläche (B1) ✓ (`printed_in_manuscript: []`)

## NUMERISCHE BEFUNDE (GAP-003)

Alt: 44 MAJOR, Stichprobe ~20/44 False Positives (Layout-`\linewidth`-Werte,
Decision-Thresholds, Komparativ-Konstrukte, Relations-Token-Kollisionen).
Neu: **0 MAJOR, 5 MINOR `unverifiable_number`** — die Pilot-FP-Klassen sind empirisch
tot (Probe auf identischem Draft/Metriken). Die 5 MINOR sind die echten Last-Träger
(MMAV-minus-Kontraste u.a.), für die die Pipeline keine Metriken ableitet — ehrlich
sichtbar statt falsch blockierend oder falsch durchgewunken.

## REVIEWS

- P23-methods: 3× MAJOR unsupported_claim (alle gebunden RESOLVED), 5× MINOR unverifiable
- P24-statistics: 5× MINOR unverifiable
- P25-adversarial: 16× MINOR no_doi (Literatur ohne DOIs — echte, bekannte Lücke),
  5× MINOR unverifiable
- Dedupe (GAP-010): keine Duplikat-Flut; U5 zählt unique

## U-INVARIANTEN (Re-Run)

U1–U8, U10–U15 **PASS**; **U9 DEGRADED** (manueller Operator-Check, kein externes
Paperpal-Evidenz — ehrlich); **U16 NOT_RUN** (keine externen Edits → keine
Rekonziliation nötig); P35 DEGRADED; **P36 HUMAN_REQUIRED** (Human-Final-Sign-off,
designgemäß); P37 SKIPPED_DEPENDENCY (keine externe Submission).

Historische Korrektur bleibt bestehen: der Original-Pilot-Report (`96b1a9c`) und seine
P31/U9-Bewertung sind unverändert gültig für den damaligen Stand.

## EXIT-SEMANTIK

`complete` → HUMAN_REQUIRED / Exit 3 (P31 Paperpal-Gate) → Operator-Check →
`resume` → HUMAN_REQUIRED / Exit 3 (P36 Sign-off). Kein Exit 0 ohne CLOSED —
der CLI-Exit-Kontrakt (`d612d0f`) hält in einem realen Lauf.

## LESSONS / OFFENE PUNKTE

1. Die drei Hauptclaims des Drafts sind ohne Metrik-Bindung unrettbar UNSUPPORTED —
   das ist die ehrliche Antwort auf ein Projekt, dessen Paper-Behauptungen die
   abgeleiteten Artefakte nicht tragen. Kein künstliches Bestehen.
2. 16× no_doi in der Projektliteratur: Datenlücke des Projekts, kein PF-Defekt.
3. GAP-011 (Kandidat, aus Reviewer B Q1): U2 bindet Werte, nicht Makro-Labels
   (`\pfget{nll}` hinter „latency"-Text). Nicht pilot-blockierend, zur Disposition.
4. Paperpal bleibt HUMAN_REQUIRED (kein API am Markt) — Bridge funktioniert,
   Operator-Check wird ehrlich als DEGRADED geführt, nie als PASS.

## GIT

- Historischer Snapshot `96b1a9c`: unverändert.
- Re-Run erzeugt: `pilots/real-pilot-01-rerun/` (neu, nichts überschrieben).
- Dieser Report: `REAL_PILOT_01_RERUN_REPORT.md` (neu, versioniert).
