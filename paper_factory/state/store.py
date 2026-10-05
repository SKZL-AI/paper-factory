"""Per-target-project workspace layout + SQLite run-state store.

Mutable orchestration state lives in SQLite; scientific evidence lives in
immutable JSON/JSONL/YAML artifacts on disk.

Schema versioning (WP3, v1.3): the DB carries PRAGMA user_version. Current
schema = SCHEMA_VERSION. Migrations live in the MIGRATIONS registry
(version -> fn); before any migration mutates an existing DB, the file is
COPIED (never moved/deleted) next to the original. A DB newer than this
code understands fails visibly (SchemaVersionError) — unknown newer schemas
are never interpreted silently, and a version with no registered migration
path fails visibly too. Re-running migrations is idempotent.
"""
from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.util import utcnow

WORKSPACE_DIRNAME = ".paper-factory"

SCHEMA_VERSION = 1


class SchemaVersionError(RuntimeError):
    """Fail-visible: runs.sqlite is on a schema this code cannot interpret —
    either newer than SCHEMA_VERSION (unknown newer schema, no silent
    guessing) or on a version without a registered migration path."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  target_root TEXT NOT NULL,
  config_hash TEXT,
  status TEXT NOT NULL DEFAULT 'OPEN'
);
CREATE TABLE IF NOT EXISTS nodes (
  run_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'NOT_RUN',
  started_at TEXT,
  finished_at TEXT,
  detail TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, node_id)
);
CREATE TABLE IF NOT EXISTS receipts (
  receipt_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  node_id TEXT,
  kind TEXT NOT NULL,
  path TEXT NOT NULL,
  sha256 TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  node_id TEXT,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload TEXT
);
"""


def _migrate_0_to_1(conn: sqlite3.Connection) -> None:
    """Legacy v1.2 databases: they already carry the full v1 schema but were
    created before user_version existed (PRAGMA reads 0). Ensure the schema
    is complete (IF NOT EXISTS — idempotent) so the version can be stamped
    honestly; a v0 DB missing tables gets them here, a complete one is
    untouched."""
    conn.executescript(SCHEMA)


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    0: _migrate_0_to_1,
}


