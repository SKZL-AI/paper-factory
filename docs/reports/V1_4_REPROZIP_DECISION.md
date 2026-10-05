# V1.4 WP-F — ReproZip Decision Gate: DEFER

Datum: 2026-10-05 · Worktree `.worktrees/v14-attestation` (Branch `v1.4/wp-c-d-e-f-attestation`)

## Gate-Frage (DEEP_RESEARCH_DELTA_POST_V1_2.md §3.10)

Zeigen die **realen Capsule-Piloten** eine System-Level-Dependency-Lücke, die
die PF-Capsule nicht sinnvoll abdeckt — und existiert ein **realer Consumer**
für ReproZip-Bundles?

## Geprüfte Evidenz

1. **v1-3-repro-synth** (`docs/reports/V1_3_PILOT_MATRIX.md` Lane A): Capsule
   `python3 pilot_compute.py`, deklarierte Code-/Input-Hashes,
   `expected_outputs: [summary.json, table.txt]`. Ergebnis:
   **REPRODUCED_EXACT** — beide Läufe identische Output-Hashes, dreifache
   Konsistenz über LocalReproductionRunner und SnakemakeBackend.
2. **repro_pilot / real-pilot-01-rerun** (`V1_2_PILOT_DIFFERENTIAL_real-pilot-01-rerun.*`,
   Fixture `tests/fixtures/repro_pilot`): gleiche Bauart — reine
   Python-Computation über deklarierte Dateien.
3. **EnvironmentIdentity** deckt die deklarierte Abhängigkeitsoberfläche:
   `python_version`, `platform`, `tool_versions`, `dependency_lock_ref`,
   `container_image` (letzterer als Docker-Hook auch in den
   Snakemake/Conda-Pfaden belegt, `V1_3_WP7_SNAKEMAKE_PROOF.md`).
4. **GAP-009** (`REAL_PILOT_01_GAP_REPORT.md`): fehlende Systempakete
   (`latexmk`, `dot`, `qpdf`, `pdftotext`) betreffen die **eigene
   Dokument-Toolchain von PF** (PDF/Graphik-Build) — nicht eine
   Capsule-Computation. Die Pipeline läuft degradations-ehrlich; es ist
   kein Reproduktionsversagen einer Kapsel und kein Nachweis, dass ein
   Tracing-Capture eine Kapsel gerettet hätte.
5. **Consumer:** Es gibt keinen realen Abnehmer für ReproZip-Bundles
   (kein Archiv-Exportpfad, kein Reviewer-Workflow, kein Drittsystem).

## Entscheidung: DEFER — beide Gate-Bedingungen unerfüllt

- **Keine demonstrierte Lücke:** Kein realer Capsule-Pilot scheiterte an einer
  System-Level-Dependency, die EnvironmentIdentity + deklarierte Dateien +
  optionales Container-Image nicht abdecken. Die bisherigen Capsules sind
  Interpreter-plus-Dateien; genau das ist ihr Design-Scope.
- **Kein Consumer:** ReproZip wäre ein Schwergewicht (OS-Tracing,
  Binary-Bundles) ohne Abnehmer — gegen die eigene Regel „keine Abstraktion
  ohne zweiten Consumer" und gegen §3.10 („never a core dependency").

## Wiederöffnungsbedingungen (beide nötig)

1. Ein **realer Capsule-Pilot** scheitert reproduzierbar an einer
   nichtdeklarierten System-Abhängigkeit (z. B. natives Shared Object,
   externes CLI-Tool ohne Versionsevidenz), die durch nachträgliches
   Ergänzen der Kapsel nicht ehrlich zu schließen ist, **und**
2. ein realer Consumer existiert (z. B. ein Journal-/Archiv-Exportpfad, der
   ReproZip als gefordertes Format nennt).

Dann ist ein **isolierter ReproZip-Adapter/Exporter-Pilot** erlaubt — nie ein
Core-Dependency, nie still im Hintergrund tragend.

## Nicht-Ziele

- Kein ReproZip-Code in diesem WP.
- Keine nachträgliche Uminterpretation der Capsule als unzureichend: die
  Capsule bleibt das primäre, contract-gebundene Format (§3.10).
