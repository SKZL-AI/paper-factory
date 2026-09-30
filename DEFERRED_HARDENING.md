# DEFERRED HARDENING — nicht blockierende Restbefunde

Alle Einträge sind bewusst zurückgestellt (kein CRITICAL/MAJOR, kein Gate betroffen).
Jeder Eintrag: Befund · Herkunft · Severity · geplante Richtung.

## Ruff (Stand nach Safe-Fix-Runde, Suite 389+1 grün)

61 verbleibende Findings, nicht auto-fixbar — Fall-zu-Fall-Prüfung nötig:

- `B023` (11) function-uses-loop-variable — Closures in Schleifen; teils beabsichtigt
  (späte Bindung in DAG-Handlern), teils prüfenswert.
- `BLE001` (9) blind-except — bewusste fail-closed-Stellen; je Stelle prüfen, ob
  die Exception-Klasse verengt werden kann ohne Semantikverlust.
- `PLW1510` (18) subprocess-run-without-check — meist bewusst (Exitcode wird
  anschließend ausgewertet); Einzelprüfung.
- `RUF059` (7) unused-unpacked-variable, `F841` (3) unused-variable,
  `RUF015` (3), `SIM102` (2), `ISC004` (2), Rest Einzelbefunde.

## Reviewer-Restbefunde (MINOR/NIT, dokumentiert)

### GAP-012 (Metrik-Discovery)

- B-F3 (akzeptiert): WAL-Kombinations-Digest wird bei Emission gehasht, die private
  Kopie bei Discovery gelesen — ein Live-Writer dazwischen kann Hash≠Gelesenem
  erzeugen; downstream als U7-Drift sichtbar, nie still grün. Offline-Pipelines
  haben keinen Live-Writer. Kommentar in `_hash_source`.
- A-R3-NIT (behoben in R4): in-root symlinkte Dateien → jetzt sichtbare Exclusion.

### GAP-011 (pfget-Label-/Gruppen-Bindung)

- E1 (MINOR, dokumentierte Designwahl): Same-Field-Lockvogel — eine zweite Makro-
  Verwendung desselben Felds kann die Design-Punkt-Attribution absorbieren.
  Der Composer schreibt diese Form nie; der Wert bleibt provenance-gebunden.
- Fenster ±200 Zeichen (A F-C): Tabellen-Kopfzeilen jenseits der Fensterweite
  lösen lautes FP aus — ehrliche Richtung, bewusst akzeptiert.
- Tie-Slack 5 bei genuin mehrdeutiger Slash-Paar-Prosa (B-N2).

### GAP-013 (Literatur-Query)

- Case-/Whitespace-Varianten von Queries werden case-sensitiv dedupliziert
  (kosmetisch, B-NIT).
- Schwache aber nicht-generische Dir-Namen können noch durch den Filter (Schaden
  begrenzt durch Downstream-Term-Overlap ≥ 2).

## System / Environment

- ~~Fehlende Systempakete (HUMAN_REQUIRED, sudo)~~ — ERLEDIGT 2026-09-30:
  `texlive-latex-extra` (war schon da), `graphviz`, `qpdf`, `poppler-utils`
  installiert; doctor meldet pdflatex/xelatex/dot/qpdf/pdftotext = present.
  Einzig `latexmk` fehlt noch (optional — export.py hat pdflatex-Fallback).
- 1 Test ehrlich umgebungsbedingt NOT_RUN (`tests/test_e2e_synthetic.py:302`,
  HoH-Receipt-Verzeichnis nicht auf dieser Maschine).
- Paperpal: manuelle Outbox/Inbox-Bridge (kein offizielles API/MCP) — P31 ist
  HUMAN-IN-THE-LOOP; operator_check ≠ external_paperpal (Status-Semantik seit
  Post-Pilot-Audit sauber getrennt).
