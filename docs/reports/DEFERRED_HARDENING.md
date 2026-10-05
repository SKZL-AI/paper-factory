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
- B-R6-2 (NIT, akzeptiert): doppelt-eskapierte HTML-Entities in DataCite-
  Titeln (`&amp;amp;`) hinterlassen nach einmaligem `html.unescape` ein
  `&amp;`-Token-Residuum → fail-closed False-Mismatch auf Registranten-Noise;
  sehr selten, Richtung nie False-Green.

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

## 2026-10-01 (P31-Block Review R3) — akzeptierte Restrisiken

- **A R3-2 (Medium, dokumentiert):** `dedupe_key` kollidiert, wenn ein Finding
  NUR claim_refs als Identität trägt (kein value/doi/span/bound_metrics) — eine
  durable Decision könnte dann ein fremdes Issue mit derselben claim_ref-Menge
  stillschließen. Richtung: false-close. Existiert schon in GAP-010-Dedupe;
  durable Store vergrößert die Tragweite. TODO: claim-only Keys um
  Statement-Hash verfeinern, wenn ein realer Kollisionsfall auftritt.
- **A R3-3 (Low, false-green Richtung):** die Phrasen-Brücke `{0,8}` matcht
  zufällige Prosa-Koinzidenz ("The nll, a rounded error estimate" nennt
  `nll_A_rounded` fälschlich). Und: Single-Part-Feld `nll` matcht weiterhin
  innerhalb von `nll_A_rounded`. Beides lockert nur U2's Label-Check; der
  Group-/Design-Point-Check darunter ist unverändert scharf.
