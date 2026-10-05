"""WP-V: historical state migration — synthetic legacy DB fixtures (v2.0).

The committed tests build MINIMAL synthetic v0 databases (v1.0/v1.2-era
shape: full v1 schema, PRAGMA user_version unset, legacy data). No real
pilot runs.sqlite is committed — those are opened locally against scratch
COPIES and documented in docs/reports/V2_0_STATE_MIGRATION.md.

Migration contract under test (state/store.py):
- user_version 0 -> 1 stamps cleanly, data (runs/nodes/events) survives;
- the pre-migration COPY appears next to the original before anything is
  mutated (copy, never move/delete — the original keeps serving);
- the backup preserves the PRE-migration bytes (a tampered/missing backup
  must not pass silently);
- a v0 DB that is missing tables the legacy era never had still migrates
  (CREATE IF NOT EXISTS completes the schema, nothing is reinterpreted);
- re-running the migration is idempotent (second connect creates no second
  backup, version stays stamped);
- a DB NEWER than SCHEMA_VERSION fails visibly (SchemaVersionError), never
  silently interpreted — the historical-evidence rule.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from paper_factory.state.store import (
    SCHEMA,
    SCHEMA_VERSION,
    SchemaVersionError,
    Workspace,
)

SHA_A = "a" * 64


def _raw(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _user_version(db_path: Path) -> int:
    conn = _raw(db_path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _make_v0_db(target: Path, *, with_data: bool = True,
                drop_tables: tuple[str, ...] = ()) -> Path:
    """Synthetic v1.0/v1.2-era DB: full v1 schema (minus `drop_tables`),
    user_version never stamped (reads 0), optionally legacy rows."""
    ws = Workspace(target)
    ws.root.mkdir(parents=True, exist_ok=True)
    conn = _raw(ws.db_path)
    conn.executescript(SCHEMA)
    for table in drop_tables:
        conn.execute(f"DROP TABLE {table}")
    conn.commit()
    if with_data:
        conn.execute(
            "INSERT INTO runs(run_id, created_at, target_root, config_hash)"
            " VALUES (?,?,?,?)",
            ("run-hist", "2026-08-01T09:00:00Z", str(target), "hist-hash"))
        conn.execute(
            "INSERT INTO nodes(run_id, node_id, status, attempts)"
            " VALUES (?,?,?,?)",
            ("run-hist", "P05", "PASS", 2))
        conn.execute(
            "INSERT INTO events(run_id, node_id, ts, kind, payload)"
            " VALUES (?,?,?,?,?)",
            ("run-hist", "P05", "2026-08-01T09:05:00Z", "complete",
             json.dumps({"note": "v1.0-era event"})))
    conn.commit()
    conn.close()
    assert _user_version(ws.db_path) == 0
    return ws.db_path


def _migration_backup(db_path: Path) -> Path:
    backups = sorted(db_path.parent.glob("runs.sqlite.v0.pre-migration-*"))
    assert len(backups) == 1, f"expected exactly one pre-migration copy, got {backups}"
    return backups[0]


def test_v0_db_migrates_and_legacy_data_survives(tmp_path):
    target = tmp_path / "target"
    db_path = _make_v0_db(target)

    ws = Workspace(target)
    assert ws.node_status("run-hist", "P05") == "PASS"
    assert ws.latest_run_id() == "run-hist"
    with ws.connect() as c:
        rows = c.execute(
            "SELECT payload FROM events WHERE run_id='run-hist'").fetchall()
    assert json.loads(rows[0]["payload"])["note"] == "v1.0-era event"
    assert _user_version(db_path) == SCHEMA_VERSION


def test_v0_migration_backup_contains_pre_migration_bytes(tmp_path):
    """Der Pre-Migration-Copy entsteht BEVOR die Migration mutiert und traegt
    die Original-Bytes (integritaetsrelevant: ein Backup der schon
    migrierten Datei waere wertlos)."""
    target = tmp_path / "target"
    db_path = _make_v0_db(target)
    original_bytes = db_path.read_bytes()

    ws = Workspace(target)
    ws.create_run("run-after-migration")
    backup = _migration_backup(db_path)
    assert backup.read_bytes() == original_bytes
    # copy semantics: the original is still the live DB, not renamed away
    assert db_path.exists()
    assert _user_version(backup) == 0
    assert _user_version(db_path) == SCHEMA_VERSION


def test_v0_db_missing_legacy_table_is_completed_not_reinterpreted(tmp_path):
    """Eine v0-DB, der eine Tabelle fehlt, die es in ihrer Aera nicht gab,
    bekommt sie per CREATE IF NOT EXISTS — die Migration ergaenzt, sie
    interpretiert nichts still um."""
    target = tmp_path / "target"
    db_path = _make_v0_db(target, with_data=False, drop_tables=("receipts",))
    ws = Workspace(target)
    ws.create_run("run-new")
    with ws.connect() as c:
        tables = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "receipts" in tables
    assert _user_version(db_path) == SCHEMA_VERSION


def test_migration_is_idempotent_no_second_backup(tmp_path):
    target = tmp_path / "target"
    db_path = _make_v0_db(target)
    ws = Workspace(target)
    ws.create_run("r1")
    first = _migration_backup(db_path)
    ws.create_run("r2")  # already at SCHEMA_VERSION: pure no-op
    backups = sorted(db_path.parent.glob("runs.sqlite.v0.pre-migration-*"))
    assert [p.name for p in backups] == [first.name]
    assert _user_version(db_path) == SCHEMA_VERSION


def test_db_newer_than_schema_fails_visible(tmp_path):
    """Historische Evidenz-Regel: eine DB mit user_version > SCHEMA_VERSION
    wird NIEMALS still interpretiert — SchemaVersionError, kein Backup, keine
    Mutation."""
    target = tmp_path / "target"
    db_path = _make_v0_db(target)
    conn = _raw(db_path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()

    ws = Workspace(target)
    with pytest.raises(SchemaVersionError, match="NEWER"):
        ws.connect()
    assert list(db_path.parent.glob("*.pre-migration-*")) == []
    assert _user_version(db_path) == SCHEMA_VERSION + 1
