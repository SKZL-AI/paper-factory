# REAL PILOT 01 — GAP REPORT

Pilot: MassInv Paper A v1.2.5 (MIXED_EVIDENCE) · PF-HEAD beim Lauf: `5f7dc75` (+GAP-001/002-Fixes) ·
Runs: `complete-20260922T103928Z` (Run 1), `…T104758Z` (Run 2), `…T111606Z` (Resume/final)

Klassifikation je Befund: A projektspezifisch · B PF-Core · C PF-Adapter · D VeriHarness generic ·
E Herdr/Runtime · F Provider/Harness · G Bedienung/Config

---

## GAP-001 — Statistik: Small-Table-Heuristik frisst Outcome-Felder — FIXED (B)

- **Beobachtet:** P09 DEGRADED „no numeric outcome fields found" auf allen realen
  Kontrast-CSV des Projekts → kein `paper_metrics.json` → P11/P12 FAIL → 25 Knoten
  SKIPPED. Pipeline-Totalschaden.
- **Erwartet:** kleine aggregierte Ergebnistabellen (≤12 Zeilen, alle Werte distinkt)
  liefern Metriken.
- **Root Cause (reproduziert):** `statistics/metrics.py` — ein numerisches Feld galt als
  Design-Parameter bei `1 < distinct ≤ 12`, ohne zu prüfen, ob Werte sich überhaupt
  wiederholen. Bei kleinen Tabellen hat jede Spalte ≤12 Distinkte → alles „Design", keine
  Outcomes.
- **Fix:** Design-Parameter müssen sich wiederholen (`distinct < rows`); Outcome-Felder
  brauchen >1 Distinktwert. Garantie unverändert (Fixture-Verhalten per Test bewacht).
- **Regres-sionstest:** `tests/test_real_pilot_gaps.py::test_gap001_*` (2 Tests).
- Klassifikation: **B (generisch)** — jede reale Aggregat-Tabelle betroffen.

## GAP-002 — Figuren-/Tabellenplanung hard-FAIL statt DEGRADED — FIXED (B)

- **Beobachtet:** P11/P12 FAIL „paper_metrics.json missing" → DAG-Blockade aller
  25 Folgeknoten.
- **Erwartet:** „nichts ableitbar" ist DEGRADED (ehrlich), nicht FAIL (blockierend) —
  Missionsregel: ein Knoten blockiert nur Abhängiges, kein Stillstand der Pipeline.
- **Fix:** P11/P12 (+ P13/P14 analog) → DEGRADED bei fehlenden/leeren Metriken.
- **Regressionstest:** `test_gap002_*` (2 Tests). Klassifikation: **B**.

## GAP-003 — number_mismatch-Heuristik: False Positives auf echter Prosa — OPEN (B, MAJOR)

- **Beobachtet:** 44 MAJOR-Findings „draft number within metric range but off every
  derived metric". Stichprobe (20 Werte) durch den adversarialen Reviewer gegen die
  Original-Artefakte verifiziert: die Draft-Zahlen sind **korrekt** — sie gehören nur zu
  anderen Größen (Schwellen 0.069, Fenster 0.0360, Kontraste 0.0024) als den zufällig
  im 0.5x–2x-Fenster liegenden Metriken. **Koinzidenz-Treffer ohne Kontextbindung.**
- **Verschärfer (ADV-05, verifiziert):** die Range-Gate (0.5x–2x) blendet gleichzeitig
  genau die tragenden Zahlen aus (2.9-fach Step-Energy, Universum 1.020.057.600,
  Tokenzahlen) — der Audit sieht nur, was zufällig nah an einer Metrik liegt.
- **Warum nicht sofort gefixt:** jede naive Lockerung (engeres Fenster) schwächt die
  echte Erkennung (synthetischer E2E-Fund 0.021↔0.0146 war genau dieser Pfad).
  Braucht Kontextbindung (Zahl ↔ benannte Größe), nicht Toleranz-Tuning.
- **Fix gerechtfertigt?** Ja, aber als eigenes Design-Paket (Pilot 2 / Hygiene-Runde),
  nicht im Pilot. Regressionstest-Kandidat: FP-Rate auf MassInv-Draft < x%.

## GAP-004 — Remediation: vakuum-Disposition „RESOLVED" — OPEN (B, CRITICAL-Semantik)

- **Beobachtet:** 141 Remediation-Einträge; 140 Findings erhielten
  `disposition=RESOLVED` mit „post-condition verified: no unsupported claims remain
  (retired: [])" — obwohl am Befund selbst nichts getan wurde. Der Post-Condition-Check
  (Claim-Graph frei von UNSUPPORTED) steht in keiner Beziehung zum Finding-Inhalt
  (z.B. number_mismatch, Prozess-Claims).
- **Erwartet:** RESOLVED nur, wenn die finding-spezifische Nachbedingung belegt ist.
- **Ehrlichkeit:** der einzige korrekt behandelte Befund ist ADV-05 → `deferred` →
  **U5 FAIL** → ehrliche Closure-Blockade. Das System hat sich hier korrekt verhalten;
  die 140 vakuum-RESOLVED sind die Schwäche.
