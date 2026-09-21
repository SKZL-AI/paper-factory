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
