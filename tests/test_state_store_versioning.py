"""SQLite state versioning (WP3, v1.3): PRAGMA user_version + migration registry.

All tmp_path only, no external processes. Covers: fresh DB, legacy v1.2 DB
(user_version 0 with complete v1 schema), migration backup (copy, never
delete), idempotency, unknown-newer schema, missing migration path.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from paper_factory.state.store import (
    MIGRATIONS,
    SCHEMA,
    SCHEMA_VERSION,
    SchemaVersionError,
    Workspace,
)

SHA_A = "a" * 64


def _raw_connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _user_version(db_path: Path) -> int:
    conn = _raw_connect(db_path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _make_legacy_v0_db(target: Path) -> Path:
    """Simulate a v1.2-era DB: full v1 schema + data, but user_version unset."""
    ws = Workspace(target)
    ws.root.mkdir(parents=True, exist_ok=True)
    conn = _raw_connect(ws.db_path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO runs(run_id, created_at, target_root, config_hash) VALUES (?,?,?,?)",
        ("run-legacy", "2026-09-30T10:00:00Z", str(target), "legacy-hash"),
    )
    conn.execute(
        "INSERT INTO receipts(receipt_id, run_id, node_id, kind, path, sha256, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        ("rcpt-legacy", "run-legacy", "P05", "hoh", "receipts/x.json", SHA_A,
         "2026-09-30T10:05:00Z"),
    )
    conn.commit()
    conn.close()
    assert _user_version(ws.db_path) == 0
    return ws.db_path


# --------------------------------------------------------------------------- #
# fresh DB
# --------------------------------------------------------------------------- #


def test_fresh_db_is_created_at_current_schema_version(tmp_path):
    ws = Workspace(tmp_path / "target")
    ws.create_run("run-1")
    assert _user_version(ws.db_path) == SCHEMA_VERSION == 1
    with ws.connect() as c:
        tables = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert {"runs", "nodes", "receipts", "events"} <= tables
    # nothing anomalous: no migration backup for a fresh DB
    assert list(ws.db_path.parent.glob("*.pre-migration-*")) == []


# --------------------------------------------------------------------------- #
# legacy v1.2 DB (user_version 0) migrates cleanly, data intact
# --------------------------------------------------------------------------- #


def test_legacy_v0_db_migrates_and_preserves_data(tmp_path):
    target = tmp_path / "target"
    db_path = _make_legacy_v0_db(target)

    ws = Workspace(target)  # first v1.3 connect migrates 0 -> 1
    assert ws.node_status("run-legacy", "P05") == "NOT_RUN"  # row still there
    ws.create_run("run-new")
    assert ws.latest_run_id() == "run-new"
    receipts = ws.receipts_for("run-legacy")
    assert len(receipts) == 1 and receipts[0]["receipt_id"] == "rcpt-legacy"
    assert receipts[0]["sha256"] == SHA_A

    assert _user_version(db_path) == SCHEMA_VERSION
    # the pre-migration copy exists next to the original (copy, not move —
    # the original is still the live DB)
    backups = list(db_path.parent.glob("runs.sqlite.v0.pre-migration-*"))
    assert len(backups) == 1
    with _raw_connect(backups[0]) as c:
        legacy_row = c.execute("SELECT run_id FROM runs WHERE run_id='run-legacy'").fetchone()
    assert legacy_row is not None


# --------------------------------------------------------------------------- #
# idempotency
# --------------------------------------------------------------------------- #


def test_migration_is_idempotent(tmp_path):
    target = tmp_path / "target"
    db_path = _make_legacy_v0_db(target)
    ws = Workspace(target)
    ws.create_run("run-1")
    backups_after_first = list(db_path.parent.glob("*.pre-migration-*"))
    assert len(backups_after_first) == 1

    ws2 = Workspace(target)  # second connect: version already current
    ws2.create_run("run-2")
    assert ws2.latest_run_id() == "run-2"
    assert _user_version(db_path) == SCHEMA_VERSION
    # no second backup, no error, no data loss
    assert list(db_path.parent.glob("*.pre-migration-*")) == backups_after_first
    assert len(ws2.receipts_for("run-legacy")) == 1


# --------------------------------------------------------------------------- #
# fail-visible: unknown newer schema, missing migration path
# --------------------------------------------------------------------------- #


def test_unknown_newer_schema_fails_visible_and_untouched(tmp_path):
    target = tmp_path / "target"
    db_path = _make_legacy_v0_db(target)
    conn = _raw_connect(db_path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()

    ws = Workspace(target)
    with pytest.raises(SchemaVersionError, match="NEWER"):
        ws.create_run("run-x")
    # the DB was refused BEFORE any write: version and content unchanged
    assert _user_version(db_path) == SCHEMA_VERSION + 1
    with _raw_connect(db_path) as c:
        assert c.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1  # legacy row only
    assert list(db_path.parent.glob("*.pre-migration-*")) == []  # no backup, no migration


def test_missing_migration_path_fails_visible(tmp_path):
    """A version below SCHEMA_VERSION with no registered migration is neither
    current nor migratable — refuse, never guess."""
    target = tmp_path / "target"
    db_path = _make_legacy_v0_db(target)
    original = dict(MIGRATIONS)
    MIGRATIONS.clear()
    try:
        ws = Workspace(target)
        with pytest.raises(SchemaVersionError, match="no migration"):
            ws.connect()
    finally:
        MIGRATIONS.update(original)
    assert _user_version(db_path) == 0  # untouched


# --------------------------------------------------------------------------- #
# registry contract
# --------------------------------------------------------------------------- #


def test_migration_registry_covers_all_versions_below_current(tmp_path):
    """Guard for the future: whenever SCHEMA_VERSION is bumped, a migration
    MUST be registered for every intermediate version — this test fails the
    moment a version gap slips in."""
    for v in range(SCHEMA_VERSION):
        assert v in MIGRATIONS, f"schema_version {v} has no registered migration"
    assert all(callable(fn) for fn in MIGRATIONS.values())
