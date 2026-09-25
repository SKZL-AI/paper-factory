# REAL PILOT 02 REPORT — TSCG-2.0 (CODE+DATA, draftlos)

Projekt: TSCG-2.0 Arbeits-Repo (Paper 3 / AOC), Quelle `/home/sai/TSCG Ubuntu/work/tscg-2.0`
(read-only, `node_modules` ausgeschlossen, Secrets-Pre-Check sauber).
Workspace: `pilots/pilot-02-tscg/project/` (248 Dateien, Source-Inventory mit SHA-256).
Config: `pilots/pilot-02-tscg/config` · PF-HEAD `1ba47a7` · Lauf: `complete-20260925T163702Z`

**Ziel des Pilots:** materiell anderes Intake-Szenario als MassInv (kein Draft, keine
Chat-History, JS/TS-Code + SQLite-DB + Fixtures statt LaTeX-Draft + JSONL-History).
Erfolgskriterium ist nicht PASS, sondern korrekte Unterscheidung der Endzustände.

## ENDZUSTAND

**overall FAILED / Exit 1** — ehrlich und korrekt: das System fabuliert kein Paper
aus dünnem Evidenzboden.

## INPUT MODE

`MIXED_EVIDENCE` (code: 105, data: 12, drafts: 0, bib: 0, chats: 0) — vom System
automatisch erkannt, korrekt.

## PIPELINE (Auswahl)

| Node | State | Befund |
|---|---|---|
| P00 Doctor | DEGRADED | fehlende Systempakete (bekannt, Umgebung) |
| P01 Intake | PASS | korrekte Modus-Erkennung, 117 T0-Evidence-Artefakte gehasht |
| P02 Context | DEGRADED | „no chat/history artifacts found" — wahr |
| P03 Reconstruction | PASS | minimale Rekonstruktion aus Intake |
| P04 Evidence | PASS | 117 T0 entries |
| P05 Integrity Audit | PASS, 0 findings | keine Drafts → nichts zu prüfen (korrekt) |
| P06 Literature | PASS | 10 unique works — **aber komplett themenfremd** (s. GAP-3) |
| P07 Prior-Art | PASS | 0 claims attacked, pool 10 (nutzlos wegen GAP-3) |
| P08 Claims | DEGRADED | „no candidate claims found" (kein Draft) — ehrlich |
| P09 Statistics | DEGRADED | „no results/ directory" — **siehe GAP-1** |
| P10 Repro | DEGRADED | keine Repro-Kommandos entdeckt (JS-Repo) |
| P16–P20 Manuscript | PASS | Scaffold mit `<<PF:…>>`-Platzhaltern, Structure-Check PASS |
| P21 Citations | DEGRADED | keine Bibliographie im Projekt (wahr) |
| P31 Paperpal | HUMAN_REQUIRED | Bridge aktiv, Outbox geschrieben (wie erwartet) |
| **P32 Venue** | **FAIL** | `bib_exists` + `compiles` fehlgeschlagen — **siehe GAP-2** |
| P33–P37 | SKIPPED_DEPENDENCY | korrekte Blockade |

## REAL-WORLD PF GAPS (Klassifikation A projekt / B PF-Core / C Adapter)

### GAP-1 (B): Metrik-Ableitung ist `results/`-pfadkonventionell
- **Beobachtet:** P09 DEGRADED „no results/ directory — no metrics derivable",
  obwohl das Projekt reiche Daten trägt (`runs/baseline.sqlite` mit Tabellen
  `sources/call_counts/savings`, `runs/scan_dump.json`, `fixtures/benchmark-logs/`).
- **Erwartet:** Datenhaltige Projekte ohne `results/`-Konvention liefern Metriken
  (Roadmap-Datenbankunterstützung: SQLite/DuckDB/CSV existiert konzeptionell).
- **Evidenz:** P09-Detail im Node-Record; `runs/baseline.sqlite` vorhanden.
- **Klassifikation:** B (PF-Core, generisch). Reproduziert: ja, deterministisch.
- **Core-Fix gerechtfertigt?** Kandidat für GAP-012: Metrik-Discovery über
  konfigurierbare Datenpfade + SQLite-Tabellen als Metrikquelle. Regressionstest:
  Projekt mit `runs/*.sqlite` statt `results/`.

