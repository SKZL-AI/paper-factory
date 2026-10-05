# V2.0 WP-III — Cross-Platform / Packaging (ehrliche Matrix)

Stand: 2026-10-05 · Basis: 756c692 + WP-I/WP-II-Docs · Maschine: Ubuntu 22.04 on
WSL2 (`Linux-6.6.87.2-microsoft-standard-WSL2`, glibc 2.39)

## 1. Plattform-Abhängigkeiten (Inventar)

| Bereich | Datei | Plattformbindung | Dokumentiert? |
|---|---|---|---|
| Nextflow-Reaping | `reproduction/nextflow_backend.py:171` (`run_owned_pids`) | **Linux-only:** `/proc`-Walk (`/proc/<pid>/cwd`, `cmdline`). Andere OS → leere Liste, Reaping no-op | ja — Docstring: „Linux /proc walk; empty list elsewhere or on any error" |
| Nextflow/Snakemake Kill | `nextflow_backend.py`, `snakemake_backend.py` | POSIX: `os.killpg`/`os.getpgid`+`SIGKILL` (Prozessgruppen). Windows-native: `os.killpg` existiert nicht | implizit (POSIX-APIs); Fail-wäre sichtbar, nicht still |
| P31 Word-Pfad | `paperpal/word/driver.py` | **WSL-Design:** `powershell.exe`-Aufrufe, `wsl_to_win`/`win_to_wsl` (`/mnt/c`-Übersetzung), Exchange-Dir unter `%USERPROFILE%` | ja — Modul-Docstring + `docs/PAPERPAL_AUTOMATION.md` |
| WSL-Erkennung | `state/inventory.py:125` | `platform.release()` enthält „microsoft" → WSL-Flag (rein informativ) | ja |
| Alles andere (DAG, contracts, exports, store, CLI, capsule/verification/reviews/statistics) | — | portabel (pure Python + `pathlib`, keine POSIX-only APIs gefunden) | n/a |

Tests mit ehrlichen Environment-Skips (kein Verstecken, echte Bedingung):
- `test_nextflow_backend.py` / `test_snakemake_backend.py`: skipif, wenn Binary
  fehlt (`requires_nextflow` / `requires_snakemake`).
- P31-nahe docx-Tests (`test_real_pilot_gaps.py`, 3×): skipif `pandoc` fehlt.
- Die **Word-Session selbst läuft grundsätzlich nicht in pytest** — sie braucht
  Windows-GUI + Word-Add-in und wird mit echten Screenshot-Receipts verifiziert
  (Kommentarblock im Test, `test_real_pilot_gaps.py` ~Zeile 6045). Die offline-testbaren Teile (Pfad-Translation,
  classify, transitions.jsonl) sind reine Funktionen und laufen überall.

## 2. CI-Matrix (Ist-Zustand, ehrlich)

`.github/workflows/ci.yml`:
- **OS: nur `ubuntu-latest`.** Kein Windows, kein macOS.
- **Python: 3.11 und 3.12** (`requires-python >=3.11`).
- System-Toolchain: pandoc, texlive, graphviz, qpdf, poppler.
- Release-Attestation (`.github/workflows/release-attestation.yml`) baut
  sdist+wheel auf ubuntu/3.12 — dort lief genau der Build, der auch lokal in
  §3 geprüft wurde.

**Windows-CI bewusst NICHT erweitert:** Die zwei P31-Word-Skips würden durch
einen Windows-Läufer nicht zu echten Tests — die Word-Session braucht eine
installierte Word-GUI mit Add-in (nicht auf GitHub-Runnern verfügbar), und der
Offline-Teil (`wsl_to_win` etc.) ist WSL-Semantik, auf nativem Windows wären
die Pfade sinnlos. Ein Windows-Runner würde also keine neue Evidenz erzeugen,
sondern nur rote/flaky Nebenpfade öffnen. Restliche Suite auf Windows: ungetestet
→ nicht als unterstützt deklariert (siehe Matrix).

## 3. Packaging (lokal verifiziert, Worktree)

Build: `python -m build` (build 1.6.1) → `paper_factory-1.4.0.tar.gz` +
`paper_factory-1.4.0-py3-none-any.whl`.

**Gefundener + behobener Befund:** `pfword.ps1` (Word-Driver-Asset) und
`paper.mplstyle` (Figure-Stylesheet) fehlten in Wheel **und** sdist — beide
werden zur Laufzeit via `Path(__file__).with_name(...)` gelesen, ein
installiertes Paket wäre dort defekt gewesen. Fix: `[tool.setuptools.package-data]`
in `pyproject.toml`; Rebuild bestätigt beide Assets in Wheel+sdist.

**Geprüfte Konventionen:**
- Wheel enthält nur `paper_factory/**`: keine `tests/`, keine privaten Dateien,
  keine absoluten Pfade, keine `state/*.json`-Snapshots (bewusst — Dashboard/
  collect_state degradieren graceful ohne sie).
- sdist enthält `tests/` — übliche Konvention (Quell-Distribution bleibt
  testbar), kein Mangel.
- Keine `/home/sai`-Pfade in committed Dateien.

**Installationsweg aus frischem venv:** `pip install dist/*.whl` (temporärer
venv im Worktree, danach versioniert nach `.archiv/` geparkt) — Ergebnis:
`paper-factory --help` läuft (Exit 0, Entry-Point wirkt),
`import paper_factory(.export.rocrate/.reproduction/.verification)` ok,
beide Runtime-Assets im site-packages vorhanden.
Hinweis: Maschine offline — Deps kamen aus dem System-Site-Packages des
Projekt-venvs (`--no-deps`); ein reiner Netz-Install (PyPI-Deps) ist auf dieser
Maschine nicht belegbar.

## 4. Support-Matrix (genau das, was die Evidenz hergibt)

| Plattform | Python | Evidenz | Status |
|---|---|---|---|
| Linux (Ubuntu 22.04) | 3.11, 3.12 | CI grün (1050 passed / 4 skipped) + lokale Suite im Worktree auf WSL2-Ubuntu (gleiche Distribution) | **getestet/unterstützt** |
| WSL2 (Ubuntu on Windows) | 3.13 (Projekt-venv), 3.11/3.12 via CI-Equivalent | lokale Dev-Maschine; volle Suite grün; P31-Word-Pfad designed+genutzt für WSL | **getestet lokal / unterstützt** |
| Windows native | — | keine CI, keine lokale Testmaschine; P31-Pfad ist WSL-spezifisch, Nextflow/Snakemake-Kill POSIX-only | **nicht getestet — nicht als unterstützt deklariert** |
| macOS | — | keine CI, kein lokaler Lauf; `/proc`-Reaping wäre no-op | **nicht getestet — nicht als unterstützt deklariert** |

Python 3.13: lokal belegt (venv + Packaging-Test), aber **nicht in CI** —
daher „funktioniert lokal", keine Support-Garantie über 3.12 hinaus.

## 5. Offene Punkte

1. POSIX-only Kill-Pfade (`os.killpg`) ohne Windows-Guard: auf Windows-native
   würde Snakemake/Nextflow-Abbruch mit AttributeError sichtbar scheitern
   (fail-visible, nicht still) — bleibt unter „nicht unterstützt" abgedeckt.
2. Windows-CI: erst sinnvoll, wenn ein echtes Windows-testbares Feature existiert
   (aktuell: keines — P31 braucht Word-GUI).
3. Wheel-Reproduzierbarkeit (Bit-Identität): ZIP/Timestamps verhindern sie —
   bekannt aus ROADMAP „Post-v2 candidates", hier nicht bearbeitet.