- **A R3-4 (Low, false-fail Richtung):** umgeordnete Feldteile ("the rounded
  nll value") matchen nicht mehr — legitime Prosa muss die Feldreihenfolge
  einhalten. Fail-visible, bewusst akzeptiert.
- **B R3-F5 (dokumentiert):** `word_auto` + kaputter Renderer + echte
  Inbox-Evidenz → P31 PASS steht (Evidenz ist an ihr eigenes staged DOCX via
  Sidecar-sha256 gebunden); der State trägt `docx_outbox_error` sichtbar.
- Paperpal "Download edits with track changes" ist im Word-Add-in web-only —
  nicht verfügbar, ehrlich verbucht (kein Export-Artefakt).


## 2026-10-02 — Release-Audit Phase 1/2 (arXiv-Render + Export)

- **B R3-MIN-1 (Residual):** absolute-path-Erkennung ist Allowlist
  (`/home/`, `/mnt/`, `/etc/`, `/Users/`, `/tmp/`, `~/`, `C:\`, UNC `//`);
  Backslash-UNC (`\\server\share`), `/var/`, `/opt/` entgehen. Langfristig:
  generischer Absolutpfad-Detektor.
- **B NIT:** custom `.bst` im Source-Dir wird von bibtex nicht gefunden
  (kein BSTINPUTS) → leere .bbl → unresolved-Gate fängt fail-closed.
- **B NIT:** undefined *References* (\ref) gaten nicht, nur Citations.
- **A R2-A2/A3-Kanten:** Head-Heuristik kann Institutszeilen/Inhalte in
  Ausnahmefällen falsch zuordnen — immer sichtbar (nie still), Accounting
  in render_provenance.json.
- **A NIT:** `×10^-4` rendert als Text-Caret („10ˆ-4") — Ziffern korrekt,
  kosmetisch.
- **A NIT:** citations_remapped zählt inkl. gestrippter Referenzlisten-Marker
  (unmapped separat ausgewiesen).
- **B NIT:** `paper.id="a."` akzeptiert (Linux-legal; Windows-irrelevant hier).

## 2026-10-04 — Repo-Professionalisierung (Review-Runden 1–3)

- E2E-Fixture `test_e2e_synthetic.py` läuft citation verification mit Live-Netz
  (OpenAlex/Crossref/doi.org) — auf GitHub-Actions bewusst akzeptiert (Egress
  offen, ehrliche Verifikation statt Hermetik). Falls Flakiness: VCR/Mock oder
  PF_LIVE_NET-Gate auf Fixture-Ebene nachrüsten.
- `paper-factory doctor` schreibt State ins Installationsverzeichnis
  (paper_factory/state/) — bei nicht-editabler Installation problematisch.
  Fix: XDG-State-Home. (v1.1)
- Ruff: 217 Style-Findings (11 auto-fixable) — Hygiene-Block v1.1.
- Social Preview (1280×640) liegt als docs/assets/banner.png — Upload nur via
  GitHub UI möglich (Settings → General), kein API-Endpoint.


## v1.2 Verification Plane — DEFER-Entscheidungen (2026-10-04)

- **LiteratureProvider/PaperQA: DEFER.** Inventur 2026-10-04: `paperqa` wird
  nirgends im Code importiert oder aufgerufen — ein LiteratureProvider-Interface
  hätte genau null reale Consumer und verletzte die eigene Regel „keine
  Abstraktion ohne zweiten Consumer". PF-native Literature Discovery (P06)
  bleibt der einzige Pfad. Der unbenutzte `LiteratureCfg.paperqa2`-Schalter
  bleibt unverändert bestehen (keine stille Mutation); das pyproject-Extra
  `literature=["paperqa"]` bleibt optional und ist keine Core-Hard-Dependency.
- **W3C-PROV-Exporter: DEFER v1.3.** Kein Consumer vorhanden; die
  PF-Provenance (Firewall, Origin-Receipts, render_provenance) bleibt
  kanonisch. Ein Standard-Export ist ohne Abnehmer Spekulation.
- **Reproduction Capsule (P10): DEFER v1.3.** Kein zwingender aktueller Use
  Case; P10-DEGRADED wird transparent dokumentiert, statt eine
  Snakemake/Nextflow/CWL-Schicht ohne Abnehmer zu bauen.
- **SQLite-Schema-Versionierung (runs.sqlite): DEFER v1.3.** Der v1.2-Contract
  versioniert sich selbst (`schema_version`); eine Migration des
  bestehenden SQLite-State ist ein eigenes Risikopaket ohne v1.2-Consumer.
  - *Korrektur-Provenance (2026-10-05): ERLEDIGT auf Branch
    `v1.3/wp2-3-state-hardening` (WP3, Commit 51ecd5b).*
    `PRAGMA user_version` + Migrations-Registry in `state/store.py`,
    Backup-Kopie vor Migration, Idempotenz, fail-visible bei unknown-newer —
    ersetzt die DEFER-Entscheidung; v1.2-DBs migrieren sauber (0→1).
- **Citation/Provenance (Phase 8): REUSE.** Keine Änderung: die bestehende
  DOI/arXiv/authoritative-URL-Verifikation (P21) und die Protected-Prose-
  Firewall bleiben kanonisch. Externe Resolver sind höchstens ergänzend.
- **Historische Freeze-Abgrenzung (Phase 10).** Drei Ebenen bleiben strikt
  getrennt: `HISTORICAL_V1_FREEZE` (Pilot 3, P21–P36, unantastbar) vs.
  `CURRENT_V1_1_COMPLIANCE` (arXiv-Gates, v1.1) vs. `V1_2_REGRESSION_PILOT`
  (zukünftige Replay-Vergleiche auf gespeicherten States). Neue
  Compliance-Anforderungen machen den historischen Freeze nicht rückwirkend
  ungültig, und es werden keine Disclosure-Inhalte erfunden.
- **Stale-/Frische-Mechanismus für ExecutionReceipts: DEFER v1.3.**
  `created_at` wird validiert, aber von keinem Consumer geprüft; `compare()`
  hat keinen Zeitstempel-Input. Der Pinning-Test
  `tests/test_verification_adversarial.py::test_stale_execution_receipt_loads_without_any_freshness_check`
  dokumentiert den Ist-Zustand — ein künftiger Frische-Check hat damit einen
  roten Test, den er grün macht. (WP6-Befund B2, 2026-10-04.)
  - *Korrektur-Provenance (2026-10-05): ERLEDIGT auf Branch
    `v1.3/wp2-3-state-hardening` (WP2.3, Commit 8352422).* Semantische
    Freshness at consumption (`ExecutionReceipt.check_freshness` /
    `ReceiptExpectation` in `verification/contract.py`): stale binding,
    replay/wrong-run (store-backed), wrong backend, wrong schema_version,
    future/missing Timestamp fail-visible; Wall-Clock-Guard opt-in
    (default aus). Der Pinning-Test wurde entsprechend umgeschrieben
    (Laden bleibt backward-kompatibel, Konsumtion geprüft).

## v1.2 Verification Plane — Review-Runde-1-Nachträge (2026-10-04, Dual-Review NEIN)

Ergänzend zu den Code-Fixes (F1–F10) — dokumentierte Ist-Zustände und
bewusste Design-Entscheidungen, nicht stille Annahmen:

- **BackendIdentity.detail als dokumentierter Escape-Hatch (A-2/A-5).**
  `detail` ist ein bewusst untypisiertes Freifeld für Provider-Interna
  (run_id, blocked_kind, hoh_detail, clone_fingerprint). Es gibt keinen
  maschinellen Rückpfad aus `detail` in Verdicts — Verdict-Logik liest nur
  typisierte Contract-Felder; `detail` ist reine Evidenz für Menschen/Reports.
- **findings_map/registry aktuell Bibliothek ohne Produktions-Verdrahtung
  (A-6).** `map_external_findings()` hat noch keinen Aufrufer im Pipeline-Pfad;
  die Verdrahtung ist für v1.3 oder späteren Bedarf vorgesehen. Disposition
  gemappeter Findings bleibt `None` (PF owned) — es gibt keinen falschen
  Grün-Pfad über externe Findings.
  *Korrektur-Provenance (2026-10-05, v1.3 WP8, Branch `v1.3/wp8-findings-
  wiring`): ersetzt durch die Produktions-Verdrahtung.* Eingangspunkt ist
  der Dual-/Shadow-Pfad in `dag/handlers.py`
  (`_ingest_verification_findings`): das shadow-seitige
  `VerificationResult` aus der geteilten `adapter.verify()` füttert
  `reviews.verification_ingest`, das einen `VF-<node>`-Review-Report
  schreibt. Closure bleibt PF-owned: Blocking läuft über U5 wie jedes
  CRITICAL/MAJOR-Finding, Schließung nur per PF-Disposition (durable
  decision); das HoH-Gate bleibt strikt downgrade-only. Identität =
  dieselbe `dedupe_key`-Logik wie native Findings (kind + claim_refs +
  Binding + Statement-Hash); das Artifact-Binding wird als Provenienz in
  `details.external` gestempelt, ist aber nie Teil der Identität.
  Bewusste Lücke: der HoH-only-Pfad (`verify_work_package` → `HohResult`)
  verliert Findings weiterhin (HohResult-Shape trägt sie nicht) — erst die
  Dual-/Shadow-Konfiguration macht Provider-Findings produktiv sichtbar.
- **MATCH im DAG-Pfad aktuell unerreichbar (A-7).** Die PF-native Seite bindet
  im Shadow-Pfad bewusst kein Artifact (honest `None`, keine fabrizierte
  Hash-Bindung); die HoH-Seite kann nur dann binden, wenn das WorkPackage
  Artefakte trägt. Bei gleichem Verdict und beidseitigem `None` ist das
  Ergebnis daher immer SEMANTIC_MATCH, bei einseitiger Bindung INCOMPARABLE —
  MATCH (starke, artifact-provable Übereinstimmung) ist in der aktuellen
  Verdrahtung konstruktiv nicht erreichbar. Dokumentierte Lücke, kein PASS.
- **Shadow-Nebenpfad-Crash → Node FAIL (B-7).** Ein Exception-Escape aus dem
  Shadow-/HoH-Pfad (z. B. Timeout zwischen `hoh start` und `hoh run` nach dem
  Best-Effort-Cleanup) bricht den Node hart (fail-visible, gewollt). Der
  Executor sieht kein stilles Weiterlaufen ohne Verification-Evidenz.
- **ensure_clone außerhalb flock (B-8).** Das Clone-Refresh läuft bewusst
  VOR der seriellen Run-Phase (außerhalb des fcntl-Locks) — Analogon zur
  dokumentierten A-R3-TOCTOU-Annahme: PF führt pro Workspace sequential
  aus (1 Job/GPU-Hausregel), daher kann kein zweiter PF-Prozess zwischen
  Fingerprint-Prüfung und Clone-Nutzung einschneiden. Parallele Fremd-Prozesse
  auf demselben Workspace werden nicht unterstützt.
- **Pane-Guard-Randfall lange node_id (B-8-Anm.).** Bei node_id > ~20 Zeichen
  würde Herdr die Agentennamen truncaten; ein Tab, dessen ID die run_id dann
  nicht mehr enthielte, wird vom Provenance-Guard als `skipped_foreign`
  protokolliert und NIEMALS geschlossen — sichtbar im pane_cleanup.json,
  nie still verworfen. PF-Run-IDs setzen den Zufallsteil deshalb vor den
  Truncation-Punkt (AGENTS.md).
- **pf_run_failure.json ohne DB-Registrierung (B-N1, Re-Review 2026-10-04).**
  Das Failure-Receipt einer gescheiterten Run-Phase landet auf Disk (Run-Baum
  + kollektiert in `receipts/hoh/<run_id>/`), wird aber bewusst NICHT als
  `kind="hoh"` in der `receipts`-Tabelle recorded: die Exception propagiert,
  der Node fällt FAIL und U7 bleibt ehrlich FAIL — ein Failure-Receipt als
  HoH-Receipt in der DB würde das Gate künstlich sättigen (Analogon zum
  F1-False-Close). Reine Sichtbarkeits-Inkonsistenz (Disk vs. DB), kein
  Handlungsbedarf.
- **Korrektur-Provenance (2026-10-05): „MATCH im DAG-Pfad unerreichbar"
  ist geschlossen.** Gesetzt in den Runde-1-Nachträgen (2026-10-04, galt für
  den Stand vor aa4de1f), ersetzt durch den Eintrag in
  `docs/V1_2_VERIFICATION_PLANE_PLAN.md` §5b (artefaktgebundener Shadow-Pfad,
  caller-deklarierte Bindung per Konstruktion, Resume-Sicherheit F-1). Dieser
  Eintrag bleibt aus Provenance-Gründen stehen; maßgeblich ist §5b.
- **Herdr-Dispatch-Stall bei neuen CLI-TUI-Versionen (Live-Feldtest
  2026-10-05).** Der Herdr-Pfad von HoH stallt bei der Developer-Rolle
  systematisch (`agent_prompt_stalled`: herdr verlangt eine beobachtete
  Zustandsänderung innerhalb 5000ms; kimi zeigt einen Welcome-Screen,
  codex ein leeres Pane — beides unterschreitet das Fenster nicht).
  Planner via Herdr funktioniert. Das 5s-Stall-Fenster ist herdr-seitig
  hartkodiert und durch PF nicht konfigurierbar; Workaround im Adapter:
  `use_herdr=False` → `hoh run --no-herdr` (Subprocess-Dispatcher statt
  Panes) mit dokumentiertem Evidenz-Trade-off (keine A01/A02/A12-
  Akzeptanz-Evidenz, Pane-Cleanup entfällt, `backend.detail["evidence_note"]`
  vermerkt es ehrlich). Empfehlung an herdr/veriharness: Stall-Fenster
  konfigurierbar machen. Belegt durch die Runs PF-73ed7828-P05,
  PF-581db7b3-P05, PF-7aeb552c-P05 (2026-10-05).
- **Gate-Asymmetrie herdr vs. --no-herdr (A-15, Proof-Review 2026-10-05).**
  Der handlers-/DAG-Pfad (`dag/handlers.py`) verlangt aktuell ein
  herdr-Runtime (`diag["herdr"]`) als Voraussetzung für HoH-Runs, auch wenn
  der Adapter `use_herdr=False` könnte. `--no-herdr` ist damit nur über
  Direkt-Caller erreichbar (Proof-Skript `scripts/run_integration_proof_v12.py`);
  das DAG-Plumbing (Config-Option, die use_herdr durch `build_handlers`/
  `wrapped` reicht) bleibt bei Bedarf — aktuell kein Consumer dafür im
  Pipeline-Pfad, und ohne Pane-Nachweis sättigt ein --no-herdr-Run das
  HoH-Receipt-Gate (U7) nur mit dokumentiertem Evidenz-Vorbehalt.

## v1.2 Integration-Proof — Review-Nachträge (2026-10-05, Dual-Review JA/JA)

Reviewer A (Integrity/Contract) und B (Receipt/Provenance/Isolation) auf
`1e68d74..4d4f9e9` + Proof-Evidenz: beide JA, CRITICAL/MAJOR = 0. Getrackte
Restpunkte:

- **MINOR: `_hoh_result_from_verify` droppt top-level `evidence_note`/`herdr`
  (Reviewer A, latent).** `handlers.py:302` kopiert nur
  `backend.detail["hoh_detail"]`; die top-level-Felder, die `verify()` bei
  `use_herdr=False` setzt, gingen im Gate-Pfad verloren. Heute unerreichbar
  (Dualpfad ruft `verify(package)` ohne Optionen; `use_herdr=False` ist im DAG
  nicht verdrahtet, vgl. A-15 oben). Vor einem künftigen DAG-Plumbing von
  `use_herdr=False` muss die Mapping-Asymmetrie geschlossen werden, sonst
  würde der Evidenz-Vorbehalt still verschwinden (Verletzung des
  „never silently dropped"-Kommentars, handlers.py:328-329).
  - *Korrektur-Provenance (2026-10-05): ERLEDIGT (WP2.2, Commit 0783c6e).*
    Die Felder werden wie im Shim in `hoh_detail` übernommen; Regressionstests
    (Mapping + dual path) liegen vor — das zukünftige Plumbing ist entlastet.
- **MINOR: `_collect_receipts` validiert Receipt-Interna nicht
  (Reviewer B).** `adapter.py:668-681` schützt run_id-Provenance nur indirekt
  über Verzeichnis-Scoping (`runs_root/<run_id>/receipts`); ein inhaltlich
  fremdes Receipt im eigenen Verzeichnis würde kopiert und SHA-registriert.
  Hardening: beim Kollektieren `receipt["run_id"] == run_id` fail-visible
  prüfen. Kein akuter Vektor (Receipt-Verzeichnis ist run-scoped und
  PF-owned), aber ein billiger zusätzlicher Guard.
  - *Korrektur-Provenance (2026-10-05): ERLEDIGT (WP2.1, Commit 2f51260).*
    `ReceiptValidationError` + `receipt_provenance.json`-Marker; fehlende
    run_id wird sichtbar markiert statt still akzeptiert (Backward-Compat).
- **NIT (A):** `shadow.py:14-15` Outcome-Docstring beschreibt MATCH ohne den
  By-Construction-Vorbehalt, den die Dualpfad-Rationale trägt (shadow.py:111-116).
  Generisch korrekt; bei Doc-Berührung präzisieren.
- **NIT (A):** `iterations`-Backend-Option ohne Wertvalidierung (0/negativ
  läuft bis zur CLI); DAG-Pfad kann Rollen nicht konfigurieren (Defaults nur)
  — Feature-Lücke, kein Defekt.
- **NIT (B):** Tilde-maskierte Home-Pfade (`~/paper-factory/…`) in
  committeter Proof-Evidenz; vollständiges Entfernen der Pfad-Strings wäre
  strenger. Akzeptiert: kein absoluter Pfad, keine Secrets (grep-bewiesen).
