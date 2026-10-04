# VERIHARNESS INTEGRATION

PAPER FACTORY integrates VeriHarness/HoH v0.1.0 through
`paper_factory/adapters/veriharness/adapter.py`, driven from
`paper_factory/dag/handlers.py`: `build_handlers` wraps the base handlers
of the configured `hoh_nodes` / `shadow_nodes` (intersected with
`VERIHARNESS_CAPABLE`), and the wrapper invokes the adapter and folds the
verification verdict into the node outcome (see
[ARCHITECTURE.md](ARCHITECTURE.md), *Verification Plane*). HoH decides
WHETHER a work package was verifiably completed; PAPER FACTORY decides
WHAT scientific work must happen. Herdr owns sessions/panes/worktrees.

## Mapping

A verification-grade PF node (default: P05; configure via
`verification.hoh_nodes` in paper-factory.yaml) becomes one HoH run:

```
PF node P05  →  hoh start --repo <PF-clone> --spec <generated spec> --run-id PF-<rand8>-P05
             →  hoh run <id> --iterations 1 --planner claude --developer … --qa …
             →  receipts copied to .paper-factory/receipts/hoh/<run_id>/
             →  accept/reject folds into the node verdict
```

A deterministic PASS plus a HoH FAIL degrades the node (never hidden).

## Two façades, one run flow

The adapter exposes the contract façade `verify(WorkPackage) ->
VerificationResult` (used by the verification-plane registry and shadow
mode) and the legacy façade `verify_work_package(node_id, spec_path, ...)
-> HohResult` (used by the DAG wrappers). Both delegate to a single shared
`_execute` run flow — one `hoh start` + one `hoh run` per invocation,
serialized per workspace by flock. HoH specifics (run_id, blocked_kind,
stage/rc summary) stay in `BackendIdentity.detail`, never as new contract
fields. `artifact_sha256` in a `VerificationResult` is the
caller-declared package artifact hash; the clone identity is reported
separately as `backend.detail["clone_fingerprint"]` so neither binding
masquerades as the other.

## ensure_clone hardening

Before every run, `ensure_clone()` (re)materializes the PF-owned snapshot
at `<target>/.paper-factory/hoh-repo/`:

- **Symlink ban**: a symlinked clone dir is a hard `PolicyViolation` — a
  symlinked clone would silently run HoH against a foreign tree.
- **Workspace-escape check**: the resolved clone path must stay inside the
  workspace.
- **Stale-park, never delete**: if the source fingerprint changed, the old
  clone is parked under a versioned name (`hoh-repo.v1.<UTC timestamp>`)
  and a fresh snapshot is taken.
- **Git-based source fingerprint**: `git rev-parse HEAD` plus digests of
  `git status --porcelain`, the uncommitted diff content (`git diff HEAD`)
  and untracked-file bytes — committed changes, new uncommitted changes,
  AND repeated in-place edits of an already-dirty file (dirty → dirtier)
  all invalidate the snapshot; a bare name list would not. Content hashing
  is capped at 10 MB per source (total length is still mixed in — a
  documented, honest bound), git calls have a 20 s timeout, and any git
  error falls back to a documented weak proxy. The fingerprint is
  persisted in `hoh-runs/clone-manifest.json` and surfaced as
  `clone_fingerprint` in the result detail.

## Failure behavior and pane cleanup

- A failure between `hoh start` and a finished `hoh run` (timeout,
  interrupt, anything else) triggers a `BaseException` handler: a
  `pf_run_failure.json` receipt is written into the run's receipts tree
  (run_id, error, note), receipts are collected, panes are cleaned up
  best-effort — and the exception is **always re-raised** (Ctrl+C still
  aborts; nothing is swallowed).
- `_cleanup_panes` closes only Herdr tabs this run spawned, under a
  provenance guard: a tab is closed only if its id contains this run's
  run_id (case-insensitive). Tabs failing the guard are treated as
  foreign, NOT closed, and recorded as `skipped_foreign` in
  `hoh-runs/<run_id>.pane_cleanup.json` — never silently dropped.
  Cleanup failure is recorded, not fatal.

## Hard policies (code-enforced; see state/concurrency_audit.json)

1. **Dedicated clone.** HoH runs against `<target>/.paper-factory/hoh-repo/`
   (PF-owned git snapshot), never against the original repo. Reason: O177 —
   two HoH runs over one repo mutually BLOCK (capability witness cannot
   distinguish foreign commits from agent commits).
2. **Own runs root** `HOH_RUNS=<target>/.paper-factory/hoh-runs`.
3. **Run-ids `PF-<rand8>-<NODE>`** — uniqueness before herdr's name
   truncation point (~24 chars).
4. **Serialized**: one HoH run per workspace at a time (flock).
5. **Never push.** Delivery/external actions are not part of the adapter.
6. **blocked_kind is read from `state.json` directly** — the launcher verdict
   misclassifies `usage_limit` (launcher.py:48 expects `usage_quota`;
   stages.py:213 writes `usage_limit`). Observed in code, worked around in
   the adapter, listed in the gap report.
7. **Pane cleanup**: tabs the run spawned (from state.json `active_tasks`)
   are closed after terminal state; foreign panes are never touched.
8. Quota discipline: tests never run HoH (`tests/e2e-config`:
   `hoh_nodes: []`); live runs only via `scripts/run_live_hoh.py`.

## Known interaction limits (measured 2026-09-21)

- `herdr agent prompt` against a fresh **kimi 2.0.2** pane stalls
  (`agent_prompt_stalled`, no state change within 5000 ms; minimal repro in
  the gap report). Planner role with claude works. Workaround: developer
  role on claude/codex; kimi remains fully usable as PF harness adapter
  (non-herdr invocation path).
