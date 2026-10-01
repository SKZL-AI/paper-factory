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

### Citation Identity (Final Acceptance 2026-10-01, Runden R1–R3)

Dokumentierte Risikoakzeptanz der verbleibenden Kollisionsklassen (Reviewer A
N9/N11/N12/N13 — alle benötigen einen falschen DOI, dessen Werkstitel nach
Normalisierung exakt mit dem zitierten Titel kollidiert):

- N9 (MAJOR-Mechanismus, End-zu-End HYPOTHESIS, akzeptiert): LaTeX-Makronamen
  werden entfernt → Titel, die sich NUR im Makro unterscheiden, kollidieren
  (`$\Lambda$CDM` vs. `$\omega$CDM` → beide `…cdm…`). Griechische Makros auf
  Unicode zu mappen wäre die nächste Härtung, ändert aber nichts am
  Grundproblem: die Norm ist bewusst auf [a-z0-9] reduziert, damit Crossref-
  Unicode-Titel mit BibTeX-Escapes matchen. Wer so etwas zitiert, hat ohnehin
  menschliche Reviewer.
- N11 (MINOR, akzeptiert): ue/oe/ae-Folding kollidiert Namensvarianten
  (Mueller ≈ Muller ≈ Müller). Gewollt für die BibTeX-Transliterations-
  konvention (B-1/F6 waren sonst False Positives); Kollisionsrichtung ist
  „zu tolerant", nie „zu streng".
- N12 (MINOR, HYPOTHESIS): abgeschnittene Bib-Titel — Trunkierung an
  Wortgrenze mit Subtitel-Separator bleibt Präfix-Match; mitten im Wort →
  CRITICAL auf korrekte Zitation. Keine Trunkierungs-Detektion vorhanden.
- N13 (NIT): der <2-Token-Guard (`unjudgeable`) ist mit zwei Schrott-Tokens
  umgehbar — ein Angreifer, der Bib-Titel fälscht, wird zusätzlich durch
  U4-Scope-Note und menschliches P36-Sign-off aufgefangen.
- A-P2 / B-R3-3 (MINOR, akzeptiert, fail-closed): parenthesisierte Editionen
  („Attention Is All You Need (Extended Version)") und Punkt-Subtitel
  („Statistical Learning. With Applications") sind keine erkannten
  Subtitel-Separatoren → legitime Zitationen dieser Form werden CRITICAL
  und müssen menschlich aufgelöst werden. Richtung ist nie False-Green;
  erkannte Separatoren sind `:`, `–`, `—`, ` - ` (Whitespace-gekapselt).
- A-P4 (MINOR, akzeptiert): Separator-Sibling-False-Negative — ein anderes Werk
  mit demselben Haupttitel (`Deep Learning: A Different Survey` bzw.
  `Deep Learning - A Different Survey`; Klasse gilt für ALLE erkannten
  Separatoren `:`/`–`/`—`/` - `) matcht den Bib-Haupttitel `Deep Learning`
  über die Subtitel-Regel. Einseitigkeit (nur resolved-Seite, B-R3-2-Fix)
  schließt die Gegenrichtung; die verbleibende Klasse braucht ein Derivat,
  das sich den Haupttitel teilt — selten, und die Autoren-/Venue-Daten bleiben
  im Audit-Record sichtbar.
- Timestamp-Generationen (NIT, akzeptiert): `utcnow` trägt seit der
  Identity-Härtung Mikrosekunden; `_ts`-Vergleiche über Formatgenerationen
  (altes Sekunden-Artefakt vs. neues Micro-Artefakt in derselben Sekunde)
  ordnen `Z` > `.` — ein altes Final kann in diesem ≤1s-Fenster nach einem
  Code-Upgrade ein neues P21-Audit „überholen". Selbstheilend beim nächsten
  Lauf; betrifft auch das Dashboard-`sorted(glob)` für dieselbe Sekunde.

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

### Pilot-3-Fixe R2/R3 (draft_refs / U4)

- B-R2-F3 (NIT, HYPOTHESIS, nicht-Linux): auf case-insensitiven Dateisystemen
  könnte `Parsed_From_Draft.BIB` dem Glob beitreten und die Verdrängung
  umgehen (exakter Namensvergleich). Linux-inert.
- A-R2-N-E/F1 (deferred): Pointer-Sätze („Figure 3 shows N …") matchen den
  Claim-Cue absichtlich weiter — sie retiren über UNSUPPORTED; Dokumentation
  im Code (builder.py CLAIM_CUE-Kommentar).
- Derived-Bib Titel können Rohbestandteile tragen („arXiv preprint …", „URL") —
  kosmetisch; die Einträge sind T4 und werden vom Citation-Audit verifiziert
  bzw. als unverifiable_citation/false_citation behandelt.
- B-R3 (MINOR, akzeptiert): ein Tippfehler-Eprint in einer ECHTEN .bib erzeugt
  jetzt über die arXiv-DOI-Synthese CRITICAL false_citation → der Eintrag wird
  aus references.bib gedroppt (laut + in references_build.json dokumentiert).
  Ehrliche Richtung, aber strenger als vor dem Fix.
- A-R3-5-Residual: Bibliographien OHNE [N]-Marker/\\bibitem werden weder
  geschnitten noch geparsed (konsistent mit draft_refs) — Referenztitel mit
  Cue-Verben können dann theoretisch noch als Claim-Rauschen erscheinen;
  Schaden begrenzt (UNSUPPORTED-Pfad, kein Evidence-Binding).
- A-R3-TOCTOU (NIT, HYPOTHESIS): zwei parallele PF-Prozesse auf demselben
  Root könnten im selben `_versioned_rename`-Fenster kollidieren; PF-Runs sind
  per Design sequentiell pro Workspace.
- A-R4-4 (MINOR, akzeptiert): ein `@type{key,`-Muster INNERHALB eines
  Bib-Felds (z.B. im Titel) splittet den Span → Phantom-Entry erbt Restfelder.
  Richtung ist laut (Phantom wird auditiert), nicht still; Trigger in realen
  Publisher-Bibs praktisch nicht vorhanden. Alternative (Zeilenanker `^@`)
  würde fail-open (stille Skipps) — bewusst abgelehnt.
- Bullet-Listen nach einem „# References"-Diskussions-Heading gelten als
  Bibliographie-Evidenz (Cut) — ein Aufzählungs-Diskussionsabschnitt in den
  4000 Zeichen danach würde geschnitten (bounded, akzeptiert).
- A-R5-B1 (MINOR): malformige Markdown-Tabellenzeile ohne schließendes Pipe
  (`| a | b | trailing`) überlebt die Grid-Maske; braucht Cue+Zahl im selben
  Fenster. A-R5-B2 (MINOR): ≥4 Spaces eingerückte Bibliographien werden nicht
  geschnitten — fail-open, aber laut (UNSUPPORTED/U1-MAJOR).
- A-R5-B3 (MINOR): `@string{key, "val"}`-Komma-Syntax / `@preamble{"A, B"}`
  erzeugen Phantom-Entries (je ein spurious no_doi-MINOR). Entry-Type-
  Whitelist als mögliche spätere Härtung notiert.
- B-R5-NIT (MINOR): Bib-Keys mit Leerzeichen werden von `_ENTRY_START` nicht
  erkannt → Entry still übersprungen (konservativ: nie als resolved
  attestierbar; LaTeX-Compile fällt sichtbar). Kein Warn-Finding heute.

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
