# Handoff for Kimi: HoH planner, run PF-P05-20260921T202553Z, iteration 1

From: Claude Code planner session (planner-b1), 2026-09-21

## What happened

1. The planner role ran on the live HoH run `PF-P05-20260921T202553Z` (arena
   `/tmp/pytest-of-sai/pytest-189/e2e-full0/proj/.paper-factory/hoh-runs/_arenas/.../planner/2b473d33e635`).
2. **While it was running, the entire `/tmp/pytest-of-sai/pytest-189/` tree
   disappeared**: arena, `answers/`, `state.json`, reports. So the first attempt
   to write `answers/i1-a0-planner.json` failed with `FileNotFoundError`.
   - Likely cause (not proven): later pytest runs (pytest-202…205 exist now)
     pruned old basetemp directories. pytest keeps only the last 3 by default.
     A live HoH run inside a pytest `tmp_path` therefore does not survive a
     parallel or following `pytest` call.
   - Recommendation: run live HoH runs with a `--basetemp` outside the pytest
     rotation, or don't run pytest in parallel while a live run is going.
3. At the user's request, the plan was written again afterwards:
   - `/tmp/pytest-of-sai/pytest-189/e2e-full0/proj/.paper-factory/hoh-runs/PF-P05-20260921T202553Z/answers/i1-a0-planner.json`
     (the directory was recreated with `mkdir -p`; the rest of the run tree is **gone**)
   - Copy: `/tmp/claude-1000/-tmp-pytest-of-sai-pytest-189-e2e-full0-proj--paper-factory-hoh-runs--arenas-PF-P05-20260921T202553Z-planner/79ef8b01-c22e-40e7-9a81-eb53ea76896b/scratchpad/i1-a0-planner.json`
   - sha256 of both: `32acf9084f67076094fa23633021f513cd2ada2e553721128a96458be5ffcc4f`
   - **Warning:** the run state no longer exists. The runner can't simply pick
     the answer up. The run needs to be restarted (and can reuse the plan).

## Plan contents (short)

- Candidate: `.paper-factory/reports/integrity_audit.json`, 2× MAJOR
  `significance_without_test`. Checked by the planner: the spans are
  **code-point offsets** (not bytes). `[2741,2766]` = "statistically
  significant", `[2768,2776]` = "p < 0.01". Both are in **the same sentence**
  (one claim, two markers). No statistical test in `code/`/`results/`, n=3
  seeds. Both findings are substantively correct.
- Targets: verbatim snapshot `verification/P05/candidate_integrity_audit.json`
  (sha256 `e81e830a…f4e9`), read-only stdlib verifier
  `verification/P05/verify_integrity_audit.py`, report
  `verification/P05/P05_verification_report.json`,
  `tests/test_p05_integrity_audit.py` with negative cases.
- Checks K1–K7: verifier exit 0; unittest; snapshot hash + report;
  independent span/test-artifact check; preserve hashes for
  draft/results/code/bib; verifier fails on mutations; verifier writes nothing.
- **NOT_RUN:** no acceptance check was run against the real arena. A dry run
  against a scratch copy was aborted when the tree disappeared.

## Side observation

- `.paper-factory/reviews/ZZ-planted.json` contains an undisposed MAJOR
  ("planted undisposed major", disposition null). It's presumably a deliberate
  test plant for the closure gate. Please confirm that the gate blocks on it.
