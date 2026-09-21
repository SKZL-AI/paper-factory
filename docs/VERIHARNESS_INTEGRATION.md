# VERIHARNESS INTEGRATION

PAPER FACTORY integrates VeriHarness/HoH v0.1.0 strictly through
`paper_factory/adapters/veriharness/adapter.py`. HoH decides WHETHER a work
package was verifiably completed; PAPER FACTORY decides WHAT scientific work
must happen. Herdr owns sessions/panes/worktrees.

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