- **Fix gerechtfertigt?** Ja — Kern der Ehrlichkeitsarchitektur. Eigenes Paket:
  Disposition braucht finding-gebundene Post-Conditions oder AUTHOR_DECISION-Pfad.

## GAP-005 — Claim-Extraktion auf echtem LaTeX schwach — OPEN (B, MAJOR)

- **Beobachtet:** nur 7 Claims; darunter LaTeX-Fragmente (`\hypertarget…`,
  Tabellenzeilen) als „Claims"; alle mit Placeholder-Evidence `["evidence_ledger"]`
  statt artefakt-gebundener IDs.
- **Konsequenz:** U1 („claims linked") PASSed formal, die Bindung ist aber nicht
  artefakt-scharf; die wissenschaftliche Rekonstruktion im Report obliegt dem
  Orchestrator, nicht P08.
- **Fix:** Extraktionsheuristik für LaTeX-Sektionen + Pflicht-Artefakt-IDs. Eigenes Paket.

## GAP-006 — History-Mining leere Previews auf JSONL-Journal — OPEN (B, MINOR)

- **Beobachtet:** P03 storyline: 50 Einträge, alle mit leerem `preview` (Quelle:
  `R_JOB_STATE_JOURNAL.jsonl`).
- **Erwartet:** sichtbare Inhalts-Snippets je Eintrag.
- **Fix:** Parser für zeilenbasierte Journal-JSONL (Feldwahl). Klein.

## GAP-007 — Zitations-Audit: 16/20 ohne DOI — OPEN (A+B, MINOR)

- **Beobachtet:** online, 0 false_citation, aber 16× MINOR `no_doi` (bib ohne
  DOI-Felder), inkl. Companion-Selbstzitation `sakizli2026audit` (unpubliziert →
  per Definition nicht auflösbar).
- **Klassifikation:** primär **A** (Datenqualität der bib des Projekts); PF-seitig
  korrekt ehrlich klassifiziert. Optional PF: Titel-basierte Crossref-Suche als
  Fallback, wenn kein DOI vorhanden (Feature-Kandidat, kein Fix).

## GAP-008 — P10 „no reproduction commands discovered" — OPEN (A, erwartbar)

- Die GPU-Trainingsläufe sind nicht im Repo; aus `code/` sind keine Reproduktions-
  Kommandos ableitbar. Ehrliches DEGRADED, projektspezifisch. Kein Fix.

## GAP-009 — P00 DEGRADED: optionale Systempakete fehlen — OPEN (G)

- `latexmk`, `dot`, `qpdf`, `pdftotext` fehlen weiterhin (sudo erforderlich —
  HUMAN_REQUIRED Systemebene). Pipeline läuft degradations-ehrlich ohne sie;
  P34 nutzte `pdflatex` (vorhanden) erfolgreich.

## GAP-010 — Review-Fanout amplifiziert Audit-Findings ×3 — OPEN (B, MINOR)

- P23/P24/P25 übernehmen je alle 44 Integrity-Findings unverändert (132 Findings,
  faktisch 44 distinct). Zählinflation in Reports; Remediation verarbeitet jede Kopie.
- **Fix:** Dedupe nach (statement, evidence) bei Review-Aggregation. Klein.

---

### Nicht-Befunde (hart gesucht, sauber)

- Kein Secret/Transkript im Release (U8 PASS, 53 Dateien gescannt, 59 gepinnt).
- Freeze/Bundle-Integrität auf echtem Projekt stabil (U6 PASS, 48 Dateien).
- Provenance-Firewall: alle geschützten Dateien mit Origins (U11–U14 PASS).
- Kein VeriHarness/Herdr-Befund im Pilot (hoh_nodes: [] per Design; D/E leer).

---

## POST-PILOT-AUDIT-Nachtrag (2026-09-22, auf Basis Snapshot `96b1a9c`)

Drei Befunde aus dem Post-Pilot Integrity Audit, alle gefixt (Regressionstests
in `tests/test_real_pilot_gaps.py`, +18 Tests; Suite 132 → 150):

### POST-AUDIT-1 — Paperpal-Lane buchte Operator-Check als externen PASS — FIXED (B)

- **Beobachtet:** P31/U9 PASS („paperpal results delivered"), U16 PASS
  („external edits semantically reconciled") — obwohl das einzige Inbox-Artefakt
  ein vom Orchestrierungs-Agenten verfasster manueller Check war (Selbstdeklaration:
  „not a Paperpal product") und `semantic_diff.json` `external_edits: false`
  verzeichnete. Kein Paperpal-API existiert (Marktcheck: nur GUI-Flächen).
- **Fix:** Bridge klassifiziert Inbox-Provenienz fail-closed
  (`external_paperpal_declared` nur via explizitem `source: paperpal`-Header oder
  Sidecar, sonst `operator_check`); P31 DEGRADED bei Operator-Check; U9 liest die
  Klasse (external→PASS, operator→DEGRADED, deklarationslos→HUMAN_REQUIRED);
  U16 NOT_RUN ohne tatsächliche externe Edits. `paperpal_state.json` trägt jetzt
  `evidence_class` + per-Item `sha256`.
- **Verifikation:** Re-Run gegen unveränderte Workspace-Kopie: P31→DEGRADED,
  U9→DEGRADED, U16→NOT_RUN, P35 bleibt FAIL (U5).

### POST-AUDIT-2 — U2 ohne Metrik-Provenienz-Gate (False-Green bis P35) — FIXED (B)

- **Beobachtet:** U2 prüfte nur rohe Dezimalzahlen im Manuskript. Ein
  quantitativer Claim (z.B. „42 %", „2.5-fold") ganz ohne `paper_metrics.json`
  erreichte U2 PASS → P35 PASS möglich. Invariante verletzt: quantitativer
  Claim ohne T0/T1-Metrik-Provenienz darf P35 nie PASS sehen.
- **Fix:** Closure-Gate in `_u2`: quantitativer Inhalt (Prozent/fold/Dezimal in
  Claim-Sections) oder `\pfget`-Nutzung ohne Metrik-Artefakt → FAIL; `\pfget`
  ohne Definition in `numbers.tex` → FAIL; unlesbares `paper_metrics.json` → FAIL.
  P11–P14 bleiben DEGRADED (GAP-002-Semantik unangetastet) — der Block sitzt
  präzise in der Closure, nicht pauschal im DAG.

### POST-AUDIT-3 — Overall-State: Dashboard als zweite Wahrheit, DEGRADED unsichtbar — FIXED (B)

- **Beobachtet:** Pilot-Summary setzte `overall = FAILED if fail else PASS`;
  kanonisch galt `run_status_overall` ohne DEGRADED-Sichtbarkeit (DEGRADED-only
  → CLOSED). Zwei Wahrheiten, DEGRADED unsichtbar.
- **Fix:** `run_status_overall` (executor.py) ist die eine Funktion für CLI und
  Dashboard: FAILED > HUMAN_REQUIRED > INCOMPLETE > DEGRADED > CLOSED;
  unbekannte States/Knoten → INCOMPLETE; String-Normalisierung für JSON-Pfade.
  Dashboard rechnet overall aus `statuses`, liest kein gebackenes Feld mehr.

### POST-AUDIT-4 — Adversariale Review-Kampagne gegen die Audit-Fixe selbst — FIXED (B)

- **Methode:** 2 unabhängige Subagenten mit Widerlegungsauftrag (A:
  GAP-001-Statistikheuristik; B: GAP-002-False-Green/Closure). Regel: Befund →
  Fix → Regressionstest → Suite → Re-Review, bis beide freigeben.
  A: 4 Runden bis JA. B: 10 Runden bis JA. ~80 verifizierte Angriffsrepros.
- **Behobene Kernklassen (Auswahl):** nan/inf-Crash-Kaskade (F1);
  Outcome↔Design-Fehlklassifikation binärer Erfolgsraten (F2); Pooling bei
  >12-Level-Designs inkl. falscher „never pooled"-Audit-Zusicherung (F3);
  Replikationsachsen-/ID-/BOM-Verwechslungen (F4/F5); String-statt
  Wert-Gruppierung (F6); Makro-Key-Kollisionen mit stillem Metrikverlust (F7);
  compose.py nutzte veraltete Makro-Sanitisierung — deterministische Kette
  wäre an U2 gescheitert (F-R0); U2-Gate-Evasionen (`42\,\%`, `42~\%`,
  `42 percent`, Unicode-`％`, `2.5x speedup`, `p < .05`, Dezimalkomma, `N =`);
  Rekursionslücke (nur flache sections/); Existenzhaltige-statt-Bindung;
  generated/-Alias-Makros (`\newcommand{\x}{99.9\%}`), Accessor-Redefinition,
  `\let`/`\csname`-Umgehung → **Zeilen-Allowlist + Vollbindung aller
  pf@-Definitionen gegen paper_metrics.json**; `\input` nach `build/`/
  Pfad-Escape verboten; U3 bindet jetzt Inhalte (Output-SHA256, Input-Hashes,
  `\includegraphics`-Rückrichtung, Reverse-Existenz von tables.tex);
  `\url`/`\href`/`\verb`-sensitiver Kommentar-Strip.
- **Dokumentierte Restgrenzen (bewusst akzeptiert):** einstellige Dezimalzahlen
  / bare Integer ohne Einheit (inhärente Regex-Grenze); Referenzen innerhalb
  policy-gebundener generated/-Dateien sind quelltext-ungescannt (N3);
  Paperpal-Deklaration ist extern unprüfbar (ehrlich gelabelt; P36 sieht es).
  **Architektur-Empfehlung (nicht umgesetzt, separater Auftrag):**
  quantitativer Scan des gebauten PDF-Texts bei der Closure — schließt die
  gesamte Evasions-Familie auf Renderebene statt Quellebene.