### GAP-2 (B): Composer referenziert `generated/*.tex` bedingungslos
- **Beobachtet:** P32 `compiles` FAIL mit `! LaTeX Error: File 'generated/numbers.tex'
  not found.` — bei P09-DEGRADED (keine Metriken) wird `generated/` nie erzeugt,
  `main.tex` `\input{}` zeigt trotzdem dorthin.
- **Erwartet:** entweder leeres valides `generated/numbers.tex`/`tables.tex`
  (Provenienz-Header, null Makros) oder bedingtes `\input` — P32 sollte dann aus
  prinzipiellem Grund (kein Inhalt) statt wegen fehlender Datei scheitern.
- **Evidenz:** `reports/venue_compliance.json` hard_errors; `paper/main.tex:6`.
- **Klassifikation:** B (PF-Core, Robustheit). Das Endzustand-FAILED bleibt in
  beiden Varianten ehrlich — es geht um die *Qualität* des Failures.
- **Core-Fix gerechtfertigt?** Ja, klein: Composer emittiert leere generated-Files
  bei DEGRADED-Metriken. Regressionstest: draftloses Projekt → P32 fällt mit
  „no content", nicht „file not found".

### GAP-3 (B): Literature-Discovery-Query zu generisch
- **Beobachtet:** 10 unique works, alle themenfremd (NCEP Reanalysis, Quantum
  Espresso, GTEx, Sperm Whales, Warships) — der Titel „…(PF Pilot 2)" mit
  generischen Termen steuert die Query.
- **Erwartet:** Projektkontext (README, Code-Struktur, vorhandene Bib) steuert
  die Query; ein „Pilot"-Suffix darf nie in die Query gelangen.
- **Evidenz:** `reports/literature_discovery.json`.
- **Klassifikation:** B (PF-Core, Query-Konstruktion). Konsequenz: P07-Pool
  wertlos für solche Projekte (hier harmlos, da 0 Claims).
- **Core-Fix gerechtfertigt?** Kandidat: Query aus Claim-/Evidence-Vokabular
  statt Titel; „Pilot"-Suffixe filtern.

## PROJEKTSPEZIFISCHE BEFUNDE (keine PF-Defekte)

- Keine Bibliographie im Projekt (`bib_exists` FAIL) — legitim.
- Kein Manuskript-Draft — nichts zu rekonstruieren; PF erfindet nichts.
- JS/TS-Toolchain: keine Python-Repro-Kommandos (P10 DEGRADED, ehrlich).

## VERGLEICH ZU PILOT 1

| | Pilot 1 (MassInv, MIXED) | Pilot 2 (TSCG-2.0, CODE+DATA) |
|---|---|---|
| Intake erkannt | MIXED_EVIDENCE ✓ | MIXED_EVIDENCE ✓ |
| Claims | 3 (gebunden, retiriert) | 0 (kein Draft — ehrlich) |
| number_mismatch MAJOR | 0 | 0 (nichts zu prüfen) |
| Endzustand | HUMAN_REQUIRED/3 (P36) | FAILED/1 (P32) |
| Substanzielle PF-Gaps | keine neuen | **GAP-1, GAP-2, GAP-3** |

## HUMAN_REQUIRED

- Paperpal (P31): Outbox steht, Inbox erwartet echten externen Check — für diesen
  Pilot nicht nachgezogen, da P32 unabhängig davon FAIL bleibt.
- P36 Sign-off: nicht erreicht (P32 FAIL blockiert).

## EMPFOHLENE NÄCHSTE SCHRITTE (aus Pilot-Evidenz, nicht davor)

1. GAP-2 fixen (klein, generisch, sofort mit Regressionstest).
2. GAP-1 als GAP-012 designen (Metrik-Discovery über konfigurierbare Datenpfade
   inkl. SQLite), danach GAP-3 (Query-Vokabular).
3. Pilot 3 erst nach GAP-1-Fix auf demselben Projekt wiederholen — erwartetes
   Delta: P09 PASS/DEGRADED mit echten Metriken aus `baseline.sqlite`.

## GIT

- `pilots/pilot-02-tscg/` lokal (untracked wie Pilot-Workspaces üblich).
- Dieser Report: `REAL_PILOT_02_REPORT.md` (neu, versioniert).
- Historische Commits unverändert; kein Push.