class Workspace:
    def __init__(self, target_root: Path):
        self.target_root = target_root.resolve()
        self.root = self.target_root / WORKSPACE_DIRNAME

    # canonical subpaths -------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.root / "runs.sqlite"

    def sub(self, *parts: str) -> Path:
        p = self.root.joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def evidence_dir(self) -> Path:
        return self.sub("evidence")

    @property
    def claims_dir(self) -> Path:
        return self.sub("claims")

    @property
    def context_dir(self) -> Path:
        return self.sub("context")

    @property
    def reviews_dir(self) -> Path:
        return self.sub("reviews")

    @property
    def receipts_dir(self) -> Path:
        return self.sub("receipts")

    @property
    def paper_dir(self) -> Path:
        return self.sub("paper")

    @property
    def paperpal_outbox(self) -> Path:
        return self.sub("paperpal", "outbox")

    @property
    def paperpal_inbox(self) -> Path:
        return self.sub("paperpal", "inbox")

    @property
    def release_dir(self) -> Path:
        return self.sub("release")

    @property
    def reports_dir(self) -> Path:
        return self.sub("reports")

    def exists(self) -> bool:
        return self.root.exists()

    # sqlite --------------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            self._migrate(conn)
        except SchemaVersionError:
            conn.close()
            raise
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Bring the DB to SCHEMA_VERSION. Fresh/legacy DBs (user_version 0)
        run the registered migration chain; an already-current DB is a no-op
        (idempotency: connecting twice must not change anything twice).
        Unknown newer schemas and missing migration paths raise
        SchemaVersionError BEFORE any schema statement runs."""
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"{self.db_path.name}: runs.sqlite schema_version {version} is NEWER than "
                f"the highest version this paper-factory understands "
                f"({SCHEMA_VERSION}); refusing to interpret an unknown newer schema "
                "(upgrade paper-factory or migrate the DB down explicitly)"
            )
        while version < SCHEMA_VERSION:
            migration = MIGRATIONS.get(version)
            if migration is None:
                raise SchemaVersionError(
                    f"{self.db_path.name}: no migration registered from schema_version "
                    f"{version} to {SCHEMA_VERSION}; the DB is neither current nor "
                    "migratable — refusing to guess"
                )
            self._backup_before_migration(version)
            migration(conn)
            version += 1
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()

    def _backup_before_migration(self, from_version: int) -> None:
        """Copy (never move, never delete) the DB file before a migration
        mutates it. A fresh empty file (sqlite3.connect just created it,
        0 bytes) has nothing to preserve — no backup noise."""
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return
        stamp = utcnow().replace(":", "")
        dest = self.db_path.with_name(
            f"{self.db_path.name}.v{from_version}.pre-migration-{stamp}"
        )
        shutil.copy2(self.db_path, dest)

    def create_run(self, run_id: str, config_hash: str = "") -> None:
        with self.connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO runs(run_id, created_at, target_root, config_hash) VALUES (?,?,?,?)",
                (run_id, utcnow(), str(self.target_root), config_hash),
            )

    def set_node_status(self, run_id: str, node_id: str, status: str, detail: Any = None) -> None:
        import json

        with self.connect() as c:
            row = c.execute(
                "SELECT attempts FROM nodes WHERE run_id=? AND node_id=?", (run_id, node_id)
            ).fetchone()
            if row is None:
                c.execute(
                    "INSERT INTO nodes(run_id, node_id, status, started_at, finished_at, detail, attempts)"
                    " VALUES (?,?,?,?,?,?,1)",
                    (run_id, node_id, status, utcnow(), utcnow(), json.dumps(detail) if detail else None),
                )
            else:
                c.execute(
                    "UPDATE nodes SET status=?, finished_at=?, detail=?, attempts=attempts+1"
                    " WHERE run_id=? AND node_id=?",
                    (status, utcnow(), json.dumps(detail) if detail else None, run_id, node_id),
                )

    def node_status(self, run_id: str, node_id: str) -> str:
        with self.connect() as c:
            row = c.execute(
                "SELECT status FROM nodes WHERE run_id=? AND node_id=?", (run_id, node_id)
            ).fetchone()
        return row["status"] if row else "NOT_RUN"

    def all_node_statuses(self, run_id: str) -> dict[str, str]:
        with self.connect() as c:
            rows = c.execute("SELECT node_id, status FROM nodes WHERE run_id=?", (run_id,)).fetchall()
        return {r["node_id"]: r["status"] for r in rows}

    def record_receipt(self, receipt_id: str, run_id: str, node_id: str | None, kind: str,
                       path: Path, sha256: str | None) -> None:
        """Record a receipt. Re-recording the same receipt_id updates the
        payload but PRESERVES the original created_at — 'created_at' is the
        first recording time, so deterministic orderings over it stay stable
        across re-records (review F-2)."""
        with self.connect() as c:
            c.execute(
                "INSERT INTO receipts(receipt_id, run_id, node_id, kind, path, sha256, created_at)"
                " VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(receipt_id) DO UPDATE SET"
                " run_id=excluded.run_id, node_id=excluded.node_id, kind=excluded.kind,"
                " path=excluded.path, sha256=excluded.sha256,"
                " created_at=receipts.created_at",
                (receipt_id, run_id, node_id, kind, str(path), sha256, utcnow()),
            )

    def receipts_for(
        self, run_id: str, node_id: str | None = None, kind: str | None = None
    ) -> list[dict[str, Any]]:
        """Receipts for a run/node. ``kind=None`` keeps the historic
        kind-agnostic behavior; pass e.g. kind="hoh" to count only receipts
        of one kind (shadow receipts must never satisfy the HoH gate).

        Deterministic order (created_at, receipt_id): without ORDER BY the
        rowid order wanders across INSERT OR REPLACE re-records, which made
        positional windows (e.g. [:20] binding caps) unstable."""
        sql = "SELECT * FROM receipts WHERE run_id=?"
        params: list[Any] = [run_id]
        if node_id:
            sql += " AND node_id=?"
            params.append(node_id)
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        sql += " ORDER BY created_at, receipt_id"
        with self.connect() as c:
            rows = c.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def event(self, run_id: str, kind: str, node_id: str | None = None, payload: Any = None) -> None:
        import json

        with self.connect() as c:
            c.execute(
                "INSERT INTO events(run_id, node_id, ts, kind, payload) VALUES (?,?,?,?,?)",
                (run_id, node_id, utcnow(), kind, json.dumps(payload) if payload is not None else None),
            )

    def events_of_kind(self, kind: str) -> list[dict[str, Any]]:
        """All ledger events of a kind, oldest first (append-only anchor for
        artifact bindings, e.g. paperpal_docx_rendered)."""
        import json

        with self.connect() as c:
            rows = c.execute(
                "SELECT * FROM events WHERE kind=? ORDER BY ts", (kind,)).fetchall()
        return [dict(r, payload=json.loads(r["payload"]) if r["payload"] else None)
                for r in rows]

    def latest_run_id(self) -> str | None:
        with self.connect() as c:
            row = c.execute("SELECT run_id FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()
        return row["run_id"] if row else None

    def receipt_runs(self) -> dict[str, str]:
        """receipt_id -> run_id over every recorded receipt row. This is the
        store-backed evidence for the WP2 replay/wrong-run dimension of
        receipt freshness: a receipt whose ID the store ties to a different
        run is a replay, provable without trusting the receipt's own fields."""
        with self.connect() as c:
            rows = c.execute("SELECT receipt_id, run_id FROM receipts").fetchall()
        return {r["receipt_id"]: r["run_id"] for r in rows}
