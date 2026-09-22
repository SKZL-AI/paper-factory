# OPERATIONS

## Prerequisites

- Python ≥ 3.11, git, a TeX engine (pdflatex; latexmk preferred),
  `herdr` (0.8.x) running for acceptance-grade runs, `hoh` installed
  (`pip install hoh==0.1.0`), agent CLIs per provider routing.
- bubblewrap (`bwrap`) for HoH `--isolation strict`.

## Usual path

```bash
cd your-research-project
paper-factory doctor                       # machine + harness inventory
paper-factory complete --dry-run           # plan, nothing executed
paper-factory complete                     # full pipeline to P36 human gate
# ... Paperpal bridge: fill .paper-factory/paperpal/inbox/ ...
paper-factory resume                       # continues after human deliveries
paper-factory status / report / audit      # inspection
```

## Process-exit contract (for CI / herdr / VeriHarness / shell callers)

`paper-factory run|complete|resume` maps the canonical `run_status_overall`
state to the process exit code. **Exit 0 means CLOSED and nothing else** —
every non-closed terminal state is non-zero, so unattended callers never see
a false-green:

| overall state   | exit |
|-----------------|------|
| CLOSED          | 0    |
| FAILED          | 1    |
| (usage error, argparse convention) | 2 |
| HUMAN_REQUIRED  | 3    |
| INCOMPLETE      | 4    |
| DEGRADED        | 5    |
| EMPTY           | 6    |
| unknown/unmapped (defensive) | 7 |

The JSON stdout of these commands carries the same truth: `overall` is the
`run_status_overall` value and `exit_code` equals the process exit code.
`--dry-run` prints a plan and exits 0 without claiming a pipeline result.
`paper-factory release` is a stub until P33–P35 produce a bundle; it reports
`NOT_RUN` and exits non-zero (4) — exit 0 stays reserved for real success.


## File layout in a target project

```
.paper-factory/
  runs.sqlite            # runs, node states, receipts, events
  evidence/              # evidence_ledger.jsonl, evidence_index.json
  claims/                # claims.yaml (+ novelty/limitations)
  context/               # chat/context mining (T3)
  reviews/               # structured findings + novelty_attack.json
  receipts/              # invocation receipts + hoh/ receipts
  paper/                 # manuscript workspace (protected paths)
  paperpal/{outbox,inbox}/
  release/<paper-id>/    # bundle + SHA256SUMS + manifests
  reports/               # per-node reports incl. global_closure.json
  hoh-runs/              # PF-owned HoH runs root
  hoh-repo/              # PF-owned clone of the target repo
```

## Intervening

- A node FAILs: the report names the artifact-level reason; fix inputs or
  code, then `paper-factory resume`.
- HUMAN_REQUIRED (paperpal bridge, final sign-off): deliver, then resume.
- A HoH run blocks on quota: `hoh --root .paper-factory/hoh-runs resume-quota`
  (or PF resume — blocked_kind is read from state.json directly).
- Archive rule: obsolete states are moved to `.archiv/`, never deleted.

## Troubleshooting

- `DEGRADED_RUNTIME`: herdr missing → HoH verification skipped honestly.
- `UNSUPPORTED_ENVIRONMENT`: e.g. no TeX engine — never rounded to PASS.
- Network off: `--offline`; literature/citation checks report NOT_RUN.
