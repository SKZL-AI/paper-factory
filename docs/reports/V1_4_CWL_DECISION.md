# V1.4 WP-C — CWL Interchange-Evaluation: Entscheidung

Datum: 2026-10-05 · Worktree `.worktrees/v14-attestation` (Branch `v1.4/wp-c-d-e-f-attestation`) ·
Spec-Grundlage: CWL v1.2/v1.2.1 CommandLineTool (commonwl.org/v1.2/CommandLineTool.html, gelesen 2026-10-05)

## Frage

Kann eine sinnvolle Teilmenge der Reproduction Capsule verlustarm als CWL v1.2
CommandLineTool exportiert werden — ohne einen dritten Runtime-Adapter zu bauen?

## Entscheidung: JA — Exporter gebaut, mit dokumentiertem Verlustprofil

`paper_factory/export/cwl.py` (`build_cwl_tool`, `write_cwl_tool`), Tests in
`tests/test_export_cwl.py` (16 Tests). EXPORT ONLY, kein Runtime-Backend —
die Capsule bleibt der kanonische Reproduktionsvertrag.

## Begründung

CWL CommandLineTool beschreibt Werkzeug-Signaturen (argv, Eingaben, Ausgaben,
Requirements) — genau die Ebene, auf der die Berechnungsbeschreibung der
Capsule liegt. Die prüfende Zuordnung Feld für Feld:

| Capsule-Feld | CWL v1.2 | Urteil |
|---|---|---|
| `command` (reines argv) | `baseCommand` + `arguments` (literal, kein Shell) | **verlustfrei** — CWL-Argument-Semantik ohne ShellCommandRequirement entspricht exakt der argv-Semantik der Capsule |
| `input_refs`/`config_refs`/`code_refs` (+ Lock) | File-`inputs` + `InitialWorkDirRequirement` (Staging am rel_path) | **verlustfrei** (Struktur) |
| Datei-sha256 | `pf:sha256`-Extension-Metadata je Input | **Metadaten-Ebene** — CWL kann Input-Content nicht hashen; Durchsetzung bleibt PF-seitig (s. Verluste) |
| `parameters` (deterministisch) | string-`inputs` mit `default` | **verlustfrei** |
| `parameters` (nichtdeterministisch) | string-`inputs` ohne `default`, `pf:deterministic: false` | **verlustfrei** |
| `expected_outputs` | `outputs` mit `outputBinding.glob` (exakter Pfad) | **verlustfrei** |
| `nondeterministic_outputs` (fnmatch-Globs) | Array-of-File-`outputs` mit `glob` | **verlustfrei** (Array-Typ deckt 0..n Treffer) |
| `environment.container_image` | Hint `DockerRequirement.dockerPull` | **verlustfrei** (als Hint, damit das Tool ohne Container-Engine lauffähig bleibt) |
| `capsule_id`, `capsule_digest`, `cwd`, `provenance_refs`, Environment-Identität, Vergleichspolitik | `pf:*`-Extension-Metadata am Dokument (`$namespaces` deklariert, CWL §2.5 erlaubt Erweiterungsfelder) | **transportiert, nicht semantisch** — s. Verluste |

Der Informationsverlust beschränkt sich damit auf **Durchsetzung statt Daten**:
nichts wird fallengelassen, aber drei Capsule-Semantiken hat CWL nativ nicht.

## Verluste (ehrlich, im Modul-Docstring gespiegelt)

1. **Kein Content-Binding der Inputs.** CWL kennt keinen Mechanismus, Input-Content
   an einen Digest zu binden. `pf:sha256` ist reine Metadaten; die
   Hash-Durchsetzung (capsule_digest als semantische Identität) bleibt
   ausschließlich PF-seitig. Der CWL-Export ist eine Tool-Signatur, keine
   Reproduktionsgarantie.
2. **`cwd`-Semantik.** Die Capsule läuft in `capsule_root/cwd`; CWL-Tools laufen in
   `runtime.outdir` mit gestagten Dateien. `cwd: "."` ist äquivalent; jeder andere
   Wert steht nur in `pf:cwd`, die Verzeichnissemantik ist approximiert.
3. **Ausführungsevidenz hat kein Zuhause.** Receipts gehören nicht in eine
   CommandLineTool-Beschreibung; Lauf-Provenance exportiert weiterhin über
   RO-Crate/PROV (WP9/WP10). Der CWL-Export ist bewusst capsule-only.

## Nicht-Ziele (bestätigt)

- Kein CWL-Runner, kein drittes Runtime-Backend (Nextflow/CWL als Backends
  bleiben hinter dem Contract-DEFER von DEEP_RESEARCH §3.7/3.8).
- Kein Round-Trip (Repo-Konvention: exported invariants statt Re-Import).
- Keine SLSA-/Provenance-Behauptung durch den CWL-Export.

## Serialisierung

JSON — ein gültiges YAML-1.2-Dokument und damit ein gültiges CWL-Dokument.
Test `test_written_document_parses_as_json_and_yaml` pinnt beides
(PyYAML ist bereits Projekt-Dependency).

## Verifikation

- `tests/test_export_cwl.py`: 16 passed (Struktur + Invarianten: argv exakt,
  jede deklarierte Datei mit Hash, jeder Parameter mit Default/Flag, jeder
  erwartete Output als Glob, Docker-Hint, Contract-Metadata, Fail-visible bei
  Identifier-Kollision).
- cwltool ist **nicht** Projekt-Dependency; die Konformitätsbehauptung beruht auf
  Struktur-Invarianten gegen die v1.2-Spec, nicht auf einem lokalen Lauf
  (NOT_RUN, ehrlich verbucht).
