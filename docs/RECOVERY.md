# RECOVERY

## Crash / interruption

The executor persists every node transition in SQLite (`runs.sqlite`) and an
event log. `paper-factory resume` continues from the persisted states; nodes
already PASS/DEGRADED are not re-executed (idempotent handlers keep existing
artifacts).

## HoH-level recovery

- `hoh status <run-id> --root <target>/.paper-factory/hoh-runs` shows stage,
  condition, blocked_kind (read from state.json — the launcher verdict has a
  known usage_limit/usage_quota classification gap).
- Quota block (`blocked_kind: usage_limit`): wait for `retry_after`, then
  `hoh resume-quota` (max 5 attempts) or `hoh unblock <id> --reason …`.
- Blocked dialogs in panes are diagnosed, not auto-answered (HoH semantics);
  the pane content is preserved in the dispatch error.
- After terminal state, PF closes the run's own herdr tabs
  (pane_cleanup record under hoh-runs/).

## Orphaned artifacts

If a workspace is deleted while a run is active (e.g. a test tempdir), herdr
keeps a dead agent registration and HoH refuses to reuse the name — this is
fail-safe, not corruption. Close the stale tab once (`herdr tab close <id>`),
then rerun with a fresh PF run-id. Prevention: tests never run HoH
(`hoh_nodes: []` in tests/e2e-config).

## States you may see

PASS · DEGRADED (works, with named limitations) · HUMAN_REQUIRED (a human
gate: credentials, paperpal bridge, sign-off) · UNAVAILABLE (optional
component missing — does not fail the install) · NOT_RUN · FAIL ·
UNSUPPORTED_ENVIRONMENT · SKIPPED_DEPENDENCY.

## Backup

Nothing is ever deleted: obsolete files are parked in `.archiv/` with
UTC-versioned names. HoH keeps its own `attic/` and backup/restore commands.
