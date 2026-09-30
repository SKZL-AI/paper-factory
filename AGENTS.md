# PAPER FACTORY — Hausregeln dieses Projekts

Gilt zusätzlich zu `~/.agents/rules/house-rules.md` (kanonisch, bindet auch alle
Subagenten). Konflikte löst die globale Regel zuerst, dann diese Datei.

## Projekt-Scope

- Schreiben nur unter `/home/sai/paper-factory/` (Repo) sowie in Ziel-Projekt-Workspaces
  `<target>/.paper-factory/`. Alles andere (insb. `/home/sai/veriharness`, die Fixture-Quellen,
  fremde Herdr-Workspaces) ist read-only, außer es wird explizit anders angewiesen.
- `/mnt/c/SAI_AI_MAIN_LAB/...` ist Report-Ziel, nie Arbeitsort (nur neue Dateien, nichts
  überschreiben/löschen).

## Archiv statt Löschen (verschärft, User-Anweisung 2026-09-21)

- Nichts wird gelöscht. Obsoletes wird nach `.archiv/` im Projektordner verschoben
  (`name.v<N>.<UTC>`). Das gilt auch für eigene Scratch-/Test-Workspaces und alte
  `.paper-factory`-Zustände.

## Quota-Disziplin (gelernt aus dem Orphaned-Planner-Vorfall 2026-09-21)

- Tests und Test-Fixtures starten NIEMALS echte HoH-Runs oder echte LLM-Invocations
  (`tests/e2e-config/paper-factory.yaml`: `hoh_nodes: []`). Ein pytest-Tmpdir, das
  gelöscht wird, während ein Agent darin arbeitet, erzeugt verwaiste Herdr-Panes.
- Echte HoH-Runs nur über `scripts/run_live_hoh.py` (oder bewusst gesetzte Config),
  mit eigener Persistenz außerhalb von pytest-Tempdirs.
- Nach jedem HoH-Run räumt der Adapter die eigenen Herdr-Tabs auf
  (`_cleanup_panes`, nur Tabs aus dem eigenen Run-State).
- PF-Run-IDs: `PF-<rand8>-<NODE>` — der Zufallsteil liegt VOR dem Truncation-Punkt
  der Herdr-Agentennamen (~24 Zeichen), sonst kollidieren Namen über Runs hinweg.

## Provenance (Kern des Produkts)

- Geschützte Pfade (`paper/main.tex`, `paper/sections/**`, …) nur via Firewall
  (`provenance/firewall.decide_write`) + Origin-Receipt. Anthropic-Backend schreibt
  unter strenger Policy keine Finalprosa. Kein Watermark-Removal, kein Paraphrasieren
  zur Umgehung von Attribution.
- Drafts sind T4, Chats T3 — nie empirische Evidenz.

## Subagenten-Politik (User-Anweisung 2026-09-21)

- Subagenten laufen vollautonom (YOLO im zugewiesenen Scope): reversible Entscheidungen
  selbst treffen, keine Rückfragen an den Nutzer; Eskalation nur an den Captain
  (diese Session) bei echten HUMAN_REQUIRED-Fällen. Der Pflichtblock aus
  `~/.agents/rules/subagent-brief.md` steht trotzdem wörtlich in jedem Brief.
- Max. 2 Subagenten parallel pro Strang; Berichte werden stichprobenartig
  selbst gegengeprüft.

## Speicher-Disziplin (User-Anweisung 2026-09-30, nach ENOSPC-Vorfall)

Die Ubuntu-Systemplatte (`/`) darf nicht wieder volllaufen. Trennung:

- **Ubuntu (`/home/sai/paper-factory`):** Repo, Reports, Dashboards, State-JSONs,
  Pilot-Workspaces (`.paper-factory/`), kleine Fixtures — alles, was das eigentliche
  Ergebnis ist.
- **Extern (`/mnt/e/paper-factory-archive/`):** alles Sperrige/Redundante, das
  VeriHarness/HoH und die Archiv-statt-Löschen-Regel sonst auf `/` aufblähen:
  - `pilot-sources/` — große Source-Snapshots für Piloten (>50 MB Rohdaten)
  - `hoh-runs/` — PF-eigene HoH-Run-Bäume, Arenas, Receipt-Massen
  - `scratch/` — große Scratch-Verzeichnisse
  - `arenas/` — HoH-Arena-Kopien
- Fremde `~/...-runs/`-Bäume (VeriHarness-Entwicklungssession) bleiben unangetastet —
  sie gehören der parallelen Claude-Session.
- Archiv-statt-Löschen gilt unverändert; das **Archiv selbst** liegt bei Bulk auf E:
  (verschieben statt auf `/` zu behalten). Reports/Reports-Hashes verweisen dann auf
  den E:-Pfad.
- Vor jedem großen Lauf: `df -h /` prüfen; bei <20G frei erst auslagern.
