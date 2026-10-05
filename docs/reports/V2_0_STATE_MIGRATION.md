# V2.0 WP-V — Historical State Migration

Datum: 2026-10-05 · Worktree `.worktrees/v2-conformance` (Branch `v2.0/wp-iv-v`,
Basis 756c692) · Store: `paper_factory/state/store.py` (SCHEMA_VERSION=1,
MIGRATIONS-Registry, Backup-vor-Mutation per Copy).

## Regelwerk (unverändert, hier verifiziert)

Historische Evidenz wird **nie umgeschrieben**: die Migration stempelt
`PRAGMA user_version` 0→1 und kopiert die DB-Datei **vor** jeder Mutation
neben das Original (`runs.sqlite.v0.pre-migration-<UTC>`, Copy nie Move).
Eine DB mit `user_version > SCHEMA_VERSION` scheitert mit
`SchemaVersionError` — unbekannte neuere Schemas werden niemals still
interpretiert. Committed wird nur eine **minimale synthetische v0-Fixture**
(`tests/test_historical_state_migration.py`); echte Pilot-DBs bleiben im
Haupt-Checkout unter `pilots/` unangetastet (nur LESEN + Kopien in
Worktree-Scratch).

## Lokal verifiziert: echte historische Pilot-States

Methode (lokal, nicht committed): Kopien der `runs.sqlite` aus fünf Piloten
in `.scratch/wp5-migration/<pilot>-target/.paper-factory/`, dann erster
`Workspace.connect()` (migriert bzw. No-op) — Originale ausschließlich
lesend, SHA-256 der Originale vorher/nachher verglichen (unverändert).

| Pilot | Ära | UV vor→nach | Zeilen (runs/nodes/receipts/events) | Backup mit Pre-Migration-Bytes |
|---|---|---|---|---|
| pilot-03-massinv-paper1 | v1.0 | 0→1 | 16/608/0/1138 → identisch | ja |
| real-pilot-01-rerun | v1.2 | 0→1 | 1/38/0/78 → identisch | ja |
| real-pilot-01 | v1.2 | 0→1 | 3/114/0/167 → identisch | ja |
| pilot-02-tscg | v1.2 | 0→1 | 1/38/0/67 → identisch | ja |
| v1-3-repro-synth (Kontrolle) | v1.3 | 1→1 (No-op) | 1/38/0/67 → identisch | korrekt **keiner** |

Ergebnis pro State: **saubere Migration, Daten intakt, älteste Runs lesbar**
(z.B. `complete-20260922T103928Z` in real-pilot-01), Backup enthält exakt
die Pre-Migration-Bytes. Die Kontroll-DB auf v1 bleibt unberührt und
bekommt zu Recht kein Backup (Idempotenz-/No-op-Pfad).

Schemabefund: alle fünf historischen DBs tragen bereits das vollständige
v1-Tabellenlayout (runs/nodes/receipts/events, identische Spalten) — die
Ära-Unterschiede liegen ausschließlich im fehlenden `user_version`-Stempel.
Der `_migrate_0_to_1`-Pfad (CREATE IF NOT EXISTS + Stempel) ist damit für
die reale Historie exakt richtig und gefahrlos.

## Verankerung in der Suite (committed)

`tests/test_historical_state_migration.py` (5 Tests, synthetische Fixtures):

1. v0→1 migriert, Legacy-Daten (runs/nodes/events) überleben.
2. Backup entsteht vor der Mutation und trägt exakt die Original-Bytes;
   Copy-Semantik (Original bleibt live).
3. v0-DB ohne in ihrer Ära unbekannte Tabelle: Schema wird ergänzt, nicht
   umgedeutet.
4. Idempotenz: zweiter Connect erzeugt kein zweites Backup.
5. `user_version > SCHEMA_VERSION`: `SchemaVersionError` (match "NEWER"),
   keine Mutation, kein Backup.

Ergänzend weiterhin grün: `tests/test_state_store_versioning.py` (6 Tests,
v1.3-WP3-Ursprungssuite inkl. Legacy-v0- und Unknown-Schema-Fällen).

## Offene Punkte

- **v2-Schema-Vorarbeit:** Sobald SCHEMA_VERSION auf 2 steigt, braucht die
  MIGRATIONS-Registry einen Eintrag `1: _migrate_1_to_2` — die Suite
  prüft dann denselben Vertrag (Backup v1→v2, Idempotenz, Fail-visible).
  Heute existiert bewusst nur der 0→1-Pfad.
- Echte Pilot-Kopien liegen unter `.scratch/` (gitignored); die
  Verifikation ist an diesem Bericht und die Suite an den synthetischen
  Fixtures gebunden — ein Re-Run ist mit `.scratch/wp5_real_pilots.py`
  jederzeit reproduzierbar.
